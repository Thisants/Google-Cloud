"""Acesso ao PostgreSQL (ETAPA 07): conexão, criação das tabelas e gravação SEM duplicar e SEM apagar.

Ideia central (armazenamento permanente):
  - cada tabela tem uma CHAVE (por exemplo, a data);
  - gravar usa "INSERT ... ON CONFLICT DO UPDATE" (upsert): se a chave não existe, insere;
    se já existe, atualiza os números (o GA4 corrige valores recentes). Rodar duas vezes NÃO duplica;
  - nenhum comando deste projeto apaga linhas: o histórico só cresce;
  - criado_em = quando a linha entrou pela 1ª vez; atualizado_em = última atualização.

O SQL usa o estilo ":nome" para os parâmetros. Para o PostgreSQL (psycopg) ele é convertido para
"%(nome)s" em _sql(). Os nomes de tabela/coluna vêm das constantes deste arquivo, nunca de entrada do usuário.
"""
import os
import re
from datetime import date

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ga_project.config import PROJECT_ROOT
from ga_project.errors import GA4ProjectError

class DatabaseWriteError(GA4ProjectError):
    """Erro ao criar tabelas ou gravar no banco (grave: a carga deve parar)."""


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------
TABLES = {
    "ga4_diario": {
        "columns": ["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"],
        "key": ["data"],
        "date_col": "data",
        "ddl": """
            CREATE TABLE IF NOT EXISTS ga4_diario (
                data                  DATE        PRIMARY KEY,
                usuarios_ativos       BIGINT      NOT NULL,
                sessoes               BIGINT      NOT NULL,
                visualizacoes_pagina  BIGINT      NOT NULL,
                sem_dados             BOOLEAN     NOT NULL,
                criado_em             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
    },
    "ga4_sessoes_canal": {
        "columns": ["data", "canal", "origem", "sessoes"],
        "key": ["data", "canal", "origem"],
        "date_col": "data",
        "ddl": """
            CREATE TABLE IF NOT EXISTS ga4_sessoes_canal (
                data           DATE        NOT NULL,
                canal          TEXT        NOT NULL,
                origem         TEXT        NOT NULL,
                sessoes        BIGINT      NOT NULL,
                criado_em      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (data, canal, origem)
            )""",
    },
    "gsc_diario": {
        "columns": ["data", "cliques", "impressoes", "ctr", "posicao_media"],
        "key": ["data"],
        "date_col": "data",
        "ddl": """
            CREATE TABLE IF NOT EXISTS gsc_diario (
                data           DATE             PRIMARY KEY,
                cliques        BIGINT           NOT NULL,
                impressoes     BIGINT           NOT NULL,
                ctr            DOUBLE PRECISION,
                posicao_media  DOUBLE PRECISION,
                criado_em      TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em  TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
    },
    # Foto de um período: o Search Console não separa por dia neste relatório (ver README da etapa).
    "gsc_consulta_pagina": {
        "columns": ["periodo_inicio", "periodo_fim", "consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media"],
        "key": ["periodo_inicio", "periodo_fim", "consulta", "pagina"],
        "date_col": "periodo_fim",
        "ddl": """
            CREATE TABLE IF NOT EXISTS gsc_consulta_pagina (
                periodo_inicio  DATE             NOT NULL,
                periodo_fim     DATE             NOT NULL,
                consulta        TEXT             NOT NULL,
                pagina          TEXT             NOT NULL,
                cliques         BIGINT           NOT NULL,
                impressoes      BIGINT           NOT NULL,
                ctr             DOUBLE PRECISION,
                posicao_media   DOUBLE PRECISION,
                criado_em       TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em   TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (periodo_inicio, periodo_fim, consulta, pagina)
            )""",
    },
}

# Registro de cada carga (só acrescenta linhas; serve de histórico/auditoria)
LOG_DDL = """
    CREATE TABLE IF NOT EXISTS carga_log (
        fonte           TEXT        NOT NULL,
        periodo_inicio  DATE,
        periodo_fim     DATE,
        linhas          INTEGER     NOT NULL,
        executado_em    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------
def _connection_settings() -> dict:
    """Lê as configurações do .env: DATABASE_URL (opcional) ou DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD."""
    load_dotenv(PROJECT_ROOT / ".env")

    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return {"conninfo": url}

    missing = [n for n in ("DB_NAME", "DB_USER", "DB_PASSWORD") if not os.getenv(n, "").strip()]
    if missing:
        raise GA4ProjectError(
            f"Faltam variáveis no .env: {', '.join(missing)}. "
            "Preencha DB_NAME, DB_USER e DB_PASSWORD (ou use DATABASE_URL)."
        )
    port = os.getenv("DB_PORT", "5432").strip()
    if not port.isdigit():
        raise GA4ProjectError("DB_PORT inválida no .env (use só números, ex.: 5432).")
    return {
        "host": os.getenv("DB_HOST", "localhost").strip() or "localhost",
        "port": int(port),
        "dbname": os.getenv("DB_NAME").strip(),
        "user": os.getenv("DB_USER").strip(),
        "password": os.getenv("DB_PASSWORD"),
    }


def connect():
    """Abre a conexão com o PostgreSQL."""
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise GA4ProjectError("Biblioteca 'psycopg' não instalada. Rode: pip install -r requirements.txt") from exc

    settings = _connection_settings()
    conninfo = settings.pop("conninfo", "")
    try:
        return psycopg.connect(conninfo, connect_timeout=10, **settings)
    except psycopg.Error as exc:
        raise GA4ProjectError(
            "Não consegui conectar ao PostgreSQL. Confira: (1) o PostgreSQL está instalado e ligado "
            "(serviço 'postgresql'); (2) host e porta no .env; (3) DB_NAME, DB_USER e DB_PASSWORD "
            f"estão corretos e o banco foi criado. Detalhe: {exc}"
        ) from exc


def _sql(conn, sql: str) -> str:
    """Converte ':nome' para o estilo do PostgreSQL ('%(nome)s'). O SQLite (usado só nos testes) já aceita ':nome'."""
    if type(conn).__module__.startswith("sqlite3"):
        return sql
    return re.sub(r":(\w+)", r"%(\1)s", sql)


# ---------------------------------------------------------------------------
# Esquema e gravação
# ---------------------------------------------------------------------------
def create_schema(conn) -> None:
    """Cria as tabelas se ainda não existirem (não mexe em dados existentes)."""
    try:
        cur = conn.cursor()
        for spec in TABLES.values():
            cur.execute(spec["ddl"])
        cur.execute(LOG_DDL)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise DatabaseWriteError(f"Erro ao criar as tabelas: {exc}") from exc


def build_upsert_sql(table: str) -> str:
    """Monta o INSERT ... ON CONFLICT DO UPDATE da tabela."""
    spec = TABLES[table]
    columns, key = spec["columns"], spec["key"]
    updates = [f"{c} = EXCLUDED.{c}" for c in columns if c not in key]
    updates.append("atualizado_em = CURRENT_TIMESTAMP")
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + c for c in columns)}) "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {', '.join(updates)}"
    )


def df_to_rows(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> lista de dicionários com tipos simples do Python (datas viram date, NaN vira None)."""
    clean = df.astype(object).where(df.notna(), None)
    rows = clean.to_dict("records")
    for row in rows:
        for name, value in row.items():
            if isinstance(value, pd.Timestamp):
                row[name] = value.date()
            elif isinstance(value, np.generic):
                row[name] = value.item()
    return rows


def save_dataframe(conn, table: str, df: pd.DataFrame, period_start, period_end) -> int:
    """Grava o DataFrame na tabela (upsert) e registra a carga em carga_log. Devolve quantas linhas foram gravadas."""
    if df.empty:
        return 0
    rows = df_to_rows(df[TABLES[table]["columns"]])
    start = period_start.date() if isinstance(period_start, pd.Timestamp) else period_start
    end = period_end.date() if isinstance(period_end, pd.Timestamp) else period_end
    try:
        cur = conn.cursor()
        cur.executemany(_sql(conn, build_upsert_sql(table)), rows)
        cur.execute(
            _sql(
                conn,
                "INSERT INTO carga_log (fonte, periodo_inicio, periodo_fim, linhas) "
                "VALUES (:fonte, :periodo_inicio, :periodo_fim, :linhas)",
            ),
            {"fonte": table, "periodo_inicio": start, "periodo_fim": end, "linhas": len(rows)},
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise DatabaseWriteError(f"Erro ao gravar na tabela {table}: {exc}") from exc
    return len(rows)


def table_summary(conn) -> pd.DataFrame:
    """Quantas linhas e qual intervalo de datas há em cada tabela."""
    cur = conn.cursor()
    rows = []
    for name, spec in TABLES.items():
        col = spec["date_col"]
        cur.execute(f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {name}")
        count, first, last = cur.fetchone()
        rows.append({"tabela": name, "linhas": count, "primeira_data": first, "ultima_data": last})
    return pd.DataFrame(rows)

"""Testes do banco multi-cliente: sem PostgreSQL (SQLite em memória entende o mesmo SQL de gravação)."""
import sqlite3
from datetime import date

import pandas as pd
import pytest

from ga_project.clientes import ensure_cliente
from ga_project.database import (
    DEFAULT_CLIENTE,
    TABLES,
    DatabaseWriteError,
    LegacySchemaError,
    _connection_settings,
    _sql,
    build_upsert_sql,
    create_schema,
    df_to_rows,
    detect_legacy_tables,
    save_dataframe,
    table_columns,
    table_summary,
)
from ga_project.errors import GA4ProjectError

sqlite3.register_adapter(date, lambda d: d.isoformat())
A, B = "cliente-a", "cliente-b"


def new_db():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    ensure_cliente(conn, A, "Cliente A")
    ensure_cliente(conn, B, "Cliente B")
    return conn


def ga4_df(rows):
    df = pd.DataFrame(rows, columns=["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"])
    df["data"] = pd.to_datetime(df["data"])
    return df


def count(conn, table, cliente=None):
    sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE cliente_id = '{cliente}'" if cliente else "")
    return conn.execute(sql).fetchone()[0]


# ---------- SQL e conversões ----------
def test_upsert_sql_inclui_o_cliente_na_chave():
    sql = build_upsert_sql("ga4_diario")
    assert "ON CONFLICT (cliente_id, data) DO UPDATE" in sql
    assert "usuarios_ativos = EXCLUDED.usuarios_ativos" in sql and "atualizado_em = CURRENT_TIMESTAMP" in sql
    assert "cliente_id = EXCLUDED" not in sql and "data = EXCLUDED.data" not in sql
    assert "criado_em" not in sql.split("DO UPDATE")[1]


def test_toda_tabela_de_dados_comeca_a_chave_pelo_cliente():
    for name, spec in TABLES.items():
        assert spec["key"][0] == "cliente_id" and spec["columns"][0] == "cliente_id", name


def test_parametros_sao_convertidos_para_o_estilo_do_postgres():
    class FakePostgresConnection:
        pass

    assert _sql(FakePostgresConnection(), "VALUES (:a, :b_c)") == "VALUES (%(a)s, %(b_c)s)"
    assert _sql(sqlite3.connect(":memory:"), "VALUES (:a)") == "VALUES (:a)"


def test_df_to_rows_converte_tipos():
    df = pd.DataFrame({"data": pd.to_datetime(["2026-09-01"]), "n": [5], "ctr": [float("nan")], "flag": [True]})
    row = df_to_rows(df)[0]
    assert type(row["data"]) is date and type(row["n"]) is int and row["ctr"] is None and row["flag"] is True


# ---------- esquema ----------
def test_create_schema_cria_tabelas_e_e_idempotente():
    conn = new_db()
    create_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES) | {"carga_log", "clientes", "execucoes", "insights", "api_chaves"} <= names
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_carga_log_cliente", "idx_execucoes_cliente"} <= indexes


def test_banco_no_formato_antigo_e_detectado_e_create_schema_recusa():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ga4_diario (data DATE PRIMARY KEY, usuarios_ativos BIGINT, sessoes BIGINT, "
                 "visualizacoes_pagina BIGINT, sem_dados BOOLEAN)")
    assert detect_legacy_tables(conn) == ["ga4_diario"]
    with pytest.raises(LegacySchemaError, match="migrar_legado"):
        create_schema(conn)
    assert "cliente_id" not in table_columns(conn, "ga4_diario")        # nada foi alterado


# ---------- gravação por cliente ----------
def test_gravar_duas_vezes_nao_duplica_e_atualiza_valores():
    conn = new_db()
    rows = [("2026-09-01", 10, 12, 30, False), ("2026-09-02", 8, 9, 20, False)]
    save_dataframe(conn, "ga4_diario", ga4_df(rows), date(2026, 9, 1), date(2026, 9, 2), cliente_id=A)
    conn.execute("UPDATE ga4_diario SET criado_em = '2020-01-01 00:00:00', atualizado_em = '2020-01-01 00:00:00'")
    rows[0] = ("2026-09-01", 99, 12, 30, False)
    save_dataframe(conn, "ga4_diario", ga4_df(rows), date(2026, 9, 1), date(2026, 9, 2), cliente_id=A)
    assert count(conn, "ga4_diario") == 2
    row = conn.execute("SELECT usuarios_ativos, criado_em, atualizado_em FROM ga4_diario WHERE data = '2026-09-01'").fetchone()
    assert row[0] == 99 and row[1] == "2020-01-01 00:00:00" and row[2] != "2020-01-01 00:00:00"
    assert count(conn, "carga_log", A) == 2


def test_mesma_data_em_clientes_diferentes_nao_se_sobrescreve():
    conn = new_db()
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 111, 1, False)]), date(2026, 9, 1), date(2026, 9, 1), cliente_id=A)
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 2, 222, 2, False)]), date(2026, 9, 1), date(2026, 9, 1), cliente_id=B)
    assert count(conn, "ga4_diario") == 2
    assert conn.execute("SELECT sessoes FROM ga4_diario WHERE cliente_id = ?", (A,)).fetchone()[0] == 111
    assert conn.execute("SELECT sessoes FROM ga4_diario WHERE cliente_id = ?", (B,)).fetchone()[0] == 222


def test_historico_antigo_nao_e_apagado_quando_a_janela_anda():
    conn = new_db()
    save_dataframe(conn, "ga4_diario", ga4_df([(f"2026-09-0{d}", d, d, d, False) for d in (1, 2, 3)]), date(2026, 9, 1), date(2026, 9, 3), cliente_id=A)
    save_dataframe(conn, "ga4_diario", ga4_df([(f"2026-09-0{d}", d, d, d, False) for d in (3, 4, 5)]), date(2026, 9, 3), date(2026, 9, 5), cliente_id=A)
    assert count(conn, "ga4_diario", A) == 5


def test_cliente_nao_cadastrado_e_recusado_com_mensagem_clara():
    conn = new_db()
    with pytest.raises(GA4ProjectError, match="não cadastrado"):
        save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 1, 1, False)]), date(2026, 9, 1), date(2026, 9, 1), cliente_id="fantasma")


def test_erro_de_gravacao_vira_database_write_error():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE clientes (slug TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO clientes VALUES ('cliente-a')")
    with pytest.raises(DatabaseWriteError, match="ga4_diario"):                 # tabela de dados não existe
        save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 1, 1, False)]), date(2026, 9, 1), date(2026, 9, 1), cliente_id=A)


def test_resumo_por_cliente_e_geral():
    conn = new_db()
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 1, 1, False)]), date(2026, 9, 1), date(2026, 9, 1), cliente_id=A)
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 1, 1, False), ("2026-09-02", 1, 1, 1, False)]), date(2026, 9, 1), date(2026, 9, 2), cliente_id=B)
    assert table_summary(conn, A).set_index("tabela").loc["ga4_diario", "linhas"] == 1
    assert table_summary(conn, B).set_index("tabela").loc["ga4_diario", "linhas"] == 2
    assert table_summary(conn).set_index("tabela").loc["ga4_diario", "linhas"] == 3


def test_cliente_padrao_transitorio_existe_como_constante():
    assert DEFAULT_CLIENTE == "padrao"


# ---------- configuração do .env ----------
def test_configuracao_pelas_partes_do_env(monkeypatch):
    monkeypatch.setattr("ga_project.database.load_dotenv", lambda *a, **k: None)
    for name in ("DATABASE_URL", "DB_HOST", "API_DB_USER", "API_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_NAME", "analytics")
    monkeypatch.setenv("DB_USER", "analytics_app")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:com/símbolos")
    monkeypatch.setenv("DB_PORT", "5433")
    assert _connection_settings() == {"host": "localhost", "port": 5433, "dbname": "analytics",
                                      "user": "analytics_app", "password": "p@ss:com/símbolos"}


def test_a_api_pode_usar_um_usuario_so_de_leitura(monkeypatch):
    monkeypatch.setattr("ga_project.database.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_NAME", "analytics")
    monkeypatch.setenv("DB_USER", "analytics_app")
    monkeypatch.setenv("DB_PASSWORD", "senha-do-app")
    monkeypatch.setenv("API_DB_USER", "analytics_api")
    monkeypatch.setenv("API_DB_PASSWORD", "senha-da-api")
    assert _connection_settings("api")["user"] == "analytics_api"
    assert _connection_settings("api")["password"] == "senha-da-api"
    assert _connection_settings("app")["user"] == "analytics_app"          # as demais rotinas continuam com o usuário completo
    monkeypatch.delenv("API_DB_PASSWORD")
    with pytest.raises(GA4ProjectError, match="API_DB_PASSWORD"):
        _connection_settings("api")


def test_configuracao_faltando_variaveis(monkeypatch):
    monkeypatch.setattr("ga_project.database.load_dotenv", lambda *a, **k: None)
    for name in ("DATABASE_URL", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(GA4ProjectError, match="DB_NAME"):
        _connection_settings()


def test_database_url_tem_prioridade(monkeypatch):
    monkeypatch.setattr("ga_project.database.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db?sslmode=require")
    assert _connection_settings() == {"conninfo": "postgresql://u:p@host:5432/db?sslmode=require"}

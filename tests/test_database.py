"""Testes da ETAPA 07: sem PostgreSQL instalado.

Usam o SQLite em memória, que entende o mesmo SQL de gravação (INSERT ... ON CONFLICT DO UPDATE).
Isto testa a LÓGICA (não duplica, atualiza, não apaga). A conexão real com o PostgreSQL é testada
rodando o 07-banco-dados/main.py na sua máquina.
"""
import sqlite3
from datetime import date

import pandas as pd
import pytest

from ga_project.carga import (
    default_paths,
    load_ga4_canais,
    load_ga4_diario,
    load_gsc_consulta_pagina,
    run_all,
)
from ga_project.database import (
    TABLES,
    DatabaseWriteError,
    _connection_settings,
    _sql,
    build_upsert_sql,
    create_schema,
    df_to_rows,
    save_dataframe,
    table_summary,
)
from ga_project.errors import GA4ProjectError

sqlite3.register_adapter(date, lambda d: d.isoformat())   # o SQLite precisa saber gravar datas


def new_db():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    return conn


def ga4_df(rows):
    df = pd.DataFrame(rows, columns=["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"])
    df["data"] = pd.to_datetime(df["data"])
    return df


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------- SQL e conversões ----------
def test_upsert_sql_atualiza_so_colunas_que_nao_sao_chave():
    sql = build_upsert_sql("ga4_diario")
    assert "ON CONFLICT (data) DO UPDATE" in sql
    assert "usuarios_ativos = EXCLUDED.usuarios_ativos" in sql
    assert "atualizado_em = CURRENT_TIMESTAMP" in sql
    assert "data = EXCLUDED.data" not in sql
    assert "criado_em" not in sql.split("DO UPDATE")[1]          # criado_em nunca é alterado


def test_parametros_sao_convertidos_para_o_estilo_do_postgres():
    class FakePostgresConnection:
        pass

    assert _sql(FakePostgresConnection(), "VALUES (:a, :b_c)") == "VALUES (%(a)s, %(b_c)s)"
    assert _sql(sqlite3.connect(":memory:"), "VALUES (:a)") == "VALUES (:a)"


def test_df_to_rows_converte_tipos():
    df = pd.DataFrame(
        {"data": pd.to_datetime(["2026-09-01"]), "n": [5], "ctr": [float("nan")], "flag": [True]}
    )
    row = df_to_rows(df)[0]
    assert row["data"] == date(2026, 9, 1) and type(row["data"]) is date
    assert row["n"] == 5 and type(row["n"]) is int
    assert row["ctr"] is None
    assert row["flag"] is True


# ---------- esquema ----------
def test_create_schema_cria_tabelas_e_e_idempotente():
    conn = new_db()
    create_schema(conn)                                         # segunda vez: sem erro
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES) | {"carga_log"} <= names


# ---------- permanência ----------
def test_gravar_duas_vezes_nao_duplica_e_atualiza_valores():
    conn = new_db()
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 10, 12, 30, False), ("2026-09-02", 8, 9, 20, False)]),
                   date(2026, 9, 1), date(2026, 9, 2))
    conn.execute("UPDATE ga4_diario SET criado_em = '2020-01-01 00:00:00', atualizado_em = '2020-01-01 00:00:00'")
    save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 99, 12, 30, False), ("2026-09-02", 8, 9, 20, False)]),
                   date(2026, 9, 1), date(2026, 9, 2))
    assert count(conn, "ga4_diario") == 2                       # não duplicou
    row = conn.execute("SELECT usuarios_ativos, criado_em, atualizado_em FROM ga4_diario WHERE data = '2026-09-01'").fetchone()
    assert row[0] == 99                                         # valor corrigido
    assert row[1] == "2020-01-01 00:00:00"                      # criado_em preservado
    assert row[2] != "2020-01-01 00:00:00"                      # atualizado_em renovado
    assert count(conn, "carga_log") == 2                        # as duas cargas ficaram registradas


def test_historico_antigo_nao_e_apagado_quando_a_janela_anda():
    conn = new_db()
    save_dataframe(conn, "ga4_diario", ga4_df([(f"2026-09-0{d}", d, d, d, False) for d in (1, 2, 3)]), date(2026, 9, 1), date(2026, 9, 3))
    save_dataframe(conn, "ga4_diario", ga4_df([(f"2026-09-0{d}", d, d, d, False) for d in (3, 4, 5)]), date(2026, 9, 3), date(2026, 9, 5))
    assert count(conn, "ga4_diario") == 5                       # dias 1 e 2 continuam no banco


def test_erro_de_gravacao_vira_database_write_error(tmp_path):
    conn = sqlite3.connect(":memory:")                          # sem create_schema: as tabelas não existem
    with pytest.raises(DatabaseWriteError, match="ga4_diario"):
        save_dataframe(conn, "ga4_diario", ga4_df([("2026-09-01", 1, 1, 1, False)]), date(2026, 9, 1), date(2026, 9, 1))
    write_csvs(tmp_path)
    with pytest.raises(DatabaseWriteError):                     # banco quebrado: run_all NÃO esconde o erro
        run_all(conn, base_dir=tmp_path)


# ---------- cargas a partir dos CSVs ----------
def write_csvs(base):
    paths = default_paths(base)
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    paths["ga4_diario"].write_text(
        "data,dia_semana,usuarios_ativos,sessoes,visualizacoes_pagina,sem_dados\n"
        "2026-09-01,terça,10,12,30,False\n2026-09-02,quarta,0,0,0,True\n", encoding="utf-8-sig")
    paths["gsc_diario"].write_text(
        "data,cliques,impressoes,ctr,posicao_media\n2026-09-01,4,100,0.04,7.5\n2026-09-02,0,0,,\n", encoding="utf-8-sig")
    paths["gsc_consulta_pagina"].write_text(
        "consulta,pagina,cliques,impressoes,ctr,posicao_media\n"
        "tinta,https://x.com/tintas,4,100,0.04,7.5\ncimento,https://x.com/cimento,1,40,0.025,9.1\n", encoding="utf-8-sig")
    paths["ga4_sessoes_canal"].write_text(
        "data,canal,origem,sessoes\n2026-09-01,Organic Search,google,8\n2026-09-01,Direct,(direct),4\n", encoding="utf-8-sig")
    return paths


def test_run_all_grava_tudo_e_e_idempotente(tmp_path):
    write_csvs(tmp_path)
    conn = new_db()
    first = run_all(conn, base_dir=tmp_path)
    assert first == {"ga4_diario": 2, "ga4_sessoes_canal": 2, "gsc_diario": 2, "gsc_consulta_pagina": 2}
    second = run_all(conn, base_dir=tmp_path)                   # rodar de novo: mesmos números, sem duplicar
    assert second == first
    summary = table_summary(conn).set_index("tabela")
    assert list(summary["linhas"]) == [2, 2, 2, 2]
    assert summary.loc["ga4_diario", "primeira_data"] == "2026-09-01"
    assert summary.loc["ga4_diario", "ultima_data"] == "2026-09-02"
    null_ctr = conn.execute("SELECT ctr FROM gsc_diario WHERE data = '2026-09-02'").fetchone()[0]
    assert null_ctr is None                                     # vazio vira NULL, não 0


def test_periodo_da_consulta_pagina_vem_do_csv_diario(tmp_path):
    paths = write_csvs(tmp_path)
    conn = new_db()
    load_gsc_consulta_pagina(conn, paths["gsc_consulta_pagina"], paths["gsc_diario"])
    row = conn.execute("SELECT DISTINCT periodo_inicio, periodo_fim FROM gsc_consulta_pagina").fetchall()
    assert row == [("2026-09-01", "2026-09-02")]


def test_csv_ausente_e_pulado_sem_quebrar(tmp_path):
    paths = write_csvs(tmp_path)
    paths["ga4_sessoes_canal"].unlink()
    conn = new_db()
    results = run_all(conn, base_dir=tmp_path)
    assert results["ga4_sessoes_canal"] is None and results["ga4_diario"] == 2


def test_loaders_com_csv_ausente_dao_erro_claro(tmp_path):
    conn = new_db()
    with pytest.raises(GA4ProjectError, match="ETAPA 06"):
        load_ga4_canais(conn, tmp_path / "nao_existe.csv")
    with pytest.raises(GA4ProjectError, match="ETAPA 03"):
        load_ga4_diario(conn, tmp_path / "nao_existe.csv")


# ---------- configuração do .env ----------
def test_configuracao_pelas_partes_do_env(monkeypatch):
    monkeypatch.setattr("ga_project.database.load_dotenv", lambda *a, **k: None)   # ignora o .env real
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setenv("DB_NAME", "analytics")
    monkeypatch.setenv("DB_USER", "analytics_app")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:com/símbolos")
    monkeypatch.setenv("DB_PORT", "5433")
    cfg = _connection_settings()
    assert cfg == {"host": "localhost", "port": 5433, "dbname": "analytics", "user": "analytics_app",
                   "password": "p@ss:com/símbolos"}


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

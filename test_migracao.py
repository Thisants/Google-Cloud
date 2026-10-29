"""Testes da migração do formato antigo (um cliente só) para o multi-cliente."""
import sqlite3

import pytest
from helpers import fresh_db  # noqa: F401  (registra os adaptadores de data)

from ga_project.clientes import get_cliente
from ga_project.database import create_schema, detect_legacy_tables, table_columns
from ga_project.errors import GA4ProjectError
from ga_project.migracao import migrate_legacy_to_multicliente

LEGACY_DDL = [
    "CREATE TABLE ga4_diario (data DATE PRIMARY KEY, usuarios_ativos BIGINT NOT NULL, sessoes BIGINT NOT NULL, "
    "visualizacoes_pagina BIGINT NOT NULL, sem_dados BOOLEAN NOT NULL, criado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, "
    "atualizado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE gsc_diario (data DATE PRIMARY KEY, cliques BIGINT NOT NULL, impressoes BIGINT NOT NULL, ctr DOUBLE PRECISION, "
    "posicao_media DOUBLE PRECISION, criado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, atualizado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE carga_log (fonte TEXT NOT NULL, periodo_inicio DATE, periodo_fim DATE, linhas INTEGER NOT NULL, "
    "executado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)",
]


def legacy_db():
    conn = sqlite3.connect(":memory:")
    for ddl in LEGACY_DDL:
        conn.execute(ddl)
    conn.executemany("INSERT INTO ga4_diario (data, usuarios_ativos, sessoes, visualizacoes_pagina, sem_dados) VALUES (?, ?, ?, ?, ?)",
                     [(f"2026-09-0{d}", d, d * 10, d * 20, 0) for d in range(1, 6)])
    conn.execute("UPDATE ga4_diario SET criado_em = '2026-09-10 08:00:00' WHERE data = '2026-09-01'")
    conn.executemany("INSERT INTO gsc_diario (data, cliques, impressoes, ctr, posicao_media) VALUES (?, ?, ?, ?, ?)",
                     [(f"2026-09-0{d}", d, d * 100, 0.01 * d, 7.0) for d in range(1, 4)])
    conn.execute("INSERT INTO carga_log (fonte, periodo_inicio, periodo_fim, linhas) VALUES ('ga4_diario', '2026-09-01', '2026-09-05', 5)")
    conn.commit()
    return conn


def test_migracao_copia_tudo_para_o_cliente_padrao_e_guarda_o_legado():
    conn = legacy_db()
    assert set(detect_legacy_tables(conn)) == {"ga4_diario", "gsc_diario", "carga_log"}
    copied = migrate_legacy_to_multicliente(conn)
    assert copied == {"ga4_diario": 5, "gsc_diario": 3, "carga_log": 1}
    assert get_cliente(conn, "padrao").nome.startswith("Cliente padrão")
    assert detect_legacy_tables(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM ga4_diario WHERE cliente_id = 'padrao'").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM legado_ga4_diario").fetchone()[0] == 5          # o legado NÃO é apagado
    assert conn.execute("SELECT criado_em FROM ga4_diario WHERE data = '2026-09-01'").fetchone()[0] == "2026-09-10 08:00:00"
    assert conn.execute("SELECT sessoes FROM ga4_diario WHERE data = '2026-09-03'").fetchone()[0] == 30
    assert "cliente_id" in table_columns(conn, "carga_log")


def test_depois_da_migracao_o_esquema_novo_funciona_e_a_migracao_nao_repete():
    conn = legacy_db()
    migrate_legacy_to_multicliente(conn, slug="loja-antiga", nome="Loja Antiga")
    create_schema(conn)                                                                       # não recusa mais
    assert migrate_legacy_to_multicliente(conn) == {}
    assert conn.execute("SELECT DISTINCT cliente_id FROM ga4_diario").fetchall() == [("loja-antiga",)]


def test_banco_ja_no_formato_novo_nao_e_mexido():
    conn = fresh_db()
    assert migrate_legacy_to_multicliente(conn) == {}


def test_se_o_legado_ja_existe_a_migracao_para_sem_alterar_nada():
    conn = legacy_db()
    conn.execute("CREATE TABLE legado_ga4_diario (x INTEGER)")
    with pytest.raises(GA4ProjectError, match="já existe"):
        migrate_legacy_to_multicliente(conn)
    assert "cliente_id" not in table_columns(conn, "ga4_diario")                              # continua intacta
    assert conn.execute("SELECT COUNT(*) FROM ga4_diario").fetchone()[0] == 5

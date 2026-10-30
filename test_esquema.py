"""Etapa 2: migrações versionadas (repetíveis e atômicas) e restrições de integridade do esquema."""
import sqlite3
from datetime import date

import pandas as pd
import pytest
from helpers import fresh_db

from ga_project.clientes import ensure_cliente
from ga_project.database import (
    LATEST_VERSION,
    DatabaseWriteError,
    apply_migrations,
    create_schema,
    current_version,
    save_dataframe,
    table_columns,
)
from ga_project.errors import GA4ProjectError

A = "cliente-a"


def table_exists(conn, name):
    return bool(table_columns(conn, name))


# ---------- migrações ----------
def test_banco_novo_sobe_para_a_ultima_versao_e_repetir_nao_muda_nada():
    conn = sqlite3.connect(":memory:")
    assert current_version(conn) == 0
    assert apply_migrations(conn) == [LATEST_VERSION]
    assert current_version(conn) == LATEST_VERSION
    assert apply_migrations(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    create_schema(conn)                                                         # também é repetível
    assert current_version(conn) == LATEST_VERSION


def test_migracoes_pendentes_rodam_em_ordem_e_so_as_que_faltam():
    conn = sqlite3.connect(":memory:")
    base = [(1, "a", ["CREATE TABLE t1 (x INTEGER)"]), (2, "b", ["CREATE TABLE t2 (x INTEGER)"])]
    assert apply_migrations(conn, list(reversed(base))) == [1, 2]               # a ordem da lista não importa
    more = base + [(3, "c", ["CREATE TABLE t3 (x INTEGER)"])]
    assert apply_migrations(conn, more) == [3]
    assert current_version(conn) == 3 and table_exists(conn, "t3")


def test_migracao_que_falha_nao_deixa_nada_pela_metade():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, [(1, "a", ["CREATE TABLE t1 (x INTEGER)"])])
    broken = [(1, "a", ["CREATE TABLE t1 (x INTEGER)"]),
              (2, "b", ["CREATE TABLE t2 (x INTEGER)", "COMANDO QUE NAO E SQL"])]
    with pytest.raises(DatabaseWriteError, match="NADA foi alterado"):
        apply_migrations(conn, broken)
    assert current_version(conn) == 1                                           # a versão não avançou
    assert not table_exists(conn, "t2")                                         # nem a tabela criada antes do erro


def test_falha_na_primeira_execucao_tambem_desfaz_tudo():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(DatabaseWriteError):
        apply_migrations(conn, [(1, "a", ["CREATE TABLE t1 (x INTEGER)", "COMANDO QUE NAO E SQL"])])
    assert not table_exists(conn, "t1") and not table_exists(conn, "schema_migrations")


def test_banco_mais_novo_que_o_codigo_e_recusado_sem_alterar_nada():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, [(1, "a", ["CREATE TABLE t1 (x INTEGER)"]), (2, "b", ["CREATE TABLE t2 (x INTEGER)"])])
    with pytest.raises(GA4ProjectError, match="mais nova"):
        apply_migrations(conn, [(1, "a", ["CREATE TABLE t1 (x INTEGER)"])])
    assert current_version(conn) == 2


def test_banco_com_tabelas_mas_sem_controle_de_versao_e_adotado_sem_perder_dados():
    conn = fresh_db()
    ensure_cliente(conn, A, "Cliente A")
    conn.execute("DROP TABLE schema_migrations")                                # simula um banco criado antes do controle de versão
    conn.commit()
    assert current_version(conn) == 0
    assert apply_migrations(conn) == [LATEST_VERSION]                           # IF NOT EXISTS: não quebra nem recria
    assert conn.execute("SELECT slug FROM clientes").fetchall() == [(A,)]       # os dados continuam


# ---------- restrições de integridade ----------
def insert(conn, sql, params=()):
    conn.execute(sql, params)


@pytest.mark.parametrize("sql", [
    "INSERT INTO ga4_diario (cliente_id, data, usuarios_ativos, sessoes, visualizacoes_pagina, sem_dados) VALUES ('cliente-a','2026-09-01',1,-5,1,0)",
    "INSERT INTO ga4_sessoes_canal (cliente_id, data, canal, origem, sessoes) VALUES ('cliente-a','2026-09-01','Direct','(direct)',-1)",
    "INSERT INTO gsc_diario (cliente_id, data, cliques, impressoes, ctr, posicao_media) VALUES ('cliente-a','2026-09-01',1,10,1.5,5)",
    "INSERT INTO gsc_diario (cliente_id, data, cliques, impressoes, ctr, posicao_media) VALUES ('cliente-a','2026-09-01',1,10,0.1,-2)",
    "INSERT INTO gsc_diario (cliente_id, data, cliques, impressoes, ctr, posicao_media) VALUES ('cliente-a','2026-09-01',-1,10,0.1,5)",
    "INSERT INTO gsc_consulta_pagina (cliente_id, periodo_inicio, periodo_fim, consulta, pagina, cliques, impressoes) VALUES ('cliente-a','2026-09-10','2026-09-01','q','/p',1,2)",
    "INSERT INTO execucoes (cliente_id, tipo, status, linhas, inicio, fim) VALUES ('cliente-a','coleta','talvez',0,'2026-09-01','2026-09-01')",
    "INSERT INTO insights (cliente_id, gerado_em, tipo, severidade, regra, titulo, detalhe) VALUES ('cliente-a','2026-09-01','erro-de-tipo','alta','r','t','d')",
    "INSERT INTO insights (cliente_id, gerado_em, tipo, severidade, regra, titulo, detalhe) VALUES ('cliente-a','2026-09-01','risco','gravissima','r','t','d')",
    "INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) VALUES ('aaaaaaaa', NULL, 'cliente', 'x', 'h1')",
    "INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) VALUES ('bbbbbbbb', 'cliente-a', 'admin', 'x', 'h2')",
    "INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) VALUES ('cccccccc', 'cliente-a', 'dono', 'x', 'h3')",
    "INSERT INTO clientes (slug, nome) VALUES ('x', 'Slug curto demais')",
    "INSERT INTO carga_log (cliente_id, fonte, linhas) VALUES ('cliente-a', 'ga4_diario', -3)",
])
def test_o_banco_recusa_dados_invalidos(sql):
    conn = fresh_db()
    ensure_cliente(conn, A, "Cliente A")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_o_banco_aceita_os_casos_validos_equivalentes():
    conn = fresh_db()
    ensure_cliente(conn, A, "Cliente A")
    conn.execute("INSERT INTO gsc_diario (cliente_id, data, cliques, impressoes, ctr, posicao_media) VALUES ('cliente-a','2026-09-01',0,0,NULL,NULL)")
    conn.execute("INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) VALUES ('aaaaaaaa', NULL, 'admin', 'x', 'h1')")
    conn.execute("INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) VALUES ('bbbbbbbb', 'cliente-a', 'cliente', 'x', 'h2')")
    conn.execute("INSERT INTO insights (cliente_id, gerado_em, tipo, severidade, regra, titulo, detalhe) VALUES ('cliente-a','2026-09-01','risco','média','r','t','d')")
    conn.commit()


def test_gravacao_com_valor_invalido_faz_rollback_completo():
    conn = fresh_db()
    ensure_cliente(conn, A, "Cliente A")
    df = pd.DataFrame({"data": pd.to_datetime(["2026-09-01", "2026-09-02"]), "usuarios_ativos": [1, 1], "sessoes": [10, -4],
                       "visualizacoes_pagina": [2, 2], "sem_dados": [False, False]})
    with pytest.raises(DatabaseWriteError, match="ga4_diario"):
        save_dataframe(conn, "ga4_diario", df, date(2026, 9, 1), date(2026, 9, 2), cliente_id=A)
    assert conn.execute("SELECT COUNT(*) FROM ga4_diario").fetchone()[0] == 0            # nem a linha boa ficou
    assert conn.execute("SELECT COUNT(*) FROM carga_log").fetchone()[0] == 0              # nem o registro da carga

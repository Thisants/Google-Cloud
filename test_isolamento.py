"""Isolamento entre clientes: nenhuma leitura pode devolver dado de outro cliente."""
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest
from helpers import expected_sessions, fresh_db, populate

from ga_project.agent import Agent
from ga_project.agent_tools import execute_tool
from ga_project.dashboard_data import (
    load_carteira, load_channels, load_daily, load_date_range, load_last_loads, load_top_queries,
)
from ga_project.insights import generate_insights, load_saved_insights, refresh_insights, save_insights

TODAY = date(2026, 9, 22)
A, B = "loja-1", "loja-10"           # slugs parecidos de propósito (um é prefixo do outro)


def two_clients():
    conn = fresh_db()
    populate(conn, A, base=100)
    populate(conn, B, base=1000)
    return conn


def test_leituras_devolvem_so_o_proprio_cliente():
    conn = two_clients()
    for slug, base in ((A, 100), (B, 1000)):
        daily = load_daily(conn, date(2026, 9, 1), date(2026, 9, 20), cliente_id=slug)
        assert len(daily) == 20 and int(daily["sessoes"].sum()) == expected_sessions(base, 20)
        channels = load_channels(conn, date(2026, 9, 1), date(2026, 9, 20), cliente_id=slug)
        assert int(channels["sessoes"].sum()) == 2 * sum((base + i) // 2 for i in range(20))
        assert list(load_top_queries(conn, 10, cliente_id=slug)["consulta"]) == [f"consulta-{slug}"]
        assert set(load_last_loads(conn, cliente_id=slug)["fonte"]) == {"ga4_diario", "ga4_sessoes_canal", "gsc_diario", "gsc_consulta_pagina"}
        assert load_date_range(conn, cliente_id=slug) == (date(2026, 9, 1), date(2026, 9, 20))


def test_cliente_sem_dados_recebe_vazio_e_nunca_os_dados_de_outro():
    conn = two_clients()
    assert load_date_range(conn, cliente_id="ninguem") is None
    assert load_daily(conn, date(2026, 9, 1), date(2026, 9, 20), cliente_id="ninguem").empty
    assert load_top_queries(conn, 10, cliente_id="ninguem").empty
    assert load_channels(conn, date(2026, 9, 1), date(2026, 9, 20), cliente_id="ninguem").empty


def test_ferramentas_do_agente_so_veem_o_cliente_informado():
    conn = two_clients()
    for slug, base in ((A, 100), (B, 1000)):
        summary = json.loads(execute_tool("get_period_summary", {"inicio": "2026-09-01", "fim": "2026-09-20"}, conn, True, TODAY, cliente_id=slug))
        sessions = {k["nome"]: k["valor"] for k in summary["kpis"]}["Sessões"]
        assert sessions == expected_sessions(base, 20)
        queries = json.loads(execute_tool("get_top_queries", {}, conn, True, TODAY, cliente_id=slug))["consultas"]
        assert [q["consulta"] for q in queries] == [f"consulta-{slug}"]


def test_o_modelo_nao_consegue_escolher_outro_cliente_pelos_argumentos():
    conn = two_clients()
    sneaky = {"inicio": "2026-09-01", "fim": "2026-09-20", "cliente_id": B, "cliente": B, "slug": B}
    summary = json.loads(execute_tool("get_period_summary", sneaky, conn, True, TODAY, cliente_id=A))
    assert {k["nome"]: k["valor"] for k in summary["kpis"]}["Sessões"] == expected_sessions(100, 20)


def test_agente_ligado_a_um_cliente_so_recebe_dados_dele():
    conn = two_clients()
    calls = []

    class Fake:
        messages = None

        def __init__(self):
            self.messages = self
            self.script = [
                NS(content=[NS(type="tool_use", id="t1", name="get_period_summary", input={"inicio": "2026-09-01", "fim": "2026-09-20"})],
                   stop_reason="tool_use", usage=NS(input_tokens=1, output_tokens=1)),
                NS(content=[NS(type="text", text="ok")], stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1)),
            ]

        def create(self, **kwargs):
            calls.append({**kwargs, "messages": list(kwargs["messages"])})
            return self.script.pop(0)

    agent = Agent(Fake(), conn, cliente_id=B, cliente_nome="Loja Dez", today=TODAY)
    agent.ask("resuma")
    assert "Loja Dez" in calls[0]["system"]
    result = calls[1]["messages"][-1]["content"][0]["content"]
    assert str(expected_sessions(1000, 20)) in result and str(expected_sessions(100, 20)) not in result


def test_insights_guardados_sao_por_cliente():
    conn = two_clients()
    assert refresh_insights(conn, A, TODAY) >= 0
    save_only_b = generate_insights(conn, TODAY, cliente_id=B)[0]
    save_insights(conn, B, save_only_b, TODAY)
    assert load_saved_insights(conn, A).equals(load_saved_insights(conn, A))
    mine, other = load_saved_insights(conn, B), load_saved_insights(conn, A)
    assert len(mine) == len(save_only_b)
    assert not any(f"consulta-{A}" in text for text in mine["detalhe"].tolist() + mine["titulo"].tolist())
    assert not any(f"consulta-{B}" in text for text in other["detalhe"].tolist() + other["titulo"].tolist())


def test_substituir_insights_de_um_cliente_nao_apaga_os_do_outro():
    conn = two_clients()
    df_b = generate_insights(conn, TODAY, cliente_id=B)[0]
    save_insights(conn, B, df_b, TODAY)
    save_insights(conn, A, generate_insights(conn, TODAY, cliente_id=A)[0], TODAY)
    save_insights(conn, A, df_b.iloc[0:0], TODAY)                                  # limpa só o A
    assert load_saved_insights(conn, A).empty and len(load_saved_insights(conn, B)) == len(df_b)


def test_carteira_calcula_por_cliente_com_poucas_consultas():
    conn = two_clients()
    refresh_insights(conn, A, TODAY)
    df = load_carteira(conn, [A, B, "sem-dados"], today=date(2026, 9, 22)).set_index("cliente_id")
    assert df.loc[A, "ultima_data"] == date(2026, 9, 20) and df.loc[B, "ultima_data"] == date(2026, 9, 20)
    assert df.loc[A, "sessoes_7d"] == sum(100 + i for i in range(13, 20))
    assert df.loc[B, "sessoes_7d"] == sum(1000 + i for i in range(13, 20))
    assert df.loc["sem-dados"].isna()["ultima_data"] or df.loc["sem-dados", "ultima_data"] is None

"""Testes da ETAPA 10: ferramentas (SQLite) e loop do agente com um cliente FALSO. Sem internet, sem chave de API."""
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest
from test_insights import CLI, build_db   # banco de teste: 20 dias (01 a 20/09/2026), GA4 + Search Console

from ga_project.agent import DEFAULT_MODEL, MAX_STEPS, Agent, load_agent_settings
from ga_project.agent_tools import _clean, available_tools, execute_tool
from ga_project.errors import GA4ProjectError

TODAY = date(2026, 9, 22)


def run_tool(conn, name, args=None, allow_queries=True):
    return json.loads(execute_tool(name, args, conn, allow_queries, TODAY, cliente_id=CLI))


# ---------- ferramentas ----------
def test_cobertura_dos_dados():
    data = run_tool(build_db(), "get_data_coverage")
    assert (data["primeira_data"], data["ultima_data"]) == ("2026-09-01", "2026-09-20")
    assert {r["fonte"] for r in data["ultimas_cargas"]} >= {"ga4_diario", "gsc_diario"}


def test_resumo_do_periodo_com_variacao():
    data = run_tool(build_db(), "get_period_summary", {"inicio": "2026-09-14", "fim": "2026-09-20"})
    kpis = {k["nome"]: k for k in data["kpis"]}
    assert kpis["Sessões"]["valor"] == 315                             # 7 dias x 45
    assert round(kpis["Sessões"]["variacao"], 1) == -41.1              # 315 contra 535 no período anterior
    assert kpis["CTR (Search Console)"]["tipo_variacao"] == "pontos percentuais"
    assert data["periodo_anterior"]["inicio"] == "2026-09-07"


def test_periodo_e_ajustado_ao_intervalo_do_banco():
    data = run_tool(build_db(), "get_daily_metrics", {"inicio": "2026-08-01", "fim": "2026-09-05"})
    assert data["periodo"] == {"inicio": "2026-09-01", "fim": "2026-09-05"} and len(data["dias"]) == 5
    assert data["dias"][0]["data"] == "2026-09-01"


def test_parametros_invalidos_viram_erro_claro():
    conn = build_db()
    with pytest.raises(GA4ProjectError, match="AAAA-MM-DD"):
        execute_tool("get_period_summary", {"inicio": "ontem", "fim": "2026-09-20"}, conn, True, TODAY, cliente_id=CLI)
    with pytest.raises(GA4ProjectError, match="depois da data final"):
        execute_tool("get_period_summary", {"inicio": "2026-09-20", "fim": "2026-09-01"}, conn, True, TODAY, cliente_id=CLI)
    with pytest.raises(GA4ProjectError, match="no máximo 120"):
        execute_tool("get_daily_metrics", {"inicio": "2026-01-01", "fim": "2026-09-20"}, conn, True, TODAY, cliente_id=CLI)
    with pytest.raises(GA4ProjectError, match="fora do intervalo"):
        execute_tool("get_daily_metrics", {"inicio": "2025-01-01", "fim": "2025-01-10"}, conn, True, TODAY, cliente_id=CLI)
    with pytest.raises(GA4ProjectError, match="desconhecida"):
        execute_tool("apagar_tudo", {}, conn, True, TODAY, cliente_id=CLI)


def test_canais_com_participacao():
    data = run_tool(build_db(), "get_channel_breakdown", {"inicio": "2026-09-01", "fim": "2026-09-20"})
    assert [c["canal"] for c in data["canais"]] == ["Organic Search", "Direct"]
    assert round(sum(c["participacao_pct"] for c in data["canais"])) == 100


def test_privacidade_bloqueia_consultas_e_esconde_insights_que_citam_paginas():
    conn = build_db()
    assert "get_top_queries" in {t["name"] for t in available_tools(True)}
    assert "get_top_queries" not in {t["name"] for t in available_tools(False)}
    assert run_tool(conn, "get_top_queries", {"limite": 5})["consultas"][0]["consulta"] == "tinta"
    with pytest.raises(GA4ProjectError, match="privacidade"):
        execute_tool("get_top_queries", {}, conn, False, TODAY, cliente_id=CLI)
    regras_com = {i["regra"] for i in run_tool(conn, "get_insights")["insights"]}
    regras_sem = {i["regra"] for i in run_tool(conn, "get_insights", allow_queries=False)["insights"]}
    assert "ctr_baixo" in regras_com and "ctr_baixo" not in regras_sem
    assert "queda_sessoes" in regras_sem                               # insights sem consultas continuam


def test_limite_de_consultas_e_ajustado():
    assert len(run_tool(build_db(), "get_top_queries", {"limite": 9999})["consultas"]) == 1   # só há 1 no banco de teste
    with pytest.raises(GA4ProjectError, match="inteiro"):
        execute_tool("get_top_queries", {"limite": "muitas"}, build_db(), True, TODAY, cliente_id=CLI)


def test_json_nao_tem_nan_nem_datas_de_python():
    assert _clean(float("nan")) is None and _clean(None) is None
    assert _clean(date(2026, 9, 1)) == "2026-09-01"
    assert _clean(3.14159265) == 3.1416


# ---------- loop do agente (cliente falso) ----------
def tool_use(tool_id, name, args):
    return NS(type="tool_use", id=tool_id, name=name, input=args)


def reply(blocks, stop_reason, tokens=(10, 5)):
    return NS(content=blocks, stop_reason=stop_reason, usage=NS(input_tokens=tokens[0], output_tokens=tokens[1]))


def text_reply(text, stop_reason="end_turn"):
    return reply([NS(type="text", text=text)], stop_reason)


class FakeClient:
    """Imita client.messages.create(...): devolve as respostas combinadas, na ordem."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def test_agente_chama_ferramenta_devolve_resultado_e_responde():
    client = FakeClient([reply([tool_use("t1", "get_data_coverage", {})], "tool_use"), text_reply("Há dados até 20/09.")])
    agent = Agent(client, build_db(), cliente_id=CLI, today=TODAY)
    assert agent.ask("Até quando há dados?") == "Há dados até 20/09."

    assert len(client.calls) == 2 and agent.tool_calls == ["get_data_coverage"]
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    result = second[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1" and "is_error" not in result
    assert "2026-09-20" in result["content"]
    assert client.calls[0]["model"] == DEFAULT_MODEL and "22/09/2026" in client.calls[0]["system"]
    assert (agent.input_tokens, agent.output_tokens) == (20, 10)


def test_erro_de_ferramenta_vira_tool_result_com_is_error():
    bad = tool_use("t9", "get_period_summary", {"inicio": "ontem", "fim": "hoje"})
    client = FakeClient([reply([bad], "tool_use"), text_reply("Não consegui consultar esse período.")])
    agent = Agent(client, build_db(), cliente_id=CLI, today=TODAY)
    assert "Não consegui" in agent.ask("Resuma ontem")
    result = client.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "AAAA-MM-DD" in result["content"]


def test_erro_inesperado_em_ferramenta_nao_derruba_a_conversa(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("falha qualquer")

    monkeypatch.setattr("ga_project.agent.execute_tool", boom)
    client = FakeClient([reply([tool_use("t1", "get_insights", {})], "tool_use"), text_reply("Ok, sem insights.")])
    agent = Agent(client, build_db(), cliente_id=CLI, today=TODAY)
    assert agent.ask("insights?") == "Ok, sem insights."
    result = client.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "RuntimeError" in result["content"]


def test_limite_de_rodadas_evita_loop_infinito():
    client = FakeClient([reply([tool_use("t1", "get_data_coverage", {})], "tool_use")])    # sempre pede ferramenta
    agent = Agent(client, build_db(), cliente_id=CLI, today=TODAY, max_steps=3)
    with pytest.raises(GA4ProjectError, match="3 rodadas"):
        agent.ask("pergunta sem fim")
    assert len(client.calls) == 4                                                          # 3 rodadas + a chamada que estourou


def test_memoria_guarda_so_o_texto_das_perguntas_anteriores():
    client = FakeClient([text_reply("Resposta 1."), text_reply("Resposta 2.")])
    agent = Agent(client, build_db(), cliente_id=CLI, today=TODAY)
    agent.ask("Pergunta 1")
    agent.ask("Pergunta 2")
    assert [m["content"] for m in client.calls[1]["messages"]] == ["Pergunta 1", "Resposta 1.", "Pergunta 2"]


def test_resposta_cortada_por_max_tokens_avisa():
    client = FakeClient([text_reply("Começo da resposta", stop_reason="max_tokens")])
    assert "cortada" in Agent(client, build_db(), cliente_id=CLI, today=TODAY).ask("pergunta")


def test_sem_consultas_a_ferramenta_nao_e_oferecida_ao_modelo():
    client = FakeClient([text_reply("ok")])
    Agent(client, build_db(), cliente_id=CLI, today=TODAY, allow_queries=False).ask("oi")
    assert "get_top_queries" not in {t["name"] for t in client.calls[0]["tools"]}


def test_max_steps_padrao():
    assert MAX_STEPS == 8


# ---------- configuração ----------
def test_configuracao_do_agente(monkeypatch):
    monkeypatch.setattr("ga_project.agent.load_dotenv", lambda *a, **k: None)          # ignora o .env real
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "AGENT_SEND_QUERIES"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(GA4ProjectError, match="ANTHROPIC_API_KEY"):
        load_agent_settings()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    settings = load_agent_settings()
    assert settings.model == DEFAULT_MODEL and settings.allow_queries is True

    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("AGENT_SEND_QUERIES", "false")
    settings = load_agent_settings()
    assert settings.model == "claude-haiku-5-5" and settings.allow_queries is False

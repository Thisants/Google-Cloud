"""Testes da API (ETAPA 11) com o TestClient do FastAPI. Sem internet, sem PostgreSQL e sem chave da Anthropic.

Usa um banco SQLite em arquivo. Se o FastAPI/httpx não estiverem instalados, o arquivo é pulado.
"""
import sqlite3
from datetime import date

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient            # noqa: E402
from test_insights import build_db                   # noqa: E402

from ga_project.api import create_app                # noqa: E402
from ga_project.api_core import ApiSettings          # noqa: E402
from ga_project.errors import GA4ProjectError        # noqa: E402

sqlite3.register_adapter(date, lambda d: d.isoformat())

KEY = "k" * 32
HEADERS = {"X-API-Key": KEY}


class FakeAgent:
    input_tokens, output_tokens, tool_calls = 11, 7, ["get_data_coverage"]

    def ask(self, question):
        return f"Resposta para: {question}"


def make_client(tmp_path, enable_agent=True, max_per_hour=2, connect_fn=None):
    db_path = tmp_path / "api.db"
    build_db().backup(sqlite3.connect(db_path))
    counter = {"connects": 0}

    def default_connect():
        counter["connects"] += 1
        return sqlite3.connect(db_path, check_same_thread=False)   # a API usa threads diferentes por requisição

    settings = ApiSettings(api_key=KEY, enable_agent=enable_agent, agent_max_per_hour=max_per_hour)
    app = create_app(settings, connect_fn=connect_fn or default_connect, agent_factory=lambda conn: FakeAgent())
    return TestClient(app), counter


def test_health_nao_exige_chave(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_sem_chave_ou_chave_errada_da_401_sem_tocar_no_banco(tmp_path):
    client, counter = make_client(tmp_path)
    assert client.get("/v1/cobertura").status_code == 401
    assert client.get("/v1/cobertura", headers={"X-API-Key": "errada"}).status_code == 401
    assert client.post("/v1/perguntar", json={"pergunta": "oi, tudo bem?"}).status_code == 401
    assert counter["connects"] == 0                                   # a chave é conferida ANTES de abrir o banco


def test_cobertura_e_resumo(tmp_path):
    client, _ = make_client(tmp_path)
    cobertura = client.get("/v1/cobertura", headers=HEADERS)
    assert cobertura.status_code == 200 and cobertura.json()["ultima_data"] == "2026-09-20"

    resumo = client.get("/v1/resumo", params={"inicio": "2026-09-14", "fim": "2026-09-20"}, headers=HEADERS)
    assert resumo.status_code == 200
    kpis = {k["nome"]: k for k in resumo.json()["kpis"]}
    assert kpis["Sessões"]["valor"] == 315


def test_parametros_invalidos(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/v1/resumo", params={"inicio": "ontem", "fim": "2026-09-20"}, headers=HEADERS).status_code == 422
    assert client.get("/v1/resumo", headers=HEADERS).status_code == 422                       # faltam parâmetros
    inverted = client.get("/v1/resumo", params={"inicio": "2026-09-20", "fim": "2026-09-01"}, headers=HEADERS)
    assert inverted.status_code == 400 and "depois da data final" in inverted.json()["detail"]
    assert client.get("/v1/consultas", params={"limite": 999}, headers=HEADERS).status_code == 422


def test_diario_canais_consultas_e_insights(tmp_path):
    client, _ = make_client(tmp_path)
    period = {"inicio": "2026-09-01", "fim": "2026-09-05"}
    assert len(client.get("/v1/diario", params=period, headers=HEADERS).json()["dias"]) == 5
    canais = client.get("/v1/canais", params=period, headers=HEADERS).json()["canais"]
    assert {c["canal"] for c in canais} == {"Organic Search", "Direct"}
    assert client.get("/v1/consultas", params={"limite": 5}, headers=HEADERS).json()["consultas"][0]["consulta"] == "tinta"
    regras = {i["regra"] for i in client.get("/v1/insights", headers=HEADERS).json()["insights"]}
    assert "queda_sessoes" in regras


def test_agente_desligado_por_padrao_da_403(tmp_path):
    client, _ = make_client(tmp_path, enable_agent=False)
    response = client.post("/v1/perguntar", json={"pergunta": "Como estão as sessões?"}, headers=HEADERS)
    assert response.status_code == 403 and "desativado" in response.json()["detail"]


def test_agente_responde_e_o_limite_por_hora_vale(tmp_path):
    client, _ = make_client(tmp_path, enable_agent=True, max_per_hour=2)
    body = {"pergunta": "Como estão as sessões?"}
    first = client.post("/v1/perguntar", json=body, headers=HEADERS)
    assert first.status_code == 200
    assert first.json()["resposta"] == "Resposta para: Como estão as sessões?"
    assert first.json()["uso"]["tokens_entrada"] == 11
    assert client.post("/v1/perguntar", json=body, headers=HEADERS).status_code == 200
    assert client.post("/v1/perguntar", json=body, headers=HEADERS).status_code == 429


def test_pergunta_invalida_da_422(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/v1/perguntar", json={"pergunta": "oi"}, headers=HEADERS).status_code == 422        # curta demais
    assert client.post("/v1/perguntar", json={"pergunta": "x" * 1001}, headers=HEADERS).status_code == 422


def test_banco_fora_do_ar_da_503_sem_vazar_detalhes(tmp_path):
    def broken():
        raise GA4ProjectError("senha=SEGREDO host=10.0.0.5")

    client, _ = make_client(tmp_path, connect_fn=broken)
    response = client.get("/v1/cobertura", headers=HEADERS)
    assert response.status_code == 503
    assert "SEGREDO" not in response.text and "10.0.0.5" not in response.text

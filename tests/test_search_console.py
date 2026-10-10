"""Testes da ETAPA 05: sem internet, sem credenciais (usam um serviço falso)."""
from datetime import date
from types import SimpleNamespace as NS

import httplib2
import pandas as pd
import pytest
from googleapiclient.errors import HttpError

from ga_project.errors import GA4ProjectError
from ga_project.search_console import (
    build_date_report,
    build_query_page_report,
    fetch_search_analytics,
    get_site_url,
    gsc_date_range,
    rows_to_dataframe,
)


def row(keys, clicks, impressions, ctr, position):
    return {"keys": keys, "clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position}


def _result(item):
    if isinstance(item, Exception):
        raise item
    return item


class FakeService:
    """Imita service.searchanalytics().query(siteUrl=..., body=...).execute()."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.bodies.append(body)
        item = self.responses.pop(0)
        return NS(execute=lambda: _result(item))


def http_error(status):
    return HttpError(httplib2.Response({"status": status}), b'{"error": {"message": "detalhe"}}')


def test_gsc_date_range_termina_3_dias_atras_e_tem_30_dias():
    start, end = gsc_date_range(30, 3, today=date(2026, 10, 9))
    assert end == date(2026, 10, 6)
    assert start == date(2026, 9, 7)
    assert (end - start).days + 1 == 30


def test_rows_to_dataframe_tipos_e_ordem():
    df = rows_to_dataframe(
        [row(["2026-09-02"], 5.0, 100, 0.05123, 8.46), row(["2026-09-01"], 3, 80, 0.0375, 9.04)],
        ["date"],
    )
    assert list(df.columns) == ["date", "clicks", "impressions", "ctr", "position"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_integer_dtype(df["clicks"])
    assert df["date"].is_monotonic_increasing
    assert df.loc[1, "ctr"] == 0.0512 and df.loc[1, "position"] == 8.5


def test_rows_to_dataframe_vazio():
    df = rows_to_dataframe([], ["query", "page"])
    assert df.empty
    assert list(df.columns) == ["query", "page", "clicks", "impressions", "ctr", "position"]


def test_paginacao_continua_ate_vir_pagina_incompleta():
    service = FakeService(
        [
            {"rows": [row(["a"], 1, 10, 0.1, 1.0), row(["b"], 1, 10, 0.1, 2.0)]},
            {"rows": [row(["c"], 1, 10, 0.1, 3.0)]},
        ]
    )
    df = fetch_search_analytics(service, "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 30), ["query"], page_size=2)
    assert len(df) == 3
    assert [b["startRow"] for b in service.bodies] == [0, 2]


def test_max_rows_limita_o_total():
    service = FakeService(
        [
            {"rows": [row(["a"], 1, 10, 0.1, 1.0), row(["b"], 1, 10, 0.1, 2.0)]},
            {"rows": [row(["c"], 1, 10, 0.1, 3.0)]},
        ]
    )
    df = fetch_search_analytics(
        service, "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 30), ["query"], max_rows=3, page_size=2
    )
    assert len(df) == 3
    assert service.bodies[1]["rowLimit"] == 1


def test_resposta_sem_linhas_da_dataframe_vazio():
    service = FakeService([{}])
    df = fetch_search_analytics(service, "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 30), ["date"])
    assert df.empty


def test_erro_403_vira_mensagem_clara():
    service = FakeService([http_error(403)])
    with pytest.raises(GA4ProjectError, match="permissão"):
        fetch_search_analytics(service, "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 30), ["date"])


def test_erro_400_e_404():
    with pytest.raises(GA4ProjectError, match="inválida"):
        fetch_search_analytics(FakeService([http_error(400)]), "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 2), ["date"])
    with pytest.raises(GA4ProjectError, match="não encontrada"):
        fetch_search_analytics(FakeService([http_error(404)]), "sc-domain:x.com", date(2026, 9, 1), date(2026, 9, 2), ["date"])


def test_relatorio_por_data_preenche_dia_sem_impressao():
    raw = rows_to_dataframe(
        [row(["2026-09-01"], 4, 100, 0.04, 7.2), row(["2026-09-03"], 6, 120, 0.05, 6.1)], ["date"]
    )
    df = build_date_report(raw, date(2026, 9, 1), date(2026, 9, 3))
    assert list(df.columns) == ["data", "cliques", "impressoes", "ctr", "posicao_media"]
    assert len(df) == 3
    dia_2 = df[df["data"] == "2026-09-02"].iloc[0]
    assert dia_2["cliques"] == 0 and dia_2["impressoes"] == 0
    assert pd.isna(dia_2["ctr"]) and pd.isna(dia_2["posicao_media"])
    assert pd.api.types.is_integer_dtype(df["cliques"])


def test_relatorio_por_data_com_resposta_vazia_nao_quebra():
    raw = rows_to_dataframe([], ["date"])
    df = build_date_report(raw, date(2026, 9, 1), date(2026, 9, 3))
    assert len(df) == 3 and (df["cliques"] == 0).all()


def test_relatorio_consulta_pagina_ordena_por_cliques():
    raw = rows_to_dataframe(
        [row(["a", "/p1"], 1, 50, 0.02, 9.0), row(["b", "/p2"], 9, 70, 0.12, 3.0)], ["query", "page"]
    )
    df = build_query_page_report(raw)
    assert list(df.columns)[:2] == ["consulta", "pagina"]
    assert df.loc[0, "consulta"] == "b"


def test_get_site_url(monkeypatch):
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:exemplo.com.br")
    assert get_site_url() == "sc-domain:exemplo.com.br"
    monkeypatch.setenv("GSC_SITE_URL", "exemplo.com.br")      # sem prefixo: inválido
    with pytest.raises(GA4ProjectError, match="GSC_SITE_URL"):
        get_site_url()
    monkeypatch.delenv("GSC_SITE_URL")
    with pytest.raises(GA4ProjectError, match="GSC_SITE_URL"):
        get_site_url()

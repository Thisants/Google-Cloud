"""Testes da ETAPA 06: sem internet, sem credenciais."""
import math
from datetime import date

import pandas as pd
import pytest

from ga_project.errors import GA4ProjectError
from ga_project.integracao import (
    channel_totals,
    integration_summary,
    merge_sources,
    read_gsc_by_date_csv,
    rename_ga4_channels,
    summarize_ga4_by_date,
)


def ga4_raw(rows):
    """rows = [(data, canal, origem, sessoes), ...] no formato bruto do GA4."""
    df = pd.DataFrame(rows, columns=["date", "sessionDefaultChannelGroup", "sessionSource", "sessions"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def gsc_daily(rows):
    """rows = [(data, cliques, impressoes), ...]"""
    df = pd.DataFrame(rows, columns=["data", "cliques", "impressoes"])
    df["data"] = pd.to_datetime(df["data"])
    df["ctr"] = 0.05
    df["posicao_media"] = 8.0
    return df


RAW = ga4_raw(
    [
        ("2026-09-01", "Organic Search", "google", 40),
        ("2026-09-01", "Organic Search", "bing", 5),      # orgânico, mas não é Google
        ("2026-09-01", "Direct", "(direct)", 30),
        ("2026-09-03", "Organic Search", "google", 50),
        ("2026-09-03", "Paid Search", "google", 20),      # Google, mas pago
    ]
)


def test_resumo_ga4_so_conta_organico_do_google_e_cria_dia_ausente():
    daily = summarize_ga4_by_date(RAW, date(2026, 9, 1), date(2026, 9, 3))
    assert list(daily.columns) == ["data", "ga4_sessoes_total", "ga4_sessoes_organicas_google"]
    assert len(daily) == 3
    assert daily.loc[0, "ga4_sessoes_total"] == 75 and daily.loc[0, "ga4_sessoes_organicas_google"] == 40
    assert daily.loc[1, "ga4_sessoes_total"] == 0 and daily.loc[1, "ga4_sessoes_organicas_google"] == 0
    assert daily.loc[2, "ga4_sessoes_total"] == 70 and daily.loc[2, "ga4_sessoes_organicas_google"] == 50
    assert pd.api.types.is_integer_dtype(daily["ga4_sessoes_total"])


def test_resumo_ga4_com_resposta_vazia_nao_quebra():
    empty = ga4_raw([])
    daily = summarize_ga4_by_date(empty, date(2026, 9, 1), date(2026, 9, 2))
    assert len(daily) == 2 and (daily["ga4_sessoes_total"] == 0).all()


def test_totais_por_canal_ordenados_e_somam_100():
    totals = channel_totals(RAW)
    assert totals.loc[0, "canal"] == "Organic Search"        # 95 sessões
    assert totals["sessoes"].sum() == 145
    assert round(totals["pct"].sum()) == 100


def test_rename_ga4_channels():
    assert list(rename_ga4_channels(RAW).columns) == ["data", "canal", "origem", "sessoes"]


def test_merge_junta_so_datas_em_comum_e_calcula_derivadas():
    ga4 = summarize_ga4_by_date(RAW, date(2026, 9, 1), date(2026, 9, 3))
    gsc = gsc_daily([("2026-09-01", 20, 400), ("2026-09-02", 0, 0), ("2026-09-04", 9, 100)])
    merged, info = merge_sources(ga4, gsc)
    assert info["dias_em_comum"] == 2                          # 01 e 02; o dia 04 só existe no GSC
    assert info["periodo_comum"] == ("2026-09-01", "2026-09-02")
    day1 = merged.iloc[0]
    assert day1["dia_semana"] == "terça"                       # 01/09/2026 é terça-feira
    assert day1["pct_organico_google"] == round(40 / 75 * 100, 1)
    assert day1["sessoes_por_clique"] == 2.0                   # 40 sessões / 20 cliques
    day2 = merged.iloc[1]                                      # dia sem dados e sem cliques
    assert math.isnan(day2["pct_organico_google"]) and math.isnan(day2["sessoes_por_clique"])


def test_merge_sem_datas_em_comum_da_erro():
    ga4 = summarize_ga4_by_date(RAW, date(2026, 9, 1), date(2026, 9, 3))
    with pytest.raises(GA4ProjectError, match="em comum"):
        merge_sources(ga4, gsc_daily([("2026-10-01", 1, 10)]))


def test_indicadores_correlacao_perfeita_e_razao():
    days = pd.date_range("2026-09-01", periods=6)
    ga4 = pd.DataFrame(
        {"data": days, "ga4_sessoes_total": [100] * 6, "ga4_sessoes_organicas_google": [10, 20, 30, 40, 50, 60]}
    )
    gsc = pd.DataFrame(
        {"data": days, "cliques": [5, 10, 15, 20, 25, 30], "impressoes": [100, 200, 300, 400, 500, 600],
         "ctr": 0.05, "posicao_media": 8.0}
    )
    merged, _ = merge_sources(ga4, gsc)
    ind = integration_summary(merged).set_index("indicador")["valor"]
    assert ind["correlacao_cliques_x_sessoes_organicas"] == 1.0
    assert ind["sessoes_organicas_por_clique"] == 2.0           # 210 sessões / 105 cliques
    assert ind["pct_sessoes_organicas_google"] == 35.0          # 210 / 600


def test_leitura_csv_gsc_ausente_e_coluna_faltando(tmp_path):
    with pytest.raises(GA4ProjectError, match="ETAPA 05"):
        read_gsc_by_date_csv(tmp_path / "nao_existe.csv")
    ruim = tmp_path / "ruim.csv"
    ruim.write_text("data,cliques\n2026-09-01,3\n", encoding="utf-8")
    with pytest.raises(GA4ProjectError, match="ausentes"):
        read_gsc_by_date_csv(ruim)


def test_leitura_csv_gsc_valido(tmp_path):
    ok = tmp_path / "ok.csv"
    ok.write_text(
        "data,cliques,impressoes,ctr,posicao_media\n2026-09-02,5,100,0.05,8.0\n2026-09-01,0,0,,\n",
        encoding="utf-8-sig",
    )
    df = read_gsc_by_date_csv(ok)
    assert df["data"].is_monotonic_increasing and len(df) == 2

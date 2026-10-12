"""Testes da ETAPA 08 (cálculos e consultas do dashboard): sem Streamlit e sem PostgreSQL (SQLite em memória)."""
import sqlite3
from datetime import date

import pandas as pd

from ga_project.dashboard_data import (
    compute_kpis,
    fmt_delta,
    fmt_value,
    load_channels,
    load_daily,
    load_date_range,
    load_last_loads,
    load_top_queries,
    pct_change,
    previous_period,
)
from ga_project.database import create_schema, save_dataframe

sqlite3.register_adapter(date, lambda d: d.isoformat())


def build_db():
    """Banco de teste: 3 dias de GA4, 2 dias de Search Console (o último dia não tem), canais e consultas."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    ga4 = pd.DataFrame(
        [("2026-09-01", 10, 100, 300, False), ("2026-09-02", 20, 200, 500, False), ("2026-09-03", 0, 0, 0, True)],
        columns=["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"],
    )
    ga4["data"] = pd.to_datetime(ga4["data"])
    save_dataframe(conn, "ga4_diario", ga4, date(2026, 9, 1), date(2026, 9, 3))
    gsc = pd.DataFrame(
        [("2026-09-01", 5, 100, 0.05, 8.0), ("2026-09-02", 15, 300, 0.05, 6.0)],
        columns=["data", "cliques", "impressoes", "ctr", "posicao_media"],
    )
    gsc["data"] = pd.to_datetime(gsc["data"])
    save_dataframe(conn, "gsc_diario", gsc, date(2026, 9, 1), date(2026, 9, 2))
    canais = pd.DataFrame(
        [("2026-09-01", "Organic Search", "google", 40), ("2026-09-01", "Organic Search", "bing", 3),
         ("2026-09-01", "Direct", "(direct)", 30), ("2026-09-02", "Organic Search", "google", 60)],
        columns=["data", "canal", "origem", "sessoes"],
    )
    canais["data"] = pd.to_datetime(canais["data"])
    save_dataframe(conn, "ga4_sessoes_canal", canais, date(2026, 9, 1), date(2026, 9, 2))
    consultas = pd.DataFrame(
        [(date(2026, 9, 1), date(2026, 9, 2), "tinta", "/tintas", 4, 100, 0.04, 7.5),
         (date(2026, 9, 1), date(2026, 9, 2), "cimento", "/cimento", 9, 90, 0.1, 5.0),
         (date(2026, 8, 1), date(2026, 8, 2), "antiga", "/antiga", 99, 99, 0.5, 1.0)],   # foto antiga: deve ficar de fora
        columns=["periodo_inicio", "periodo_fim", "consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media"],
    )
    save_dataframe(conn, "gsc_consulta_pagina", consultas, date(2026, 9, 1), date(2026, 9, 2))
    return conn


def test_intervalo_de_datas_e_banco_vazio():
    assert load_date_range(build_db()) == (date(2026, 9, 1), date(2026, 9, 3))
    empty = sqlite3.connect(":memory:")
    create_schema(empty)
    assert load_date_range(empty) is None


def test_load_daily_junta_fontes_e_mantem_dias_sem_gsc():
    df = load_daily(build_db(), date(2026, 9, 1), date(2026, 9, 3))
    assert len(df) == 3
    assert df.loc[0, "sessoes_organicas_google"] == 40                  # só origem google (bing fica de fora)
    assert df.loc[1, "sessoes_organicas_google"] == 60
    assert df.loc[2, "sessoes_organicas_google"] == 0                   # dia sem canal: 0, não vazio
    assert df.loc[1, "cliques"] == 15
    assert pd.isna(df.loc[2, "cliques"])                                # sem Search Console nesse dia: vazio
    assert bool(df.loc[2, "sem_dados"]) is True
    assert pd.api.types.is_datetime64_any_dtype(df["data"])


def test_load_daily_respeita_o_periodo():
    assert len(load_daily(build_db(), date(2026, 9, 2), date(2026, 9, 2))) == 1


def test_canais_ordenados_e_somados():
    df = load_channels(build_db(), date(2026, 9, 1), date(2026, 9, 3))
    assert list(df["canal"]) == ["Organic Search", "Direct"]
    assert list(df["sessoes"]) == [103, 30]


def test_top_consultas_usa_so_a_foto_mais_recente():
    df = load_top_queries(build_db(), limit=10)
    assert list(df["consulta"]) == ["cimento", "tinta"]                 # ordenado por cliques; "antiga" fora
    assert load_top_queries(build_db(), limit=1).shape[0] == 1


def test_ultimas_cargas():
    df = load_last_loads(build_db())
    assert set(df["fonte"]) == {"ga4_diario", "gsc_diario", "ga4_sessoes_canal", "gsc_consulta_pagina"}


def test_periodo_anterior_tem_mesmo_tamanho():
    start, end = previous_period(date(2026, 9, 11), date(2026, 9, 20))     # 10 dias
    assert (start, end) == (date(2026, 9, 1), date(2026, 9, 10))


def test_pct_change():
    assert pct_change(110, 100) == 10.0
    assert pct_change(5, 0) is None and pct_change(None, 5) is None and pct_change(5, float("nan")) is None


def test_kpis_somam_sessoes_e_usam_media_para_usuarios():
    current = load_daily(build_db(), date(2026, 9, 1), date(2026, 9, 3))
    kpis = {k["label"]: k for k in compute_kpis(current, current.iloc[0:0])}
    assert kpis["Sessões"]["value"] == 300
    assert kpis["Usuários ativos (média/dia)"]["value"] == 15.0         # (10 + 20) / 2: dia sem_dados fora da média
    assert kpis["Cliques (Search Console)"]["value"] == 20
    assert kpis["CTR (Search Console)"]["value"] == 5.0                 # 20 cliques / 400 impressões
    assert all(k["delta"] is None for k in kpis.values())               # sem período anterior: sem variação


def test_kpis_variacao_so_com_periodo_anterior_completo():
    def frame(sessoes, cliques, impressoes):
        return pd.DataFrame({
            "data": pd.date_range("2026-09-01", periods=len(sessoes)), "sessoes": sessoes,
            "sessoes_organicas_google": sessoes, "usuarios_ativos": sessoes, "visualizacoes_pagina": sessoes,
            "cliques": cliques, "impressoes": impressoes, "sem_dados": False,
        })
    previous = frame([100, 100], [10, 10], [200, 200])
    current = frame([120, 120], [20, 20], [400, 400])
    kpis = {k["label"]: k for k in compute_kpis(current, previous)}
    assert kpis["Sessões"]["delta"] == 20.0
    assert kpis["CTR (Search Console)"]["delta_kind"] == "pp"
    assert kpis["CTR (Search Console)"]["delta"] == 0.0                 # 5% -> 5%
    incompleto = {k["label"]: k for k in compute_kpis(current, previous.iloc[:1])}
    assert incompleto["Sessões"]["delta"] is None                       # anterior com menos dias: não compara


def test_formatacao_brasileira():
    assert fmt_value(1234567, "int") == "1.234.567"
    assert fmt_value(1234.5, "float") == "1.234,5"
    assert fmt_value(4.567, "pct") == "4,57%"
    assert fmt_value(None, "int") == "—" and fmt_value(float("nan"), "pct") == "—"
    assert fmt_delta(8.54, "pct") == "+8,5%"
    assert fmt_delta(-0.3, "pp") == "-0,3 pp"
    assert fmt_delta(None, "pct") is None

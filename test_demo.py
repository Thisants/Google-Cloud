"""Testes dos dados de demonstração (ETAPA 12): determinismo, consistência e se as regras da etapa 09 os detectam."""
import sqlite3
from datetime import date, timedelta

import pandas as pd
import pytest

from ga_project.database import create_schema
from ga_project.demo import build_demo_data, save_demo_data
from ga_project.insights import generate_insights

sqlite3.register_adapter(date, lambda d: d.isoformat())

TODAY = date(2026, 10, 12)


def test_mesma_semente_gera_os_mesmos_dados_e_outra_semente_muda():
    a, b = build_demo_data(TODAY, 60, seed=1), build_demo_data(TODAY, 60, seed=1)
    c = build_demo_data(TODAY, 60, seed=2)
    pd.testing.assert_frame_equal(a["ga4_diario"], b["ga4_diario"])
    assert not a["ga4_diario"]["sessoes"].equals(c["ga4_diario"]["sessoes"])


def test_poucos_dias_da_erro_claro():
    with pytest.raises(ValueError, match="30 dias"):
        build_demo_data(TODAY, 10)


def test_periodos_e_atraso_do_search_console():
    data = build_demo_data(TODAY, 120)
    assert len(data["ga4_diario"]) == 120 and len(data["gsc_diario"]) == 120
    assert data["periodos"]["ga4"][1] == TODAY - timedelta(days=1)       # GA4 até ontem
    assert data["periodos"]["gsc"][1] == TODAY - timedelta(days=3)       # Search Console: atraso de 3 dias


def test_canais_somam_exatamente_as_sessoes_de_cada_dia():
    data = build_demo_data(TODAY, 120)
    by_day = data["ga4_sessoes_canal"].groupby("data")["sessoes"].sum()
    daily = data["ga4_diario"].set_index("data")["sessoes"]
    assert (data["ga4_sessoes_canal"]["sessoes"] > 0).all()
    assert (by_day == daily.loc[by_day.index]).all()


def test_dia_sem_dados_e_queda_nas_ultimas_sete_datas():
    ga4 = build_demo_data(TODAY, 120)["ga4_diario"]
    assert ga4["sem_dados"].sum() == 1
    valid = ga4[~ga4["sem_dados"]]
    recent, previous = valid.tail(7)["sessoes"].mean(), valid.iloc[-14:-7]["sessoes"].mean()
    assert recent < 0.7 * previous


def test_valores_validos_nos_formatos_das_tabelas():
    data = build_demo_data(TODAY, 90)
    for col in ("cliques", "impressoes"):
        assert (data["gsc_diario"][col] >= 0).all() and pd.api.types.is_integer_dtype(data["gsc_diario"][col])
    assert (data["gsc_diario"]["impressoes"] > data["gsc_diario"]["cliques"]).all()
    assert (data["gsc_diario"]["ctr"].between(0, 1)).all()
    assert len(data["gsc_consulta_pagina"]) == 29                         # 9 consultas-modelo + 20 de cauda longa


def test_regras_da_etapa_09_detectam_as_situacoes_da_demonstracao():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    saved = save_demo_data(conn, build_demo_data(TODAY, 120))
    assert saved["ga4_diario"] == 120 and saved["gsc_consulta_pagina"] == 29

    insights, _, _ = generate_insights(conn, today=TODAY)
    regras = set(insights["regra"])
    assert {"queda_sessoes", "queda_cliques", "dias_sem_dados", "ctr_baixo", "quase_primeira_pagina"} <= regras
    assert "dados_desatualizados" not in regras and "lacuna_historico" not in regras


def test_gravar_a_demonstracao_duas_vezes_nao_duplica():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    data = build_demo_data(TODAY, 60)
    save_demo_data(conn, data)
    save_demo_data(conn, data)
    assert conn.execute("SELECT COUNT(*) FROM ga4_diario").fetchone()[0] == 60

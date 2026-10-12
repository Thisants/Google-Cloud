"""Testes da ETAPA 09: regras de insights com dados fictícios (sem PostgreSQL; integração com SQLite)."""
import sqlite3
from datetime import date

import pandas as pd
import pytest

from ga_project.database import create_schema, save_dataframe
from ga_project.errors import GA4ProjectError
from ga_project.insights import (
    COLUMNS,
    format_report,
    generate_insights,
    rule_channel_concentration,
    rule_clicks_trend,
    rule_days_without_data,
    rule_history_gaps,
    rule_low_ctr,
    rule_near_first_page,
    rule_position_trend,
    rule_sessions_trend,
    rule_stale_data,
)

sqlite3.register_adapter(date, lambda d: d.isoformat())


def daily_frame(sessoes, cliques=None, impressoes=None, posicao=None, start="2026-09-01", sem_dados=None):
    n = len(sessoes)
    return pd.DataFrame({
        "data": pd.date_range(start, periods=n),
        "sessoes": sessoes,
        "sem_dados": sem_dados if sem_dados is not None else [s == 0 for s in sessoes],
        "cliques": cliques if cliques is not None else [float("nan")] * n,
        "impressoes": impressoes if impressoes is not None else [float("nan")] * n,
        "posicao_media": posicao if posicao is not None else [float("nan")] * n,
    })


def kinds(result):
    return [(i["tipo"], i["severidade"], i["regra"]) for i in result[0]]


# ---------- tendências ----------
def test_queda_forte_de_sessoes_e_risco_alta():
    result = rule_sessions_trend(daily_frame([100] * 7 + [55] * 7))      # -45%
    assert kinds(result) == [("risco", "alta", "queda_sessoes")]
    assert result[0][0]["impacto"] == -45.0


def test_queda_moderada_e_media_e_queda_pequena_nao_alerta():
    assert kinds(rule_sessions_trend(daily_frame([100] * 7 + [75] * 7))) == [("risco", "média", "queda_sessoes")]   # -25%
    assert rule_sessions_trend(daily_frame([100] * 7 + [90] * 7)) == ([], None)                                      # -10%


def test_alta_de_sessoes_vira_destaque():
    assert kinds(rule_sessions_trend(daily_frame([100] * 7 + [130] * 7))) == [("destaque", "baixa", "alta_sessoes")]


def test_sessoes_poucos_dados_ou_volume_baixo_explica_por_que_nao_avaliou():
    items, note = rule_sessions_trend(daily_frame([100] * 6))
    assert items == [] and "precisa de" in note
    items, note = rule_sessions_trend(daily_frame([3] * 7 + [1] * 7))
    assert items == [] and "volume baixo" in note


def test_dia_sem_dados_nao_entra_na_media():
    sessoes = [100] * 7 + [100, 100, 0, 100, 100, 100, 100]               # o zero é falha de coleta, não queda
    assert rule_sessions_trend(daily_frame(sessoes))[0] == []


def test_queda_de_cliques_usa_so_dias_com_search_console():
    cliques = [20.0] * 7 + [8.0] * 7 + [float("nan")] * 3                 # últimos 3 dias sem GSC (atraso)
    daily = daily_frame([100] * 17, cliques=cliques, impressoes=[400.0] * 14 + [float("nan")] * 3)
    assert kinds(rule_clicks_trend(daily)) == [("risco", "alta", "queda_cliques")]            # -60%


def test_posicao_piorou_e_melhorou():
    n = 14
    pior = daily_frame([100] * n, cliques=[10.0] * n, impressoes=[200.0] * n, posicao=[5.0] * 7 + [8.0] * 7)
    assert kinds(rule_position_trend(pior)) == [("risco", "média", "piora_posicao")]           # +3
    melhor = daily_frame([100] * n, cliques=[10.0] * n, impressoes=[200.0] * n, posicao=[9.0] * 7 + [5.0] * 7)
    assert kinds(rule_position_trend(melhor)) == [("destaque", "baixa", "melhora_posicao")]    # -4


# ---------- qualidade dos dados ----------
def test_dias_sem_dados_severidade():
    um = daily_frame([100] * 6 + [0] + [100] * 7)
    assert kinds(rule_days_without_data(um)) == [("risco", "média", "dias_sem_dados")]
    tres = daily_frame([100] * 10 + [0, 0, 0, 100])
    assert kinds(rule_days_without_data(tres)) == [("risco", "alta", "dias_sem_dados")]
    assert rule_days_without_data(daily_frame([100] * 14)) == ([], None)


def test_lacunas_no_historico_agrupa_intervalos():
    daily = daily_frame([100] * 10)
    daily = daily[~daily["data"].isin(pd.to_datetime(["2026-09-03", "2026-09-04", "2026-09-08"]))]
    items, note = rule_history_gaps(daily, date(2026, 9, 1), date(2026, 9, 10))
    assert note is None and items[0]["regra"] == "lacuna_historico"
    assert items[0]["impacto"] == 3.0
    assert "03/09/2026 a 04/09/2026" in items[0]["detalhe"] and "08/09/2026" in items[0]["detalhe"]
    assert items[0]["severidade"] == "alta"                                  # buraco recente (últimos 30 dias)
    assert rule_history_gaps(daily_frame([100] * 5), date(2026, 9, 1), date(2026, 9, 5)) == ([], None)


def test_dados_desatualizados():
    assert rule_stale_data(date(2026, 9, 28), date(2026, 9, 30)) == ([], None)
    assert kinds(rule_stale_data(date(2026, 9, 20), date(2026, 9, 30))) == [("risco", "média", "dados_desatualizados")]
    assert kinds(rule_stale_data(date(2026, 9, 1), date(2026, 9, 30))) == [("risco", "alta", "dados_desatualizados")]


# ---------- canais ----------
def test_concentracao_de_canal():
    canais = pd.DataFrame({"canal": ["Organic Search", "Direct", "Referral"], "sessoes": [800, 150, 50]})
    items, _ = rule_channel_concentration(canais)
    assert [(i["severidade"], i["regra"]) for i in items] == [("média", "concentracao_canal")]     # 80%
    assert rule_channel_concentration(pd.DataFrame({"canal": ["A", "B"], "sessoes": [300, 300]}))[0] == []
    items, note = rule_channel_concentration(pd.DataFrame({"canal": ["A"], "sessoes": [10]}))
    assert items == [] and "poucas sessões" in note


# ---------- oportunidades ----------
def queries_frame(rows):
    return pd.DataFrame(rows, columns=["consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media"]).assign(
        periodo_inicio="2026-09-01", periodo_fim="2026-09-30")


def test_ctr_baixo_calcula_potencial_e_ignora_casos_fora_da_regra():
    queries = queries_frame([
        ("tinta", "/tintas", 10, 1000, 0.01, 2.0),       # alvo 8% -> (0,08-0,01)*1000 = 70 cliques
        ("cimento", "/cimento", 80, 1000, 0.08, 2.0),    # CTR ok
        ("piso", "/pisos", 0, 50, 0.0, 2.0),             # poucas impressões
        ("ladrilho", "/ladrilho", 5, 1000, 0.005, 15.0), # fora da 1ª página: não é a regra de CTR
    ])
    items, _ = rule_low_ctr(queries)
    assert len(items) == 1
    assert (items[0]["tipo"], items[0]["severidade"], items[0]["impacto"]) == ("oportunidade", "alta", 70.0)
    assert 'CTR baixo para "tinta"' in items[0]["titulo"] and "/tintas" in items[0]["detalhe"]


def test_quase_na_primeira_pagina():
    queries = queries_frame([
        ("rejunte", "/rejunte", 2, 500, 0.004, 12.0),    # 500*2% - 2 = 8 cliques
        ("argamassa", "/argamassa", 0, 500, 0.0, 5.0),   # já na 1ª página
        ("massa", "/massa", 0, 60, 0.0, 14.0),           # poucas impressões
    ])
    items, _ = rule_near_first_page(queries)
    assert len(items) == 1 and items[0]["regra"] == "quase_primeira_pagina"
    assert (items[0]["severidade"], items[0]["impacto"]) == ("baixa", 8.0)


def test_sem_consultas_explica_por_que_nao_avaliou():
    assert "não há consultas" in rule_low_ctr(queries_frame([]))[1]
    assert "não há consultas" in rule_near_first_page(queries_frame([]))[1]


# ---------- integração com o banco (SQLite) ----------
def build_db():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    days = pd.date_range("2026-09-01", periods=20)
    ga4 = pd.DataFrame({"data": days, "usuarios_ativos": 50, "sessoes": [100] * 10 + [45] * 10,
                        "visualizacoes_pagina": 200, "sem_dados": False})
    save_dataframe(conn, "ga4_diario", ga4, date(2026, 9, 1), date(2026, 9, 20))
    gsc = pd.DataFrame({"data": days, "cliques": 10, "impressoes": 300, "ctr": 0.033, "posicao_media": 6.0})
    save_dataframe(conn, "gsc_diario", gsc, date(2026, 9, 1), date(2026, 9, 20))
    canais = pd.DataFrame({"data": list(days) * 2, "canal": ["Organic Search"] * 20 + ["Direct"] * 20,
                           "origem": ["google"] * 20 + ["(direct)"] * 20, "sessoes": [40] * 40})
    save_dataframe(conn, "ga4_sessoes_canal", canais, date(2026, 9, 1), date(2026, 9, 20))
    consultas = queries_frame([("tinta", "/tintas", 10, 1000, 0.01, 2.0)])
    consultas["periodo_inicio"] = date(2026, 9, 1)
    consultas["periodo_fim"] = date(2026, 9, 20)
    save_dataframe(conn, "gsc_consulta_pagina", consultas, date(2026, 9, 1), date(2026, 9, 20))
    return conn


def test_generate_insights_do_banco_ordena_e_lista_colunas():
    df, skipped, last = generate_insights(build_db(), today=date(2026, 9, 22))
    assert list(df.columns) == COLUMNS and last == date(2026, 9, 20)
    regras = list(df["regra"])
    assert "queda_sessoes" in regras and "ctr_baixo" in regras
    assert regras.index("queda_sessoes") < regras.index("ctr_baixo")        # riscos antes de oportunidades
    assert df.loc[0, "tipo"] == "risco" and df.loc[0, "severidade"] == "alta"
    assert (df["gerado_em"] == date(2026, 9, 22)).all()


def test_generate_insights_banco_vazio_da_erro_claro():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    with pytest.raises(GA4ProjectError, match="ETAPA 07"):
        generate_insights(conn)


def test_relatorio_em_texto():
    df, skipped, last = generate_insights(build_db(), today=date(2026, 9, 22))
    text = format_report(df, skipped, last, date(2026, 9, 22))
    assert "=== RISCOS ===" in text and "=== OPORTUNIDADES ===" in text
    assert "[ALTA] Queda de sessões" in text
    empty = format_report(df.iloc[0:0], ["alguma regra: poucos dados"], last, date(2026, 9, 22))
    assert "Nenhum alerta" in empty and "REGRAS NÃO AVALIADAS" in empty

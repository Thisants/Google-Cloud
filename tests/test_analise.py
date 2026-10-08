"""Testes da ETAPA 04: sem internet, sem credenciais."""
import math

import pandas as pd
import pytest

from ga_project.analise import (
    add_derived_metrics,
    analyze,
    by_weekday,
    compare_periods,
    read_treated_csv,
    summarize,
)
from ga_project.errors import GA4ProjectError
from ga_project.tratamento import WEEKDAYS_PT


def make_df(sessions, users=None, pages=None, start="2026-09-14"):
    """DataFrame tratado fictício. 2026-09-14 é uma segunda-feira."""
    n = len(sessions)
    dates = pd.date_range(start, periods=n, freq="D")
    users = users or [max(s - 1, 0) for s in sessions]
    pages = pages or [s * 2 for s in sessions]
    df = pd.DataFrame(
        {
            "data": dates,
            "dia_semana": [WEEKDAYS_PT[d.dayofweek] for d in dates],
            "usuarios_ativos": users,
            "sessoes": sessions,
            "visualizacoes_pagina": pages,
        }
    )
    df["sem_dados"] = (df[["usuarios_ativos", "sessoes", "visualizacoes_pagina"]] == 0).all(axis=1)
    return df


def test_metricas_derivadas_e_divisao_por_zero():
    df = add_derived_metrics(make_df([10, 0], users=[5, 0], pages=[30, 0]))
    assert df.loc[0, "sessoes_por_usuario"] == 2.0
    assert df.loc[0, "paginas_por_sessao"] == 3.0
    assert math.isnan(df.loc[1, "sessoes_por_usuario"])
    assert math.isnan(df.loc[1, "paginas_por_sessao"])


def test_resumo_ignora_dia_sem_dados():
    res = summarize(make_df([10, 0, 30])).set_index("metrica").loc["sessoes"]
    assert res["total"] == 40
    assert res["media_diaria"] == 20.0          # (10 + 30) / 2, o dia zerado fica fora
    assert res["maximo"] == 30 and res["data_maximo"] == "2026-09-16"
    assert res["minimo"] == 10 and res["data_minimo"] == "2026-09-14"


def test_por_dia_semana_ordem_e_contagem():
    table = by_weekday(make_df([10, 20, 30, 40, 50, 60, 70, 20]))   # 8 dias: segunda aparece 2x
    assert list(table["dia_semana"]) == WEEKDAYS_PT
    seg = table.set_index("dia_semana").loc["segunda"]
    assert seg["dias"] == 2 and seg["sessoes"] == 15.0               # (10 + 20) / 2


def test_comparacao_de_periodos():
    table, periods = compare_periods(make_df([10] * 7 + [20] * 7))
    sessoes = table.set_index("metrica").loc["sessoes"]
    assert sessoes["media_anterior"] == 10.0 and sessoes["media_atual"] == 20.0
    assert sessoes["variacao_pct"] == 100.0
    assert periods["anterior"] == ("2026-09-14", "2026-09-20")
    assert periods["atual"] == ("2026-09-21", "2026-09-27")


def test_comparacao_com_poucos_dias_devolve_none():
    assert compare_periods(make_df([10] * 13)) is None


def test_analyze_tudo_sem_dados_da_erro():
    with pytest.raises(GA4ProjectError):
        analyze(make_df([0, 0, 0]))


def test_analyze_devolve_todas_as_partes():
    result = analyze(make_df([10] * 7 + [20] * 7))
    assert set(result) == {"periodo", "dias", "dias_sem_dados", "diario", "resumo", "dia_semana", "comparacao"}
    assert result["dias"] == 14 and result["dias_sem_dados"] == 0


def test_leitura_csv_ausente_e_coluna_faltando(tmp_path):
    with pytest.raises(GA4ProjectError, match="ETAPA 03"):
        read_treated_csv(tmp_path / "nao_existe.csv")
    ruim = tmp_path / "ruim.csv"
    ruim.write_text("data,sessoes\n2026-09-14,10\n", encoding="utf-8")
    with pytest.raises(GA4ProjectError, match="ausentes"):
        read_treated_csv(ruim)


def test_leitura_csv_valido(tmp_path):
    ok = tmp_path / "ok.csv"
    ok.write_text(
        "data,dia_semana,usuarios_ativos,sessoes,visualizacoes_pagina,sem_dados\n"
        "2026-09-15,terça,5,6,9,False\n2026-09-14,segunda,0,0,0,True\n",
        encoding="utf-8-sig",
    )
    df = read_treated_csv(ok)
    assert df["data"].is_monotonic_increasing
    assert list(df["sem_dados"]) == [True, False]

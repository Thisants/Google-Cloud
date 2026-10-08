"""Testes da ETAPA 03: sem internet, sem credenciais."""
import pandas as pd
import pytest

from ga_project.errors import GA4ProjectError
from ga_project.tratamento import check_columns, clean, read_raw_csv, treat


def make_df(rows):
    return pd.DataFrame(rows, columns=["date", "activeUsers", "sessions", "screenPageViews"])


def test_csv_ausente_da_erro_claro(tmp_path):
    with pytest.raises(GA4ProjectError, match="ETAPA 02"):
        read_raw_csv(tmp_path / "nao_existe.csv")


def test_coluna_ausente_da_erro():
    with pytest.raises(GA4ProjectError, match="sessions"):
        check_columns(pd.DataFrame({"date": [], "activeUsers": [], "screenPageViews": []}))


def test_clean_ordena_e_converte_tipos():
    df, warnings = clean(make_df([["2026-09-29", "10", "12", "30"], ["2026-09-28", "8", "9", "20"]]))
    assert df["date"].is_monotonic_increasing
    assert pd.api.types.is_integer_dtype(df["sessions"])
    assert warnings == []


def test_clean_remove_data_invalida_e_avisa():
    df, warnings = clean(make_df([["2026-09-28", 1, 1, 1], ["abc", 2, 2, 2]]))
    assert len(df) == 1
    assert any("data inválida" in w for w in warnings)


def test_clean_troca_metrica_invalida_por_zero():
    df, warnings = clean(make_df([["2026-09-28", "x", 1, 1]]))
    assert df.loc[0, "activeUsers"] == 0
    assert any("inválido" in w for w in warnings)


def test_clean_remove_datas_repetidas_mantendo_a_ultima():
    df, warnings = clean(make_df([["2026-09-28", 1, 1, 1], ["2026-09-28", 5, 5, 5]]))
    assert len(df) == 1 and df.loc[0, "sessions"] == 5
    assert any("repetida" in w for w in warnings)


def test_clean_cria_dia_ausente():
    df, warnings = clean(make_df([["2026-09-27", 1, 1, 1], ["2026-09-29", 3, 3, 3]]))
    assert len(df) == 3
    assert df.loc[1, "sessions"] == 0
    assert any("ausente" in w for w in warnings)


def test_clean_avisa_negativo_sem_alterar():
    df, warnings = clean(make_df([["2026-09-28", -1, 1, 1]]))
    assert df.loc[0, "activeUsers"] == -1
    assert any("negativo" in w for w in warnings)


def test_clean_tudo_invalido_da_erro():
    with pytest.raises(GA4ProjectError):
        clean(make_df([["abc", 1, 1, 1]]))


def test_treat_completo_nomes_dia_semana_e_flag():
    raw = make_df([["2026-09-28", 8, 9, 20], ["2026-09-29", 0, 0, 0]])
    df, _ = treat(raw)
    assert list(df.columns) == [
        "data", "dia_semana", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados",
    ]
    assert df.loc[0, "dia_semana"] == "segunda"   # 28/09/2026 é segunda-feira
    assert df.loc[1, "dia_semana"] == "terça"
    assert bool(df.loc[0, "sem_dados"]) is False
    assert bool(df.loc[1, "sem_dados"]) is True

"""Testes SEM internet e SEM credenciais: usam uma resposta falsa da API."""
from datetime import date
from types import SimpleNamespace as NS

import pandas as pd

from ga_project.analytics_client import (
    fill_missing_dates,
    last_n_days_range,
    response_to_dataframe,
)

METRICS = ("activeUsers", "sessions", "screenPageViews")


def fake_response(rows, dims=("date",), metrics=METRICS):
    """Imita o formato da resposta do GA4. rows = [(['20260929'], ['10', '12', '30']), ...]"""
    return NS(
        dimension_headers=[NS(name=n) for n in dims],
        metric_headers=[NS(name=n) for n in metrics],
        rows=[
            NS(
                dimension_values=[NS(value=v) for v in d],
                metric_values=[NS(value=v) for v in m],
            )
            for d, m in rows
        ],
        row_count=len(rows),
    )


def test_last_n_days_range_termina_ontem_e_tem_30_dias():
    start, end = last_n_days_range(30, today=date(2026, 9, 30))
    assert end == date(2026, 9, 29)
    assert start == date(2026, 8, 31)
    assert (end - start).days + 1 == 30


def test_response_to_dataframe_converte_tipos_e_ordena():
    resp = fake_response(
        [
            (["20260929"], ["10", "12", "30"]),
            (["20260928"], ["8", "9", "20"]),  # fora de ordem de propósito
        ]
    )
    df = response_to_dataframe(resp)
    assert list(df.columns) == ["date", *METRICS]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_integer_dtype(df["sessions"])
    assert df["date"].is_monotonic_increasing
    assert df.loc[0, "activeUsers"] == 8


def test_fill_missing_dates_cria_dia_zerado():
    resp = fake_response(
        [
            (["20260927"], ["5", "6", "7"]),
            (["20260929"], ["10", "12", "30"]),  # 28/09 não veio da API
        ]
    )
    df = fill_missing_dates(response_to_dataframe(resp), date(2026, 9, 27), date(2026, 9, 29))
    assert len(df) == 3
    dia_28 = df[df["date"] == "2026-09-28"].iloc[0]
    assert dia_28["sessions"] == 0
    assert pd.api.types.is_integer_dtype(df["sessions"])


def test_resposta_vazia_gera_dataframe_vazio_com_colunas():
    df = response_to_dataframe(fake_response([]))
    assert df.empty
    assert list(df.columns) == ["date", *METRICS]

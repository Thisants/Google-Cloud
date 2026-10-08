"""Coleta de dados do GA4 e transformação em DataFrame.

Fluxo:  fetch_report()  ->  build_request() -> _run_report() -> response_to_dataframe()

As funções são GENÉRICAS (aceitam qualquer lista de dimensões e métricas),
então as próximas etapas (canal, página, país, dispositivo...) reaproveitam
este mesmo código, sem copiar nada.
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.api_core import exceptions as gexc

from ga_project.errors import GA4ProjectError


def last_n_days_range(n_days: int = 30, today: date | None = None) -> tuple[date, date]:
    """Devolve (início, fim) dos últimos n dias COMPLETOS.

    O fim é ontem: o dia de hoje ainda está incompleto no GA4.
    Com n_days=30 são exatamente 30 dias (30 linhas no relatório por data).
    """
    today = today or date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=n_days - 1)
    return start, end


def build_request(
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    start: date,
    end: date,
) -> RunReportRequest:
    """Monta o pedido (RunReportRequest) que será enviado ao GA4."""
    return RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=name) for name in dimensions],
        metrics=[Metric(name=name) for name in metrics],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        limit=10000,
    )


def _run_report(client, request: RunReportRequest):
    """Envia o pedido ao GA4 e traduz os erros mais comuns para mensagens claras."""
    try:
        return client.run_report(request)
    except gexc.PermissionDenied as exc:
        raise GA4ProjectError(
            "Sem permissão (403). Confira: (1) a Google Analytics Data API está ativada "
            "no projeto do Google Cloud; (2) o e-mail da Service Account foi adicionado "
            "como Leitor/Viewer na propriedade GA4."
        ) from exc
    except gexc.InvalidArgument as exc:
        raise GA4ProjectError(
            f"Consulta inválida (400): nome de métrica/dimensão errado, combinação "
            f"incompatível ou datas inválidas. Detalhe: {exc.message}"
        ) from exc
    except gexc.NotFound as exc:
        raise GA4ProjectError("Propriedade não encontrada (404). Confira o GA4_PROPERTY_ID.") from exc
    except gexc.Unauthenticated as exc:
        raise GA4ProjectError("Não autenticado (401). A credencial JSON pode estar inválida.") from exc
    except gexc.ResourceExhausted as exc:
        raise GA4ProjectError("Cota da API excedida (429). Aguarde e tente de novo.") from exc
    except gexc.GoogleAPICallError as exc:
        raise GA4ProjectError(f"Erro da API do Google: {exc}") from exc


def response_to_dataframe(response) -> pd.DataFrame:
    """Transforma a resposta da API em DataFrame com tipos corretos.

    A API devolve TUDO como texto (inclusive a data '20260929' e as métricas).
    Aqui convertemos: dimensão 'date' -> datetime; métricas -> números.
    """
    dimension_names = [h.name for h in response.dimension_headers]
    metric_names = [h.name for h in response.metric_headers]

    records = []
    for row in response.rows:
        record = {}
        for name, cell in zip(dimension_names, row.dimension_values):
            record[name] = cell.value
        for name, cell in zip(metric_names, row.metric_values):
            record[name] = cell.value
        records.append(record)

    df = pd.DataFrame(records, columns=dimension_names + metric_names)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df = df.sort_values("date").reset_index(drop=True)  # a API não garante ordem
    for name in metric_names:
        df[name] = pd.to_numeric(df[name])
    return df


def fetch_report(
    client,
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Consulta o GA4 e devolve o resultado como DataFrame (função principal)."""
    request = build_request(property_id, dimensions, metrics, start, end)
    response = _run_report(client, request)

    if response.row_count > len(response.rows):
        # Não deve acontecer em 30 dias por data; vira paginação nas próximas etapas.
        print(
            f"AVISO: a API tem {response.row_count} linhas, mas só {len(response.rows)} "
            "foram retornadas (limite por página)."
        )
    return response_to_dataframe(response)


def fill_missing_dates(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Garante uma linha para cada dia do período (dias sem dados viram 0).

    O GA4 NÃO retorna dias sem nenhum dado. Sem isso, um dia zerado some do
    DataFrame e atrapalha médias e gráficos. Use só com a dimensão 'date' sozinha.
    """
    full_index = pd.date_range(start, end, freq="D", name="date")
    metric_cols = [c for c in df.columns if c != "date"]
    was_integer = {c: pd.api.types.is_integer_dtype(df[c]) for c in metric_cols}

    filled = df.set_index("date").reindex(full_index).fillna(0)
    for col in metric_cols:
        if was_integer[col] or df.empty:
            filled[col] = filled[col].astype("int64")
    return filled.reset_index()


def save_csv(df: pd.DataFrame, path: Path) -> Path:
    """Salva o DataFrame em CSV (cria a pasta se não existir)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise GA4ProjectError(
            f"Não consegui salvar o CSV em {path}: {exc} "
            "(se o arquivo estiver aberto no Excel, feche-o e tente de novo)."
        ) from exc
    return path

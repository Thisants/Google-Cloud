"""Coleta de dados do Google Search Console (ETAPA 05).

Fluxo:  create_gsc_service() -> fetch_search_analytics() -> build_date_report() / build_query_page_report()

Mesma Service Account do GA4, mas com outra API e outra permissão:
  1) a "Google Search Console API" precisa estar ativada no projeto do Google Cloud;
  2) o e-mail da Service Account precisa ser adicionado como usuário na propriedade do Search Console.

Esta etapa só COLETA e organiza. Cruzar com o GA4 é a ETAPA 06.
"""
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ga_project.analytics_client import fill_missing_dates
from ga_project.errors import GA4ProjectError

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]  # somente leitura
PAGE_SIZE = 25000  # máximo de linhas por requisição da API

RENAME_MAP = {
    "date": "data",
    "query": "consulta",
    "page": "pagina",
    "clicks": "cliques",
    "impressions": "impressoes",
    "ctr": "ctr",
    "position": "posicao_media",
}


def get_site_url() -> str:
    """Lê GSC_SITE_URL do ambiente (chame load_settings() antes, que carrega o .env)."""
    site_url = os.getenv("GSC_SITE_URL", "").strip()
    if not site_url.startswith(("sc-domain:", "http://", "https://")):
        raise GA4ProjectError(
            "GSC_SITE_URL ausente ou inválido no .env. Use EXATAMENTE como aparece no Search Console: "
            "'sc-domain:exemplo.com.br' (propriedade de domínio) ou "
            "'https://www.exemplo.com.br/' (prefixo de URL, com a barra final)."
        )
    return site_url


def gsc_date_range(n_days: int = 30, lag_days: int = 3, today: date | None = None) -> tuple[date, date]:
    """Devolve (início, fim) dos últimos n dias, terminando `lag_days` dias atrás.

    O Search Console demora cerca de 2-3 dias para consolidar os dados, então os dias
    mais recentes viriam incompletos (e pareceriam uma queda que não existe).
    """
    today = today or date.today()
    end = today - timedelta(days=lag_days)
    start = end - timedelta(days=n_days - 1)
    return start, end


def create_gsc_service(credentials_path: Path):
    """Cria o cliente do Search Console usando a Service Account (JSON)."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=SCOPES
        )
        return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    except (ValueError, OSError) as exc:
        raise GA4ProjectError(f"Credencial inválida ou ilegível: {exc}") from exc


def _execute_query(service, site_url: str, body: dict) -> dict:
    """Envia uma consulta e traduz os erros mais comuns para mensagens claras."""
    try:
        return service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        detail = getattr(exc, "reason", str(exc))
        if status == 403:
            raise GA4ProjectError(
                "Sem permissão (403). Confira: (1) a Google Search Console API está ativada no projeto "
                "do Google Cloud; (2) o e-mail da Service Account foi adicionado como usuário na "
                "propriedade do Search Console; (3) GSC_SITE_URL é igual ao da propriedade cadastrada."
            ) from exc
        if status == 404:
            raise GA4ProjectError("Propriedade não encontrada (404). Confira o GSC_SITE_URL.") from exc
        if status == 400:
            raise GA4ProjectError(f"Consulta inválida (400). Detalhe: {detail}") from exc
        if status == 429:
            raise GA4ProjectError("Cota da API excedida (429). Aguarde e tente de novo.") from exc
        raise GA4ProjectError(f"Erro da API do Google (HTTP {status}): {detail}") from exc
    except OSError as exc:
        raise GA4ProjectError(f"Falha de conexão com a API do Google: {exc}") from exc


def rows_to_dataframe(rows: list[dict], dimensions: list[str]) -> pd.DataFrame:
    """Transforma as linhas da API em DataFrame com tipos corretos.

    A API devolve cada linha como {"keys": [...], "clicks": ..., "impressions": ..., "ctr": ..., "position": ...}.
    O CTR vem como fração (0.034 = 3,4%).
    """
    records = []
    for row in rows:
        record = dict(zip(dimensions, row["keys"]))
        record["clicks"] = row["clicks"]
        record["impressions"] = row["impressions"]
        record["ctr"] = row["ctr"]
        record["position"] = row["position"]
        records.append(record)

    df = pd.DataFrame(records, columns=[*dimensions, "clicks", "impressions", "ctr", "position"])

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="ISO8601")
        df = df.sort_values("date").reset_index(drop=True)
    df["clicks"] = pd.to_numeric(df["clicks"]).astype("int64")
    df["impressions"] = pd.to_numeric(df["impressions"]).astype("int64")
    df["ctr"] = pd.to_numeric(df["ctr"]).round(4)
    df["position"] = pd.to_numeric(df["position"]).round(1)
    return df


def fetch_search_analytics(
    service,
    site_url: str,
    start: date,
    end: date,
    dimensions: list[str],
    max_rows: int | None = None,
    page_size: int = PAGE_SIZE,
) -> pd.DataFrame:
    """Consulta o Search Console (com paginação) e devolve um DataFrame.

    dimensions: por exemplo ["date"] ou ["query", "page"].
    max_rows:   limite total de linhas (None = traz tudo).
    """
    rows: list[dict] = []
    start_row = 0
    while True:
        limit = page_size if max_rows is None else min(page_size, max_rows - len(rows))
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": limit,
            "startRow": start_row,
        }
        batch = _execute_query(service, site_url, body).get("rows", [])
        rows.extend(batch)
        start_row += len(batch)
        if len(batch) < limit or (max_rows is not None and len(rows) >= max_rows):
            break
    return rows_to_dataframe(rows, dimensions)


def build_date_report(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Relatório por data: uma linha por dia, nomes padronizados.

    Dias sem nenhuma impressão não vêm da API: são criados com 0 cliques e 0 impressões.
    CTR e posição ficam vazios nesses dias (não existe CTR/posição sem impressão).
    """
    filled = fill_missing_dates(df, start, end)
    filled[["ctr", "position"]] = filled[["ctr", "position"]].astype("float64")
    filled.loc[filled["impressions"] == 0, ["ctr", "position"]] = float("nan")
    return filled.rename(columns=RENAME_MAP)


def build_query_page_report(df: pd.DataFrame) -> pd.DataFrame:
    """Relatório por consulta + página, ordenado por cliques e impressões (maiores primeiro)."""
    df = df.rename(columns=RENAME_MAP)
    return df.sort_values(["cliques", "impressoes"], ascending=False).reset_index(drop=True)

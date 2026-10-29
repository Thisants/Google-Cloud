"""Coleta de UM cliente direto para o banco (GA4 + Search Console), sem arquivos CSV no meio.

Fluxo por cliente:  GA4 (diário + canais) -> tratamento -> banco  |  Search Console (diário + consultas) -> banco

Pensado para MUITOS clientes:
  - cada função recebe o cliente e grava só nele (cliente_id vem do cadastro, nunca de variável global);
  - falhas temporárias do Google (cota, instabilidade) são repetidas com espera crescente (retry_call);
  - períodos longos (carga histórica) são quebrados em blocos de 90 dias, para não estourar o limite de linhas por consulta.
"""
import time
from datetime import date, timedelta

from ga_project.analytics_client import fetch_report, fill_missing_dates, last_n_days_range
from ga_project.clientes import Cliente
from ga_project.database import save_dataframe
from ga_project.errors import GA4ProjectError, RetryableError
from ga_project.integracao import GA4_DIMENSIONS, GA4_METRICS, rename_ga4_channels
from ga_project.search_console import (
    build_date_report,
    build_query_page_report,
    fetch_search_analytics,
    gsc_date_range,
)
from ga_project.tratamento import treat

DAILY_METRICS = ["activeUsers", "sessions", "screenPageViews"]
GA4_DAILY_COLUMNS = ["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"]
CHUNK_DAYS = 90            # tamanho de cada bloco de coleta do GA4
MAX_GSC_DAYS = 480         # o Search Console guarda cerca de 16 meses
GSC_LAG_DAYS = 3           # atraso de consolidação do Search Console
SNAPSHOT_DAYS = 30         # janela do relatório de consultas + páginas
MAX_QUERY_ROWS = 5000


def retry_call(fn, *, tries: int = 4, base_delay: float = 2.0, sleep=time.sleep):
    """Executa fn(); se der RetryableError (cota/instabilidade), espera 2s, 4s, 8s... e tenta de novo."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except RetryableError:
            if attempt == tries:
                raise
            sleep(base_delay * 2 ** (attempt - 1))


def date_chunks(start: date, end: date, size: int = CHUNK_DAYS):
    """Divide [start, end] em blocos consecutivos de até `size` dias."""
    current = start
    while current <= end:
        block_end = min(current + timedelta(days=size - 1), end)
        yield current, block_end
        current = block_end + timedelta(days=1)


def collect_ga4(conn, ga4_client, cliente: Cliente, dias: int, today: date | None, sleep=time.sleep) -> dict[str, int]:
    """GA4 do cliente: métricas por dia e sessões por canal/origem."""
    pid = cliente.ga4_property_id
    start, end = last_n_days_range(dias, today)
    saved = {"ga4_diario": 0, "ga4_sessoes_canal": 0}
    for block_start, block_end in date_chunks(start, end):
        raw = retry_call(lambda s=block_start, e=block_end: fetch_report(ga4_client, pid, ["date"], DAILY_METRICS, s, e),
                         sleep=sleep)
        daily, _ = treat(fill_missing_dates(raw, block_start, block_end))
        saved["ga4_diario"] += save_dataframe(conn, "ga4_diario", daily[GA4_DAILY_COLUMNS], block_start, block_end,
                                              cliente_id=cliente.slug)
        channels = retry_call(
            lambda s=block_start, e=block_end: fetch_report(ga4_client, pid, GA4_DIMENSIONS, GA4_METRICS, s, e),
            sleep=sleep)
        saved["ga4_sessoes_canal"] += save_dataframe(
            conn, "ga4_sessoes_canal", rename_ga4_channels(channels)[["data", "canal", "origem", "sessoes"]],
            block_start, block_end, cliente_id=cliente.slug)
    return saved


def collect_gsc(conn, gsc_service, cliente: Cliente, dias: int, today: date | None, sleep=time.sleep) -> dict[str, int]:
    """Search Console do cliente: métricas por dia e foto das consultas + páginas dos últimos 30 dias."""
    url = cliente.gsc_site_url
    start, end = gsc_date_range(min(dias, MAX_GSC_DAYS), GSC_LAG_DAYS, today)
    raw = retry_call(lambda: fetch_search_analytics(gsc_service, url, start, end, ["date"]), sleep=sleep)
    saved = {"gsc_diario": save_dataframe(conn, "gsc_diario", build_date_report(raw, start, end), start, end,
                                          cliente_id=cliente.slug)}

    q_start, q_end = gsc_date_range(SNAPSHOT_DAYS, GSC_LAG_DAYS, today)
    raw_q = retry_call(lambda: fetch_search_analytics(gsc_service, url, q_start, q_end, ["query", "page"],
                                                      max_rows=MAX_QUERY_ROWS), sleep=sleep)
    queries = build_query_page_report(raw_q)
    queries["periodo_inicio"] = q_start
    queries["periodo_fim"] = q_end
    saved["gsc_consulta_pagina"] = save_dataframe(conn, "gsc_consulta_pagina", queries, q_start, q_end,
                                                  cliente_id=cliente.slug)
    return saved


def collect_cliente(conn, cliente: Cliente, *, ga4_client=None, gsc_service_factory=None, dias: int = 30,
                    today: date | None = None, fontes=("ga4", "gsc"), sleep=time.sleep) -> dict[str, int]:
    """Coleta as fontes configuradas do cliente e devolve {tabela: linhas gravadas}."""
    use_ga4 = "ga4" in fontes and bool(cliente.ga4_property_id)
    use_gsc = "gsc" in fontes and bool(cliente.gsc_site_url)
    if not (use_ga4 or use_gsc):
        raise GA4ProjectError(
            f"O cliente '{cliente.slug}' não tem GA4 nem Search Console configurados para as fontes pedidas "
            f"({', '.join(fontes)}). Use gerenciar_clientes.py update.")
    saved: dict[str, int] = {}
    if use_ga4:
        if ga4_client is None:
            raise GA4ProjectError("Cliente do GA4 não informado.")
        saved.update(collect_ga4(conn, ga4_client, cliente, dias, today, sleep))
    if use_gsc:
        if gsc_service_factory is None:
            raise GA4ProjectError("Serviço do Search Console não informado.")
        saved.update(collect_gsc(conn, gsc_service_factory(), cliente, dias, today, sleep))
    return saved

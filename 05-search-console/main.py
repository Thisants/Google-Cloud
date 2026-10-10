"""ETAPA 05 - Coleta de dados do Google Search Console (últimos 30 dias).

Gera dois relatórios:
  1) por data              -> tendência diária de cliques e impressões
  2) por consulta + página -> quais buscas levam a quais páginas

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 05-search-console/main.py
"""
import sys
from pathlib import Path

from ga_project.analytics_client import save_csv
from ga_project.config import load_settings
from ga_project.errors import GA4ProjectError
from ga_project.search_console import (
    build_date_report,
    build_query_page_report,
    create_gsc_service,
    fetch_search_analytics,
    get_site_url,
    gsc_date_range,
)

DAYS = 30
LAG_DAYS = 3          # o Search Console leva ~2-3 dias para consolidar os dados
MAX_QUERY_ROWS = 5000
OUTPUT_DIR = Path(__file__).resolve().parent / "dados"


def main() -> int:
    try:
        settings = load_settings()      # carrega o .env e valida a credencial
        site_url = get_site_url()
        service = create_gsc_service(settings.credentials_path)

        start, end = gsc_date_range(DAYS, LAG_DAYS)
        print(f"Consultando Search Console ({site_url}) de {start} a {end}...")

        raw_dates = fetch_search_analytics(service, site_url, start, end, ["date"])
        if raw_dates.empty:
            print("AVISO: o Search Console não devolveu nenhuma linha (site novo ou sem impressões no período).")
        by_date = build_date_report(raw_dates, start, end)

        raw_queries = fetch_search_analytics(
            service, site_url, start, end, ["query", "page"], max_rows=MAX_QUERY_ROWS
        )
        by_query = build_query_page_report(raw_queries)

        print("\n=== Por data ===")
        print(by_date.to_string(index=False))
        print(f"\nTotal no período: {by_date['cliques'].sum()} cliques | {by_date['impressoes'].sum()} impressões")

        print(f"\n=== Top 10 consultas + páginas por cliques (de {len(by_query)} linhas) ===")
        print(by_query.head(10).to_string(index=False, max_colwidth=50))

        save_csv(by_date, OUTPUT_DIR / "gsc_30_dias_por_data.csv")
        save_csv(by_query, OUTPUT_DIR / "gsc_30_dias_consulta_pagina.csv")
        print(f"\nArquivos salvos em: {OUTPUT_DIR}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

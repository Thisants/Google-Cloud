"""ETAPA 02 - Coleta dos últimos 30 dias do GA4.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 02-coleta-dados/main.py
"""
import sys
from pathlib import Path

from ga_project.analytics_client import (
    fetch_report,
    fill_missing_dates,
    last_n_days_range,
    save_csv,
)
from ga_project.auth import create_ga4_client
from ga_project.config import load_settings
from ga_project.errors import GA4ProjectError

DAYS = 30
DIMENSIONS = ["date"]
METRICS = ["activeUsers", "sessions", "screenPageViews"]
OUTPUT_CSV = Path(__file__).resolve().parent / "dados" / "analytics_30_dias.csv"


def main() -> int:
    try:
        settings = load_settings()
        client = create_ga4_client()

        start, end = last_n_days_range(DAYS)
        print(f"Consultando GA4 (propriedade {settings.property_id}) de {start} a {end}...")

        df = fetch_report(client, settings.property_id, DIMENSIONS, METRICS, start, end)
        df = fill_missing_dates(df, start, end)

        print()
        print(df.to_string(index=False))
        print(f"\n{len(df)} linhas | colunas: {', '.join(df.columns)}")

        saved = save_csv(df, OUTPUT_CSV)
        print(f"CSV salvo em: {saved}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

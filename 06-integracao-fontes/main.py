"""ETAPA 06 - Integração GA4 + Search Console (cruzamento por data).

Entradas:
  - GA4 (consulta ao vivo): sessões por data x canal x origem
  - 05-search-console/dados/gsc_30_dias_por_data.csv  (gerado pela ETAPA 05)
Saídas (06-integracao-fontes/dados/):
  - ga4_sessoes_por_canal_30_dias.csv
  - integrado_por_data.csv
  - indicadores_integracao.csv

Rode a ETAPA 05 e esta etapa NO MESMO DIA, para os dois cobrirem o mesmo período.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 06-integracao-fontes/main.py
"""
import sys
from pathlib import Path

from ga_project.analytics_client import fetch_report, save_csv
from ga_project.auth import create_ga4_client
from ga_project.config import PROJECT_ROOT, load_settings
from ga_project.errors import GA4ProjectError
from ga_project.integracao import (
    GA4_DIMENSIONS,
    GA4_METRICS,
    channel_totals,
    integration_summary,
    merge_sources,
    read_gsc_by_date_csv,
    rename_ga4_channels,
    summarize_ga4_by_date,
)
from ga_project.search_console import gsc_date_range

DAYS = 30
LAG_DAYS = 3  # mesmo período da ETAPA 05 (o Search Console demora ~3 dias para consolidar)
GSC_CSV = PROJECT_ROOT / "05-search-console" / "dados" / "gsc_30_dias_por_data.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "dados"


def main() -> int:
    try:
        settings = load_settings()
        client = create_ga4_client()

        start, end = gsc_date_range(DAYS, LAG_DAYS)
        print(f"Consultando GA4 (propriedade {settings.property_id}) de {start} a {end}...")
        raw = fetch_report(client, settings.property_id, GA4_DIMENSIONS, GA4_METRICS, start, end)
        if raw.empty:
            print("AVISO: o GA4 não devolveu nenhuma linha para o período.")

        gsc = read_gsc_by_date_csv(GSC_CSV)
        ga4_daily = summarize_ga4_by_date(raw, start, end)
        merged, info = merge_sources(ga4_daily, gsc)

        first, last = info["periodo_comum"]
        print(f"\nDias no GA4: {info['dias_ga4']} | no Search Console: {info['dias_gsc']} | em comum: {info['dias_em_comum']}")
        print(f"Período cruzado: {first} a {last}")
        if info["dias_em_comum"] < info["dias_gsc"]:
            print("AVISO: o CSV da ETAPA 05 cobre datas fora do período do GA4. Rode a ETAPA 05 de novo hoje.")

        print("\n=== Sessões por canal (GA4, no período) ===")
        print(channel_totals(raw).to_string(index=False))

        print("\n=== Integrado por data ===")
        print(merged.to_string(index=False))

        summary = integration_summary(merged)
        print("\n=== Indicadores ===")
        print(summary.to_string(index=False))

        save_csv(rename_ga4_channels(raw), OUTPUT_DIR / "ga4_sessoes_por_canal_30_dias.csv")
        save_csv(merged, OUTPUT_DIR / "integrado_por_data.csv")
        save_csv(summary, OUTPUT_DIR / "indicadores_integracao.csv")
        print(f"\nArquivos salvos em: {OUTPUT_DIR}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

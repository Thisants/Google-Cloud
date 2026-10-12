"""ETAPA 09 - Detecção de problemas e oportunidades (regras sobre os dados do PostgreSQL).

Lê o banco (somente SELECT), roda as regras de src/ga_project/insights.py, mostra o relatório no terminal
e salva 09-insights/dados/insights.csv.

Não usa a credencial do Google: usa as variáveis DB_* do .env.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 09-insights/main.py
"""
import sys
from datetime import date
from pathlib import Path

from ga_project.analytics_client import save_csv
from ga_project.database import connect
from ga_project.errors import GA4ProjectError
from ga_project.insights import format_report, generate_insights

OUTPUT_CSV = Path(__file__).resolve().parent / "dados" / "insights.csv"


def main() -> int:
    conn = None
    try:
        conn = connect()
        today = date.today()
        insights, skipped, last_date = generate_insights(conn, today)

        print(format_report(insights, skipped, last_date, today))
        saved = save_csv(insights, OUTPUT_CSV)
        print(f"\nInsights salvos em: {saved}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())

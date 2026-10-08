"""ETAPA 03 - Tratamento dos dados coletados na ETAPA 02.

Entrada : 02-coleta-dados/dados/analytics_30_dias.csv
Saída   : 03-tratamento/dados/analytics_30_dias_tratado.csv

Não precisa de internet nem de credencial do Google.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 03-tratamento/main.py
"""
import sys
from pathlib import Path

from ga_project.analytics_client import save_csv
from ga_project.config import PROJECT_ROOT
from ga_project.errors import GA4ProjectError
from ga_project.tratamento import read_raw_csv, treat

INPUT_CSV = PROJECT_ROOT / "02-coleta-dados" / "dados" / "analytics_30_dias.csv"
OUTPUT_CSV = Path(__file__).resolve().parent / "dados" / "analytics_30_dias_tratado.csv"


def main() -> int:
    try:
        raw = read_raw_csv(INPUT_CSV)
        print(f"CSV bruto lido: {INPUT_CSV} ({len(raw)} linhas)")

        df, warnings = treat(raw)

        print("\nRelatório de qualidade:")
        if warnings:
            for message in warnings:
                print(f"  - {message}")
        else:
            print("  Nenhum problema encontrado.")

        print()
        print(df.to_string(index=False))
        print(f"\n{len(df)} linhas | colunas: {', '.join(df.columns)}")

        saved = save_csv(df, OUTPUT_CSV)
        print(f"CSV tratado salvo em: {saved}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""ETAPA 04 - Análise descritiva dos dados tratados.

Entrada : 03-tratamento/dados/analytics_30_dias_tratado.csv
Saída   : 04-analise/dados/*.csv  (4 arquivos)

Não precisa de internet nem de credencial do Google.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 04-analise/main.py
"""
import sys
from pathlib import Path

from ga_project.analise import analyze, read_treated_csv
from ga_project.analytics_client import save_csv
from ga_project.config import PROJECT_ROOT
from ga_project.errors import GA4ProjectError

INPUT_CSV = PROJECT_ROOT / "03-tratamento" / "dados" / "analytics_30_dias_tratado.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "dados"


def show(title: str, table) -> None:
    print(f"\n=== {title} ===")
    print(table.to_string(index=False))


def main() -> int:
    try:
        df = read_treated_csv(INPUT_CSV)
        result = analyze(df)

        start, end = result["periodo"]
        print(f"Período analisado: {start} a {end} ({result['dias']} dias)")
        print(f"Dias sem dados (fora das médias): {result['dias_sem_dados']}")

        show("Resumo por métrica", result["resumo"])
        show("Média por dia da semana", result["dia_semana"])

        comparison = result["comparacao"]
        if comparison is None:
            print("\n=== Últimos 7 dias vs 7 anteriores ===\nDados insuficientes (precisa de 14 dias).")
        else:
            table, periods = comparison
            shown = table.copy()
            shown["variacao_pct"] = shown["variacao_pct"].map(lambda v: "n/d" if v != v else f"{v:+.1f}%")
            a0, a1 = periods["anterior"]
            c0, c1 = periods["atual"]
            show(f"Média diária: {c0} a {c1} (atual) vs {a0} a {a1} (anterior)", shown)

        save_csv(result["diario"], OUTPUT_DIR / "metricas_diarias.csv")
        save_csv(result["resumo"], OUTPUT_DIR / "resumo.csv")
        save_csv(result["dia_semana"], OUTPUT_DIR / "por_dia_semana.csv")
        if comparison is not None:
            save_csv(comparison[0], OUTPUT_DIR / "comparacao_7_dias.csv")
        print(f"\nArquivos salvos em: {OUTPUT_DIR}")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

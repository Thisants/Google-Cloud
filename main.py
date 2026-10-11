"""ETAPA 07 - Banco de dados PostgreSQL (armazenamento permanente).

1) conecta ao PostgreSQL  2) cria as tabelas (se não existirem)  3) grava os CSVs das etapas anteriores
4) mostra um resumo do que há no banco.

Rodar quantas vezes quiser: não duplica dados e não apaga nada.

Não usa a credencial do Google: usa as variáveis DB_* do .env.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    python 07-banco-dados/main.py
"""
import sys

from ga_project.carga import run_all
from ga_project.database import connect, create_schema, table_summary
from ga_project.errors import GA4ProjectError


def main() -> int:
    conn = None
    try:
        conn = connect()
        print("Conectado ao PostgreSQL.")
        create_schema(conn)
        print("Tabelas conferidas/criadas.")

        print("\nGravando os CSVs das etapas anteriores:")
        results = run_all(conn)
        for table, rows in results.items():
            status = "pulada (CSV ausente)" if rows is None else f"{rows} linhas gravadas"
            print(f"  {table}: {status}")
        if all(rows is None for rows in results.values()):
            print("\nAVISO: nenhum CSV foi encontrado. Rode antes as etapas 03, 05 e 06.")

        print("\n=== O que há no banco agora ===")
        print(table_summary(conn).to_string(index=False))
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())

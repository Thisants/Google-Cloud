"""ETAPA 12 - Gera dados FICTÍCIOS em um banco de demonstração (para prints, apresentações e entrevistas).

  python 12-documentacao/gerar_dados_demo.py                      # usa o banco "analytics_demo"
  python 12-documentacao/gerar_dados_demo.py --banco meu_demo --dias 90

Proteções: o nome do banco PRECISA conter "demo", e o programa recusa rodar se DATABASE_URL estiver definida
(a URL completa tem prioridade e poderia apontar para o seu banco REAL). Os dados reais nunca são tocados.
Crie o banco antes (uma vez), no psql:   CREATE DATABASE analytics_demo OWNER analytics_app;
"""
import argparse
import os
import sys
from datetime import date

from dotenv import load_dotenv

from ga_project.config import PROJECT_ROOT
from ga_project.database import connect, create_schema, table_summary
from ga_project.demo import build_demo_data, save_demo_data
from ga_project.errors import GA4ProjectError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera dados fictícios de demonstração no PostgreSQL.")
    parser.add_argument("--banco", default="analytics_demo", help='nome do banco de demonstração (deve conter "demo")')
    parser.add_argument("--dias", type=int, default=120, help="quantidade de dias de histórico (mínimo 30)")
    parser.add_argument("--semente", type=int, default=42, help="semente aleatória (mesma semente = mesmos dados)")
    args = parser.parse_args(argv)

    if "demo" not in args.banco.lower():
        print('ERRO: por segurança, o nome do banco de demonstração precisa conter "demo".', file=sys.stderr)
        return 1
    load_dotenv(PROJECT_ROOT / ".env")
    if os.getenv("DATABASE_URL", "").strip():
        print("ERRO: DATABASE_URL está definida e tem prioridade sobre DB_NAME: poderia apontar para o banco REAL. "
              "Comente essa linha no .env para gerar os dados de demonstração.", file=sys.stderr)
        return 1
    os.environ["DB_NAME"] = args.banco            # só para este programa; não altera o seu .env

    conn = None
    try:
        data = build_demo_data(date.today(), args.dias, args.semente)
        conn = connect()
        create_schema(conn)
        saved = save_demo_data(conn, data)
        print(f"Dados fictícios gravados no banco '{args.banco}':")
        for table, rows in saved.items():
            print(f"  {table}: {rows} linhas")
        print("\n" + table_summary(conn).to_string(index=False))
        print(
            "\nPara usar o banco de demonstração nesta janela do PowerShell (o seu .env não muda):\n"
            f'  $env:DB_NAME = "{args.banco}"\n'
            "  streamlit run 08-dashboard\\app.py\n"
            "  python 09-insights\\main.py\n"
            "Para voltar ao banco real: feche a janela ou rode  Remove-Item Env:DB_NAME"
        )
        return 0
    except (GA4ProjectError, ValueError) as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())

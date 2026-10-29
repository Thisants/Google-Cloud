"""Comando da rotina de coleta (usado por 02-coleta-dados/main.py e 11-api-aplicacao/atualizar_tudo.py).

  --cliente SLUG (repetível) | --todos     quais clientes
  --dias 30                                 janela de coleta (use 480 uma vez para a CARGA HISTÓRICA)
  --workers 2                               clientes ao mesmo tempo (aumente devagar: o Google tem cotas)
  --fonte ga4|gsc|todas                     o que coletar
  --sem-insights                            não recalcular os insights
Código de saída: 0 = todos ok; 1 = algum cliente falhou (os outros NÃO são afetados).
"""
import argparse
import sys
import time
from datetime import date

from ga_project.config import PROJECT_ROOT, load_credentials
from ga_project.database import connect, create_schema
from ga_project.errors import GA4ProjectError
from ga_project.rotina import all_ok, format_summary, run_clientes, select_clientes

FONTES = {"ga4": ("ga4",), "gsc": ("gsc",), "todas": ("ga4", "gsc")}


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--cliente", action="append", metavar="SLUG", help="cliente a coletar (pode repetir)")
    parser.add_argument("--todos", action="store_true", help="todos os clientes ATIVOS")
    parser.add_argument("--dias", type=int, default=30, help="quantos dias coletar (padrão 30; até 480 para a carga histórica)")
    parser.add_argument("--workers", type=int, default=2, help="clientes processados ao mesmo tempo (padrão 2)")
    parser.add_argument("--fonte", choices=sorted(FONTES), default="todas")
    parser.add_argument("--sem-insights", action="store_true")
    return parser


def run(args, *, connect_fn, ga4_client, gsc_service_factory, out=print, today=None, sleep=time.sleep,
        todos_por_padrao: bool = False) -> int:
    """Roda a rotina com as dependências injetadas (por isso é testável sem Google nem PostgreSQL)."""
    if not (args.cliente or args.todos or todos_por_padrao):
        out("Diga quais clientes: --cliente SLUG (pode repetir) ou --todos.")
        return 2
    if not 1 <= args.dias <= 480:
        out("--dias precisa estar entre 1 e 480.")
        return 2
    conn = connect_fn()
    try:
        create_schema(conn)
        clientes = select_clientes(conn, args.cliente or None)
    finally:
        conn.close()
    if not clientes:
        out("Nenhum cliente ativo cadastrado. Cadastre com: python 01-clientes\\gerenciar_clientes.py add ...")
        return 1
    out(f"Coletando {len(clientes)} cliente(s): {args.dias} dias, {args.workers} por vez, fonte '{args.fonte}'.")
    results = run_clientes(connect_fn, clientes, ga4_client=ga4_client, gsc_service_factory=gsc_service_factory,
                           dias=args.dias, workers=args.workers, today=today, fontes=FONTES[args.fonte],
                           with_insights=not args.sem_insights, sleep=sleep)
    out(format_summary(results))
    return 0 if all_ok(results) else 1


def main(argv=None, *, description: str = "Coleta os clientes e grava no banco.", todos_por_padrao: bool = False,
         gravar_log: bool = False) -> int:
    args = build_parser(description).parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log_path = PROJECT_ROOT / "logs" / f"atualizacao_{date.today().isoformat()}.log"

    def out(text="", end="\n"):
        print(text, end=end, flush=True)
        if gravar_log:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(text + end)

    try:
        from ga_project.auth import create_ga4_client
        from ga_project.search_console import create_gsc_service

        path = load_credentials()
        ga4_client = create_ga4_client()
        return run(args, connect_fn=connect, ga4_client=ga4_client,
                   gsc_service_factory=lambda: create_gsc_service(path), out=out, todos_por_padrao=todos_por_padrao)
    except GA4ProjectError as exc:
        out(f"\nERRO: {exc}")
        return 1

"""ETAPA 11 - Atualiza tudo com um comando: coleta (02, 03, 05, 06), grava no PostgreSQL (07) e gera insights (09).

  python 11-api-aplicacao/atualizar_tudo.py              # rotina completa
  python 11-api-aplicacao/atualizar_tudo.py --so-banco   # só 07 e 09 (usa os CSVs que já existem)

Tudo o que aparece na tela também é gravado em logs/atualizacao_AAAA-MM-DD.log (útil quando agendado).
Código de saída: 0 = tudo certo; 1 = alguma etapa falhou (o Agendador de Tarefas mostra isso).
Rode pelo menos a cada ~3 semanas (de preferência toda semana) para não abrir buracos no histórico.
"""
import argparse
import sys
from datetime import date

from ga_project.config import PROJECT_ROOT
from ga_project.pipeline import all_ok, format_summary, make_logged_runner, run_pipeline, select_steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atualiza os dados do projeto de ponta a ponta.")
    parser.add_argument("--so-banco", action="store_true", help="roda só as etapas 07 e 09 (sem coletar de novo)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):          # sem console (agendado), evita erro de acentos
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log_path = PROJECT_ROOT / "logs" / f"atualizacao_{date.today().isoformat()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def out(text="", end="\n"):
        print(text, end=end, flush=True)
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(text + end)

    out(f"Rotina iniciada. Log: {log_path}")
    results = run_pipeline(PROJECT_ROOT, steps=select_steps(only_db=args.so_banco),
                           runner=make_logged_runner(out), out=out)
    out(format_summary(results))
    return 0 if all_ok(results) else 1


if __name__ == "__main__":
    sys.exit(main())

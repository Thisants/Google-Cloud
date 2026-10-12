"""Rotina de atualização (ETAPA 11): roda as etapas de coleta e gravação, na ordem certa, com UM comando.

Por que existe: o banco só acumula histórico se a coleta e a carga rodarem com frequência (no máximo a cada ~3 semanas,
pois a coleta pega 30 dias). Esta rotina evita esquecer etapas e pode ser agendada no Windows.

Ordem:  02 coleta GA4 -> 03 tratamento -> 05 Search Console -> 06 integração -> 07 grava no PostgreSQL -> 09 insights
Se uma etapa falhar, as seguintes NÃO rodam (não grava dados velhos como se fossem novos).
A etapa 10 (IA) fica de fora de propósito: ela tem custo por uso.
"""
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

STEPS = [
    ("ETAPA 02 - Coleta do GA4", "02-coleta-dados/main.py"),
    ("ETAPA 03 - Tratamento", "03-tratamento/main.py"),
    ("ETAPA 05 - Coleta do Search Console", "05-search-console/main.py"),
    ("ETAPA 06 - Integração GA4 + Search Console", "06-integracao-fontes/main.py"),
    ("ETAPA 07 - Gravação no PostgreSQL", "07-banco-dados/main.py"),
    ("ETAPA 09 - Insights", "09-insights/main.py"),
]
DB_ONLY_PREFIXES = ("07-", "09-")


@dataclass
class StepResult:
    name: str
    script: str
    status: str                 # "ok" | "falhou" | "nao_executada"
    returncode: int | None
    seconds: float


def select_steps(only_db: bool = False) -> list[tuple[str, str]]:
    """Todas as etapas, ou só as que leem os CSVs já existentes e gravam no banco (07 e 09)."""
    if not only_db:
        return list(STEPS)
    return [step for step in STEPS if step[1].startswith(DB_ONLY_PREFIXES)]


def run_pipeline(base_dir: Path, steps=None, python: str | None = None, runner=subprocess.run,
                 clock=time.monotonic, out=print) -> list[StepResult]:
    """Executa cada etapa como um programa separado e para na primeira falha."""
    steps = list(steps if steps is not None else STEPS)
    python = python or sys.executable
    results: list[StepResult] = []
    failed = False

    for name, relative in steps:
        if failed:
            results.append(StepResult(name, relative, "nao_executada", None, 0.0))
            continue
        script = Path(base_dir) / relative
        out(f"\n=== {name} ===")
        if not script.is_file():
            out(f"ERRO: script não encontrado: {script}")
            results.append(StepResult(name, relative, "falhou", None, 0.0))
            failed = True
            continue

        started = clock()
        completed = runner([python, str(script)], cwd=str(base_dir))
        seconds = clock() - started
        ok = completed.returncode == 0
        results.append(StepResult(name, relative, "ok" if ok else "falhou", completed.returncode, seconds))
        failed = not ok
    return results


def make_logged_runner(out):
    """Runner que executa cada etapa e envia a saída dela para `out(texto, end="")` (tela + arquivo de log).

    Útil quando a rotina é agendada (sem janela de console): o log guarda o que cada etapa escreveu.
    PYTHONUTF8=1 faz as etapas escreverem em UTF-8 (acentos corretos no log, mesmo sem console).
    """
    def runner(cmd, cwd):
        env = {**os.environ, "PYTHONUTF8": "1"}
        completed = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out(completed.stdout.decode("utf-8", errors="replace"), end="")
        return completed

    return runner


def all_ok(results: list[StepResult]) -> bool:
    return bool(results) and all(r.status == "ok" for r in results)


def format_summary(results: list[StepResult]) -> str:
    labels = {"ok": "OK      ", "falhou": "FALHOU  ", "nao_executada": "NÃO RODOU"}
    lines = ["", "=== RESUMO ==="]
    for r in results:
        extra = f" ({r.seconds:.1f} s)" if r.status != "nao_executada" else ""
        lines.append(f"{labels[r.status]} {r.name}{extra}")
    lines.append("")
    lines.append("Tudo certo: dados atualizados no banco." if all_ok(results)
                 else "Atenção: a atualização NÃO foi concluída. Corrija a etapa que falhou e rode de novo.")
    return "\n".join(lines)

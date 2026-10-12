"""Testes da rotina de atualização (ETAPA 11): ordem, parada na falha e execução real de scripts."""
import sys
from types import SimpleNamespace as NS

from ga_project.pipeline import STEPS, all_ok, format_summary, make_logged_runner, run_pipeline, select_steps


def make_project(tmp_path, exit_codes=None):
    """Cria scripts fictícios que registram a execução em log.txt e saem com o código combinado."""
    exit_codes = exit_codes or {}
    log = tmp_path / "log.txt"
    for _, relative in STEPS:
        script = tmp_path / relative
        script.parent.mkdir(parents=True, exist_ok=True)
        code = exit_codes.get(relative, 0)
        script.write_text(
            f"import sys\nopen(r'{log}', 'a').write({relative!r} + '\\n')\nsys.exit({code})\n", encoding="utf-8")
    return log


def test_ordem_das_etapas_e_so_banco():
    assert [s[1][:3] for s in STEPS] == ["02-", "03-", "05-", "06-", "07-", "09-"]
    assert [s[1][:3] for s in select_steps(only_db=True)] == ["07-", "09-"]
    assert len(select_steps()) == 6


def test_executa_scripts_reais_na_ordem(tmp_path):
    log = make_project(tmp_path)
    results = run_pipeline(tmp_path, out=lambda *a: None)
    assert all_ok(results)
    assert log.read_text().split() == [relative for _, relative in STEPS]


def test_para_na_primeira_falha_e_nao_roda_as_seguintes(tmp_path):
    log = make_project(tmp_path, {"05-search-console/main.py": 1})
    results = run_pipeline(tmp_path, out=lambda *a: None)
    assert [r.status for r in results] == ["ok", "ok", "falhou", "nao_executada", "nao_executada", "nao_executada"]
    assert log.read_text().split() == ["02-coleta-dados/main.py", "03-tratamento/main.py", "05-search-console/main.py"]
    assert not all_ok(results)
    summary = format_summary(results)
    assert "FALHOU" in summary and "NÃO RODOU" in summary and "NÃO foi concluída" in summary


def test_script_ausente_conta_como_falha(tmp_path):
    results = run_pipeline(tmp_path, steps=[("Etapa X", "nao_existe/main.py"), ("Etapa Y", "outra/main.py")], out=lambda *a: None)
    assert [r.status for r in results] == ["falhou", "nao_executada"]


def test_runner_recebe_python_e_pasta_do_projeto(tmp_path):
    calls = []

    def fake_runner(cmd, cwd):
        calls.append((cmd, cwd))
        return NS(returncode=0)

    make_project(tmp_path)
    run_pipeline(tmp_path, steps=select_steps(only_db=True), python="meu-python", runner=fake_runner, out=lambda *a: None)
    assert calls[0][0][0] == "meu-python" and calls[0][0][1].endswith("main.py") and calls[0][1] == str(tmp_path)
    assert len(calls) == 2


def test_resumo_de_sucesso(tmp_path):
    make_project(tmp_path)
    results = run_pipeline(tmp_path, out=lambda *a: None)
    assert "Tudo certo" in format_summary(results) and sys.executable


def test_runner_com_log_captura_saida_com_acentos(tmp_path):
    script = tmp_path / "02-coleta-dados" / "main.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('coleta concluída: ação ok')\n", encoding="utf-8")
    captured = []
    runner = make_logged_runner(lambda text, end="\n": captured.append(text + end))
    results = run_pipeline(tmp_path, steps=[("ETAPA 02", "02-coleta-dados/main.py")], runner=runner,
                           out=lambda text, end="\n": captured.append(text + end))
    assert all_ok(results)
    assert "coleta concluída: ação ok" in "".join(captured)


def test_runner_com_log_registra_falha_e_a_saida_de_erro(tmp_path):
    script = tmp_path / "03-tratamento" / "main.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys\nprint('deu problema', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8")
    captured = []
    runner = make_logged_runner(lambda text, end="\n": captured.append(text + end))
    results = run_pipeline(tmp_path, steps=[("ETAPA 03", "03-tratamento/main.py")], runner=runner, out=lambda *a, **k: None)
    assert results[0].status == "falhou" and results[0].returncode == 3
    assert "deu problema" in "".join(captured)

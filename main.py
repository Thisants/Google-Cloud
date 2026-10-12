"""ETAPA 10 - Analytics agêntico: converse com seus dados usando IA.

Modos:
  python 10-analytics-agentico/main.py                        # conversa no terminal ("sair" encerra)
  python 10-analytics-agentico/main.py --pergunta "Por que as sessões caíram?"
  python 10-analytics-agentico/main.py --relatorio            # relatório semanal salvo em dados/relatorio_AAAA-MM-DD.md

O agente só LÊ o banco, por ferramentas fixas. Usa a API da Anthropic (precisa de ANTHROPIC_API_KEY no .env e
internet): a pergunta e os resultados das ferramentas são enviados à API. Veja o README para o que sai do computador.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

from ga_project.agent import (
    QA_MAX_TOKENS,
    REPORT_MAX_TOKENS,
    REPORT_PROMPT,
    Agent,
    create_client,
    load_agent_settings,
)
from ga_project.database import connect
from ga_project.errors import GA4ProjectError

OUTPUT_DIR = Path(__file__).resolve().parent / "dados"


def chat(agent: Agent) -> None:
    print("Pergunte sobre os seus dados (digite 'sair' para encerrar).")
    while True:
        try:
            question = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"sair", "exit", "quit"}:
            break
        try:
            print(f"\nAgente: {agent.ask(question, QA_MAX_TOKENS)}")
        except GA4ProjectError as exc:       # erro passageiro (ex.: limite de uso): a conversa continua
            print(f"\nERRO: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analytics agêntico (IA sobre o seu banco).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pergunta", help="faz uma única pergunta e mostra a resposta")
    group.add_argument("--relatorio", action="store_true", help="gera o relatório semanal em Markdown")
    args = parser.parse_args(argv)

    conn = None
    try:
        settings = load_agent_settings()
        conn = connect()
        agent = Agent(create_client(settings), conn, model=settings.model, allow_queries=settings.allow_queries)
        print(f"Modelo: {settings.model} | consultas/páginas enviadas à IA: {'sim' if settings.allow_queries else 'NÃO'}")

        if args.relatorio:
            report = agent.ask(REPORT_PROMPT, REPORT_MAX_TOKENS)
            print("\n" + report)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            path = OUTPUT_DIR / f"relatorio_{date.today().isoformat()}.md"
            path.write_text(report, encoding="utf-8")
            print(f"\nRelatório salvo em: {path}")
        elif args.pergunta:
            print("\n" + agent.ask(args.pergunta, QA_MAX_TOKENS))
        else:
            chat(agent)

        print(f"\n[Uso: {agent.input_tokens} tokens de entrada, {agent.output_tokens} de saída; "
              f"{len(agent.tool_calls)} chamada(s) de ferramenta]")
        return 0
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())

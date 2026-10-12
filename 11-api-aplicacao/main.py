"""ETAPA 11 - Sobe a API REST (FastAPI + uvicorn) sobre o banco.

  python 11-api-aplicacao/main.py                 # sobe a API em http://127.0.0.1:8000  (Ctrl+C encerra)
  python 11-api-aplicacao/main.py --gerar-chave   # gera uma chave forte para colocar em API_KEY no .env

Documentação interativa: http://127.0.0.1:8000/docs (botão "Authorize" para informar a chave).
Por padrão a API só é acessível neste computador. Todas as rotas de dados exigem o cabeçalho X-API-Key.
"""
import argparse
import sys

from ga_project.api_core import LOCAL_HOSTS, generate_api_key, load_api_settings
from ga_project.errors import GA4ProjectError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="API de analytics (somente leitura).")
    parser.add_argument("--gerar-chave", action="store_true", help="gera uma chave forte para API_KEY e sai")
    args = parser.parse_args(argv)

    if args.gerar_chave:
        print("Cole esta linha no seu .env (e guarde a chave em local seguro):\n")
        print(f"API_KEY={generate_api_key()}")
        return 0

    try:
        settings = load_api_settings()
        from ga_project.api import create_app      # importa o FastAPI só aqui (--gerar-chave não precisa dele)

        app = create_app(settings)
        import uvicorn
    except ModuleNotFoundError as exc:
        print(f"\nERRO: biblioteca '{exc.name}' não instalada. Rode: pip install -r requirements.txt", file=sys.stderr)
        return 1
    except GA4ProjectError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1

    print(f"API em http://{settings.host}:{settings.port}  (documentação em /docs) | agente de IA: "
          f"{'LIGADO' if settings.enable_agent else 'desligado'}")
    if settings.host not in LOCAL_HOSTS:
        print("ATENÇÃO: a API está acessível por OUTROS computadores da rede. Ela dá acesso aos dados do negócio: "
              "use apenas em rede confiável, com firewall, e guarde bem a API_KEY.", file=sys.stderr)
    uvicorn.run(app, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

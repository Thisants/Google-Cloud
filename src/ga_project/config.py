"""Leitura das configurações a partir de variáveis de ambiente (.env).

Nada secreto fica no código: o .env (que NÃO vai para o Git) guarda o
Property ID e o caminho do arquivo JSON da Service Account.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from ga_project.errors import GA4ProjectError

# Raiz do projeto: .../google-analytics-project (config.py está em src/ga_project/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    property_id: str
    credentials_path: Path


def _resolve_credentials_path(raw_path: str) -> Path:
    credentials_path = Path(raw_path)
    if not credentials_path.is_absolute():
        # Caminho relativo é resolvido a partir da raiz do projeto,
        # então funciona de qualquer pasta em que você rode o script.
        credentials_path = PROJECT_ROOT / credentials_path
    return credentials_path


def validate_project_environment(
    *,
    check_api: bool = False,
    check_agent: bool = False,
    check_database: bool = False,
) -> list[str]:
    """Valida o .env e os itens principais do projeto sem derrubar a aplicação."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    issues: list[str] = []

    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        issues.append("Arquivo .env ausente: copie .env.example para .env e preencha os valores necessários.")

    property_id = os.getenv("GA4_PROPERTY_ID", "").strip()
    if not property_id:
        issues.append("GA4_PROPERTY_ID ausente no .env.")
    elif not property_id.isdigit():
        issues.append("GA4_PROPERTY_ID inválido no .env. Use só números (ex.: 123456789).")

    raw_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw_path:
        issues.append("GOOGLE_APPLICATION_CREDENTIALS ausente no .env (caminho do JSON da Service Account).")
    else:
        credentials_path = _resolve_credentials_path(raw_path)
        if not credentials_path.is_file():
            issues.append(f"Arquivo de credencial não encontrado: {credentials_path}")

    if check_database:
        db_url = os.getenv("DATABASE_URL", "").strip()
        if db_url:
            return issues
        missing_db = [name for name in ("DB_NAME", "DB_USER", "DB_PASSWORD") if not os.getenv(name, "").strip()]
        if missing_db:
            issues.append(f"Variáveis do PostgreSQL ausentes no .env: {', '.join(missing_db)}.")
        db_port = os.getenv("DB_PORT", "5432").strip()
        if db_port and (not db_port.isdigit() or not 1 <= int(db_port) <= 65535):
            issues.append("DB_PORT inválida no .env (use um número entre 1 e 65535).")

    if check_api:
        api_key = os.getenv("API_KEY", "").strip()
        if len(api_key) < 24:
            issues.append("API_KEY ausente ou curta demais no .env. Gere uma com: python 11-api-aplicacao\\main.py --gerar-chave")

    if check_agent:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not anthropic_key:
            issues.append("ANTHROPIC_API_KEY ausente no .env. Ela é obrigatória para o agente de IA.")

    return issues


def load_settings() -> Settings:
    """Lê e valida GA4_PROPERTY_ID e GOOGLE_APPLICATION_CREDENTIALS."""
    load_dotenv(PROJECT_ROOT / ".env")

    property_id = os.getenv("GA4_PROPERTY_ID", "").strip()
    if not property_id.isdigit():
        raise GA4ProjectError(
            "GA4_PROPERTY_ID ausente ou inválido no .env. "
            "Use só números (ex.: 123456789), sem o prefixo 'properties/'."
        )

    raw_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw_path:
        raise GA4ProjectError(
            "GOOGLE_APPLICATION_CREDENTIALS ausente no .env "
            "(caminho do JSON da Service Account)."
        )

    credentials_path = _resolve_credentials_path(raw_path)
    if not credentials_path.is_file():
        raise GA4ProjectError(f"Arquivo de credencial não encontrado: {credentials_path}")

    # A biblioteca do Google lê esta variável sozinha.
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
    return Settings(property_id=property_id, credentials_path=credentials_path)

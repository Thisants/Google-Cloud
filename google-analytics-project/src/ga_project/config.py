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

    credentials_path = Path(raw_path)
    if not credentials_path.is_absolute():
        # Caminho relativo é resolvido a partir da raiz do projeto,
        # então funciona de qualquer pasta em que você rode o script.
        credentials_path = PROJECT_ROOT / credentials_path
    if not credentials_path.is_file():
        raise GA4ProjectError(f"Arquivo de credencial não encontrado: {credentials_path}")

    # A biblioteca do Google lê esta variável sozinha.
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)
    return Settings(property_id=property_id, credentials_path=credentials_path)

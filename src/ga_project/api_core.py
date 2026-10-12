"""Peças da API (ETAPA 11) que NÃO dependem do FastAPI: configuração, comparação segura de chave e limite de uso.

Ficam separadas do api.py para serem testadas sem instalar o FastAPI.
"""
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass

from dotenv import load_dotenv

from ga_project.config import PROJECT_ROOT
from ga_project.errors import GA4ProjectError

MIN_KEY_LENGTH = 24
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class ApiSettings:
    api_key: str             # chave que os clientes da SUA API precisam enviar (não é a chave da Anthropic)
    host: str = "127.0.0.1"  # só este computador, por padrão
    port: int = 8000
    enable_agent: bool = False
    agent_max_per_hour: int = 20
    allow_queries: bool = True   # mesma regra de privacidade da etapa 10 (AGENT_SEND_QUERIES)


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value not in {"false", "0", "no", "nao", "não"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not minimum <= int(raw) <= maximum:
        raise GA4ProjectError(f"{name} inválido no .env: use um número inteiro de {minimum} a {maximum}.")
    return int(raw)


def generate_api_key() -> str:
    """Gera uma chave aleatória forte (43 caracteres)."""
    return secrets.token_urlsafe(32)


def load_api_settings() -> ApiSettings:
    """Lê API_KEY, API_HOST, API_PORT, API_ENABLE_AGENT, API_AGENT_MAX_PER_HOUR e AGENT_SEND_QUERIES do .env."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("API_KEY", "").strip()
    if len(api_key) < MIN_KEY_LENGTH:
        raise GA4ProjectError(
            f"API_KEY ausente ou curta demais no .env (mínimo {MIN_KEY_LENGTH} caracteres). "
            "Gere uma com: python 11-api-aplicacao\\main.py --gerar-chave"
        )
    return ApiSettings(
        api_key=api_key,
        host=os.getenv("API_HOST", "").strip() or "127.0.0.1",
        port=_int("API_PORT", 8000, 1, 65535),
        enable_agent=_flag("API_ENABLE_AGENT", False),
        agent_max_per_hour=_int("API_AGENT_MAX_PER_HOUR", 20, 1, 10_000),
        allow_queries=_flag("AGENT_SEND_QUERIES", True),
    )


def keys_match(provided: str | None, expected: str) -> bool:
    """Compara as chaves em tempo constante (evita descobrir a chave pelo tempo de resposta)."""
    if not provided:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class RateLimiter:
    """Limite simples em memória: no máximo `max_calls` usos por janela de tempo (padrão: 1 hora)."""

    def __init__(self, max_calls: int, window_seconds: float = 3600, clock=time.monotonic):
        self.max_calls = max_calls
        self.window = window_seconds
        self.clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Registra um uso e devolve True; devolve False se o limite da janela já foi atingido."""
        now = self.clock()
        with self._lock:
            while self._calls and now - self._calls[0] >= self.window:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True

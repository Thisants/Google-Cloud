"""Peças da API que NÃO dependem do FastAPI: configuração, permissões e limites de uso (testáveis sem instalar o FastAPI)."""
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from dotenv import load_dotenv

from ga_project.apikeys import KeyInfo
from ga_project.config import PROJECT_ROOT
from ga_project.errors import GA4ProjectError

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_PAGE = 200


@dataclass(frozen=True)
class ApiSettings:
    host: str = "127.0.0.1"          # só este computador, por padrão
    port: int = 8000
    allow_external: bool = False     # aceitar conexões de outros computadores (exige HTTPS na frente; veja o README)
    docs: bool = True
    enable_agent: bool = False       # endpoint de IA (gera custo): desligado por padrão
    agent_max_per_hour: int = 20     # perguntas à IA por chave, por hora
    requests_per_minute: int = 120   # pedidos por chave, por minuto
    allow_queries: bool = True       # chave geral; cada cliente também precisa ter enviar_consultas_ia ligado


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


def load_api_settings() -> ApiSettings:
    """Lê API_HOST, API_PORT, API_ALLOW_EXTERNAL, API_DOCS, API_ENABLE_AGENT, API_AGENT_MAX_PER_HOUR,
    API_REQUESTS_PER_MINUTE e AGENT_SEND_QUERIES do .env. As CHAVES da API ficam no banco (não no .env)."""
    load_dotenv(PROJECT_ROOT / ".env")
    settings = ApiSettings(
        host=os.getenv("API_HOST", "").strip() or "127.0.0.1",
        port=_int("API_PORT", 8000, 1, 65535),
        allow_external=_flag("API_ALLOW_EXTERNAL", False),
        docs=_flag("API_DOCS", True),
        enable_agent=_flag("API_ENABLE_AGENT", False),
        agent_max_per_hour=_int("API_AGENT_MAX_PER_HOUR", 20, 1, 10_000),
        requests_per_minute=_int("API_REQUESTS_PER_MINUTE", 120, 1, 100_000),
        allow_queries=_flag("AGENT_SEND_QUERIES", True),
    )
    if settings.host not in LOCAL_HOSTS and not settings.allow_external:
        raise GA4ProjectError(
            f"API_HOST={settings.host} abriria a API para a rede, e ela NÃO tem HTTPS. "
            "Se você realmente precisa, coloque API_ALLOW_EXTERNAL=true e uma camada HTTPS na frente."
        )
    return settings


def can_access(info: KeyInfo, slug: str) -> bool:
    """Administrador acessa qualquer cliente; chave de cliente acessa SOMENTE o próprio."""
    return info.papel == "admin" or (info.papel == "cliente" and info.cliente_id == slug)


def page_args(limite: int, offset: int) -> tuple[int, int]:
    """Limites seguros de paginação (a resposta nunca cresce junto com a carteira)."""
    return max(1, min(int(limite), MAX_PAGE)), max(0, int(offset))


class RateLimiter:
    """Limite simples em memória: no máximo `max_calls` usos por janela de tempo."""

    def __init__(self, max_calls: int, window_seconds: float = 3600, clock=time.monotonic):
        self.max_calls = max_calls
        self.window = window_seconds
        self.clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self.clock()
        with self._lock:
            while self._calls and now - self._calls[0] >= self.window:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True


class LimiterRegistry:
    """Um RateLimiter por chave da API (cada cliente tem o seu limite; um cliente não gasta o limite do outro)."""

    def __init__(self, max_calls: int, window_seconds: float = 60, clock=time.monotonic):
        self._args = (max_calls, window_seconds, clock)
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str) -> bool:
        with self._lock:
            limiter = self._limiters.setdefault(key_id, RateLimiter(*self._args))
        return limiter.allow()

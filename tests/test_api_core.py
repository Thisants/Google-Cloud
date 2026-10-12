"""Testes da ETAPA 11 (partes sem FastAPI): configuração, chave e limite de uso."""
import pytest

from ga_project.api_core import (
    MIN_KEY_LENGTH,
    ApiSettings,
    RateLimiter,
    generate_api_key,
    keys_match,
    load_api_settings,
)
from ga_project.errors import GA4ProjectError

ENV_NAMES = ("API_KEY", "API_HOST", "API_PORT", "API_ENABLE_AGENT", "API_AGENT_MAX_PER_HOUR", "AGENT_SEND_QUERIES")


def clean_env(monkeypatch):
    monkeypatch.setattr("ga_project.api_core.load_dotenv", lambda *a, **k: None)   # ignora o .env real
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_chave_gerada_e_forte_e_diferente_a_cada_vez():
    a, b = generate_api_key(), generate_api_key()
    assert len(a) >= MIN_KEY_LENGTH and a != b


def test_comparacao_de_chave():
    assert keys_match("abc", "abc") is True
    assert keys_match("abc", "abd") is False
    assert keys_match(None, "abc") is False and keys_match("", "abc") is False
    assert keys_match("chave-ção", "chave-ção") is True          # acentos não quebram a comparação


def test_configuracao_padrao_e_segura(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k" * 32)
    settings = load_api_settings()
    assert settings == ApiSettings(api_key="k" * 32, host="127.0.0.1", port=8000, enable_agent=False,
                                   agent_max_per_hour=20, allow_queries=True)


def test_configuracao_personalizada(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k" * 32)
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("API_ENABLE_AGENT", "true")
    monkeypatch.setenv("API_AGENT_MAX_PER_HOUR", "5")
    monkeypatch.setenv("AGENT_SEND_QUERIES", "false")
    settings = load_api_settings()
    assert (settings.port, settings.enable_agent, settings.agent_max_per_hour, settings.allow_queries) == (9000, True, 5, False)


def test_sem_chave_ou_chave_curta_a_api_nao_sobe(monkeypatch):
    clean_env(monkeypatch)
    with pytest.raises(GA4ProjectError, match="API_KEY"):
        load_api_settings()
    monkeypatch.setenv("API_KEY", "curta")
    with pytest.raises(GA4ProjectError, match="mínimo"):
        load_api_settings()


def test_porta_invalida(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k" * 32)
    monkeypatch.setenv("API_PORT", "abc")
    with pytest.raises(GA4ProjectError, match="API_PORT"):
        load_api_settings()
    monkeypatch.setenv("API_PORT", "70000")
    with pytest.raises(GA4ProjectError, match="API_PORT"):
        load_api_settings()


def test_limite_de_uso_por_janela():
    now = [0.0]
    limiter = RateLimiter(max_calls=2, window_seconds=3600, clock=lambda: now[0])
    assert limiter.allow() and limiter.allow()
    assert limiter.allow() is False                        # terceira dentro da hora: bloqueada
    now[0] = 3599
    assert limiter.allow() is False
    now[0] = 3601                                          # a 1ª saiu da janela
    assert limiter.allow() is True

"""Testes de validação do ambiente do projeto."""

import ga_project.config as config


def test_validate_project_environment_reports_missing_values(monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", config.PROJECT_ROOT)
    monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    issues = config.validate_project_environment(check_api=True, check_agent=True, check_database=True)

    assert any("GA4_PROPERTY_ID" in issue for issue in issues)
    assert any("GOOGLE_APPLICATION_CREDENTIALS" in issue for issue in issues)
    assert any("API_KEY" in issue for issue in issues)
    assert any("ANTHROPIC_API_KEY" in issue for issue in issues)
    assert any("Variáveis do PostgreSQL" in issue for issue in issues)


def test_validate_project_environment_accepts_ready_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "credenciais/test.json")
    monkeypatch.setenv("API_KEY", "k" * 32)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-123")
    monkeypatch.setenv("DB_NAME", "analytics")
    monkeypatch.setenv("DB_USER", "analytics_app")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    (tmp_path / "credenciais").mkdir()
    (tmp_path / "credenciais" / "test.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")

    issues = config.validate_project_environment(check_api=True, check_agent=True, check_database=True)

    assert not issues

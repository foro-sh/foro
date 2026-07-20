import pytest

from foro import secret


def test_secret_returns_env_value(monkeypatch):
    monkeypatch.setenv("API_KEY", "shh")

    assert secret("API_KEY") == "shh"


def test_secret_raises_dashboard_actionable_error_when_unset(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API_KEY"):
        secret("API_KEY")

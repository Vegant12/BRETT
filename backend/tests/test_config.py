"""FOUND-05 config-layer tests: fail-fast, secret masking, asyncpg URL normalization."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]

DB_URL = "postgresql://u:sup3rpw@h:5432/db"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test starts from a known-empty environment."""
    for var in (
        "ENVIRONMENT",
        "LOG_LEVEL",
        "DATABASE_URL",
        "HEVY_API_KEY",
        "MCP_AUTH_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_secrets_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("HEVY_API_KEY", "hevy-secret-key")
    monkeypatch.setenv("MCP_AUTH_SECRET", "mcp-secret-token")
    settings = Settings(_env_file=None)

    rendered = repr(settings) + settings.model_dump_json()

    assert "**********" in rendered
    for secret in (DB_URL, "sup3rpw", "hevy-secret-key", "mcp-secret-token"):
        assert secret not in rendered


def test_missing_env_fails_fast() -> None:
    """No DATABASE_URL anywhere -> ValidationError at construction, not at first query."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_is_gitignored() -> None:
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", ".env"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0


def test_async_url_normalizes_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{DB_URL}?sslmode=require")
    url = Settings(_env_file=None).async_database_url

    assert url.startswith("postgresql+asyncpg://")
    assert "ssl=require" in url
    assert "sslmode" not in url


def test_async_url_drops_channel_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{DB_URL}?channel_binding=require")
    url = Settings(_env_file=None).async_database_url

    assert url.startswith("postgresql+asyncpg://")
    assert "channel_binding" not in url


def test_secret_values_includes_password_longest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("HEVY_API_KEY", "abc")
    values = Settings(_env_file=None).secret_values()

    assert DB_URL in values
    assert "sup3rpw" in values
    assert "abc" in values
    assert values == sorted(values, key=len, reverse=True)


def test_invalid_url_error_does_not_echo_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://u:pw@h/db")
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    rendered = str(excinfo.value) + repr(excinfo.value)
    assert "pw" not in rendered
    assert "mysql://" not in rendered


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    assert get_settings() is get_settings()

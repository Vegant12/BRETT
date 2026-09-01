"""FOUND-05 config-layer tests: fail-fast, secret masking, asyncpg URL normalization."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import _SECRET_FIELDS, Settings, get_settings

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
        "MCP_AUTH_MODE",
        "MCP_ISSUER_URL",
        "MCP_RESOURCE_URL",
        "MCP_JWKS_URI",
        "MCP_ALLOWED_HOSTS",
        "RATE_LIMIT_PER_MINUTE",
        "RATE_LIMIT_BURST",
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


def test_mcp_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every MCP_* var is optional: the app must still boot for local dev."""
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    settings = Settings(_env_file=None)

    assert settings.mcp_auth_mode == "static"
    assert settings.mcp_issuer_url == "https://example.authkit.app"
    assert settings.mcp_resource_url == "http://localhost:8000/mcp"
    assert settings.mcp_jwks_uri == ""
    assert settings.mcp_allowed_hosts == ["localhost", "127.0.0.1"]


def test_mcp_allowed_hosts_splits_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-02-01: whitespace and empty entries must not widen the Host allowlist.

    A bare ``split(",")`` on ``"a,,b"`` yields an empty-string entry, and an
    empty host in the allowlist is the difference between a closed allowlist and
    one that matches more than intended.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "brett.onrender.com, testserver ,")
    settings = Settings(_env_file=None)

    assert settings.mcp_allowed_hosts == ["brett.onrender.com", "testserver"]


def test_mcp_config_is_not_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-02-04: public MCP config must not reach the log value scrubber.

    These are hostnames and URLs published anonymously in the RFC 9728 metadata
    document. Scrubbing a public hostname would redact it from every log line
    that mentions the service and make the logs unreadable. ``MCP_AUTH_SECRET``
    is the control: it must still be scrubbed.

    Asserting only ``value not in secret_values()`` would be vacuous, because
    ``secret_values`` skips anything that is not a ``SecretStr``. The field types
    are asserted directly so this test also fails if a public field is later
    redeclared as ``SecretStr`` -- the half of the mistake that a value-only
    assertion cannot see.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("MCP_AUTH_SECRET", "mcp-secret-token")
    monkeypatch.setenv("MCP_ISSUER_URL", "https://distinctive-issuer.example")
    monkeypatch.setenv("MCP_RESOURCE_URL", "https://distinctive-resource.example/mcp")
    monkeypatch.setenv("MCP_JWKS_URI", "https://distinctive-jwks.example/keys")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "distinctive-host.example")
    settings = Settings(_env_file=None)
    values = settings.secret_values()

    assert "mcp-secret-token" in values, "MCP_AUTH_SECRET must still be scrubbed"
    for name in (
        "mcp_auth_mode",
        "mcp_issuer_url",
        "mcp_resource_url",
        "mcp_jwks_uri",
        "mcp_allowed_hosts_raw",
    ):
        assert name not in _SECRET_FIELDS, (
            f"T-02-04 violated: public MCP field {name!r} was added to _SECRET_FIELDS"
        )
        assert isinstance(getattr(settings, name), str), (
            f"T-02-04 violated: public MCP field {name!r} is not a plain str"
        )
    for public in (
        "https://distinctive-issuer.example",
        "https://distinctive-resource.example/mcp",
        "https://distinctive-jwks.example/keys",
        "distinctive-host.example",
    ):
        assert public not in values, (
            f"T-02-04 violated: public MCP config {public!r} was treated as a secret"
        )


def test_mcp_auth_mode_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised auth mode must fail at boot, not silently fall through."""
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("MCP_AUTH_MODE", "nonsense")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

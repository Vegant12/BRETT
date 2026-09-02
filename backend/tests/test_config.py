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
        "HEALTH_INGEST_SECRET",
        "INGEST_RATE_LIMIT_PER_MINUTE",
        "INGEST_RATE_LIMIT_BURST",
        "INGEST_MAX_BODY_BYTES",
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


def test_health_ingest_secret_is_masked_and_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """HEALTH-07/T-08-14: the webhook credential gets both layers, not just one.

    Layer 1 is the ``SecretStr`` rendering (``repr`` and ``model_dump_json`` show
    ``**********``). Layer 3 is membership in ``_SECRET_FIELDS``, which is the ONLY
    wiring that puts a value into ``secret_values()`` and therefore into the log
    value scrubber. Both are asserted here because either alone leaks: a plain
    ``str`` field would print itself into a validation error, and a ``SecretStr``
    outside ``_SECRET_FIELDS`` is invisible to the scrubber the moment any call
    site does ``get_secret_value()`` near a log line.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("HEALTH_INGEST_SECRET", "ingest-secret-4c1d-must-not-be-logged")
    settings = Settings(_env_file=None)

    rendered = repr(settings) + settings.model_dump_json()

    assert "ingest-secret-4c1d-must-not-be-logged" not in rendered, (
        f"T-08-14 violated: HEALTH_INGEST_SECRET rendered its own value. It must be a "
        f"SecretStr so repr/model_dump_json show ********** instead. Got: {rendered}"
    )
    assert "**********" in rendered, (
        "T-08-14 violated: nothing in the rendered settings is masked at all, so the "
        "SecretStr layer is not doing its job"
    )
    assert "ingest-secret-4c1d-must-not-be-logged" in settings.secret_values(), (
        f"T-08-14 violated: health_ingest_secret is absent from _SECRET_FIELDS, so the log "
        f"value scrubber never learns the literal and one careless log call publishes the "
        f"webhook credential. _SECRET_FIELDS: {_SECRET_FIELDS}"
    )


def test_health_ingest_secret_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-08-16: an unconfigured deployment has a DISABLED ingest path, not a dead process.

    Requiring the secret at boot would break every developer machine, every test
    environment and the Hevy sync job -- all of which never touch the ingest route --
    for a guarantee that belongs to the deploy script instead. The route fails CLOSED
    at request time (plan 08-07); ``test_cloud_run_deploy.py`` is what guarantees
    production actually has the binding.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    settings = Settings(_env_file=None)

    assert settings.health_ingest_secret is None, (
        f"T-08-16 violated: health_ingest_secret must default to None so an unset credential "
        f"is a disabled path rather than a boot failure. Got: {settings.health_ingest_secret!r}"
    )
    assert settings.secret_values(), "the DATABASE_URL secret must still be scrubbed"


def test_ingest_tuning_numbers_default_correctly_and_are_not_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RESEARCH Pitfalls 2 and 5: operational numbers must stay readable in logs.

    The three values are the ingest bucket's geometry and the pre-parse body cap.
    They are asserted to be plain ``int`` AND absent from ``_SECRET_FIELDS`` for the
    same reason ``test_mcp_config_is_not_secret`` asserts it of the public MCP
    config: a number added to the value scrubber gets replaced by ``***REDACTED***``
    in every log line that happens to contain it -- ``30`` would redact timestamps,
    counts and IDs across the whole stream and make the logs unreadable.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    settings = Settings(_env_file=None)

    assert settings.ingest_rate_limit_per_minute == 30, (
        f"RESEARCH Pitfall 2 violated: the ingest bucket's refill default changed. "
        f"Got: {settings.ingest_rate_limit_per_minute!r}"
    )
    assert settings.ingest_rate_limit_burst == 30, (
        f"RESEARCH Pitfall 2 violated: the ingest bucket's burst default changed. "
        f"Got: {settings.ingest_rate_limit_burst!r}"
    )
    assert settings.ingest_max_body_bytes == 10_485_760, (
        f"RESEARCH Pitfall 5 violated: the pre-parse body cap is not 10 MiB. Measured peak "
        f"resident memory decoding a 10 MB body is ~235 MB, and the cap is what keeps the 1Gi "
        f"instance from OOMing into a 503 with no log line. Got: {settings.ingest_max_body_bytes!r}"
    )

    for name in (
        "ingest_rate_limit_per_minute",
        "ingest_rate_limit_burst",
        "ingest_max_body_bytes",
    ):
        assert name not in _SECRET_FIELDS, (
            f"RESEARCH Pitfall 2 violated: operational tuning field {name!r} was added to "
            f"_SECRET_FIELDS; the log value scrubber would then redact that plain number "
            f"everywhere it appears and make the log stream unreadable"
        )
        assert isinstance(getattr(settings, name), int), (
            f"{name!r} must be a plain int, not a SecretStr or a str"
        )


def test_ingest_tuning_numbers_are_env_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEPLOY-01: deploy/cloud-run.env.yaml must be able to retune without a commit.

    Deliberately distinct values, so a field that silently ignored its environment
    variable -- a typo'd name, a ``validation_alias`` that does not match the key the
    env file sets -- fails here instead of shipping a service whose real limits differ
    from the file that claims to configure them.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("INGEST_RATE_LIMIT_PER_MINUTE", "12")
    monkeypatch.setenv("INGEST_RATE_LIMIT_BURST", "7")
    monkeypatch.setenv("INGEST_MAX_BODY_BYTES", "2048")
    settings = Settings(_env_file=None)

    assert (
        settings.ingest_rate_limit_per_minute,
        settings.ingest_rate_limit_burst,
        settings.ingest_max_body_bytes,
    ) == (12, 7, 2048), (
        f"DEPLOY-01 violated: an INGEST_* environment variable is not read into its Settings "
        f"field, so deploy/cloud-run.env.yaml would describe limits the process does not use. "
        f"Got: {settings.ingest_rate_limit_per_minute}, {settings.ingest_rate_limit_burst}, "
        f"{settings.ingest_max_body_bytes}"
    )

"""Typed, fail-fast application settings.

Layer 1 of the three-layer FOUND-05 secret defense:

1. **this module** — every secret is a ``SecretStr``, so ``repr`` and
   ``model_dump_json`` render ``**********`` and validation errors never echo
   the raw input.
2. ``app/logging.py`` — key-name censor + value scrubber built from
   :meth:`Settings.secret_values`.
3. the FastAPI error handler — sanitized responses.

Nothing here may ``print`` or log a settings value.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_SSL_REQUIRING_MODES = ("require", "verify-ca", "verify-full")

_SECRET_FIELDS = ("database_url", "hevy_api_key", "mcp_auth_secret")


class Settings(BaseSettings):
    """Process configuration, validated at construction time.

    Constructing this with a missing or malformed ``DATABASE_URL`` raises
    ``pydantic.ValidationError`` immediately, so a misconfigured process dies at
    boot rather than at its first query.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Without this, pydantic renders `input_value='postgresql://u:pw@h/db'`
        # into the ValidationError for a rejected DATABASE_URL -- password and
        # all. Raising `from None` inside the validator is NOT enough, because
        # the echoed value comes from the error's own `input` field, not from
        # the chained exception. Verified by `test_invalid_url_error_does_not_
        # echo_input`.
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # SecretStr, never a pydantic DSN type: a DSN-typed field's validation
    # failure echoes the raw input -- password included -- into the
    # ValidationError message.
    database_url: SecretStr
    hevy_api_key: SecretStr | None = None
    mcp_auth_secret: SecretStr | None = None

    # MCP transport/auth configuration. NOT secrets: these are public hostnames
    # and URLs that appear in the RFC 9728 metadata document Claude fetches
    # anonymously. They must stay OUT of `_SECRET_FIELDS` -- adding a public
    # hostname to the value scrubber would redact it from every log line and
    # make the logs unreadable.
    #
    # `static` = constant-time compare against MCP_AUTH_SECRET (D-01 CLI proof).
    # `authkit` = WorkOS AuthKit JWKS validation (D-03/D-04), landed in 02-06.
    mcp_auth_mode: Literal["static", "authkit"] = "static"
    mcp_issuer_url: str = "https://example.authkit.app"
    # Must match, character for character, the URL the user types into Claude's
    # "Add custom connector" dialog and the Resource Indicator registered in
    # WorkOS. No trailing slash. (RESEARCH Pitfall 8.)
    mcp_resource_url: str = "http://localhost:8000/mcp"
    # Empty means "not yet discovered". Set explicitly from the `jwks_uri` field
    # of the authorization server's own discovery document rather than assuming
    # a path -- RESEARCH assumption A1 is unverified.
    mcp_jwks_uri: str = ""
    # Comma-separated so a Cloud Run custom domain, or the second URL Cloud Run
    # assigns, can be added without a code change. Read via `mcp_allowed_hosts`.
    # The env var is MCP_ALLOWED_HOSTS (not ..._RAW) because that is the name
    # deploy/cloud-run.env.yaml sets.
    mcp_allowed_hosts_raw: str = Field(
        default="localhost,127.0.0.1",
        validation_alias="MCP_ALLOWED_HOSTS",
    )

    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: SecretStr) -> SecretStr:
        try:
            url = make_url(v.get_secret_value())
        except Exception:
            # `from None` and NO interpolation of the input value.
            raise ValueError("DATABASE_URL is not a valid database URL") from None
        if not url.drivername.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a postgresql:// URL") from None
        return v

    @property
    def async_database_url(self) -> str:
        """Return a URL that ``asyncpg`` actually accepts.

        Managed Postgres providers hand out libpq-flavoured URLs.
        ``asyncpg.connect()`` has no ``sslmode`` parameter and no ``**kwargs``,
        so passing one through raises ``TypeError`` at connect time. Translate
        ``sslmode`` to ``ssl`` and drop the other libpq-only parameters.
        """
        url = make_url(self.database_url.get_secret_value())
        url = url.set(drivername="postgresql+asyncpg")
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        if sslmode in _SSL_REQUIRING_MODES and "ssl" not in query:
            query["ssl"] = "require"
        query.pop("channel_binding", None)  # libpq-only
        return url.set(query=query).render_as_string(hide_password=False)

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        """Host header allowlist for the MCP transport's DNS-rebinding guard.

        A list in the environment is a comma-separated string by necessity, and
        an empty or whitespace-only entry would widen the allowlist by accident,
        so entries are stripped and empties dropped. With `transport_security`
        left at ``None`` the SDK silently allows only ``127.0.0.1``/``localhost``
        and the deployed service's real Host header returns ``421 Invalid Host
        header`` with no MCP-level error body (T-02-01, RESEARCH Pitfall 2).
        """
        return [h.strip() for h in self.mcp_allowed_hosts_raw.split(",") if h.strip()]

    def secret_values(self) -> list[str]:
        """Every literal secret string the log scrubber must never emit.

        Consumed by ``app.logging.make_value_scrubber``. Sorted longest-first so
        a scrubber replacing sequentially removes the full DB URL before it
        removes the bare password substring inside it.
        """
        out: list[str] = []
        for field in _SECRET_FIELDS:
            value = getattr(self, field, None)
            if isinstance(value, SecretStr) and value.get_secret_value():
                raw = value.get_secret_value()
                out.append(raw)
                try:
                    password = make_url(raw).password
                    if password:
                        out.append(password)
                except Exception:  # noqa: S110 - a non-URL secret is fine here
                    pass
        return sorted(set(out), key=len, reverse=True)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, constructing them on first use.

    Raises ``pydantic.ValidationError`` if a required variable is missing.
    Tests must call ``get_settings.cache_clear()`` after changing the
    environment.
    """
    # mypy cannot know that BaseSettings populates `database_url` from the
    # environment, so it reports a missing named argument here.
    return Settings()  # type: ignore[call-arg]

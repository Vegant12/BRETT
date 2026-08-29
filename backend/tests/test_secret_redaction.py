"""FOUND-05: a seeded secret must never reach the rendered log stream.

RESEARCH Pitfall 6 is the reason every assertion here runs against the *rendered*
stream. ``structlog.testing``'s log-capturing context manager clears the entire
configured processor list for its duration, so the redaction processors under test
would never run and this suite would pass while proving nothing. Do not reach for
it here, no matter how much more convenient it looks.
"""

import io
import json
import logging
import os
from collections.abc import Iterator

import pytest
import structlog
from asgi_correlation_id import correlation_id
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.config import Settings, get_settings
from app.logging import configure_logging

SEEDED = "brett-test-secret-DO-NOT-LEAK-9f3a"
DB_URL = f"postgresql://u:{SEEDED}@localhost:5432/db"
REQUEST_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"

# Deliberately NOT seeded into the environment and therefore NOT in
# `Settings.secret_values()`, so Layer 3 cannot see it. That is the whole point:
# it isolates the Layer-2 deny-list in
# `test_hevy_header_key_name_is_redacted_by_layer_2_alone`.
UNSEEDED_KEY = "hevy-key-9f3a-only-layer-2-can-catch-this"

# `app.main` calls get_settings() and configure_logging() at import time, so the
# seeded environment has to exist before the import happens. Nothing ever connects
# to this DATABASE_URL -- these are unit tests, no container required.
os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = DB_URL
os.environ["HEVY_API_KEY"] = SEEDED
get_settings.cache_clear()

from app.main import app  # noqa: E402

# The raising route is registered on the imported app HERE, not in app/main.py, so
# no failure surface ships to production. Guarded so parametrized runs cannot
# register it twice.
if not any(getattr(route, "path", None) == "/__test_boom__" for route in app.routes):

    @app.get("/__test_boom__")
    async def _boom() -> None:
        raise ValueError(f"leaky {SEEDED}")

    # Phase 2: `app/main.py` ends with `app.mount("/", mcp_app)`, a CATCH-ALL,
    # and Starlette resolves routes in list order. Anything appended to the
    # router after import therefore lands BEHIND it and is never reached -- the
    # MCP sub-app answered `/__test_boom__` with its own 404 and the D-05
    # handler under test was never exercised. Re-appending the mount puts it
    # back to being the handler of last resort.
    #
    # Only this module is affected: nothing in production registers a route
    # after import, which is exactly why `app/main.py` can register the mount
    # last and be done with it.
    for _mount in [route for route in app.router.routes if isinstance(route, Mount)]:
        app.router.routes.remove(_mount)
        app.router.routes.append(_mount)


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """``configure_logging`` mutates global state; put it back afterwards.

    Without this, this module poisons every later test module in the session.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    get_settings.cache_clear()
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    structlog.reset_defaults()
    get_settings.cache_clear()


def _settings(monkeypatch: pytest.MonkeyPatch, environment: str = "development") -> Settings:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("HEVY_API_KEY", SEEDED)
    return Settings(_env_file=None)


def _configure(monkeypatch: pytest.MonkeyPatch, environment: str = "development") -> io.StringIO:
    """Install the real pipeline, then point its single handler at a buffer."""
    configure_logging(_settings(monkeypatch, environment))
    buf = io.StringIO()
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(buf)
    return buf


def test_denied_key_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer 2: the key-name deny-list."""
    buf = _configure(monkeypatch)
    structlog.get_logger().info("probe", api_key=SEEDED)

    out = buf.getvalue()
    assert SEEDED not in out
    assert "***REDACTED***" in out


def test_hevy_header_key_name_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer 2 covers Hevy's literal header spelling, not just `api_key`.

    Layer 3 (the value scrubber) would catch this anyway because HEVY_API_KEY is in
    `_SECRET_FIELDS` -- but the deny-list exists precisely so that no single layer is
    load-bearing.
    """
    buf = _configure(monkeypatch)
    structlog.get_logger().info("probe", **{"api-key": SEEDED})

    out = buf.getvalue()
    assert SEEDED not in out
    assert "***REDACTED***" in out


def test_hevy_header_key_name_is_redacted_by_layer_2_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same header name, with Layer 3 taken out of the picture.

    The test above logs ``SEEDED``, which Layer 3 scrubs BY VALUE whatever the key is
    called -- so it stays green even with `"api-key"` deleted from ``DENY_KEYS`` again,
    which is the failure mode this module's docstring warns about: green while proving
    nothing. ``UNSEEDED_KEY`` is not in ``Settings.secret_values()``, so Layer 3 has
    never heard of it and only the key-name deny-list can redact it. Delete `"api-key"`
    from ``DENY_KEYS`` and this test -- and only this test -- goes red.
    """
    buf = _configure(monkeypatch)
    structlog.get_logger().info("probe", **{"api-key": UNSEEDED_KEY})

    out = buf.getvalue()
    assert UNSEEDED_KEY not in out, "T-03-01 violated: Layer 2 does not cover `api-key`"
    assert "***REDACTED***" in out


def test_secret_inside_non_denied_value_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leak channel (a): layer 2 alone fails this; layer 3 closes it."""
    buf = _configure(monkeypatch)
    structlog.get_logger().info("probe", note=f"inline {SEEDED} tail")

    out = buf.getvalue()
    assert SEEDED not in out, "FOUND-05 violated: secret present in a non-denied value"
    assert "***REDACTED***" in out


def test_secret_in_rendered_traceback_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leak channel (b): layer 3 must run AFTER format_exc_info."""
    buf = _configure(monkeypatch)
    log = structlog.get_logger()
    try:
        raise ValueError(f"leaky {SEEDED}")
    except ValueError:
        log.exception("boom")

    out = buf.getvalue()
    assert "Traceback" in out, "the traceback must still be logged, only scrubbed"
    assert SEEDED not in out, "FOUND-05 violated: secret present in rendered traceback"


@pytest.mark.parametrize("name", ["uvicorn.error", "sqlalchemy.engine", "alembic"])
def test_third_party_stdlib_logger_is_redacted(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Leak channel (c): foreign_pre_chain covers loggers nobody here wrote."""
    buf = _configure(monkeypatch)
    logging.getLogger(name).error("third party %s", SEEDED)

    out = buf.getvalue()
    assert SEEDED not in out, f"FOUND-05 violated: secret leaked via {name}"


def test_production_renders_json_without_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-06: the renderer split is cosmetic — redaction is identical in both modes."""
    buf = _configure(monkeypatch, "production")
    structlog.get_logger().info("probe", note=f"inline {SEEDED}", api_key=SEEDED)

    out = buf.getvalue().strip()
    payload = json.loads(out)
    assert payload["event"] == "probe"
    assert payload["api_key"] == "***REDACTED***"
    assert SEEDED not in out


def test_correlation_id_is_attached_to_every_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pitfall 7: merge_contextvars does NOT see asgi-correlation-id's ContextVar."""
    buf = _configure(monkeypatch, "production")
    token = correlation_id.set("cid-11111111")
    try:
        structlog.get_logger().info("probe")
        logging.getLogger("uvicorn.error").error("foreign")
    finally:
        correlation_id.reset(token)

    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    assert all(line["correlation_id"] == "cid-11111111" for line in lines)


def test_secret_never_appears_in_logs_or_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """FOUND-05 end to end: all four leak channels plus the HTTP response."""
    buf = _configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    # (a) secret in a log VALUE, under both a denied and a non-denied key
    structlog.get_logger().info("probe", note=f"inline {SEEDED}", api_key=SEEDED)

    # (b) secret inside an unhandled exception traceback (the D-05 path)
    response = client.get("/__test_boom__", headers={"X-Request-ID": REQUEST_ID})
    assert response.status_code == 500
    assert set(response.json()) == {"error", "correlation_id"}
    assert "Traceback" not in response.text

    # (c) secret from a third-party stdlib logger
    logging.getLogger("uvicorn.error").error("third party %s", SEEDED)

    out = buf.getvalue()
    assert "Traceback" in out, "the traceback must reach the log, only scrubbed"
    assert SEEDED not in out, "FOUND-05 violated: secret present in log stream"
    assert SEEDED not in response.text, "FOUND-05 violated: secret present in HTTP response"


@pytest.mark.parametrize("environment", ["development", "production"])
def test_error_body_sanitized_in_all_environments(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """D-05: the 500 body is identical in every environment. No debug branch."""
    _configure(monkeypatch, environment)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/__test_boom__", headers={"X-Request-ID": REQUEST_ID})

    assert response.status_code == 500
    assert set(response.json()) == {"error", "correlation_id"}
    assert response.json()["error"] == "internal server error"
    assert "Traceback" not in response.text
    assert "ValueError" not in response.text, "exception class name leaked to the client"
    assert "leaky" not in response.text, "exception message leaked to the client"


def test_correlation_id_links_body_to_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-01-11: a sanitized error stays debuggable through the correlation id."""
    buf = _configure(monkeypatch, "production")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/__test_boom__", headers={"X-Request-ID": REQUEST_ID})

    assert response.json()["correlation_id"] == REQUEST_ID
    assert REQUEST_ID in buf.getvalue()

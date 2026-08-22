"""FOUND-05: a seeded secret must never reach the rendered log stream.

RESEARCH Pitfall 6 is the reason every assertion here runs against the *rendered*
stream: ``structlog.testing.capture_logs()`` calls ``configured_processors.clear()``,
so the redaction processors under test would never run and the suite would pass
while proving nothing.
"""

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog
from asgi_correlation_id import correlation_id

from app.config import Settings
from app.logging import configure_logging

SEEDED = "brett-test-secret-DO-NOT-LEAK-9f3a"
DB_URL = f"postgresql://u:{SEEDED}@localhost:5432/db"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """``configure_logging`` mutates global state; put it back afterwards.

    Without this, this module poisons every later test module in the session.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    structlog.reset_defaults()


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
def test_third_party_stdlib_logger_is_redacted(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
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

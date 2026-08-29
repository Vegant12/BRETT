"""Structured logging with the three-layer FOUND-05 secret defense.

Layer 1 lives in :mod:`app.config` (``SecretStr`` + ``hide_input_in_errors``).
Layers 2 and 3 live here:

============  ==================================  =================================
Layer         Mechanism                           Leak channel it closes
============  ==================================  =================================
2             :func:`censor_keys` deny-list       secret under a known key name
3             :func:`make_value_scrubber`         secret inside *any* string value,
                                                  including a rendered traceback
============  ==================================  =================================

RESEARCH proved each layer alone leaks. Three ordering constraints are
load-bearing and must survive any future edit:

1. Layer 3 must run **after** ``structlog.processors.format_exc_info``. Before it,
   the traceback is still an ``exc_info`` tuple and a string scrubber sees nothing.
2. The whole shared chain must be handed to
   ``ProcessorFormatter(foreign_pre_chain=...)`` and the root logger's handlers
   replaced, or records from uvicorn / SQLAlchemy / Alembic bypass redaction.
3. :func:`add_correlation_id` must be its own processor —
   ``structlog.contextvars.merge_contextvars`` does not see asgi-correlation-id's
   ContextVar.

The D-06 renderer split (console vs JSON) is applied *after* the shared chain, so
it is cosmetic and cannot affect redaction.
"""

import logging
import sys
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from structlog.typing import EventDict, Processor, WrappedLogger

from app.config import Settings

# Layer 2: key-name deny-list. Cheap, catches the common case, NOT sufficient alone.
DENY_KEYS = frozenset(
    {
        "api_key",
        # Hevy's live OpenAPI declares the auth header as the literal name `api-key`
        # (lowercase, hyphen). `api_key` and `x-api-key` were already here; this exact
        # spelling was not, and it is the one this project actually sends (Pitfall 9).
        "api-key",
        "apikey",
        "hevy_api_key",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "mcp_auth_secret",
        "jwt_secret",
        "token",
        "access_token",
        "refresh_token",
        "database_url",
        "db_url",
        "dsn",
        "credentials",
        "encrypted_credentials",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)

REDACTED = "***REDACTED***"

_NOISY_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "sqlalchemy.engine",
    "alembic",
)


def censor_keys(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Layer 2 — replace the value of any key whose name is on the deny-list."""
    for key in list(event_dict):
        if key.lower() in DENY_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def add_correlation_id(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Bridge asgi-correlation-id's ContextVar into the event dict.

    ``structlog.contextvars.merge_contextvars`` only reads structlog's own
    prefixed ContextVars, so without this processor no log line carries the
    request id and a sanitized 500 response becomes undebuggable.
    """
    cid = correlation_id.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def make_value_scrubber(secrets: list[str]) -> Processor:
    """Layer 3 — recursively replace known secret *values* anywhere in the event.

    ``secrets`` arrives longest-first from :meth:`app.config.Settings.secret_values`,
    which matters when one secret contains another (the database URL contains the
    password): the longer match is consumed before the substring can match.
    """

    def _scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            for secret in secrets:
                if secret and secret in obj:
                    obj = obj.replace(secret, REDACTED)
            return obj
        if isinstance(obj, dict):
            return {key: _scrub(value) for key, value in obj.items()}
        if isinstance(obj, list | tuple):
            return type(obj)(_scrub(value) for value in obj)
        return obj

    def scrub_values(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
        scrubbed: EventDict = _scrub(event_dict)
        return scrubbed

    return scrub_values


def configure_logging(settings: Settings) -> None:
    """Install the one and only logging configuration for this process.

    Every record in the process — structlog events and third-party stdlib
    records alike — leaves through the single root handler installed here, and
    therefore through both redaction layers.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        censor_keys,  # layer 2
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,  # exc_info tuple -> str
        # layer 3 - position is load-bearing, see the module docstring
        make_value_scrubber(settings.secret_values()),
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # D-06: rendering choice only. Both branches share the identical `shared` chain.
    dev = settings.environment == "development"
    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=True) if dev else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # CRITICAL: foreign_pre_chain applies `shared` -- and therefore BOTH
        # redaction layers -- to records from uvicorn, sqlalchemy, alembic and
        # every other stdlib logger in the process.
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # Strip library-installed handlers so nothing reaches stdout unredacted.
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True

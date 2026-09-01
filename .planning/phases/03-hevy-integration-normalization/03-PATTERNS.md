# Phase 3: Hevy Integration & Normalization - Pattern Map

**Mapped:** 2026-08-29
**Files analyzed:** 33 (26 new, 7 modified)
**Analogs found:** 29 / 33

> **How to read this.** Every "Analog" below is a real file already in this repo. The excerpts are
> verbatim, with line numbers, so a plan action can say *"copy lines N–M of `<path>`"* rather than
> *"follow the existing pattern."* Four files have no analog at all — they are listed in
> **No Analog Found** with the RESEARCH.md section the planner should use instead.

## File Classification

### Application code

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|-------------------|------|-----------|----------------|-------|
| `backend/app/integrations/__init__.py` | package init | — | `backend/app/mcp/__init__.py` | exact |
| `backend/app/integrations/hevy/__init__.py` | package init | — | `backend/app/mcp/tools/__init__.py` | exact |
| `backend/app/integrations/hevy/errors.py` | utility (exception types) | transform | — | **none** |
| `backend/app/integrations/hevy/schemas.py` | model (wire DTO) | transform / validation | `backend/app/mcp/tools/ping.py` + `backend/app/config.py` | partial |
| `backend/app/integrations/hevy/client.py` | service (outbound HTTP client) | request-response | `backend/app/mcp/auth.py` (`AuthKitJWTVerifier`) | partial |
| `backend/app/integrations/hevy/sync.py` | service (orchestration) | batch + event-driven | — (composite, see below) | **none** |
| `backend/app/normalization/__init__.py` | package init | — | `backend/app/core/__init__.py` | exact |
| `backend/app/normalization/muscles.py` | utility (domain translation) | transform | `backend/app/core/time.py` | role-match |
| `backend/app/normalization/exercise_map.py` | config/data (curated) | transform | `backend/app/logging.py` (`DENY_KEYS`) | partial |
| `backend/app/db/models/workout.py` | model | CRUD (parent + cascade children) | `backend/app/db/models/user.py` | role-match |
| `backend/app/db/models/exercise.py` | model | CRUD | `backend/app/db/models/user.py` | role-match |
| `backend/app/db/models/body.py` | model | CRUD (upsert by natural key) | `backend/app/db/models/user.py` | role-match |
| `backend/app/db/models/sync_state.py` | model | CRUD (checkpoint) | `backend/app/db/models/user.py` | role-match |
| `backend/app/cli.py` | entrypoint (CLI) | batch | — (partial: `backend/app/main.py` bootstrap) | **none** |
| `backend/app/db/models/__init__.py` *(mod)* | registry | — | itself | exact |
| `backend/app/logging.py` *(mod)* | config | — | itself | exact |

### Migrations

| New File | Role | Data Flow | Closest Analog | Match |
|----------|------|-----------|----------------|-------|
| `backend/migrations/versions/0003_*.py` | migration (DDL) | schema | `backend/migrations/versions/0001_initial_schema.py` | exact |
| `backend/migrations/versions/0004_*.py` *(only if D-02 ships as seeded rows)* | migration (data seed) | batch insert | `backend/migrations/versions/0002_seed_default_user.py` | exact |

### Tests

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|-------------------|------|-----------|----------------|-------|
| `backend/tests/fixtures/hevy/*.json` | test data | — | — | **none** |
| `backend/tests/test_hevy_client.py` | test (unit, stubbed boundary) | request-response | `backend/tests/test_mcp_auth.py` | role-match |
| `backend/tests/test_hevy_events.py` | test (unit, pure logic) | transform | `backend/tests/test_time.py` | role-match |
| `backend/tests/test_hevy_sync.py` | test (integration, container) | CRUD | `backend/tests/test_migrations.py` | role-match |
| `backend/tests/test_hevy_templates.py` | test (integration) | CRUD | `backend/tests/test_migrations.py` | role-match |
| `backend/tests/test_hevy_body.py` | test (integration) | CRUD | `backend/tests/test_migrations.py` | role-match |
| `backend/tests/test_hevy_resilience.py` | test (integration, failure paths) | batch | `backend/tests/test_mcp_tools.py` / `test_health.py` | role-match |
| `backend/tests/test_hevy_isolation.py` | test (static, no container) | — | `backend/tests/test_cloud_run_deploy.py` | exact |
| `backend/tests/test_normalization.py` | test (unit + integration) | transform | `backend/tests/test_db_models.py` | role-match |
| `backend/tests/test_sync_state.py` | test (integration) | CRUD | `backend/tests/test_migrations.py` | role-match |
| `backend/tests/conftest.py` *(mod)* | fixtures | — | itself | exact |
| `backend/tests/test_db_models.py` *(mod)* | test (unit) | — | itself | exact |
| `backend/tests/test_secret_redaction.py` *(mod)* | test (unit) | — | itself | exact |

### Config

| Modified File | Role | Closest Analog | Match |
|---------------|------|----------------|-------|
| `pyproject.toml` | config | itself (lines 6–32) | exact |
| `.env.example` | config | itself | exact |

---

## Pattern Assignments

### `backend/app/db/models/workout.py`, `exercise.py`, `body.py`, `sync_state.py` (model, CRUD)

**Analog:** `backend/app/db/models/user.py` (the only model in the repo)

**Imports pattern** (`backend/app/db/models/user.py:1-12`):
```python
"""The ``users`` table (blueprint §5.1).

v1 is single-user, but the schema is deliberately not hard-coded to one row.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
```

Note: `PGUUID` is aliased on import, `Mapped`/`mapped_column` is the SQLAlchemy 2.0 typed style
(never `Column(...)`), and **`Base` + `TimestampMixin` always come from `app.db.base`** — a second
`DeclarativeBase` would be invisible to Alembic autogenerate.

**Core model pattern** (`backend/app/db/models/user.py:15-28`):
```python
class User(Base, TimestampMixin):
    """A platform user. Exactly one row exists in v1, seeded by migration 0002."""

    __tablename__ = "users"

    # UUID PK, not an integer: blueprint §5.1 requires not precluding multi-user
    # later, and the seed migration needs a stable, known identifier.
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # FOUND-03: the user's timezone lives HERE, not in an env var, so analytics
    # bucketing reads it from the row it is already loading.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Jakarta")
```

**Timestamp columns — do NOT redeclare them** (`backend/app/db/base.py:37-50`):
```python
class TimestampMixin:
    """FOUND-04: every timestamp is TIMESTAMPTZ. Never use bare ``DateTime()``.

    ``DateTime()`` maps to ``TIMESTAMP WITHOUT TIME ZONE``, which silently
    discards the offset on write and hands back a naive datetime on read --
    the exact failure mode the requirement exists to prevent.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

Every new Hevy timestamp column (`start_time`, `end_time`, `provider_updated_at`,
`last_synced_at`, `cursor_timestamp`) must be `DateTime(timezone=True)` for the same reason.
`body_measurements.measured_on` is the one deliberate exception — `sa.Date`, per RESEARCH Pattern 9.

**Constraint naming — inherited, not declared** (`backend/app/db/base.py:18-34`):
```python
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

RESEARCH Pattern 7 and Pattern 9 both pass an explicit `name=` to `UniqueConstraint` — that is
compatible with the convention (an explicit name wins) and is what the ON CONFLICT clauses need.

**What has NO precedent in `user.py` and must be written fresh** (use RESEARCH.md, not this analog):
- `ForeignKey("users.id", ondelete="CASCADE")` — no FK exists anywhere yet
- `UniqueConstraint(...)` / `__table_args__` — `user.py` has none
- `Numeric(...)` columns — RESEARCH "Alternatives Considered" bans `Float` for weights
- `relationship()` — `backend/tests/test_db_models.py:55-57` currently asserts
  `list(User.__mapper__.relationships) == []`; that test is about `User`, so new models may define
  relationships without touching it.

---

### `backend/app/db/models/__init__.py` (registry, modified)

**Analog:** itself. This file is 13 lines and Pitfall 8 makes it load-bearing.

**Current full contents** (`backend/app/db/models/__init__.py:1-13`):
```python
"""Model registry.

Importing this package is what attaches every table to ``Base.metadata``.
``migrations/env.py`` imports it for exactly that reason: without the import,
``alembic revision --autogenerate`` sees empty metadata and emits an empty
migration with no error.

Every new model must be imported here.
"""

from app.db.models.user import User

__all__ = ["User"]
```

Add one import line per new model and extend `__all__`. `backend/migrations/env.py:27` is the
consumer:
```python
import app.db.models  # noqa: E402, F401
```

---

### `backend/migrations/versions/0003_*.py` (migration, DDL)

**Analog:** `backend/migrations/versions/0001_initial_schema.py`

**Header pattern** (`backend/migrations/versions/0001_initial_schema.py:1-22`):
```python
"""initial schema: the users table (blueprint §5.1)

Generated by ``alembic revision --autogenerate`` and hand-reviewed. Only the
``users`` table ships in Phase 1 -- the provider-credentials table of blueprint
§5.2 is deferred to Phase 3 per D-07, so no unencrypted credential column
exists in the interim.

Revision ID: 0001
Revises:
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```

Revision ids are **zero-padded sequential strings** (`"0001"`, `"0002"`), not alembic's default
random hashes. The new one is `"0003"` with `down_revision = "0002"`, and the filename follows
`0003_<snake_case_summary>.py`.

**DDL pattern with `op.f()`** (`backend/migrations/versions/0001_initial_schema.py:25-50`):
```python
def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Jakarta", nullable=False),
        # FOUND-04: both timestamps are TIMESTAMPTZ, never bare TIMESTAMP.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # `op.f` marks the name as already-conventionalized so the naming
        # convention is not applied a second time.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )


def downgrade() -> None:
    op.drop_table("users")
```

`downgrade()` must be complete — `backend/tests/test_migrations.py:47-50` asserts
`downgrade base` leaves only `alembic_version`. Drop child tables before parents.

---

### `backend/migrations/versions/0004_*.py` (migration, data seed — only if D-02 ships as rows)

**Analog:** `backend/migrations/versions/0002_seed_default_user.py`

**Constants + rationale** (`backend/migrations/versions/0002_seed_default_user.py:25-33`):
```python
# A FIXED UUID, not uuid4(). Later phases, fixtures and manual queries reference
# this constant, and re-running migrations on a fresh database yields an
# identical row rather than a new random identity each time.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# D-02: hardcoded, deliberately NOT read from the environment. A migration
# describes a fixed historical transition; making it env-coupled means two
# databases at the same revision can hold different data.
DEFAULT_TIMEZONE = "Asia/Jakarta"
```

**Seed pattern — lightweight `sa.table()`, never the ORM model**
(`backend/migrations/versions/0002_seed_default_user.py:36-61`):
```python
def upgrade() -> None:
    # A lightweight `sa.table()` construct, NOT `app.db.models.User`. A revision
    # must describe the schema as of that revision; importing the live model
    # couples this file to whatever the model looks like today and breaks
    # replay once the model changes.
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("timezone", sa.String),
    )
    op.bulk_insert(users, [{"id": DEFAULT_USER_ID, "timezone": DEFAULT_TIMEZONE}])


def downgrade() -> None:
    # Bound parameter, never an f-string (T-01-14, Ruff S608).
    op.execute(
        sa.text("DELETE FROM users WHERE id = :uid").bindparams(
            sa.bindparam("uid", DEFAULT_USER_ID, type_=postgresql.UUID(as_uuid=True))
        )
    )
```

**Direct consequence for D-02.** This analog forbids `from app.normalization.exercise_map import
CURATED_MAP` inside a migration. If the curated mapping ships as seeded rows, the migration must
carry its own literal copy of the data as of that revision. That is a real cost, and it is a
concrete argument for the Python-module option in CONTEXT.md's discretion list — the planner should
weigh it explicitly rather than by default.

---

### `backend/app/integrations/hevy/client.py` (service, request-response)

**Analog:** `backend/app/mcp/auth.py` — `AuthKitJWTVerifier`, the repo's only class that holds a
credential and talks to a remote host.

**Class docstring convention — state the failure mode, not the mechanism**
(`backend/app/mcp/auth.py:54-74`):
```python
class AuthKitJWTVerifier:
    """Validate a WorkOS AuthKit JWT against the tenant's JWKS (D-03, D-04).

    ``PyJWKClient.fetch_data`` uses a BLOCKING ``urllib.request.urlopen``, so
    calling it from this async method would stall the whole event loop for the
    duration of an HTTPS round trip -- one slow JWKS fetch would freeze every
    concurrent request (T-02-08). It is therefore pushed to a worker thread.
    ...
    Any failure returns ``None``. Failing CLOSED on a JWKS outage means a
    transient IdP problem locks us out for up to the cache lifetime; failing
    OPEN would mean an IdP outage silently disables authentication on a health
    data endpoint (T-02-07). Nothing is logged -- an exception raised while
    decoding can carry the token itself (T-02-04).
    """
```

**Credential handling in `__init__`** (`backend/app/mcp/auth.py:76-79`):
```python
    def __init__(self, issuer: str, audience: str, jwks_uri: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks = PyJWKClient(jwks_uri, cache_jwk_set=True)
```

The credential is **unwrapped once at construction and stored privately**, never re-read per call.
RESEARCH's `HevyClient.__init__(self, api_key: SecretStr)` calling
`api_key.get_secret_value()` into the `httpx2.AsyncClient` headers matches this exactly.
`StaticTokenVerifier.__init__` (`backend/app/mcp/auth.py:37-46`) does the same with an explanatory
comment about *why* the encoding choice matters — copy that commenting density.

**Fail-closed / never-log-the-credential** (`backend/app/mcp/auth.py:103-104`):
```python
        except Exception:  # noqa: BLE001 - any validation failure is just "unauthenticated"
            return None
```

Two things to carry across: the `# noqa: BLE001 - <reason>` form (a bare `except Exception` is only
acceptable with an inline justification), and the rule that **nothing is logged from a credential
path**. `HevyAuthError` must not interpolate the key, and per RESEARCH Pattern 7 `last_error` stores
an exception class name + message, never a response body.

**Factory + fail-fast selector** (`backend/app/mcp/auth.py:117-141`):
```python
def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Select the verifier for the configured auth mode.

    Fails fast at import time rather than at first request: a server that starts
    without a working verifier is a server that is unauthenticated in production
    until someone notices. ...
    """
    if settings.mcp_auth_mode == "authkit":
        if not settings.mcp_jwks_uri:
            raise RuntimeError(
                "MCP_JWKS_URI is required when MCP_AUTH_MODE=authkit; read it "
                "from the authorization server's discovery document"
            )
        ...
    secret = settings.mcp_auth_secret
    if secret is None or not secret.get_secret_value():
        raise RuntimeError("MCP_AUTH_SECRET is required to start the MCP server")
    return StaticTokenVerifier(secret.get_secret_value())
```

`Settings.hevy_api_key` is `SecretStr | None` (`backend/app/config.py:56`), so a
`build_hevy_client(settings)` factory needs the identical `is None or not get_secret_value()` guard
with a `RuntimeError` naming the env var. Note the message names `MCP_AUTH_SECRET` (the env var),
not `mcp_auth_secret` (the field) — do the same with `HEVY_API_KEY`.

**Also relevant — factory-not-singleton** (`backend/app/db/session.py:1-7, 19-32`):
```python
"""Engine and session factories.

Factories, not module-level singletons, on purpose: a module-level
``create_async_engine(...)`` binds its pool to whichever event loop imported it,
which breaks under pytest-asyncio and leaks connections between tests. The
caller (``lifespan``, a fixture, the CLI) owns the engine's lifetime.
"""
```
The same reasoning applies to `httpx2.AsyncClient`: build it in a factory (or an async context
manager), never at module import.

---

### `backend/app/integrations/hevy/schemas.py` (model, validation)

**Analog:** `backend/app/mcp/tools/ping.py` (the only `BaseModel` outside `Settings`) plus
`backend/app/config.py` for validator conventions.

**BaseModel declaration style** (`backend/app/mcp/tools/ping.py:24-29`):
```python
class PingResult(BaseModel):
    """Returning a BaseModel auto-populates outputSchema and structuredContent."""

    status: str
    database: str
```

**Validator conventions — never echo the rejected input** (`backend/app/config.py:86-96`):
```python
    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: SecretStr) -> SecretStr:
        try:
            url = make_url(v.get_secret_value())
        except Exception:
            # `from None` and NO interpolation of the input value.
            raise ValueError("DATABASE_URL is not a valid database URL") from None
```

Directly relevant: a Hevy response can carry workout titles and body-composition numbers. A
Pydantic `ValidationError` from `schemas.py` renders `input_value=...`. RESEARCH Pattern 6 routes
malformed workouts into `log.warning("hevy.workout.skipped", workout_id=..., reason=type(exc).__name__)`
— i.e. **the exception class name only, never the exception's rendered message**. That mirrors
`hide_input_in_errors=True` at `backend/app/config.py:46`. Consider setting
`model_config = ConfigDict(hide_input_in_errors=True)` on the Hevy schema base for the same reason.

**Discriminated union (RESEARCH Pattern 2) has no in-repo analog.** Use RESEARCH.md's
`UpdatedWorkout` / `DeletedWorkout` guidance directly.

---

### `backend/app/normalization/muscles.py` (utility, transform)

**Analog:** `backend/app/core/time.py` — the repo's model for a provider-neutral, framework-free
domain module. `normalization/` sits at the same architectural level as `core/`.

**Module docstring pattern — state the stake** (`backend/app/core/time.py:1-15`):
```python
"""Timezone bucketing. FOUND-03 (configurable tz) and FOUND-04 (UTC storage).

Every day/week grouping in this project routes through this module. In SQL,
always write ``AT TIME ZONE :tz`` before ``date_trunc``, and use
``local_day_bounds()`` for WHERE-clause filtering.
...
Getting this wrong is not a rounding error. At a UTC+7 offset, any instant
between 17:00Z and 24:00Z belongs to the *next* local day -- which is every
morning workout.
"""
```

`muscles.py` should open the same way: name NORM-01, name the 19 canonical groups as the single
source of truth, and state the stake (the delt split does not exist in any public dataset — RESEARCH
"Muscle Taxonomy").

**Reject-at-the-boundary pattern** (`backend/app/core/time.py:43-54`):
```python
def validate_timezone(tz: str) -> str:
    """Reject a non-IANA timezone at the boundary rather than deep in analytics.

    ``users.timezone`` carries no DB-level CHECK constraint, so a bad value
    would otherwise surface as a ``ZoneInfoNotFoundError`` from inside an
    aggregate query.
    """
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown IANA timezone") from None
    return tz
```

This is the shape for `translate_hevy_muscle_group(value) -> CanonicalGroup | None`: an unknown
Hevy enum value must be handled explicitly (D-03 unmapped path) rather than silently passed through.
Note `raise ... from None` and the no-interpolation rule.

**Guard-not-convention pattern** (`backend/app/core/time.py:31-40`):
```python
def _require_aware(ts: dt.datetime) -> dt.datetime:
    """Fail loudly on naive datetimes.

    FOUND-04 is enforced by a guard, not a convention. Silently assuming UTC
    for a naive input is how a local-time value ends up mis-bucketed with no
    error anywhere in the stack.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware UTC")
    return ts
```

RESEARCH Pattern 9 notes `datetime.fromisoformat("2024-08-14")` returns a **naive** datetime that
this guard correctly rejects — parse Hevy's `date` field with `datetime.date.fromisoformat`, which
produces a `date` and never reaches `_require_aware`.

---

### `backend/app/normalization/exercise_map.py` (config/data, curated)

**Analog:** `backend/app/logging.py` — the repo's only module-level curated data constant.

**Curated constant pattern** (`backend/app/logging.py:40-65`):
```python
# Layer 2: key-name deny-list. Cheap, catches the common case, NOT sufficient alone.
DENY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "hevy_api_key",
        ...
        "x-api-key",
    }
)
```

Carry across: an **immutable** container (`frozenset` / a module-level `dict` treated as read-only),
`UPPER_SNAKE` naming, and a leading comment that says what the data *is for* and what it does not
cover. `exercise_map.py`'s comment should record D-02 ("authored and reviewed like code") and D-03
("absence from this map is a supported state, not an error").

**Note:** this same file, at line 41–65, is the thing Pitfall 9 says must change — see
*Shared Patterns → Secret redaction* below.

---

### `backend/app/cli.py` (entrypoint, batch) — partial analog only

**Partial analog:** `backend/app/main.py` — the only process entrypoint in the repo. Copy the
**bootstrap ordering** and the **engine ownership**, not the FastAPI parts.

**Bootstrap order is load-bearing** (`backend/app/main.py:1-7, 24-26`):
```python
"""FastAPI application bootstrap.

Bootstrap order is load-bearing: configuration is read first so a misconfigured
process dies immediately, then logging is configured -- the value scrubber needs
``settings.secret_values()`` -- and only then is the app object built. Any log
line emitted before ``configure_logging`` would bypass redaction entirely.
"""
...
settings = get_settings()  # fail-fast BEFORE anything else
configure_logging(settings)  # then logging, so the scrubber has the secret values
log = structlog.get_logger()
```

A `sync-hevy` CLI that logs before `configure_logging(settings)` writes an unredacted line — and
the very first thing it would log is a Hevy request. Same three lines, same order.

**Engine lifetime + lifecycle logging** (`backend/app/main.py:49-59`):
```python
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            yield
    finally:
        await engine.dispose()
        log.info("service_stopped")
```

The CLI owns its engine exactly the same way: `make_engine(settings)` →
`make_sessionmaker(engine)` → `try/finally: await engine.dispose()`. The
`log.info("service_starting", ...)` / `log.info("service_stopped")` bracket is the event-naming
convention for blueprint §44's sync-lifecycle logs (`hevy_sync_started` / `hevy_sync_completed`).

**Gap:** there is no argument-parsing, no `__main__.py`, and no console-script entry in
`pyproject.toml`. `Procfile` (`web: uvicorn app.main:app --app-dir backend ...`) shows `backend/` is
the import root, so `python -m app.cli` requires the same `--app-dir`-equivalent (`cwd=backend` or
`PYTHONPATH=backend`) — `backend/tests/conftest.py:31-33` and `backend/migrations/env.py:19-22`
both document this exact constraint.

---

### `backend/tests/test_hevy_isolation.py` (test, static assertions) — best analog in the repo

**Analog:** `backend/tests/test_cloud_run_deploy.py` — same shape: static assertions over committed
files, no container, and **deliberately no `integration` marker** so drift fails the fast suite.

**Why-it-is-a-test-not-a-comment docstring** (`backend/tests/test_cloud_run_deploy.py:20-24`):
```python
Static assertions over committed files: no container, no network, and
deliberately no integration marker -- drift must fail the fast suite on the
commit that introduces it, not after a deploy.
"""
```

**Path constants pattern** (`backend/tests/test_cloud_run_deploy.py:26-41`):
```python
import re
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / "deploy" / "cloud-run.env.yaml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-cloud-run.sh"
```

For HEVY-05, walk `backend/app/` with `Path.rglob("*.py")`, skip anything under
`app/integrations/hevy/`, and assert no remaining file's source matches
`from app.integrations.hevy.schemas import` / `import app.integrations.hevy.schemas`.
`REPO_ROOT = Path(__file__).resolve().parents[2]` is the exact idiom (also used at
`backend/tests/test_config.py:12`).

---

### `backend/tests/test_hevy_client.py` (test, unit with stubbed network boundary)

**Analog:** `backend/tests/test_mcp_auth.py`

**Where the stub boundary sits — state it in the docstring**
(`backend/tests/test_mcp_auth.py:28-42`):
```python
Plan 02-06 added the third block: the Stage-B `AuthKitJWTVerifier`. **Where the
stubbing boundary sits matters more here than anywhere else in the suite, so it
is stated explicitly.** The signing key is a real RSA-2048 key pair generated
per module by `cryptography`, the tokens are really signed by `jwt.encode`, and
the acceptance/rejection decision is really made by `jwt.decode`. ...
The *only* thing replaced is `PyJWKClient.get_signing_key_from_jwt` -- i.e. the
blocking HTTPS round trip ...

The inverse approach, mocking `jwt.decode`, would prove nothing at all: every
threat this class exists to stop ... lives *inside* that call. Stubbing it would
leave a green suite over a verifier that accepts anything.
"""
```

Apply verbatim in spirit: mock **the HTTP transport only**. The status→exception mapping, the
tenacity predicate, the page-size constants and the pagination loop must all be the real code.
Mocking `HevyClient.get_workouts` would leave a green suite over an untested client.

**Distinctive-constant pattern** (`backend/tests/test_mcp_auth.py:104-107`):
```python
# Distinctive on purpose: `test_401_leaks_nothing` asserts this exact string is
# absent from the rejection body, so an SDK that starts echoing the presented
# credential back to the caller fails loudly instead of shipping.
BAD_TOKEN = "wrong-token-9f3a-must-not-be-echoed"
```

Use the same trick for the Hevy key in client tests: a distinctive
`HEVY_KEY = "hevy-key-9f3a-must-not-be-logged"` makes the Pitfall 9 assertion unambiguous.

**Also note** (`backend/tests/test_mcp_auth.py:76-82`): *"test modules in this repo do not import
each other, and a shared fixture file would hide which envelope a given assertion actually sent."*
Duplicate constants across `test_hevy_*.py` rather than creating a shared helper module. Shared
**fixtures** belong in `conftest.py`; shared **constants** get duplicated with a comment.

---

### `backend/tests/test_hevy_sync.py`, `test_hevy_templates.py`, `test_hevy_body.py`, `test_sync_state.py` (test, integration)

**Analog:** `backend/tests/test_migrations.py`

**Marker + fixture + raw-SQL-assertion pattern** (`backend/tests/test_migrations.py:1-6, 19-33`):
```python
"""FOUND-02: migrations are the sole authority over the schema.

Every assertion here runs against a real Postgres container. SQLite would prove
nothing -- ``TIMESTAMPTZ``, ``information_schema`` and the UUID type all behave
differently or not at all.
"""
...
async def _tables(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' order by table_name"
            )
        )
    return [row[0] for row in rows]
```

```python
@pytest.mark.integration
async def test_migrations_round_trip(
    engine: AsyncEngine,
    alembic: Callable[..., subprocess.CompletedProcess[str]],
    restore_schema: None,
) -> None:
```

Every container-touching test carries `@pytest.mark.integration` (declared at
`pyproject.toml:51-53`) and takes `engine` or `session` from `conftest.py`. `asyncio_mode = "auto"`
(`pyproject.toml:48`) means **no `@pytest.mark.asyncio` decorator** — an `async def` test just works.

**Row-count assertions** are the idiom for HEVY-03's "three consecutive syncs hold counts at
(1,1,2)" — mirror `_users()` at `backend/tests/test_migrations.py:30-33` with small
`_count(engine, table)` helpers rather than ORM loads.

**Shared-container hygiene** — `backend/tests/test_time.py:19-24` documents the rule:
> The Postgres container is session-scoped and shared, and ``test_migrations`` asserts
> ``count(*) == 1`` on ``users`` ... The two tests here that mutate state therefore never commit --
> they roll back in a ``finally``, which is strictly stronger than a compensating UPDATE
> because it also survives an assertion failure mid-test.

Hevy sync tests *must* commit (per-page commit is the thing under test), so they must clean up in a
`finally` instead — `DELETE FROM workouts WHERE user_id = ...`. A leaked workout row would break
later tests in the same session.

---

### `backend/tests/test_hevy_resilience.py` (test, integration failure paths)

**Analog:** `backend/tests/test_mcp_tools.py` and `backend/tests/test_health.py` — for the
*real-failure-not-a-mock* philosophy.

**The rule, stated in the analog** (`backend/tests/test_mcp_tools.py:13-18`):
```python
**The unreachable database is a REAL connection to closed port 1, never a
mock**, for the same reason ``test_health.py`` gives: a patched exception proves
the ``except`` branch runs, not that an actual driver error is what lands in it.
Connection failures are precisely where the DSN, the credentials, and the driver
internals live, so the leak assertion is only worth anything if the failure that
produced the payload was genuine (T-02-09).
```

**Swap-and-restore, never dispose** (`backend/tests/test_mcp_tools.py:75-90`):
```python
    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    try:
        ...
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()
```

Applied to HEVY-08: prefer a **genuine** `DataError` (e.g. a value that overflows a `Numeric`
column) over a patched raise, so the SAVEPOINT quarantine of RESEARCH Pattern 6 is proven against
real PostgreSQL abort semantics rather than a Python exception.

---

### `backend/tests/test_normalization.py` (test, unit + integration)

**Analog:** `backend/tests/test_db_models.py` for the fast/unit half.

**Fast-suite framing** (`backend/tests/test_db_models.py:1-6`):
```python
"""Unit tests for the declarative layer (no database required).

These assert the *shape* of ``Base.metadata`` rather than any live schema, so
they run in the fast (non-integration) suite. The corresponding live-schema
assertions live in ``test_migrations.py``.
"""
```

NORM-01 ("all 20 Hevy enum values translate or are explicitly unmapped") and NORM-03 ("role stored,
weight applied at query time") are pure-function assertions and belong in the fast suite.
NORM-02 (override replaces base) needs the container and gets `@pytest.mark.integration`.

---

### `backend/tests/test_db_models.py` (modified — Pitfall 10)

**Exact line to change** (`backend/tests/test_db_models.py:18-20`):
```python
def test_metadata_contains_only_users_table() -> None:
    """D-07: `external_connections` is deferred to Phase 3."""
    assert set(Base.metadata.tables) == {"users"}
```

Update the assertion to the full expected table set and rewrite the name and docstring — do not
delete the test. Its value is that an *accidental* table (a stray model, a typo'd `__tablename__`)
fails the fast suite. Keep the equality form; a subset check would forfeit that.

---

### `backend/tests/conftest.py` (modified — add a `hevy_client` fixture)

**Analog:** itself. Two existing fixtures are the shape to copy.

**Async fixture with explicit lifetime** (`backend/tests/conftest.py:175-195`):
```python
@pytest_asyncio.fixture
async def engine(postgres_url: str) -> AsyncEngine:
    """A per-test engine.

    One engine per fixture scope, never a module-level global: a global binds
    its pool to whichever event loop imported it, and pytest-asyncio gives each
    test a fresh loop.
    """
    engine = create_async_engine(postgres_url)
    try:
        yield engine  # type: ignore[misc]
    finally:
        await engine.dispose()
```

A `hevy_client` fixture follows this exactly: `async with`/`try-finally` around
`httpx2.AsyncClient`, `@pytest_asyncio.fixture`, and the `# type: ignore[misc]` on the `yield`
(mypy's `disallow_untyped_defs` + the generator return annotation force it).

**Where to put the Pitfall 3 comment.** `conftest.py` already carries long block comments explaining
non-obvious test-only concessions — `backend/tests/conftest.py:60-77` (module-scope env seeding) and
`backend/tests/conftest.py:216-229` (`mcp.session_manager._has_started = False`). The
`httpx.Response`-for-responses / `httpx2`-for-exceptions rule belongs in exactly that register:
state what breaks, what the error message looks like, and why the workaround is safe.

---

## Shared Patterns

### 1. Module docstring convention — applies to every new file

**Source:** every module in `backend/app/`. Clearest examples: `backend/app/db/base.py:1-8`,
`backend/app/core/time.py:1-15`, `backend/app/mcp/auth.py:1-21`.

```python
"""Declarative base and the mixin that makes FOUND-04 structural.

Two rules are enforced here rather than by review:

* every table's constraints get a deterministic, model-derived name, so
  ``alembic revision --autogenerate`` produces reversible downgrades;
* every timestamp column is ``TIMESTAMPTZ``.
"""
```

The invariant: **name the requirement ID, then say what breaks if the rule is violated.** Not one
module in this repo opens with "This module contains the X class." Comments explain *why*, and
they name the failure mode concretely (`421 Invalid Host header`, `current transaction is aborted`,
`emits an EMPTY migration and reports no error at all`). RESEARCH.md's Pitfalls 1–12 supply exactly
this material for Phase 3 — quote them into the code.

### 2. Structured logging

**Source:** `backend/app/mcp/tools/ping.py:14-21`, `backend/app/api/routes/health.py:9-15`
**Apply to:** `client.py`, `sync.py`, `cli.py`

```python
import structlog

log = structlog.get_logger()
```

Module-level `log = structlog.get_logger()`, always that exact name. Event names are
`snake_case` strings as the first positional arg with structured kwargs after —
`log.info("service_starting", environment=settings.environment)` (`backend/app/main.py:52`),
`log.exception("health_db_check_failed")` (`backend/app/api/routes/health.py:37`). RESEARCH uses
dotted names (`log.warning("hevy.workout.skipped", ...)`); the existing repo convention is
underscores (`mcp_lifespan_starting`, `mcp_ping_db_check_failed`, `unhandled_error`). **Pick
underscores for consistency** unless the planner has a reason to diverge.

### 3. Secret redaction — the one mandatory edit (Pitfall 9)

**Source:** `backend/app/logging.py:41-65`
**Apply to:** `backend/app/logging.py` + `backend/tests/test_secret_redaction.py`

```python
DENY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "hevy_api_key",
        "authorization",
        ...
        "x-api-key",
    }
)
```

`"api-key"` — the literal header name Hevy requires — is **absent**. Add it. The three-layer
contract is documented at `backend/app/logging.py:1-28`; Layer 3 currently catches it via
`_SECRET_FIELDS`, so this is defence-in-depth, but the deny-list exists precisely so no single layer
is load-bearing.

**Test to extend** (`backend/tests/test_secret_redaction.py:97-105`):
```python
def test_denied_key_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer 2: the key-name deny-list."""
    buf = _configure(monkeypatch)
    structlog.get_logger().info("probe", api_key=SEEDED)

    out = buf.getvalue()
    assert SEEDED not in out
    assert "***REDACTED***" in out
```

Note the module-level seeding it depends on (`backend/tests/test_secret_redaction.py:32-35`) already
sets `HEVY_API_KEY`:
```python
os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = DB_URL
os.environ["HEVY_API_KEY"] = SEEDED
get_settings.cache_clear()
```
And the module docstring's warning (`backend/tests/test_secret_redaction.py:1-8`) — assert against
the **rendered stream**, never `structlog.testing`, which clears the processor chain and would make
the suite pass while proving nothing.

### 4. Settings access + new secrets

**Source:** `backend/app/config.py:24, 55-57`

```python
_SECRET_FIELDS = ("database_url", "hevy_api_key", "mcp_auth_secret")
...
    database_url: SecretStr
    hevy_api_key: SecretStr | None = None
    mcp_auth_secret: SecretStr | None = None
```

`hevy_api_key` already exists and is already registered — **no `config.py` change is needed for the
Hevy key.** If any *other* secret appears this phase it needs both the `SecretStr` annotation and
the `_SECRET_FIELDS` entry, or Layer 3 will not scrub it (`backend/app/config.py:129-148`).

Settings are read via `get_settings()` (`backend/app/config.py:151-161`, `lru_cache`d) at the
process entrypoint and **passed down as a parameter**, never re-read inside a service — see
`make_engine(settings)` (`backend/app/db/session.py:19`), `configure_logging(settings)`
(`backend/app/logging.py:126`), `build_token_verifier(settings)` (`backend/app/mcp/auth.py:117`).
`HevyClient` should take `api_key: SecretStr`, not `settings`.

### 5. Database session usage

**Source:** `backend/app/mcp/tools/ping.py:31-44`
**Apply to:** `sync.py`, `cli.py`

```python
async def fitness_ping(ctx: Context[AppContext]) -> PingResult:
    """Round-trip the database through the lifespan-wired session factory."""
    database = "connected"
    try:
        sessionmaker = ctx.request_context.lifespan_context.sessionmaker
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not error
        # Mirrors health.py: the detail goes to the log (which runs through the
        # redaction pipeline); the caller gets only the coarse state. Connection
        # errors carry the DSN, host, and driver internals (T-02-09, FOUND-05).
        log.exception("mcp_ping_db_check_failed")
        database = "error"
    return PingResult(status="ok", database=database)
```

Carry across: `async with sessionmaker() as session`, a **borrowed** sessionmaker passed in
(never `make_engine()` inside a service — see `backend/app/mcp/context.py:1-13` for why a second
engine is a bug), and the rule that a driver exception is logged and never returned to a caller.
RESEARCH Pattern 5's per-page `async with sessionmaker() as session: ... await session.commit()`
is the same construct, one commit deeper.

### 6. Test suite mechanics

**Source:** `pyproject.toml:47-53`, `backend/tests/conftest.py:116-136`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
pythonpath = ["backend"]
markers = [
    "integration: test requires a live Postgres container (deselect with -m 'not integration')",
]
```

- `async def test_...` needs no decorator (`asyncio_mode = "auto"`).
- Container-touching tests need `@pytest.mark.integration`. Baseline fast suite:
  **72 passed, 28 deselected in 0.75s** — new fast tests must not slow that materially.
- The container is `postgres:18-alpine` with `driver="asyncpg"`, migrated by a real
  `alembic upgrade head` **subprocess** (`backend/tests/conftest.py:123-134`), not by
  `metadata.create_all`.
- `backend/tests/*` waives `S101`, `S105`, `S106` (`pyproject.toml:68`) — asserts and hardcoded
  test credentials are fine in tests and nowhere else.

### 7. Lint / type gates every new file must pass

**Source:** `pyproject.toml:55-82`

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "S", "DTZ"]

[tool.ruff.lint.isort]
known-first-party = ["app"]
```

```toml
[tool.mypy]
python_version = "3.13"
disallow_untyped_defs = true
mypy_path = "backend"
```

Consequences for Phase 3 specifically:
- `DTZ` bans naive datetimes — relevant to every Hevy timestamp parse.
- `S` (bandit) is live on `backend/app/`; `subprocess`/`assert` need `# noqa: S...` with a reason,
  as at `backend/tests/conftest.py:127` (`# noqa: S603`).
- `B` flags bare `except` and mutable defaults; `BLE001` suppressions must carry an inline reason
  (`backend/app/mcp/auth.py:103`).
- `disallow_untyped_defs` — every function, including fixtures and `_helpers`, needs full
  annotations. `-> None` on tests.
- New third-party packages without stubs go in `[[tool.mypy.overrides]]`
  (`pyproject.toml:79-81`) — check whether `tenacity` and `pytest_httpx2` need entries.

### 8. Dependency addition

**Source:** `pyproject.toml:6-45`

```toml
dependencies = [
    "fastapi==0.141.1",
    ...
    "mcp==2.0.0",
    "tzdata",
]

[dependency-groups]
dev = [
    "pytest==9.1.1",
    ...
    "httpx2==2.12.0",
    "pyyaml==6.0.3",
]

[tool.uv]
default-groups = []
```

Every version is **exactly pinned** (`==`), one per line, runtime deps in `dependencies` and test-only
deps in the `dev` group. `tenacity==9.1.4` → `dependencies`. `pytest-httpx2==1.0.0` → `dev`.

⚠️ **`httpx2==2.12.0` is currently in the `dev` group, not `dependencies`.** `HevyClient` is runtime
code that imports it, so this phase must **move `httpx2` into `dependencies`** — otherwise the
production image (built with a bare `uv sync` and `default-groups = []`, per the comment at
`pyproject.toml:35-41`) ships without the HTTP client and the CLI sync fails at import in Cloud Run
only. This is invisible locally and is the single highest-value packaging catch in the phase.

---

## No Analog Found

The planner should use RESEARCH.md's verified patterns for these — there is nothing in the codebase
to copy.

| File | Role | Data Flow | Reason | Use instead |
|------|------|-----------|--------|-------------|
| `backend/app/integrations/hevy/errors.py` | utility (exception hierarchy) | transform | No custom exception class exists anywhere in `backend/app/`. Every error path today either raises `RuntimeError`/`ValueError` inline or returns `None`. | RESEARCH "Code Examples → HevyClient" (status→exception map) and Pitfall 7 (401/403 must bypass the retry predicate). Structural convention only: `backend/app/core/time.py` for module shape. |
| `backend/app/integrations/hevy/sync.py` | service (orchestration) | batch + event-driven | No sync service, no pagination loop, no transaction-boundary code and no `pg_insert`/`on_conflict_do_update` call exists in the repo. This is the phase's genuinely new tier. | RESEARCH Patterns 1–6 (all verified against a live PostgreSQL 18 container) + Pitfalls 1, 2, 4, 11. Borrow only the session idiom from `backend/app/mcp/tools/ping.py:35-37`. |
| `backend/app/cli.py` | entrypoint | batch | No CLI, no `__main__.py`, no console-script entry. `Procfile` and `scripts/deploy-cloud-run.sh` are the only other entrypoints and neither is Python. | `backend/app/main.py:24-26` (bootstrap order) and `:49-59` (engine lifetime) for the bootstrap half; the argument-parsing half is greenfield. CONTEXT.md leaves the mechanism to Claude's discretion. |
| `backend/tests/fixtures/hevy/*.json` | test data | — | `backend/tests/` has no `fixtures/` directory; every current test builds data inline or reads a committed config file. | RESEARCH "Hevy API Ground Truth" — the verbatim `Workout` / `ExerciseTemplate` / `BodyMeasurement` / event schemas. **Do not hand-write these from the blueprint**: it is wrong about `rir`, `weight_unit`, and child object IDs. |

---

## Cross-Cutting Risks the Planner Should Route Into Plan Actions

1. **`httpx2` is in the wrong dependency group** (`pyproject.toml:30`). Runtime import in a
   dev-only package = production-only ImportError. Fix in the same task that adds `tenacity`.
2. **Pitfall 8 / `models/__init__.py`.** Every new model file needs a matching import line, or
   `alembic revision --autogenerate` emits an empty migration with no error.
   `backend/tests/test_migrations.py:80-86` (`alembic check`) catches it, but only in the
   Docker-backed suite.
3. **Pitfall 10 / `test_db_models.py:20`.** A currently-green test fails on the first new model.
   Plan the edit; do not let it surface as a surprise failure mid-wave.
4. **Pitfall 9 / `logging.py:41-65`.** One-line change plus one assertion. Cheap, and it is a
   security requirement (FOUND-05, blueprint §44).
5. **Migrations may not import application modules** (`0002_seed_default_user.py:37-40`). If D-02
   ships as Alembic-seeded rows, the curated mapping data must be duplicated verbatim into the
   revision file. Weigh this against the Python-module option before committing to a shape.
6. **Shared session-scoped container.** Sync tests commit by design; every one of them needs
   `finally`-block cleanup or it poisons later tests
   (`backend/tests/test_time.py:19-24` documents the rule).

---

## Metadata

**Analog search scope:** `backend/app/` (17 modules), `backend/migrations/` (env + 2 revisions),
`backend/tests/` (11 modules + conftest), `pyproject.toml`, `Procfile`, `.env.example`,
`deploy/`, `scripts/`

**Files scanned:** 34 Python files + 5 config files (entire backend tree; nothing excluded)

**Project skills:** none found (`.claude/skills/`, `.agents/skills/` absent) — conventions extracted
from `CLAUDE.md` and from the code itself.

**Pattern extraction date:** 2026-08-29

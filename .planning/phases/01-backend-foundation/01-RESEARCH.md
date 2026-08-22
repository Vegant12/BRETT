# Phase 1: Backend Foundation - Research

**Researched:** 2026-08-23
**Domain:** Async Python web service foundation — FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL, timezone-correct time handling, secret-safe structured logging
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Default User Bootstrap**
- **D-01:** The single v1 user row is created by an Alembic migration (data migration seeding one row), not by app-startup get-or-create logic and not by a CLI command. Every later phase (Hevy sync, MCP tools) can assume the user already exists once migrations have run.
- **D-02:** The seed migration hardcodes `timezone='Asia/Jakarta'` directly — it does not read an env var at migration time. Changing it later is a one-off `UPDATE` against the single row (acceptable for a single-user app). Migrations should not be env-coupled.

**Health Endpoint**
- **D-03:** `GET /health` is minimal: reports `{status, database}` (connected/error) — service status plus the live DB connectivity check required by FOUND-01. No Alembic revision, environment name, or uptime in the response body. Claude has discretion to add trivial extra fields later if genuinely useful, but nothing was asked for.
- **D-04:** `GET /health` is unauthenticated/open — no MCP bearer token required (that auth mechanism doesn't exist until Phase 2 anyway). This matches standard practice: Render's own health checks and uptime monitors need to reach it without a token, and the minimal response body has nothing sensitive to protect.

**Secret-Safety in Errors**
- **D-05:** A global FastAPI exception handler ALWAYS returns a generic, sanitized error body (e.g. `{"error": "internal server error", "correlation_id": "..."}`) — same behavior in dev and prod. Full tracebacks go only to the structured log (which itself runs through the secret-redaction processor), never to the HTTP response. This guarantees FOUND-05's "never appears in any log line or response" holds regardless of `ENVIRONMENT`, and avoids a leak risk if that var is ever misconfigured in production. Rejected: FastAPI's default debug-mode split (tracebacks in dev, generic in prod) — it only proves the secret-safety test in one of two code paths.

**Local Dev Logging Format**
- **D-06:** structlog uses `ConsoleRenderer` (human-readable, colored key=value) when `ENVIRONMENT=development`, and a JSON renderer in production. The secret-redaction processor (deny-list for API keys/tokens/credentials) runs identically in both modes as a separate pipeline step, so this is purely a rendering choice, not a safety one.

### Claude's Discretion
- Exact shape/wording of the sanitized error body beyond `{error, correlation_id}` (additional fields, error codes, etc.)
- structlog processor pipeline details and the specific deny-list of redacted key names
- Whether `/health` DB check is a raw `SELECT 1` or something equivalent — as long as it's a live connectivity check
- Naming/structure of Alembic migration files, correlation-ID generation mechanism (e.g. `asgi-correlation-id` per CLAUDE.md)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Auth, deployment, and richer health diagnostics were considered and explicitly deferred to Phase 2 / Claude's discretion, not dropped — see decisions above.)

### Phase Boundary — Explicitly NOT this phase
MCP server, MCP auth, Render deployment (all Phase 2). Hevy integration (Phase 3). Analytics calculations beyond the UTC/timezone bucketing helpers (Phase 4+).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **FOUND-01** | Backend exposes a health endpoint reporting service and database status | Pattern 4 (lifespan-managed async engine + `SELECT 1` health probe). Verified `create_async_engine` + `AsyncSession` round-trip against real Postgres 18. D-03/D-04 constrain the response shape and auth. |
| **FOUND-02** | Database schema is managed via versioned Alembic migrations | Pattern 2 (`alembic init -t async`, env.py reading `DATABASE_URL` from env). **Empirically verified** full `upgrade head` → `downgrade base` → `upgrade head` round-trip against Postgres 18 with both schema and seed migrations. Pattern 3 covers the D-01 seed data migration via `op.bulk_insert`. |
| **FOUND-03** | User's timezone is configurable (defaulting to Asia/Jakarta) and used for all daily/weekly calculations | Pattern 5 (`users.timezone` column read at query time, `zoneinfo.ZoneInfo`). **Verified**: Python `astimezone(ZoneInfo(tz)).date()` and SQL `date_trunc('day', ts AT TIME ZONE tz)` agree exactly, and SQL result is independent of the session `TimeZone` setting. |
| **FOUND-04** | All timestamps stored in UTC, converted only at calculation/display boundaries | Pattern 1 (`DateTime(timezone=True)` → `TIMESTAMPTZ`, verified). Pitfall 1 documents the exact failing case that the FOUND-04 test must assert against. |
| **FOUND-05** | Secrets never committed, loaded from env, never appear in logs | **Three-layer defense** (Pattern 6) — verified empirically that a *single* key-name deny-list is INSUFFICIENT and leaks secrets via (a) secret-in-a-value, (b) rendered exception tracebacks, (c) third-party stdlib loggers, (d) Pydantic validation errors. See Pitfall 2 — this is the highest-risk finding in this document. |
</phase_requirements>

## Summary

This is a greenfield infrastructure phase with a fully pre-locked stack (CLAUDE.md), so the research question is not "what libraries?" but "what are the concrete, verified wiring patterns and where do they silently fail?" I verified every version in CLAUDE.md against the PyPI JSON API (all 16 checked are still current as of 2026-08-23), then installed the real stack into a Python 3.13.13 venv and exercised the actual code paths — including a live Postgres 18 container — rather than relying on training knowledge.

**Four findings materially change how this phase should be planned.** First, and most important: **the secret-redaction design implied by D-06 ("a deny-list for API keys/tokens/credentials") is not sufficient to satisfy FOUND-05 as written.** I built the deny-list processor and proved it leaks the secret through four separate channels — a secret embedded in a non-denied field's *value*, the rendered exception traceback, log records emitted by third-party stdlib loggers (uvicorn, SQLAlchemy, Alembic), and Pydantic `ValidationError` messages that echo the raw input. FOUND-05's acceptance test ("a seeded secret passed through config, logs, and error output never appears in any log line") will fail against a naive deny-list. The fix is a three-layer defense (`SecretStr` in config + key-name censor + a **value-scrubbing processor placed after `format_exc_info`**, all wired into `ProcessorFormatter.foreign_pre_chain` so third-party loggers are covered) — verified working end to end.

Second, `DateTime(timezone=True)` correctly maps to `TIMESTAMPTZ` and asyncpg round-trips tz-aware UTC datetimes, and Postgres `date_trunc('day', ts AT TIME ZONE 'Asia/Jakarta')` agrees exactly with Python's `zoneinfo` — including at the 17:00-UTC Jakarta midnight boundary, and independent of the session `TimeZone` GUC. That makes FOUND-03/04 straightforwardly testable in both tiers. Third, `sslmode` in a `DATABASE_URL` is passed through raw to `asyncpg.connect()`, which has **no `sslmode` parameter and no `**kwargs`** — a guaranteed `TypeError` the moment a managed-Postgres URL is used. Phase 1 must normalize the URL at config load, not discover this in Phase 2. Fourth, `testcontainers.postgres` is deprecated in 4.15.0 in favor of `testcontainers.community.postgres`, and its default driver is `psycopg2` — `driver="asyncpg"` must be passed explicitly.

The Alembic side is low-risk and fully proven: `alembic init -t async` produces a working async `env.py` unchanged, and the complete FOUND-02 acceptance criterion (empty → head → base → head, with the D-01 seed row present and no manual SQL) executed cleanly against Postgres 18.

**Primary recommendation:** Build the config module first (`SecretStr` + URL normalization + fail-fast), then the logging module with all three redaction layers and its FOUND-05 test, and only then the DB/Alembic/health layers — because the redaction design is the one thing that is expensive to retrofit and the one requirement a naive implementation will silently fail.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config loading & validation | Process bootstrap (`app/config.py`) | — | Must fail fast at import/startup, before any request or migration runs. Not a request-scoped concern. |
| Secret redaction | Logging pipeline (`app/logging.py`) | Config (`SecretStr`) + API (error handler) | Defense in depth: redaction cannot live in one tier because leaks originate in three (app logs, third-party logs, HTTP responses). |
| Correlation ID generation | ASGI middleware | Logging processor (reads ContextVar) | Must wrap the entire request including error handling; a route dependency is too late. |
| Schema definition (DDL) | Alembic migrations (`backend/migrations/`) | SQLAlchemy models (autogenerate source) | FOUND-02 requires migrations to be authoritative. `metadata.create_all()` must never run in app or prod. |
| Default-user seeding | Alembic data migration | — | D-01 locks this. Explicitly NOT app startup, NOT CLI. |
| Timestamp storage (UTC) | Database (`TIMESTAMPTZ`) | ORM (`DateTime(timezone=True)`) | Postgres normalizes to UTC on write; the type system enforces FOUND-04 rather than convention. |
| Local-day/week bucketing | Python helper module (`app/core/time.py`) | SQL (`AT TIME ZONE`) for aggregate queries | Phase 1 delivers the Python helpers (testable with time-machine). Phase 4+ analytics will push the same logic into SQL — both tiers must be verified to agree. |
| User timezone source | Database (`users.timezone`) | — | FOUND-03 requires "read from user configuration rather than hard-coded". Env var is NOT the source of truth; the DB column is. |
| Health/DB connectivity check | API route (`/health`) | DB engine | D-03/D-04: open, minimal, live check. |
| Unhandled-error sanitization | FastAPI exception handler | ASGI `ServerErrorMiddleware` (fallback) | D-05: one handler, same behavior in all environments. |

## Standard Stack

All versions below were verified against the PyPI JSON API on 2026-08-23 and installed together into a Python 3.13.13 venv with zero resolution conflicts. **The stack is locked by CLAUDE.md — this table confirms currency, it does not re-litigate choices.**

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.13 | Runtime | `uv venv --python 3.13` resolved and installed 3.13.13 on this machine `[VERIFIED: uv]`. Note the *system* python3 is 3.14.0 — pin explicitly via `.python-version`. |
| fastapi | 0.141.1 (2026-07-29) | HTTP API | `[VERIFIED: pypi.org/pypi/fastapi/json]` |
| starlette | 1.6.0 (transitive) | ASGI foundation | Resolved automatically by `fastapi==0.141.1`, no conflict `[VERIFIED: uv pip install]` |
| sqlalchemy[asyncio] | 2.0.52 (2026-08-11) | ORM + query builder | `[VERIFIED: pypi]`. Pulls `greenlet==3.5.5` `[VERIFIED: install output]` |
| asyncpg | 0.31.0 (2025-11-24) | Async Postgres driver | `[VERIFIED: pypi]`. Round-tripped tz-aware datetimes against Postgres 18 `[VERIFIED: live container]` |
| alembic | 1.19.1 (2026-08-08) | Migrations | `[VERIFIED: pypi]`. Async template + up/down round-trip proven `[VERIFIED: live container]` |
| pydantic | 2.13.4 (2026-05-06) | Validation | `[VERIFIED: pypi]` |
| pydantic-settings | 2.15.0 (2026-08-07) | Typed env config | `[VERIFIED: pypi]`. Fail-fast + `SecretStr` masking verified `[VERIFIED: live repl]` |
| structlog | 26.1.0 (2026-06-06) | Structured logging | `[VERIFIED: pypi]`. Processor pipeline + `ProcessorFormatter` verified `[VERIFIED: live repl]` |
| asgi-correlation-id | 5.0.1 (2026-06-09) | Correlation IDs | `[VERIFIED: pypi]`. Pure-ASGI middleware; ContextVar readable inside exception handlers `[VERIFIED: live TestClient run]` |
| uvicorn | 0.52.4 (2026-08-19) | ASGI server | `[VERIFIED: pypi]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tzdata | latest | Bundled IANA tz database | **Recommended but not strictly required.** `python:3.13-slim` already ships system tzdata and resolved `Asia/Jakarta` fine `[VERIFIED: docker run python:3.13-slim]`. Adding the pip package makes the tz database an explicitly versioned, reproducible dependency rather than an implicit property of the base image. Cheap insurance; ~450 KB. |
| psycopg2-binary | 2.9.12 | Sync driver for test helpers only | Optional. Only if you want a sync connection in test fixtures/assertions. asyncpg alone is sufficient. |

### Development

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| uv | 0.11.7 installed / 0.12.5 in CLAUDE.md | Dependency mgmt + lockfile | **Discrepancy — see Open Question 1.** Installed version is 0.11.7 `[VERIFIED: uv --version]`; CLAUDE.md specifies 0.12.5. |
| ruff | 0.16.4 (2026-08-20) | Lint + format | `[VERIFIED: pypi]`. Enable `E,F,I,UP,B,ASYNC,S` per CLAUDE.md. |
| mypy | 2.3.1 (2026-08-15) | Type checking | `[VERIFIED: pypi]`. No plugins needed for SQLAlchemy 2.0 / Pydantic v2. |
| pytest | 9.1.1 (2026-06-19) | Test runner | `[VERIFIED: pypi + install]` |
| pytest-asyncio | 1.4.0 (2026-05-26) | Async tests | `[VERIFIED: pypi + install]`. Set `asyncio_mode = "auto"`. |
| pytest-cov | 7.1.0 (2026-03-21) | Coverage | `[VERIFIED: pypi]` |
| testcontainers[postgres] | 4.15.0 (2026-07-24) | Real Postgres in tests | `[VERIFIED: pypi + live run]`. **See Pitfall 5 — import path changed.** |
| time-machine | 3.4.0 (2026-08-10) | Freeze clock | `[VERIFIED: pypi + install]` |
| pre-commit + gitleaks/detect-secrets | latest | Prevent committing `.env` | Required by FOUND-05's "never committed" clause. |

**Installation:**
```bash
uv init --python 3.13
uv add fastapi uvicorn "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings structlog asgi-correlation-id tzdata
uv add --dev pytest pytest-asyncio pytest-cov "testcontainers[postgres]" time-machine ruff mypy pre-commit
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `alembic init -t async` | `alembic init -t pyproject_async` | Puts `script_location` etc. in `pyproject.toml` under `[tool.alembic]`, keeping `alembic.ini` for the URL + logging config only. **The generated `env.py` is byte-identical between the two templates** `[VERIFIED: diff, exit 0]`, so this is purely a config-location preference. Recommend plain `async` — better-trodden and matches every existing tutorial. |
| Value-scrubbing processor | Rely on `SecretStr` alone | Insufficient — `SecretStr` protects config repr but not a secret that reaches a log call or traceback as a plain `str`. `[VERIFIED: probe]` |
| `zoneinfo` | `pendulum` / `pytz` | No. `Asia/Jakarta` is UTC+7 with no DST `[VERIFIED: utcoffset in Jan and Jul both 7:00:00]`; stdlib `zoneinfo` is exact and dependency-free. CLAUDE.md already rules this. |

## Architecture Patterns

### System Architecture Diagram

```
   ENV / .env file                      Render / operator
   (DATABASE_URL, ENVIRONMENT,          runs migrations
    HEVY_API_KEY, MCP_AUTH_SECRET)      out-of-band
          │                                    │
          ▼                                    ▼
  ┌───────────────────┐              ┌────────────────────┐
  │ app/config.py     │              │ alembic upgrade    │
  │ Settings          │              │ head               │
  │ (pydantic-        │              │  ├─ 0001 schema    │
  │  settings)        │              │  └─ 0002 seed user │
  │                   │              │     (D-01/D-02)    │
  │ • fail-fast on    │              └─────────┬──────────┘
  │   missing vars    │                        │ (async env.py,
  │ • SecretStr wrap  │                        │  NullPool, one-shot)
  │ • normalize URL:  │                        ▼
  │   +asyncpg, strip │              ┌────────────────────────┐
  │   sslmode         │              │   PostgreSQL           │
  └────────┬──────────┘              │   • users              │
           │                         │     (id, timezone,     │
           │ secret VALUES           │      created_at TZ,    │
           │ (for scrubber)          │      updated_at TZ)    │
           ▼                         │   • external_conns     │
  ┌───────────────────────────┐      │   ALL ts = TIMESTAMPTZ │
  │ app/logging.py            │      └───────────▲────────────┘
  │ structlog pipeline        │                  │
  │  1 merge_contextvars      │                  │ asyncpg pool
  │  2 add correlation_id     │      ┌───────────┴────────────┐
  │  3 censor DENY key names  │      │ app/db/session.py      │
  │  4 format_exc_info        │      │ async engine (lifespan)│
  │  5 SCRUB secret VALUES ◀──┘      │ async_sessionmaker     │
  │  6 Console | JSON (D-06)  │      └───────────▲────────────┘
  └────────▲───────┬──────────┘                  │
           │       │ stdout                      │
           │       ▼                             │
           │   log stream                        │
           │                                     │
  ┌────────┴─────────────────────────────────────┴──────────┐
  │                    FastAPI app (app/main.py)             │
  │                                                          │
  │  HTTP request                                            │
  │      │                                                   │
  │      ▼                                                   │
  │  ┌────────────────────────────┐                          │
  │  │ CorrelationIdMiddleware    │ reads/creates             │
  │  │ (pure ASGI)                │ X-Request-ID → ContextVar │
  │  └──────────┬─────────────────┘                          │
  │             │                                            │
  │             ├──── success ──▶ GET /health ──▶ SELECT 1 ──┼──▶ DB
  │             │                    │                       │
  │             │                    ▼                       │
  │             │            {status, database}  (D-03/D-04) │
  │             │                                            │
  │             └──── raises ───▶ ┌──────────────────────┐   │
  │                               │ @exception_handler   │   │
  │                               │ (Exception)   D-05   │   │
  │                               └──┬────────────────┬──┘   │
  │                                  │                │      │
  │            full traceback ───────┘                └──────┼──▶ HTTP 500
  │            → structlog (scrubbed)                        │  {error,
  │                                                          │   correlation_id}
  │  ┌────────────────────────────────────────────────────┐  │  (never a traceback)
  │  │ app/core/time.py — zoneinfo bucketing helpers      │  │
  │  │ utc_now() / to_local(ts,tz) / local_day / week_start│ │
  │  │ tz argument comes from users.timezone (FOUND-03)   │  │
  │  └────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────┘
```

Note the two arrows into the scrubber: it consumes secret *values* from `Settings`, which is why config must be constructed before logging is configured.

### Recommended Project Structure

Flat at the BRETT repo root per PROJECT.md (overriding the blueprint's `fitness-platform/` nesting), following blueprint §4 otherwise. Only the directories Phase 1 actually creates are listed; blueprint §4's `integrations/`, `analytics/`, `mcp/` are later phases.

```
BRETT/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, lifespan, middleware, exception handler
│   │   ├── config.py            # Settings (pydantic-settings) — blueprint §4
│   │   ├── logging.py           # structlog config + redaction processors
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   └── health.py    # GET /health (D-03, D-04)
│   │   │   └── dependencies.py  # get_db session dependency
│   │   ├── core/
│   │   │   └── time.py          # zoneinfo bucketing helpers (FOUND-03/04)
│   │   └── db/
│   │       ├── base.py          # DeclarativeBase + naming convention
│   │       ├── session.py       # async engine + async_sessionmaker
│   │       └── models/
│   │           ├── __init__.py  # imports all models for autogenerate
│   │           ├── user.py
│   │           └── external_connection.py
│   ├── migrations/
│   │   ├── env.py               # from `alembic init -t async`, DATABASE_URL from env
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_seed_default_user.py   # D-01 / D-02
│   ├── tests/
│   │   ├── conftest.py          # testcontainers Postgres, migrated-DB fixture
│   │   ├── test_health.py
│   │   ├── test_migrations.py
│   │   ├── test_time.py
│   │   └── test_secret_redaction.py
│   └── alembic.ini
├── docs/
├── .env.example                 # names only, never values
├── .gitignore                   # MUST include .env
├── .python-version              # "3.13"
├── pyproject.toml
├── uv.lock
└── README.md
```

### Pattern 1: SQLAlchemy 2.0 `Mapped[]` models with UTC enforcement (FOUND-04)

**What:** Declarative models where `DateTime(timezone=True)` is the *only* datetime column type used.
**When to use:** Every model, every timestamp column, no exceptions.

Verified: `DateTime(timezone=True)` produces `timestamp with time zone` and asyncpg returns a `tzinfo=UTC`-aware datetime on read `[VERIFIED: live Postgres 18 container]`.

```python
# backend/app/db/base.py
import datetime as dt
import uuid
from sqlalchemy import MetaData, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Named constraints make Alembic autogenerate diffs stable and downgrades reliable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """FOUND-04: every timestamp is TIMESTAMPTZ. Never use DateTime() bare."""
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

```python
# backend/app/db/models/user.py  — blueprint §5.1
import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # UUID PK, not an integer: blueprint §5.1 says "do not hard-code the schema so that
    # multi-user support becomes impossible". A surrogate UUID keeps that door open.
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # FOUND-03: the user's timezone lives HERE, not in an env var.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Jakarta")

    connections: Mapped[list["ExternalConnection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
```

```python
# backend/app/db/models/external_connection.py  — blueprint §5.2
import datetime as dt
import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class ExternalConnection(Base, TimestampMixin):
    __tablename__ = "external_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_external_connections_user_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)   # 'hevy' | 'apple_health'
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")

    # blueprint §39 Data Freshness. Nullable: never synced yet.
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NOTE (blueprint §5.2): the column for provider credentials is deliberately NOT added in
    # Phase 1. v1 reads HEVY_API_KEY from the environment (blueprint §5.2 explicitly permits this
    # for the first personal deployment). Adding an `encrypted_credentials` column now would mean
    # shipping either plaintext secrets in the DB or an unused encryption scheme — both worse than
    # a Phase-3 migration that adds the column when there is a real key-management design.
    user: Mapped["User"] = relationship(back_populates="connections")
```

### Pattern 2: Async Alembic env.py reading `DATABASE_URL` from the environment (FOUND-02, FOUND-05)

**What:** `alembic init -t async` scaffolding, with the URL injected from env rather than committed in `alembic.ini`.
**When to use:** Always — `alembic.ini` is a committed file, so a real URL in it violates FOUND-05.

The generated async `env.py` needs **no structural changes**; only `target_metadata` and the URL override `[VERIFIED: read from installed alembic/templates/async/env.py]`.

```bash
cd backend && uv run alembic init -t async migrations
```

```python
# backend/migrations/env.py  — edits to the generated file only
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from app.db.base import Base
import app.db.models  # noqa: F401  — MUST import so autogenerate sees every table

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# FOUND-05: URL comes from the environment, never from the committed alembic.ini.
# `.replace("%", "%%")` is REQUIRED: set_main_option passes the value to ConfigParser,
# which performs pyformat interpolation — a raw '%' in a URL-encoded password raises
# InterpolationSyntaxError. [VERIFIED: Config.set_section_option docstring]
from app.config import get_settings
config.set_main_option("sqlalchemy.url", get_settings().async_database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,          # catch column type changes in autogenerate
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # migrations are one-shot; never hold a pool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### Pattern 3: Seed data migration for the default user (D-01, D-02)

**What:** `op.bulk_insert` against a lightweight `sa.table()` construct — never the ORM model.
**Why not the ORM model:** a migration must describe the schema *as of that revision*. Importing `app.db.models.User` couples the migration to today's model and breaks the moment the model changes. `[CITED: alembic.sqlalchemy.org/en/latest/cookbook.html]`

**Verified end to end** against Postgres 18: `upgrade head` seeds exactly one row with `timezone='Asia/Jakarta'`; `downgrade base` removes both tables cleanly; a second `upgrade head` re-seeds exactly one row.

```python
# backend/migrations/versions/0002_seed_default_user.py
"""seed the single v1 default user (D-01, D-02)"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# A FIXED UUID, not uuid4(). Later phases, fixtures and manual queries can all reference
# this constant, and re-running migrations on a fresh DB yields an identical row.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# D-02: hardcoded. Deliberately NOT os.environ — migrations must not be env-coupled.
DEFAULT_TIMEZONE = "Asia/Jakarta"


def upgrade() -> None:
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("timezone", sa.String),
    )
    op.bulk_insert(users, [{"id": DEFAULT_USER_ID, "timezone": DEFAULT_TIMEZONE}])


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM users WHERE id = :uid").bindparams(uid=str(DEFAULT_USER_ID))
    )
```

### Pattern 4: Lifespan-managed async engine + health endpoint (FOUND-01)

**What:** One engine created at startup, disposed at shutdown; sessions per request via a dependency.
**Why lifespan:** creating an engine at import time binds it to the wrong event loop and leaks connections across test runs.

```python
# backend/app/db/session.py
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.async_database_url,
        pool_pre_ping=True,     # a spun-down/restarted managed Postgres kills idle conns
        pool_size=5,
        max_overflow=5,
        echo=False,             # NEVER True in prod: echo logs bound parameter VALUES
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
```

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
import structlog

from app.config import get_settings
from app.logging import configure_logging
from app.db.session import make_engine, make_sessionmaker
from app.api.routes import health

settings = get_settings()        # fail-fast BEFORE anything else
configure_logging(settings)      # then logging, so the scrubber has the secret values
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("service_stopped")


app = FastAPI(title="BRETT", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware)
app.include_router(health.router)


# D-05: identical behavior in every environment. No traceback ever reaches the client.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error", "correlation_id": correlation_id.get()},
    )
```

```python
# backend/app/api/routes/health.py  — D-03, D-04 (open, minimal)
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
import structlog

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    database = "connected"
    status_code = 200
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        # Log the detail; return only the coarse state (D-03/D-05).
        log.exception("health_db_check_failed")
        database, status_code = "error", 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if status_code == 200 else "degraded", "database": database},
    )
```

**Verified behavior of the exception handler** `[VERIFIED: live starlette TestClient run]`: with `CorrelationIdMiddleware` registered, `correlation_id.get()` returns the request's ID inside the handler (the middleware is pure-ASGI, not `BaseHTTPMiddleware`, so the ContextVar propagates outward correctly), the response body contains no traceback, and the `X-Request-ID` header is echoed on success responses.

### Pattern 5: Timezone bucketing helpers (FOUND-03, FOUND-04)

**What:** A tiny pure-function module that takes an aware UTC datetime and an IANA tz string.
**When to use:** Every day/week grouping in Phase 4+ analytics goes through these.

Verified boundary behavior `[VERIFIED: live repl, zoneinfo]`:

| UTC instant | Asia/Jakarta local | local day | naive UTC day |
|---|---|---|---|
| 2026-08-23T16:30Z | 2026-08-23 23:30 +07 | 2026-08-23 | 2026-08-23 |
| 2026-08-23T17:00Z | 2026-08-24 00:00 +07 | **2026-08-24** | 2026-08-23 ✗ |
| 2026-08-23T23:30Z | 2026-08-24 06:30 +07 | **2026-08-24** | 2026-08-23 ✗ |
| 2026-08-24T00:30Z | 2026-08-24 07:30 +07 | 2026-08-24 | 2026-08-24 |

The 17:00Z row is the exact Jakarta midnight boundary; the 23:30Z row is the "near midnight UTC" case named in the phase success criteria. `Asia/Jakarta` is a fixed UTC+7 with no DST `[VERIFIED: utcoffset() == 7:00:00 in both January and July 2026]`.

```python
# backend/app/core/time.py
import datetime as dt
from zoneinfo import ZoneInfo


def utc_now() -> dt.datetime:
    """FOUND-04: the ONLY sanctioned source of 'now'. Always aware, always UTC.
    Never use datetime.utcnow() — it returns a naive datetime and is deprecated."""
    return dt.datetime.now(dt.UTC)


def _require_aware(ts: dt.datetime) -> dt.datetime:
    """Fail loudly on naive datetimes. FOUND-04 is enforced by a guard, not a convention."""
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware UTC")
    return ts


def to_local(ts: dt.datetime, tz: str) -> dt.datetime:
    """Convert an aware UTC instant into the user's local wall time."""
    return _require_aware(ts).astimezone(ZoneInfo(tz))


def local_day(ts: dt.datetime, tz: str) -> dt.date:
    """The user's local calendar day that this instant falls on. FOUND-03."""
    return to_local(ts, tz).date()


def local_week_start(ts: dt.datetime, tz: str) -> dt.date:
    """Monday of the user's local ISO week — matches Postgres date_trunc('week', ...)."""
    d = local_day(ts, tz)
    return d - dt.timedelta(days=d.weekday())


def local_day_bounds(day: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime]:
    """Half-open [start, end) UTC range covering one local day.
    Use this to FILTER in SQL — it is index-friendly, unlike wrapping the column
    in AT TIME ZONE, which prevents index use on the timestamp column."""
    zone = ZoneInfo(tz)
    start_local = dt.datetime.combine(day, dt.time.min, tzinfo=zone)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.UTC), end_local.astimezone(dt.UTC)
```

**SQL-side equivalent** (for Phase 4+ aggregates; verify agreement now, in Phase 1):

```sql
-- VERIFIED against Postgres 18: agrees exactly with the Python helper above,
-- and the result is independent of the session TimeZone GUC.
SELECT date_trunc('day',  started_at AT TIME ZONE :tz)::date AS local_day,
       date_trunc('week', started_at AT TIME ZONE :tz)::date AS local_week_start
FROM workouts;
```

`[VERIFIED: live Postgres 18]` — for `2026-08-23T23:30Z` with `tz='Asia/Jakarta'`: `local_day = 2026-08-24`, `local_week_start = 2026-08-24`, `extract(isodow) = 1` (Monday). The same query run with the session set to `UTC` and to `America/New_York` returned identical results.

### Pattern 6: Three-layer secret redaction (FOUND-05) — the critical pattern

**What:** `SecretStr` config + key-name censor + value scrubber, with all layers applied to third-party stdlib logs too.
**Why three layers:** each one alone was empirically shown to leak. See Pitfall 2 for the proof.

**Layer 1 — config (`SecretStr`)**

```python
# backend/app/config.py
from functools import lru_cache
from typing import Literal
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # SecretStr, NOT PostgresDsn — see Pitfall 2(d): a PostgresDsn validation failure
    # echoes the raw input (password included) into the ValidationError message.
    database_url: SecretStr
    hevy_api_key: SecretStr | None = None
    mcp_auth_secret: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: SecretStr) -> SecretStr:
        try:
            url = make_url(v.get_secret_value())
        except Exception as exc:
            # Re-raise WITHOUT the input value.
            raise ValueError("DATABASE_URL is not a valid database URL") from None
        if not url.drivername.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a postgresql:// URL")
        return v

    @property
    def async_database_url(self) -> str:
        """Normalize any managed-Postgres URL into one asyncpg accepts. See Pitfall 3."""
        url = make_url(self.database_url.get_secret_value())
        url = url.set(drivername="postgresql+asyncpg")
        # asyncpg.connect() has NO 'sslmode' parameter and NO **kwargs -> TypeError.
        # It uses 'ssl' instead. Translate, then drop.
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        if sslmode in ("require", "verify-ca", "verify-full") and "ssl" not in query:
            query["ssl"] = "require"
        query.pop("channel_binding", None)   # also libpq-only
        return url.set(query=query).render_as_string(hide_password=False)

    def secret_values(self) -> list[str]:
        """Every literal secret string the log scrubber must never emit."""
        out: list[str] = []
        for f in ("database_url", "hevy_api_key", "mcp_auth_secret"):
            v = getattr(self, f, None)
            if isinstance(v, SecretStr) and v.get_secret_value():
                raw = v.get_secret_value()
                out.append(raw)
                # also scrub just the password component of the DB URL
                try:
                    pw = make_url(raw).password
                    if pw:
                        out.append(pw)
                except Exception:
                    pass
        return sorted(set(out), key=len, reverse=True)   # longest-first


@lru_cache
def get_settings() -> Settings:
    return Settings()   # raises ValidationError at import time if a var is missing
```

Verified `[VERIFIED: live repl]`: a missing `DATABASE_URL` raises `ValidationError: Field required` at construction; `repr(settings)`, `str(field)`, `model_dump()` and `model_dump_json()` all render `SecretStr` as `**********`; only `.get_secret_value()` reveals it.

**Layers 2 and 3 — logging pipeline**

```python
# backend/app/logging.py
import logging
import sys
from typing import Any

import structlog
from asgi_correlation_id import correlation_id

from app.config import Settings

# Layer 2: key-name deny-list. Cheap, catches the common case, NOT sufficient alone.
DENY_KEYS = frozenset({
    "api_key", "apikey", "hevy_api_key", "authorization", "auth", "password", "passwd",
    "secret", "mcp_auth_secret", "jwt_secret", "token", "access_token", "refresh_token",
    "database_url", "db_url", "dsn", "credentials", "encrypted_credentials", "cookie",
    "set-cookie", "x-api-key",
})
REDACTED = "***REDACTED***"


def censor_keys(_logger: Any, _name: str, event_dict: dict) -> dict:
    for k in list(event_dict):
        if k.lower() in DENY_KEYS:
            event_dict[k] = REDACTED
    return event_dict


def add_correlation_id(_logger: Any, _name: str, event_dict: dict) -> dict:
    # structlog's merge_contextvars does NOT see asgi-correlation-id's ContextVar
    # (it is a separate, non-structlog-prefixed ContextVar). Bridge it explicitly.
    if (cid := correlation_id.get()) is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def make_value_scrubber(secrets: list[str]):
    """Layer 3: recursively replace known secret VALUES anywhere in the event dict,
    including inside the rendered traceback string. MUST be placed AFTER
    format_exc_info so the traceback is already a str by the time it runs."""
    def _scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            for s in secrets:
                if s in obj:
                    obj = obj.replace(s, REDACTED)
            return obj
        if isinstance(obj, dict):
            return {k: _scrub(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return type(obj)(_scrub(v) for v in obj)
        return obj

    def scrub_values(_logger: Any, _name: str, event_dict: dict) -> dict:
        return _scrub(event_dict)

    return scrub_values


def configure_logging(settings: Settings) -> None:
    dev = settings.environment == "development"

    shared = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        censor_keys,                              # layer 2
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,     # traceback -> string
        make_value_scrubber(settings.secret_values()),   # layer 3, AFTER the above
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # D-06: rendering choice only; both branches share the identical `shared` chain.
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True) if dev
        else structlog.processors.JSONRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # CRITICAL: foreign_pre_chain applies `shared` (and therefore BOTH redaction
        # layers) to records from uvicorn, sqlalchemy, alembic and any other stdlib logger.
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine", "alembic"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True
```

**Verified** `[VERIFIED: live TestClient run with a seeded secret]`: with all three layers, the secret appeared **zero** times across six log lines that included a structlog event with the secret in a value, a full unhandled-exception traceback containing the secret, a `logging.getLogger("uvicorn.error").error(...)` call, and a `logging.getLogger("sqlalchemy.engine").exception(...)` with a traceback. The HTTP 500 body was exactly `{"error":"internal server error","correlation_id":"..."}`.

### Anti-Patterns to Avoid

- **`Base.metadata.create_all()` anywhere outside a throwaway scratch script.** It bypasses Alembic, so the DB and migration history diverge and FOUND-02's down-migration criterion becomes untestable. Tests must run `alembic upgrade head`, not `create_all`.
- **`datetime.utcnow()` / `datetime.now()` without tz.** Both produce naive datetimes; `utcnow()` is deprecated in 3.12+. Use `app.core.time.utc_now()`. Consider a Ruff `flake8-datetimez` (DTZ) rule to ban it mechanically.
- **`DateTime()` without `timezone=True`.** Produces `TIMESTAMP WITHOUT TIME ZONE` and silently destroys the offset — the direct FOUND-04 violation.
- **`echo=True` on the engine outside local debugging.** SQLAlchemy's echo logs bound parameter values, which will eventually include something sensitive; it also bypasses the intent of the redaction design even though `foreign_pre_chain` would scrub known secrets.
- **Importing ORM models inside a migration file.** Couples a historical revision to the current model. Use `sa.table()`/`sa.column()` (Pattern 3).
- **Reading the timezone from an env var at query time.** FOUND-03 says "read from user configuration"; D-01/D-02 put it in `users.timezone`. An env var is the wrong source of truth and would make the FOUND-03 test pass for the wrong reason.
- **Wrapping the timestamp column in `AT TIME ZONE` inside a `WHERE` clause.** It defeats the index. Filter on a UTC range from `local_day_bounds()`; use `AT TIME ZONE` only in `GROUP BY`/`SELECT`.
- **A single global `AsyncEngine` created at module import.** Binds to the wrong event loop under pytest-asyncio and leaks connections between tests. Create it in `lifespan` / a fixture.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request correlation IDs | Custom `BaseHTTPMiddleware` setting a ContextVar | `asgi-correlation-id` `CorrelationIdMiddleware` | Already handles inbound-header reuse, UUID validation, header echo on the response, and — critically — is a **pure ASGI** middleware, so the ContextVar survives out to the exception handler. A `BaseHTTPMiddleware` implementation runs in a separate anyio task and the ContextVar would not propagate. `[VERIFIED: read middleware source + live run]` |
| Timezone conversion | Manual `timedelta(hours=7)` offset math | `zoneinfo.ZoneInfo` | Hardcoding +7 works for Jakarta today but silently breaks the "must be configurable" half of FOUND-03 the instant any other tz is used. |
| Secret masking in config | Custom `__repr__` on a config class | `pydantic.SecretStr` | Masks `repr`, `str`, `model_dump` and `model_dump_json` in one type. `[VERIFIED]` |
| Test database | SQLite, or a hand-managed local Postgres | `testcontainers[postgres]` | CLAUDE.md forbids SQLite for a reason proven here: `AT TIME ZONE`, `date_trunc`, `isodow` and `TIMESTAMPTZ` semantics are all Postgres-specific and are exactly what FOUND-03/04 depend on. |
| Migration ordering / version table | A `schema_version` table and custom runner | Alembic | FOUND-02 explicitly requires versioned migrations with a working downgrade. |
| Structured log rendering | `json.dumps` inside a logging Formatter | `structlog` processor chain | The processor chain is what makes redaction a pipeline stage applied uniformly to app *and* third-party logs, rather than a discipline every call site must remember. |
| Connection-liveness check | Reconnect/retry loop of your own | `pool_pre_ping=True` | Handles the managed-Postgres idle-connection-reaped case correctly. |
| Constraint naming for downgrades | Manual `op.f(...)` names everywhere | `MetaData(naming_convention=...)` | Without it, autogenerated downgrades reference server-assigned constraint names and break. |

**Key insight:** Nearly every FOUND-05 leak found in this research came from a code path *nobody wrote* — a library's traceback formatter, uvicorn's error logger, Pydantic's validation message. Hand-rolled redaction only ever covers the call sites you remembered. Put redaction in the one place every log record must pass through (the structlog/`ProcessorFormatter` chain) and it covers the code you didn't write.

## Common Pitfalls

### Pitfall 1: Bucketing by UTC day instead of local day

**What goes wrong:** A workout at `2026-08-23T23:30Z` is counted on August 23 instead of August 24 — a full day off for any session between 17:00Z and 24:00Z, i.e. every Jakarta-morning workout.
**Why it happens:** `date_trunc('day', started_at)` and `ts.date()` both look correct and both silently use UTC.
**How to avoid:** Route every day/week grouping through `app.core.time`. In SQL always write `AT TIME ZONE :tz` before `date_trunc`.
**Warning signs:** Weekly volume totals shift when you change the reporting window; a workout appears in the "wrong" week near a Sunday/Monday boundary.
**Confidence:** HIGH `[VERIFIED: live Postgres 18 — naive date_trunc returned 2026-08-23, correct AT TIME ZONE version returned 2026-08-24]`

### Pitfall 2: A key-name deny-list does not satisfy FOUND-05 — four proven leak channels

This is the single highest-risk item in the phase. I implemented exactly the design D-06 describes (a deny-list processor censoring `api_key`, `token`, `password`, ...) and confirmed the seeded secret still reached the log output. `[VERIFIED: live probe, structlog 26.1.0 + FastAPI 0.141.1]`

| # | Channel | Observed leak | Fix |
|---|---------|---------------|-----|
| a | Secret inside a **non-denied key's value** | `log.info("hello", note=f"inline {SECRET}")` → `"note": "inline hevy-sk-SUPERSECRET123"` | Value-scrubbing processor (layer 3) |
| b | **Rendered exception traceback** | `ValueError: leaky secret hevy-sk-SUPERSECRET123` appeared verbatim inside the `"exception"` field | Scrubber placed **after** `format_exc_info` |
| c | **Third-party stdlib loggers** | `logging.getLogger("uvicorn.error").error("... %s", SECRET)` and a `sqlalchemy.engine` `.exception()` both bypassed the structlog chain entirely | `ProcessorFormatter(foreign_pre_chain=shared)` + route root logger through it |
| d | **Pydantic validation errors** | Declaring `database_url: PostgresDsn` and feeding a malformed URL produced `input_value='not-a-url://u:SUPERSECRETPW@h/db'` in the error text | Use `SecretStr` and re-raise validators with `from None`, without echoing input |

**Warning signs:** the FOUND-05 test asserts against `structlog.testing.capture_logs()` output (see Pitfall 6) rather than the rendered stream; the deny-list is the only redaction code in the repo; `ProcessorFormatter` is absent.

**Planner note:** This does not contradict D-06 — D-06 correctly frames the renderer choice as cosmetic and the deny-list as a pipeline step. It adds the finding that the deny-list must be *one* step among three. The exact deny-list contents remain Claude's discretion per CONTEXT.md.

### Pitfall 3: `sslmode` in `DATABASE_URL` crashes asyncpg

**What goes wrong:** `TypeError: connect() got an unexpected keyword argument 'sslmode'` at first connection.
**Why it happens:** SQLAlchemy's asyncpg dialect passes unrecognized URL query parameters straight through to `asyncpg.connect()` as kwargs. `asyncpg.connect()` accepts `ssl`, **not** `sslmode`, and has **no `**kwargs`** to absorb it. Managed Postgres providers routinely append `?sslmode=require`.
**How to avoid:** Normalize the URL in `Settings.async_database_url` (Pattern 6, layer 1) — translate `sslmode` → `ssl`, drop `channel_binding`.
**Warning signs:** Works locally against a plain container, fails on the first managed-database connection. This would otherwise surface as a confusing Phase 2 deploy blocker.
**Confidence:** HIGH — three independent verifications:
- `grep -c "sslmode" sqlalchemy/dialects/postgresql/asyncpg.py` → **0 matches** (no translation exists)
- `PGDialect_asyncpg().create_connect_args(...)` on `...?sslmode=require` → `{'host':..., 'sslmode': 'require'}` (passed through raw)
- `inspect.signature(asyncpg.connect)` → `has ssl: True | has sslmode: False | has **kwargs: False`

### Pitfall 4: `set_main_option` and the `%` character

**What goes wrong:** `configparser.InterpolationSyntaxError` during `alembic upgrade` when the DB password contains a URL-encoded `%`.
**Why it happens:** `Config.set_main_option` writes into a `ConfigParser`, which performs pyformat interpolation.
**How to avoid:** `config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))`.
**Confidence:** HIGH `[VERIFIED: Config.set_section_option docstring — "A raw percent sign not part of an interpolation symbol must therefore be escaped, e.g. %%"]`

### Pitfall 5: `testcontainers.postgres` is deprecated and defaults to psycopg2

**What goes wrong:** A `DeprecationWarning` on import, and `get_connection_url()` returning a `postgresql+psycopg2://` URL that your async engine cannot use (psycopg2 isn't even installed).
**How to avoid:** `from testcontainers.community.postgres import PostgresContainer` and always pass `driver="asyncpg"`.
**Confidence:** HIGH `[VERIFIED: emitted "testcontainers.postgres is deprecated, use testcontainers.community.postgres instead" on 4.15.0; new path imports cleanly; signature shows driver default is 'psycopg2']`

### Pitfall 6: `structlog.testing.capture_logs()` disables the redaction you are trying to test

**What goes wrong:** The FOUND-05 test is written against `capture_logs()` and proves nothing about production behavior.
**Why it happens:** `capture_logs()` **clears the entire configured processor list** for the duration of the context manager and installs only a `LogCapture`. Your redaction processors never run.
**How to avoid:** Test FOUND-05 against the **rendered output stream** — attach a `logging.StreamHandler(io.StringIO())` using the real `ProcessorFormatter`, or use pytest's `capsys`, and assert the secret literal is absent from the raw text. Use `capture_logs()` only for asserting on event names/fields in non-security tests.
**Also note:** `capture_logs` is documented as **not thread-safe**.
**Confidence:** HIGH `[VERIFIED: read structlog.testing.capture_logs source — "configured_processors.clear()"]`

### Pitfall 7: `merge_contextvars` does not pick up the correlation ID

**What goes wrong:** Log lines have no `correlation_id`, so the ID returned to the client in the D-05 error body can't be used to find the traceback — defeating the whole point.
**Why it happens:** `asgi-correlation-id` stores its value in its own `ContextVar`, which is not one of structlog's `STRUCTLOG_KEY_PREFIX`-namespaced vars that `merge_contextvars` merges.
**How to avoid:** Add the explicit `add_correlation_id` processor (Pattern 6). Alternatively call `structlog.contextvars.bind_contextvars(correlation_id=...)` from middleware.
**Confidence:** HIGH `[VERIFIED: first probe omitted the bridge processor and produced log lines with no correlation_id; second probe with the bridge produced matching IDs in both the log line and the HTTP body]`

### Pitfall 8: Autogenerate silently produces an empty migration

**What goes wrong:** `alembic revision --autogenerate` emits a migration with `pass` in both `upgrade()` and `downgrade()`.
**Why it happens:** `env.py` sets `target_metadata = Base.metadata`, but no module ever imported the model classes, so nothing registered on that metadata.
**How to avoid:** `import app.db.models  # noqa: F401` in `env.py`, and have `app/db/models/__init__.py` import every model module.
**Warning signs:** Empty migration; or a later migration that tries to create a table that already exists.
**Confidence:** MEDIUM-HIGH — standard Alembic behavior, not separately re-verified in this session `[ASSUMED, consistent with CITED: alembic autogenerate docs]`

### Pitfall 9: Naive-vs-aware datetime comparison inside tests

**What goes wrong:** `TypeError: can't compare offset-naive and offset-aware datetimes` in a test, usually after `time_machine.travel(...)` with a naive argument.
**How to avoid:** Always pass aware datetimes to `time_machine.travel()`; use the `_require_aware` guard in `app.core.time` so the failure is a clear `ValueError` at the boundary rather than a `TypeError` deep in a comparison.
**Confidence:** MEDIUM `[ASSUMED]`

## Code Examples

### Test fixture: migrated Postgres per session

```python
# backend/tests/conftest.py
import asyncio, os, subprocess, sys
import pytest, pytest_asyncio
from testcontainers.community.postgres import PostgresContainer
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture(scope="session")
def postgres_url() -> str:
    # driver="asyncpg" is required; the default is psycopg2. [VERIFIED]
    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        # FOUND-02: build the schema with migrations, never metadata.create_all().
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd="backend", env={**os.environ, "DATABASE_URL": url}, check=True,
        )
        yield url


@pytest_asyncio.fixture
async def session(postgres_url):
    engine = create_async_engine(postgres_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
```

### FOUND-02 test: full up/down/up round-trip

This exact sequence was executed successfully against Postgres 18 during this research `[VERIFIED]`.

```python
# backend/tests/test_migrations.py
def test_migrations_round_trip(postgres_url, alembic):
    alembic("upgrade", "head")
    assert alembic("current").stdout.strip().endswith("(head)")
    assert count(postgres_url, "select count(*) from users") == 1          # D-01 seed
    assert tz_of_default_user(postgres_url) == "Asia/Jakarta"              # D-02

    alembic("downgrade", "base")
    assert tables(postgres_url) == ["alembic_version"]                     # no manual SQL

    alembic("upgrade", "head")
    assert count(postgres_url, "select count(*) from users") == 1          # not duplicated
```

Observed output during verification:
```
$ alembic upgrade head -> rc=0
$ alembic current -> 0002 (head)
users: [(UUID('00000000-0000-0000-0000-000000000001'), 'Asia/Jakarta')]
tables: ['alembic_version', 'external_connections', 'users']
$ alembic downgrade base -> rc=0
tables after downgrade: ['alembic_version']
$ alembic upgrade head -> rc=0
users after re-upgrade: 1
```

### FOUND-04 test: UTC storage enforced by the type system

```python
# backend/tests/test_time.py
import datetime as dt
from sqlalchemy import text
from app.db.models.user import User


async def test_timestamps_are_timestamptz(session):
    rows = (await session.execute(text(
        "select column_name, data_type from information_schema.columns "
        "where table_schema='public' and data_type like 'timestamp%'"
    ))).all()
    assert rows, "expected at least one timestamp column"
    for name, data_type in rows:
        assert data_type == "timestamp with time zone", f"{name} is not TIMESTAMPTZ (FOUND-04)"


async def test_roundtrip_is_aware_utc(session):
    u = User(created_at=dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC))
    session.add(u); await session.commit()
    got = (await session.execute(text("select created_at from users"))).scalar_one()
    assert got.tzinfo is not None
    assert got.utcoffset() == dt.timedelta(0)
```

### FOUND-03 test: near-midnight-UTC bucketing, tz from the DB

```python
import datetime as dt
import pytest
from sqlalchemy import text
from app.core.time import local_day, local_week_start


@pytest.mark.parametrize("utc_iso,expected_day", [
    ("2026-08-23T16:30:00+00:00", dt.date(2026, 8, 23)),
    ("2026-08-23T17:00:00+00:00", dt.date(2026, 8, 24)),   # exact Jakarta midnight
    ("2026-08-23T23:30:00+00:00", dt.date(2026, 8, 24)),   # "near midnight UTC"
])
async def test_local_day_uses_user_timezone(session, utc_iso, expected_day):
    # FOUND-03: tz read from user configuration, not hard-coded in the helper.
    tz = (await session.execute(text("select timezone from users"))).scalar_one()
    assert tz == "Asia/Jakarta"
    ts = dt.datetime.fromisoformat(utc_iso)
    assert local_day(ts, tz) == expected_day
    assert local_day(ts, tz) != ts.date() or expected_day == ts.date()


async def test_python_and_sql_bucketing_agree(session):
    tz = (await session.execute(text("select timezone from users"))).scalar_one()
    ts = dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC)
    sql_day = (await session.execute(
        text("select date_trunc('day', :ts AT TIME ZONE :tz)::date"), {"ts": ts, "tz": tz}
    )).scalar_one()
    assert sql_day == local_day(ts, tz)     # [VERIFIED: both == 2026-08-24]
```

### FOUND-05 test: assert against the rendered stream, not `capture_logs`

```python
# backend/tests/test_secret_redaction.py
import io, logging
from fastapi.testclient import TestClient

SEEDED = "brett-test-secret-DO-NOT-LEAK-9f3a"


def test_secret_never_appears_in_logs_or_response(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", SEEDED)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{SEEDED}@localhost/db")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.logging import configure_logging
    from app.main import app

    buf = io.StringIO()
    configure_logging(get_settings())
    logging.getLogger().handlers[0].setStream(buf)

    client = TestClient(app, raise_server_exceptions=False)

    # 1. secret in a log VALUE under a non-denied key
    import structlog
    structlog.get_logger().info("probe", note=f"inline {SEEDED}", api_key=SEEDED)

    # 2. secret inside an unhandled exception traceback (D-05 path)
    r = client.get("/__test_boom__")
    assert r.status_code == 500
    assert set(r.json()) >= {"error", "correlation_id"}
    assert "Traceback" not in r.text

    # 3. secret from a third-party stdlib logger
    logging.getLogger("uvicorn.error").error("third party %s", SEEDED)

    out = buf.getvalue()
    assert SEEDED not in out, "FOUND-05 violated: secret present in log stream"
    assert SEEDED not in r.text, "FOUND-05 violated: secret present in HTTP response"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `declarative_base()` + `Column(...)` | `DeclarativeBase` subclass + `Mapped[]` / `mapped_column()` | SQLAlchemy 2.0 | Statically type-checkable with no mypy plugin. CLAUDE.md already mandates this. |
| `sqlalchemy2-stubs` | Nothing — SQLAlchemy 2.0 ships its own types | 2023 | CLAUDE.md "What NOT to Use" already forbids the stubs. |
| `datetime.utcnow()` | `datetime.now(datetime.UTC)` | Deprecated in Python 3.12 | `utcnow()` returns a naive datetime — actively harmful for FOUND-04. |
| `pytz` | stdlib `zoneinfo` | Python 3.9 | No third-party tz dependency needed. |
| `from testcontainers.postgres import PostgresContainer` | `from testcontainers.community.postgres import PostgresContainer` | testcontainers-python 4.x | Deprecation warning today; likely removal later. `[VERIFIED: warning emitted on 4.15.0]` |
| `requirements.txt` | `pyproject.toml` + `uv.lock` | — | CLAUDE.md decision; blueprint §4's `requirements.txt` is explicitly overridden. |
| `alembic.ini` holding all config | optional `[tool.alembic]` in `pyproject.toml` (`-t pyproject_async`) | Alembic 1.16+ | Optional. Generated `env.py` is identical either way `[VERIFIED: diff]`. |

**Deprecated/outdated:**
- `testcontainers.postgres` module path — use `testcontainers.community.postgres`.
- `datetime.utcnow()` — use `app.core.time.utc_now()`.
- Blueprint §4's `requirements.txt` and `authentication` under Phase 1 — both superseded (by uv, and by ROADMAP scoping auth to Phase 2 respectively). CONTEXT.md already records this.

## Project Constraints (from CLAUDE.md)

| Directive | How Phase 1 complies |
|-----------|---------------------|
| Tech stack pinned (Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic, pytest, Ruff, mypy where practical) | Every version confirmed current against PyPI; nothing substituted. |
| Flat repo layout — `backend/`, `ios/`, `docs/` at BRETT root, no `fitness-platform/` nesting | Project structure above is flat at root. |
| Never expose API keys, DB credentials, or internal tokens through responses or logs | Pattern 6 three-layer redaction; D-05 sanitized error body. |
| Secrets only via environment/secret storage, never committed | `pydantic-settings` + `.env` in `.gitignore` + `.env.example` with names only + a `gitleaks`/`detect-secrets` pre-commit hook. `alembic.ini` must not contain a real URL. |
| HTTPS everywhere | Phase 2 (Render TLS termination). Not a Phase 1 code concern. |
| Provider isolation — Hevy logic confined to `backend/app/integrations/hevy/` | Phase 1 creates no `integrations/` code. The `external_connections.provider` column is a plain string, so no Hevy-specific type leaks into the schema. |
| Data integrity — sync idempotent, never corrupts on partial failure | Phase 3. Phase 1 contributes the `uq_external_connections_user_provider` constraint and FK `ON DELETE CASCADE`. |
| Deployment portable beyond Render | uv + uvicorn + plain Postgres; `DATABASE_URL` normalization (Pitfall 3) makes the app host-agnostic. |
| Do NOT use: `requirements.txt`, `sqlalchemy2-stubs`, SQLite for tests, pandas/numpy | All honored — testcontainers Postgres for tests; no stubs; `pyproject.toml` + `uv.lock`. |
| GSD workflow enforcement — no direct edits outside a GSD command | This phase's work runs through `/gsd-execute-phase`. |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | Runtime pin (`.python-version`) | ✓ | 3.13.13 via `uv venv --python 3.13` | uv auto-downloads it; system python3 is 3.14.0 |
| uv | Dependency management + lockfile | ✓ | **0.11.7** (CLAUDE.md says 0.12.5) | `uv self update` |
| Docker daemon | `testcontainers[postgres]` | ✓ | Engine 29.4.2, `docker ps` succeeded | None viable — SQLite is forbidden by CLAUDE.md |
| PostgreSQL (test) | Integration tests | ✓ via Docker | `postgres:18-alpine` pulled and run successfully | — |
| PostgreSQL (local dev server) | Optional local dev DB | ✗ | `psql` client 18.6 present, `pg_isready` → "no response" on :5432 | Use a Docker Postgres for local dev too — recommended, keeps dev == test |
| `Asia/Jakarta` tz data | FOUND-03 | ✓ | Present on macOS (`/usr/share/zoneinfo`) and in `python:3.13-slim` | Add the `tzdata` pip package |
| git | Version control | ✓ | 2.39.5 | — |
| Network / PyPI | Package install | ✓ | All 16 version checks + installs succeeded | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- No local Postgres server running. Not a blocker — Docker covers both test and local dev. The planner should include a `docker compose` file (or a documented `docker run`) for the local dev database so `alembic upgrade head` can be run by hand.

**Version discrepancy to resolve:** installed uv is 0.11.7; CLAUDE.md specifies 0.12.5. See Open Question 1.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 + pytest-cov 7.1.0 |
| Config file | **none — Wave 0** (`[tool.pytest.ini_options]` in `pyproject.toml`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest backend/tests -x -q -m "not integration"` |
| Full suite command | `uv run pytest backend/tests -q --cov=backend/app` |

Integration tests that spin a container should be marked `@pytest.mark.integration` so the per-task quick run stays under ~30 s. The container is session-scoped, so the full suite pays the startup cost once (~5–10 s observed).

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | `/health` returns 200 `{status, database:"connected"}` against a live DB | integration | `pytest backend/tests/test_health.py::test_health_reports_connected -x` | ❌ Wave 0 |
| FOUND-01 | `/health` returns 503 `database:"error"` when the DB is unreachable | integration | `pytest backend/tests/test_health.py::test_health_reports_db_error -x` | ❌ Wave 0 |
| FOUND-01 | `/health` requires no auth (D-04) | unit | `pytest backend/tests/test_health.py::test_health_is_open -x` | ❌ Wave 0 |
| FOUND-02 | empty → `upgrade head` → `downgrade base` → `upgrade head`, no manual SQL | integration | `pytest backend/tests/test_migrations.py::test_migrations_round_trip -x` | ❌ Wave 0 |
| FOUND-02 | seed migration creates exactly one user with `Asia/Jakarta` (D-01/D-02) | integration | `pytest backend/tests/test_migrations.py::test_default_user_seeded -x` | ❌ Wave 0 |
| FOUND-02 | `alembic revision --autogenerate` against head produces an empty diff (models == migrations) | integration | `pytest backend/tests/test_migrations.py::test_no_pending_model_drift -x` | ❌ Wave 0 |
| FOUND-03 | 23:30Z and 17:00Z bucket to the correct Jakarta local day | unit | `pytest backend/tests/test_time.py::test_local_day_uses_user_timezone -x` | ❌ Wave 0 |
| FOUND-03 | tz is read from `users.timezone`, not a constant — changing the row changes the bucket | integration | `pytest backend/tests/test_time.py::test_timezone_is_configurable -x` | ❌ Wave 0 |
| FOUND-03 | Python helper and SQL `AT TIME ZONE` agree | integration | `pytest backend/tests/test_time.py::test_python_and_sql_bucketing_agree -x` | ❌ Wave 0 |
| FOUND-03 | week bucketing is stable under a frozen clock | unit | `pytest backend/tests/test_time.py::test_week_start_with_frozen_clock -x` | ❌ Wave 0 |
| FOUND-04 | every timestamp column in `information_schema` is `timestamp with time zone` | integration | `pytest backend/tests/test_time.py::test_timestamps_are_timestamptz -x` | ❌ Wave 0 |
| FOUND-04 | round-trip returns an aware datetime with zero UTC offset | integration | `pytest backend/tests/test_time.py::test_roundtrip_is_aware_utc -x` | ❌ Wave 0 |
| FOUND-04 | naive datetimes are rejected at the helper boundary | unit | `pytest backend/tests/test_time.py::test_naive_datetime_rejected -x` | ❌ Wave 0 |
| FOUND-05 | seeded secret absent from the rendered log stream (value, traceback, third-party logger) | unit | `pytest backend/tests/test_secret_redaction.py::test_secret_never_appears_in_logs_or_response -x` | ❌ Wave 0 |
| FOUND-05 | 500 body is `{error, correlation_id}` with no traceback, in dev AND prod ENVIRONMENT (D-05) | unit | `pytest backend/tests/test_secret_redaction.py::test_error_body_sanitized_in_all_environments -x` | ❌ Wave 0 |
| FOUND-05 | `repr(Settings())` and `model_dump_json()` mask every secret field | unit | `pytest backend/tests/test_config.py::test_secrets_masked -x` | ❌ Wave 0 |
| FOUND-05 | missing required env var fails fast at construction | unit | `pytest backend/tests/test_config.py::test_missing_env_fails_fast -x` | ❌ Wave 0 |
| FOUND-05 | `.env` is gitignored and no secret-looking literal is committed | unit | `pytest backend/tests/test_config.py::test_env_is_gitignored -x` (+ `gitleaks` pre-commit) | ❌ Wave 0 |
| FOUND-05 | `?sslmode=require` in `DATABASE_URL` is normalized (Pitfall 3) | unit | `pytest backend/tests/test_config.py::test_async_url_normalizes_sslmode -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest backend/tests -x -q -m "not integration"` (plus `ruff check` and `mypy backend/app`)
- **Per wave merge:** `uv run pytest backend/tests -q --cov=backend/app`
- **Phase gate:** full suite green, `ruff check` clean, `mypy` clean, before `/gsd-verify-work`

### Wave 0 Gaps

Everything is a gap — greenfield repo with zero test infrastructure.

- [ ] `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and an `integration` marker
- [ ] `backend/tests/conftest.py` — session-scoped `testcontainers.community.postgres` fixture, `alembic upgrade head` bootstrap, `session` and `client` fixtures, and an `alembic()` subprocess helper
- [ ] `backend/tests/test_health.py`
- [ ] `backend/tests/test_migrations.py`
- [ ] `backend/tests/test_time.py`
- [ ] `backend/tests/test_secret_redaction.py`
- [ ] `backend/tests/test_config.py`
- [ ] Framework install: `uv add --dev pytest pytest-asyncio pytest-cov "testcontainers[postgres]" time-machine`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | **no** (this phase) | No auth surface exists in Phase 1; D-04 makes `/health` deliberately open. All auth is Phase 2 (MCP-04). |
| V3 Session Management | no | No sessions. Correlation IDs are not authentication and must never be treated as such. |
| V4 Access Control | no | Single user, no user-facing endpoints beyond open `/health`. |
| V5 Input Validation | **yes** | Pydantic v2 for all boundary input; `Literal` types for enum-like settings; SQLAlchemy bound parameters / `sa.text().bindparams()` for every query — never f-string SQL. |
| V6 Cryptography | no (this phase) | Blueprint §5.2's `encrypted_credentials` column is deliberately deferred to Phase 3 rather than shipping an unused or hand-rolled encryption scheme. |
| V7 Error Handling & Logging | **yes — the core of this phase** | D-05 generic error body; three-layer structlog redaction; blueprint §44's deny-list; correlation IDs to make sanitized errors still debuggable. |
| V8 Data Protection | **yes** | Secrets never committed (`.gitignore` + `gitleaks`/`detect-secrets` pre-commit); `SecretStr` in config; secrets from env only. |
| V14 Configuration | **yes** | Fail-fast typed config; `.env.example` with names only; `alembic.ini` must contain no real URL; migrations run out-of-band, never at app startup. |

### Known Threat Patterns for FastAPI + SQLAlchemy + Postgres

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leakage via log output | Information Disclosure | Three-layer redaction, Pattern 6 — **empirically verified as necessary** |
| Secret leakage via stack trace in an HTTP response | Information Disclosure | D-05 global exception handler; never `debug=True` |
| Secret leakage via a Pydantic `ValidationError` echoing input | Information Disclosure | `SecretStr` fields; validators re-raise `from None` without input `[VERIFIED as a real leak]` |
| Credentials committed to git (`.env`, `alembic.ini`) | Information Disclosure | `.gitignore`, `.env.example` names-only, `gitleaks` pre-commit hook |
| SQL injection | Tampering | SQLAlchemy Core/ORM constructs and bound parameters exclusively; Ruff `S608` catches string-built SQL |
| Unauthenticated info disclosure via `/health` | Information Disclosure | D-03 keeps the body to `{status, database}` — no versions, no revision, no env name, no DSN |
| Startup-time migration race across restarts | Tampering / Availability | Run `alembic upgrade head` out-of-band (Render pre-deploy), never in `lifespan` |
| Dependency supply chain | Tampering | `uv.lock` committed, `uv sync --frozen`, Ruff `S` (bandit) ruleset enabled |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Alembic autogenerate produces an empty migration when models aren't imported in `env.py` | Pitfall 8 | Low — worst case is a wasted debugging cycle; the mitigation (importing models) is harmless regardless. |
| A2 | `time_machine.travel()` with a naive datetime causes aware/naive comparison errors | Pitfall 9 | Low — surfaces immediately as a test failure. |
| A3 | Render's `DATABASE_URL` includes `?sslmode=require` (the docs page 404'd; this is the general managed-Postgres convention) | Pitfall 3 | **Low, because the mitigation is unconditional** — normalizing the URL is correct whether or not `sslmode` is present. The underlying asyncpg incompatibility is VERIFIED regardless of which provider triggers it. |
| A4 | Deferring blueprint §5.2's `encrypted_credentials` column to Phase 3 is acceptable | Pattern 1 | Medium — if the user wants the column present now (even unused), it's a one-line migration change. Worth confirming with the user, since it is a deliberate deviation from the blueprint's stated schema. |
| A5 | A UUID primary key (rather than bigint) best satisfies blueprint §5.1's "don't preclude multi-user" | Pattern 1 | Low — either works; UUID avoids ID-guessing and merge conflicts if multi-user ever arrives. Changing it later is a painful migration, so it's worth a deliberate decision now. |

## Open Questions

1. **uv version discrepancy: installed 0.11.7 vs CLAUDE.md's 0.12.5**
   - What we know: `uv --version` reports 0.11.7 (2026-04-15). CLAUDE.md's stack research names 0.12.5.
   - What's unclear: whether 0.11.7 writes a lockfile format that 0.12.x would rewrite, causing churn.
   - Recommendation: run `uv self update` as the first task of the phase, then generate `uv.lock`. Low risk either way, but pinning `UV_VERSION` matters for Phase 2's Render build reproducibility.

2. **Does `external_connections` get an `encrypted_credentials` column in Phase 1? (A4)**
   - What we know: blueprint §5.2 lists the column; §5.2 also says "For the first personal deployment, environment secrets are acceptable for the Hevy key."
   - What's unclear: whether the user wants the column present-but-unused now, or added in Phase 3 with a real key-management design.
   - Recommendation: **omit in Phase 1**, add in Phase 3. Shipping a credentials column with no encryption implementation invites someone (or some future agent) to write a plaintext key into it, directly violating FOUND-05. Flag to the user during planning — it is a visible deviation from the blueprint.

3. **Does anything in Phase 1 need `users.timezone` to be validated as a real IANA zone?**
   - What we know: FOUND-03 requires it be configurable. A bad value raises `ZoneInfoNotFoundError` deep in analytics.
   - Recommendation: add a `CHECK`-free application-level validation — validate with `ZoneInfo(tz)` in the repository/service layer that reads it, and cover it with a test. Cheap; prevents a confusing Phase 4 failure.

4. **Which Postgres major should tests pin?**
   - What we know: I verified against `postgres:18-alpine`. Render's managed offering major is not confirmed in this session.
   - Recommendation: pin the test container to whatever major Render provides once Phase 2 confirms it; `18-alpine` is a reasonable default and nothing in this phase depends on a version-specific feature.

## Sources

### Primary (HIGH confidence)

**Live verification in this session — the strongest evidence in this document:**
- Clean venv install, Python 3.13.13: `fastapi 0.141.1 + starlette 1.6.0 + sqlalchemy 2.0.52 + asyncpg 0.31.0 + alembic 1.19.1 + pydantic 2.13.4 + pydantic-settings 2.15.0 + structlog 26.1.0 + asgi-correlation-id 5.0.1 + uvicorn 0.52.4` — no resolution conflicts
- Live `postgres:18-alpine` container via testcontainers 4.15.0 — `TIMESTAMPTZ` mapping, aware-UTC round-trip, `AT TIME ZONE` / `date_trunc` day + week bucketing, session-TimeZone independence, `isodow`
- Live Alembic run — `upgrade head` → `current` → `downgrade base` → `upgrade head` with schema + seed data migrations
- Live FastAPI `TestClient` runs — exception handler + correlation ID propagation + secret-redaction leak reproduction and fix
- Source reads: `alembic/templates/async/env.py`, `alembic/templates/pyproject_async/env.py` (identical), `alembic.config.Config.set_section_option`, `structlog.testing.capture_logs`, `asgi_correlation_id.middleware.CorrelationIdMiddleware.__call__`, `sqlalchemy/dialects/postgresql/asyncpg.py`
- `inspect.signature(asyncpg.connect)` — no `sslmode`, no `**kwargs`
- `docker run python:3.13-slim` — `ZoneInfo("Asia/Jakarta")` resolves

**Registry:**
- PyPI JSON API (`pypi.org/pypi/<pkg>/json`), queried 2026-08-23 — all 16 version numbers and release dates in the Standard Stack tables

**Project documents:**
- `CLAUDE.md` §Technology Stack, §What NOT to Use, §Constraints
- `.planning/phases/01-backend-foundation/01-CONTEXT.md` — D-01..D-06
- `.planning/REQUIREMENTS.md` — FOUND-01..05
- `.planning/STATE.md`, `.planning/config.json`
- `BRETT blueprint.md` §4, §5.1, §5.2, §39, §40, §41, §42, §44, §45, §48

### Secondary (MEDIUM confidence)
- https://alembic.sqlalchemy.org/en/latest/cookbook.html — `op.bulk_insert` with `sa.table()`/`sa.column()` for data migrations; async `run_sync()` guidance. Corroborated by the live round-trip run.

### Tertiary (LOW confidence)
- https://render.com/docs/postgresql-connecting — **returned HTTP 404**; Render's exact `DATABASE_URL` format is therefore unverified (see A3). Does not affect the recommendation, since URL normalization is correct unconditionally and the asyncpg incompatibility is independently verified.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every version confirmed against PyPI and installed together successfully
- Architecture / patterns: **HIGH** — every pattern executed against real Postgres and a real FastAPI app, not reasoned from training data
- Pitfalls 1, 2, 3, 5, 6, 7: **HIGH** — each reproduced and then fixed in a live probe
- Pitfall 4: **HIGH** — from the library's own docstring
- Pitfalls 8, 9: **MEDIUM** — standard behavior, not separately reproduced this session
- Security domain: **HIGH** for V7/V8/V14 (directly exercised); mapping of non-applicable categories is judgment
- Environment availability: **HIGH** — every tool probed directly on this machine
- Render specifics: **LOW** — docs page 404'd; deliberately scoped out of Phase 1 (Phase 2 concern)

**Research date:** 2026-08-23
**Valid until:** 2026-09-22 (30 days — the stack is stable and all versions were current on the research date)

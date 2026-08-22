# Phase 1: Backend Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-23
**Phase:** 01-backend-foundation
**Areas discussed:** Default user bootstrap, Health endpoint scope, Secret-safety in errors, Local dev logging format

---

## Default User Bootstrap

| Option | Description | Selected |
|--------|-------------|----------|
| Migration-seeded | Alembic migration inserts the one user row as part of `alembic upgrade head`. Zero runtime logic, matches single-user v1. | ✓ |
| Lazy get-or-create on boot | App lifespan checks/creates a user row on startup. | |
| Explicit CLI/setup command | `uv run python -m app.cli create-user` run once manually. | |

**User's choice:** Migration-seeded
**Notes:** Every later phase (Hevy sync, MCP tools) can assume the user already exists once migrations have run.

Follow-up — seed timezone value:

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcode Asia/Jakarta | Migration inserts `timezone='Asia/Jakarta'` directly; change later via a one-off UPDATE. | ✓ |
| Env-var driven | Migration reads `DEFAULT_USER_TIMEZONE` from environment, falling back to Asia/Jakarta. | |

**User's choice:** Hardcode Asia/Jakarta
**Notes:** Avoids env-coupling a migration file; trivial to change later for a single-user app.

---

## Health Endpoint Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal: status + DB ping | `{status, database}` only — exactly FOUND-01's minimum. | ✓ |
| Richer diagnostics | Also Alembic revision, environment name, uptime. | |

**User's choice:** Minimal: status + DB ping

Follow-up — auth on /health:

| Option | Description | Selected |
|--------|-------------|----------|
| Open, no auth | Render health checks and monitors reach it without a token. | ✓ |
| Require bearer auth | Same auth as /mcp (which doesn't exist until Phase 2). | |

**User's choice:** Open, no auth

---

## Secret-Safety in Errors

| Option | Description | Selected |
|--------|-------------|----------|
| Sanitized always, even in dev | Global exception handler always returns generic body + correlation ID; full traceback only to redacted logs. | ✓ |
| Full tracebacks in dev, sanitized in prod | FastAPI's default debug-mode split by `ENVIRONMENT`. | |

**User's choice:** Sanitized always, even in dev
**Notes:** Guarantees FOUND-05 holds regardless of environment config; avoids a misconfigured-`ENVIRONMENT` leak risk in production.

---

## Local Dev Logging Format

| Option | Description | Selected |
|--------|-------------|----------|
| Human-readable in dev, JSON in prod | structlog `ConsoleRenderer` in dev, JSON renderer in prod; same redaction processor in both. | ✓ |
| Always JSON | Same JSON renderer everywhere. | |

**User's choice:** Human-readable in dev, JSON in prod

---

## Claude's Discretion

- Exact shape/wording of the sanitized error body beyond `{error, correlation_id}`
- structlog processor pipeline details and the specific secret deny-list
- Whether the `/health` DB check is a raw `SELECT 1` or equivalent
- Alembic migration file naming, correlation-ID generation mechanism

## Deferred Ideas

None — discussion stayed within Phase 1 scope.

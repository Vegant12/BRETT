# Phase 1: Backend Foundation - Context

**Gathered:** 2026-08-23
**Status:** Ready for planning

<domain>
## Phase Boundary

A running FastAPI service backed by a migration-managed PostgreSQL schema, with timezone and secret handling correct from the first line of code. Delivers: FastAPI app skeleton, PostgreSQL + Alembic migrations, a seeded single-user schema, a health endpoint, timezone-aware day/week bucketing helpers, and structured logging with secret redaction.

**Explicitly NOT this phase:** MCP server, MCP auth, Render deployment (all Phase 2). Hevy integration (Phase 3). Analytics calculations beyond the UTC/timezone bucketing helpers (Phase 4+).

</domain>

<decisions>
## Implementation Decisions

### Default User Bootstrap
- **D-01:** The single v1 user row is created by an Alembic migration (data migration seeding one row), not by app-startup get-or-create logic and not by a CLI command. Every later phase (Hevy sync, MCP tools) can assume the user already exists once migrations have run.
- **D-02:** The seed migration hardcodes `timezone='Asia/Jakarta'` directly — it does not read an env var at migration time. Changing it later is a one-off `UPDATE` against the single row (acceptable for a single-user app). Migrations should not be env-coupled.

### Health Endpoint
- **D-03:** `GET /health` is minimal: reports `{status, database}` (connected/error) — service status plus the live DB connectivity check required by FOUND-01. No Alembic revision, environment name, or uptime in the response body. Claude has discretion to add trivial extra fields later if genuinely useful, but nothing was asked for.
- **D-04:** `GET /health` is unauthenticated/open — no MCP bearer token required (that auth mechanism doesn't exist until Phase 2 anyway). This matches standard practice: Render's own health checks and uptime monitors need to reach it without a token, and the minimal response body has nothing sensitive to protect.

### Secret-Safety in Errors
- **D-05:** A global FastAPI exception handler ALWAYS returns a generic, sanitized error body (e.g. `{"error": "internal server error", "correlation_id": "..."}`) — same behavior in dev and prod. Full tracebacks go only to the structured log (which itself runs through the secret-redaction processor), never to the HTTP response. This guarantees FOUND-05's "never appears in any log line or response" holds regardless of `ENVIRONMENT`, and avoids a leak risk if that var is ever misconfigured in production. Rejected: FastAPI's default debug-mode split (tracebacks in dev, generic in prod) — it only proves the secret-safety test in one of two code paths.

### Local Dev Logging Format
- **D-06:** structlog uses `ConsoleRenderer` (human-readable, colored key=value) when `ENVIRONMENT=development`, and a JSON renderer in production. The secret-redaction processor (deny-list for API keys/tokens/credentials) runs identically in both modes as a separate pipeline step, so this is purely a rendering choice, not a safety one.

### Claude's Discretion
- Exact shape/wording of the sanitized error body beyond `{error, correlation_id}` (additional fields, error codes, etc.)
- structlog processor pipeline details and the specific deny-list of redacted key names
- Whether `/health` DB check is a raw `SELECT 1` or something equivalent — as long as it's a live connectivity check
- Naming/structure of Alembic migration files, correlation-ID generation mechanism (e.g. `asgi-correlation-id` per CLAUDE.md)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope & requirements
- `.planning/PROJECT.md` — Requirements (Active), Constraints, Key Decisions for v1
- `.planning/REQUIREMENTS.md` — FOUND-01 through FOUND-05 (exact acceptance criteria for this phase)
- `.planning/ROADMAP.md` — Phase 1 section (goal, success criteria, requirements mapping)

### Technology stack (already researched and locked — see project CLAUDE.md)
- `CLAUDE.md` §"Technology Stack" — full pinned dependency list: Python 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.52 (async, `Mapped[]`), asyncpg 0.31.0, Alembic 1.19.1, Pydantic 2.13.4, pydantic-settings 2.15.0, structlog 26.1.0, asgi-correlation-id 5.0.1, uv 0.12.5, Ruff, mypy, pytest + pytest-asyncio + testcontainers[postgres]. Treat as decided; do not re-litigate without cause.
- `CLAUDE.md` §"What NOT to Use" — explicitly avoid `requirements.txt`, `sqlalchemy2-stubs`, SQLite for tests, pandas/numpy for analytics (not relevant to Phase 1 but binds the repo generally)

### Source spec (authoritative for schema/architecture shape)
- `BRETT blueprint.md` §4 "Repository Structure" — target layout (note: PROJECT.md overrides the blueprint's `fitness-platform/` root nesting with a flat repo-root layout — `backend/`, `ios/`, `docs/` directly at BRETT root)
- `BRETT blueprint.md` §5.1 "users" — schema: `id, created_at, updated_at, timezone`; single-user now, not hard-coded to preclude multi-user
- `BRETT blueprint.md` §5.2 "external_connections" — schema for provider credentials (relevant context for Phase 1's DB design even though Hevy integration itself is Phase 3)
- `BRETT blueprint.md` §39 "Data Freshness" — `last_synced_at` pattern (context for `external_connections`, not needed as a Phase 1 deliverable)
- `BRETT blueprint.md` §40 "Time Zones" — store UTC, convert to local only at calculation boundaries, default `Asia/Jakarta`, must be configurable
- `BRETT blueprint.md` §41 "Units" — kg/m/kcal/seconds/cm internal units, convert at application boundary (context for later phases, not Phase 1 itself)
- `BRETT blueprint.md` §44 "Observability" — what to log (sync lifecycle events) and what never to log (API keys, tokens, full health samples); correlation IDs where useful
- `BRETT blueprint.md` §48 "Phase 1 — Backend foundation" — FastAPI, PostgreSQL, migrations, users, health endpoint, configuration (note: blueprint lists "authentication" here, but ROADMAP.md correctly scopes all auth to Phase 2 — MCP-04 — since there is no user-facing auth surface in Phase 1)

</canonical_refs>

<code_context>
## Existing Code Insights

Repo is currently empty except for `CLAUDE.md` and `BRETT blueprint.md` — this is a greenfield phase. No existing components, patterns, or integration points to reuse. The `backend/` directory structure, `app/config.py`, `app/db/`, `app/main.py`, etc. described in the blueprint (§4) and CLAUDE.md's FastAPI + MCP integration pattern do not exist yet and are Phase 1's job to create.

</code_context>

<specifics>
## Specific Ideas

None beyond the decisions above — this is an infrastructure phase and most ambiguity was resolved through the discussion questions rather than freeform user references.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Auth, deployment, and richer health diagnostics were considered and explicitly deferred to Phase 2 / Claude's discretion, not dropped — see decisions above.)

</deferred>

---

*Phase: 01-backend-foundation*
*Context gathered: 2026-08-23*

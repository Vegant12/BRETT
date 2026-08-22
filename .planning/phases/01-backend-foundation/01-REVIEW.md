---
phase: 01
slug: backend-foundation
status: issues_found
reviewed: 2026-08-23
---

# Phase 01 — Code Review

> Advisory review of the phase 01 diff (backend/app/**, backend/tests/**, migrations). Does not block phase completion. Consider `/gsd-code-review-fix 01` or manual fixes, especially for the two security-relevant findings.

## Findings

### 1. [Security] D-05 sanitized exception handler doesn't catch `HTTPException`
**File:** `backend/app/main.py:62`
The handler is registered only for the generic `Exception` type, so it never intercepts `HTTPException` — Starlette/FastAPI route those to their own more-specific built-in handler, which returns `exc.detail` verbatim to the client.
**Failure scenario:** Any future dependency or route raising `HTTPException(status_code=500, detail="...internal detail...")` bypasses FOUND-05's "no traceback/detail ever reaches the client, same behavior in every environment" guarantee. No current Phase 1 code triggers this (no HTTPException is raised anywhere yet), but it's a live trap for Phase 2+ routes.

### 2. [Security] `structlog.reset_defaults()` in test teardown strips the FOUND-05 redaction pipeline process-wide
**File:** `backend/tests/test_secret_redaction.py:61`
`app.main`'s `configure_logging(settings)` installs the three-layer redaction pipeline once at import time. The `_restore_logging` fixture's teardown calls `structlog.reset_defaults()`, which discards that pipeline with nothing re-installing it afterward.
**Failure scenario:** Verified by reproduction — after this reset, a later `structlog.get_logger().exception(...)` call (the same call `health.py` makes on a DB failure) prints an unredacted traceback, including a literal DSN password, straight to stderr. Currently masked only by pytest's alphabetical collection order; any test file sorting after `test_secret_redaction.py` that exercises a real DB-error logging path leaks secrets with zero redaction.

### 3. [Correctness] `postgres://` scheme rejected by `_validate_db_url`
**File:** `backend/app/config.py:67`
Only `postgresql://`-prefixed drivernames pass validation; `postgres://` (a common legacy/managed-provider DSN format) fails `ValidationError` at boot despite being a valid Postgres connection string.

### 4. [Correctness] `sslmode=prefer`/`allow` silently dropped instead of translated
**File:** `backend/app/config.py:83`
Only `require`/`verify-ca`/`verify-full` are translated to asyncpg's `ssl=` param; other libpq sslmode values are popped from the URL with no substitute added, silently downgrading to a plaintext connection.

### 5. [Correctness] `validate_timezone()` guard is never called from any write path
**File:** `backend/app/core/time.py:43`
Documented as the boundary guard against a bad `users.timezone` value, but nothing calls it outside its own unit test — no SQLAlchemy `@validates` on `User.timezone`. Not exploitable yet (no write path for `users.timezone` exists in Phase 1), but the docstring's promised protection isn't wired up.

### 6. [Reliability] `/health` DB probe has no connect/statement timeout
**File:** `backend/app/api/routes/health.py:31`
If the database is reachable at the TCP level but hanging, the probe can block indefinitely holding a pool connection instead of failing fast, risking pool exhaustion under repeated uptime-monitor polling.

### 7. [Reliability] `app.main.settings` module-level binding not updated by `get_settings.cache_clear()`
**File:** `backend/app/main.py:22`
`settings = get_settings()` binds once at import; later cache-clear calls elsewhere in the test suite don't update this reference, so whichever test imports `app.main` first pins the config used by `lifespan()`. Currently masked because the `client` fixture overwrites `app.state.engine` post-startup.

### 8. [Reuse/Maintainability] Secret field names duplicated across two hand-maintained lists
**Files:** `backend/app/logging.py:664` (`DENY_KEYS`), `backend/app/config.py:255` (`_SECRET_FIELDS`)
Both lists are manually maintained rather than derived from `Settings`' `SecretStr` type annotations. A future secret field added to `Settings` without also updating both lists silently loses redaction coverage.

## Non-blocking notes (lower priority, not itemized above)
- Alembic's `migrations/env.py` logging is independent of `app.logging.configure_logging` — a migration-time connection failure could leak a DSN password to CI logs unredacted (migrations run as a separate process per the deploy plan).
- Minor duplication: `information_schema` timestamp-column checks are hand-written in both `test_migrations.py` and `test_time.py` rather than using SQLAlchemy's `Inspector` API.
- Minor efficiency: `async_database_url` and `secret_values()` re-parse the DSN with `make_url()` on every access rather than caching; not a hot path today.

## Verdict
No CLAUDE.md convention violations found. All findings are advisory — the phase's automated test suite (47/47 passing) and goal-backward verification are unaffected. Findings #1 and #2 are the two worth prioritizing before Phase 2 adds routes/tests that could trigger them.

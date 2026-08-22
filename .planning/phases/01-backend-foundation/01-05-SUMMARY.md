---
phase: 01-backend-foundation
plan: 05
subsystem: api
tags: [fastapi, health, lifespan, sqlalchemy, readme, found-01]
requires:
  - "app.config.get_settings (Plan 01-01)"
  - "app.main.app + D-05 exception handler (Plan 01-02)"
  - "app.db.session.make_engine / make_sessionmaker (Plan 01-03)"
  - "backend/tests/conftest.py client + postgres_url fixtures (Plan 01-03)"
provides:
  - "GET /health — open endpoint returning {status, database} with a live SELECT 1 probe"
  - "app.state.engine / app.state.sessionmaker, created and disposed in lifespan"
  - "backend/app/api/ package root for future route modules"
  - "README.md — clean-checkout bootstrap"
affects:
  - "Phase 2 (Render deploy) uses /health as the platform health check path"
  - "Phase 3 adds backend/app/api/dependencies.py (get_db) reading app.state.sessionmaker"
  - "Any future router mounts under backend/app/api/routes/"
tech-stack:
  added: []
  patterns:
    - "Engine lifetime owned by lifespan; never a module-level engine global"
    - "Routes read app.state.engine directly; no DI layer until there is a consumer"
    - "Health degrades (503) rather than 500s — bare except around the DB probe by design"
    - "Failure detail goes to the log, coarse state goes to the client"
key-files:
  created:
    - backend/app/api/__init__.py
    - backend/app/api/routes/__init__.py
    - backend/app/api/routes/health.py
    - backend/tests/test_health.py
    - README.md
    - .planning/phases/01-backend-foundation/deferred-items.md
  modified:
    - backend/app/main.py
    - backend/tests/conftest.py
decisions:
  - "The client fixture must override app.state.engine AFTER TestClient startup — the new lifespan builds its own engine from DATABASE_URL and clobbers any pre-startup assignment"
  - "DB-unreachable is simulated with a real engine at 127.0.0.1:1 with connect_args={'timeout': 1}, not a mock; the shared session engine is swapped and restored, never disposed"
  - "Route-registration is verified via app.openapi()['paths'], not app.routes — Starlette 1.x stores an unflattened _IncludedRouter with no .path"
  - "app/api/dependencies.py (get_db) deferred to Phase 3 — Phase 1 has no session consumer"
metrics:
  duration: ~35 min
  tasks: 2
  completed: 2026-08-22
---

# Phase 1 Plan 05: Health Endpoint and Lifespan Engine Summary

`GET /health` now answers with a live `SELECT 1` against a lifespan-owned engine — 200 `{"status":"ok","database":"connected"}` when the database is reachable, 503 `{"status":"degraded","database":"error"}` when it is not, with no DSN, driver name, or traceback in either body. FOUND-01 and the last Phase 1 roadmap criterion are closed.

## What Was Built

**`backend/app/api/routes/health.py`.** A single `APIRouter` with one open route. The DB check is a real `engine.connect()` + `SELECT 1` — the field reports what it just measured, never a cached or assumed value, because a health check that reports belief keeps Render routing traffic at a service whose database has gone away. The `except` clause is deliberately bare (`# noqa: BLE001`): any failure to reach the database must degrade to 503, not escape into the D-05 500 handler. The exception detail goes to `log.exception`, which passes through the Plan 01-02 redaction chain; the client receives the literal string `"error"` and nothing else. No `Depends` (D-04), no Alembic revision / environment / uptime / hostname in the body (D-03).

**`backend/app/main.py` — three additions, nothing removed.** The lifespan now calls `make_engine(settings)`, publishes `app.state.engine` and `app.state.sessionmaker`, and `await engine.dispose()`s in the `finally` branch. There is no module-level engine (it would bind its pool to the importing event loop) and no `alembic upgrade head` at startup (migrations race across restarts; they run as a Render pre-deploy command in Phase 2). `app.include_router(health.router)` sits directly after the correlation-ID middleware. The Plan 01-02 bootstrap order and the `@app.exception_handler(Exception)` block are byte-for-byte unchanged.

**`backend/tests/test_health.py`.** The three test names VALIDATION.md references, all `@pytest.mark.integration`. The failure direction is the one that matters: `test_health_reports_db_error` asserts the 503 body contains none of `nobody`, `nopass`, `127.0.0.1`, `asyncpg`, or `Traceback`.

**`README.md`.** Clean checkout → `uv sync` → compose db → `alembic upgrade head` → passing suite, plus the `/health` contract and the UTC/timezone/secrets conventions.

## Final `/health` Response Shape

| Condition | Status | Body |
|---|---|---|
| Database reachable | 200 | `{"status": "ok", "database": "connected"}` |
| Database unreachable | 503 | `{"status": "degraded", "database": "error"}` |

Verified end to end outside the test suite, against the real Docker Compose database:

```
$ curl http://localhost:8123/health
{"status":"ok","database":"connected"}
```

## DB-Unreachable Simulation — the approach that worked

`create_async_engine("postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb", connect_args={"timeout": 1}, pool_pre_ping=False)`, swapped into `app.state.engine` and restored in a `finally`. **Timeout value used: 1 second** — and it was never reached in practice; port 1 is reserved and never listening, so the OS returns `ECONNREFUSED` immediately and the whole test costs milliseconds. Disposing the shared session-scoped engine would have been the obvious alternative and is exactly wrong: it poisons every later test in the session.

## Deferred: `app/api/dependencies.py` (`get_db`)

**Explicitly deferred to Phase 3, not forgotten.** `/health` reads `app.state.engine` directly, so Phase 1 has no consumer for a session dependency; shipping one now would be dead code. Phase 3 planning should add `get_db` as a FastAPI dependency over `request.app.state.sessionmaker` when the first Hevy sync endpoint needs a session.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The `client` fixture set `app.state.engine` before startup, where the new lifespan clobbers it**

- **Found during:** Task 1 (GREEN phase — `test_health_reports_connected` returned 503)
- **Issue:** Plan 01-03's `client` fixture assigned `app.state.engine` *before* entering the `TestClient` context. Entering that context runs `lifespan`, which — as of this plan — creates its own engine from `DATABASE_URL`. Under pytest that is conftest's `_PLACEHOLDER_DB_URL` (`localhost:5432/test`), so `/health` probed a database that does not exist and reported `degraded`. This was a latent ordering bug the moment the lifespan gained an engine.
- **Fix:** The fixture now captures the lifespan's engine after startup, overrides `app.state.engine`/`app.state.sessionmaker` with the container-backed pair for the duration of the test, and restores the lifespan's own engine in a `finally` so shutdown disposes what it created.
- **Files modified:** `backend/tests/conftest.py`
- **Commit:** `d00a3f3`

**2. [Rule 3 - Blocking] The plan's Task 1 verify command crashed on Starlette 1.x**

- **Found during:** Task 1
- **Issue:** `[r.path for r in app.routes]` raised `AttributeError: '_IncludedRouter' object has no attribute 'path'`. Starlette 1.x (the 0.x → 1.x major jump noted in CLAUDE.md) stores an unflattened `_IncludedRouter` placeholder for `include_router`, so the mounted route is not visible via `.path` at import time.
- **Fix:** Verified registration through `app.openapi()["paths"]` instead, which resolves the router and returned `['/health']`. The intent of the check is unchanged.
- **Files modified:** none (verification command only)
- **Commit:** n/a

### Out of Scope — Logged, Not Fixed

`uv run pre-commit run --all-files` rewrites three files this plan does not own (`backend/migrations/versions/0001_initial_schema.py` via `ruff-format`, `backend/migrations/README` and `.planning/config.json` via `end-of-file-fixer`). Those edits were reverted and recorded in `.planning/phases/01-backend-foundation/deferred-items.md`, along with a suggestion to add `.planning/` to Ruff's `exclude` so the formatter stops rewriting fenced code blocks inside planning documents. The `gitleaks`/detect-secrets hook **passed** — the `brett_local_dev` DSN in the README is triaged the same way `docker-compose.yml` already triages it.

### README Adjustments

The documented run command needed no change to the flag itself — `uv run uvicorn app.main:app --reload --app-dir backend` was executed for real (on port 8123) against a migrated Compose database and returned the documented body. Two clarifications were added beyond the plan's draft: a note that the Alembic commands read `DATABASE_URL` from the environment, and a short statement of the `/health` contract so the endpoint's failure behavior is discoverable without reading the tests.

## Verification Results

| Gate | Result |
|---|---|
| `uv run pytest backend/tests/test_health.py -q` | 3 passed |
| `uv run pytest backend/tests -q` (full phase suite) | 33 passed |
| `uv run pytest backend/tests -q -m "not integration"` | 27 passed, 6 deselected |
| `uv run ruff check .` | clean |
| `uv run mypy backend/app` | clean, 12 source files |
| `uv run pre-commit run --all-files` — gitleaks | passed |
| Manual `curl /health` against Compose db | 200 `{"status":"ok","database":"connected"}` |

## Threat Model Coverage

| Threat ID | Disposition | Evidence |
|---|---|---|
| T-01-23 | mitigated | Body is `{status, database}` only; leak-substring loop in `test_health_reports_db_error` |
| T-01-24 | mitigated | `log.exception` on the server side; the client receives the literal `"error"` |
| T-01-25 | accepted (D-04) | `grep -c Depends health.py` = 0; `test_health_is_open` |
| T-01-26 | mitigated | `make_engine` supplies `pool_pre_ping=True`, `pool_size=5`, `max_overflow=5` |
| T-01-27 | mitigated | Engine created in `lifespan`, `await engine.dispose()` in `finally`; no module-level engine |

## TDD Gate Compliance

RED → GREEN → (no refactor needed) gates all present in the log:

- `21bf51d` `test(01-05)` — 2 of 3 tests failing with 404 before any implementation existed
- `d00a3f3` `feat(01-05)` — 3 of 3 passing

## Commits

| Commit | Message |
|---|---|
| `21bf51d` | test(01-05): add failing health endpoint tests |
| `d00a3f3` | feat(01-05): add GET /health with a live database probe |
| `47b53a6` | docs(01-05): add local dev bootstrap README |

## Self-Check: PASSED

All 9 claimed files exist on disk; all 3 claimed commits exist in `git log`.

## Known Stubs

None. `/health` is fully wired to a live database probe; nothing in this plan returns a hardcoded or placeholder value.

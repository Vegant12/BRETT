---
phase: 01-backend-foundation
plan: 02
subsystem: infra
tags: [structlog, redaction, foundation-05, fastapi, asgi-correlation-id, error-handling, tdd]

# Dependency graph
requires:
  - "01-01: backend/app/config.py -- Settings.secret_values(), get_settings()"
provides:
  - "backend/app/logging.py: configure_logging, censor_keys, make_value_scrubber, add_correlation_id, DENY_KEYS, REDACTED"
  - "backend/app/main.py: app (FastAPI), lifespan, unhandled_exception_handler"
  - "backend/tests/test_secret_redaction.py: FOUND-05 rendered-stream acceptance suite"
  - "httpx2 available as a dev dependency (starlette 1.6 TestClient requires it)"
affects: [01-03-migrations, 01-04-database, 01-05-health, 02-deploy-mcp-spike, 03-hevy-integration]

# Tech tracking
tech-stack:
  added: [httpx2]
  patterns:
    - "Every log record in the process leaves through ONE root handler whose ProcessorFormatter applies both redaction layers, including to third-party stdlib loggers"
    - "make_value_scrubber(settings.secret_values()) is placed strictly after format_exc_info so rendered tracebacks are scrubbed"
    - "add_correlation_id is its own processor; merge_contextvars cannot see asgi-correlation-id's ContextVar"
    - "D-05: one exception handler, no environment branch, no debug=True anywhere"
    - "Security tests assert against the rendered log stream, never structlog's log-capture helper"

key-files:
  created:
    - backend/app/logging.py
    - backend/app/main.py
    - backend/tests/test_secret_redaction.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "Added httpx2==2.12.0 to the dev group -- starlette 1.6's TestClient raises RuntimeError without it; Phase 3 will promote it to a runtime dependency for the Hevy client"
  - "Mutation-verified the three load-bearing constraints rather than trusting the passing suite"
  - "The seeded-secret environment is set at test-module import time because app.main reads config and configures logging at import"
  - "Did not touch .planning/REQUIREMENTS.md -- FOUND-05 was already checked off by plan 01-01 and the file is shared across this parallel wave"

metrics:
  duration: ~22min
  tasks: 3
  files: 5
  commits: 5

requirements-completed: [FOUND-05]
completed: 2026-08-23
---

# Phase 1 Plan 02: Secret-Redaction Logging and Sanitized Error Handling Summary

**A three-layer structlog pipeline that provably strips a seeded secret from every log channel — arbitrary field values, rendered tracebacks, and third-party stdlib loggers — plus a FastAPI bootstrap whose unhandled-exception handler returns only `{error, correlation_id}` in every environment.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3 of 3
- **Files created:** 3 (433 lines)
- **Commits:** 5 (RED/GREEN pairs for Tasks 1 and 2, plus the Task 3 finalization)

## Task Commits

| Task | Gate | Commit | Message |
|------|------|--------|---------|
| 1 | RED | `482241a` | `test(01-02): add failing FOUND-05 log-redaction tests` |
| 1 | GREEN | `d5ffe9c` | `feat(01-02): three-layer secret-redaction logging pipeline` |
| 2 | RED | `50aff73` | `test(01-02): add failing D-05 sanitized-error-handler tests` |
| 2 | GREEN | `09837a9` | `feat(01-02): FastAPI bootstrap with D-05 sanitized exception handler` |
| 3 | — | `0eb8d7c` | `test(01-02): finalize FOUND-05 acceptance suite` |

No REFACTOR commits were needed; both GREEN implementations were lint-, format- and type-clean as written.

## Final `DENY_KEYS` Contents

Unchanged from the plan — 21 entries, matched case-insensitively against the event-dict key:

```
api_key, apikey, hevy_api_key, authorization, auth, password, passwd, secret,
mcp_auth_secret, jwt_secret, token, access_token, refresh_token, database_url,
db_url, dsn, credentials, encrypted_credentials, cookie, set-cookie, x-api-key
```

`REDACTED` is `***REDACTED***`.

Note that the deny-list is layer 2 only — it is the cheap first pass, and the plan's own research already proved it insufficient alone. Adding a key here is never the correct response to a leak; the correct response is to make sure the value reaches `Settings.secret_values()` so layer 3 covers it.

## Verification: Mutation-Tested, Not Just Green

A passing security suite proves nothing unless it fails when the defense is removed. Each of the three load-bearing constraints was individually broken and the suite re-run:

| Mutation applied to `logging.py` | Result |
|---|---|
| Remove `make_value_scrubber(...)` from the shared chain (layer 3 gone) | **7 of 12 tests fail** |
| `foreign_pre_chain=[]` instead of `foreign_pre_chain=shared` | **5 of 12 tests fail** |
| Move layer 3 to *before* `format_exc_info` | **2 of 12 tests fail**, including `test_secret_in_rendered_traceback_is_redacted` |

`logging.py` was restored byte-identically afterwards (`git status` clean before the Task 3 commit). This is the strongest evidence in this plan: the suite is genuinely load-bearing, and a future refactor that quietly breaks any of the three constraints will be caught.

## Additional Leak Channels Found While Testing

**None beyond the four RESEARCH already documented.** Channels (a) value, (b) traceback and (c) third-party loggers are closed here and asserted; channel (d) Pydantic validation errors was closed in plan 01-01 via `hide_input_in_errors=True`.

Two things were checked specifically because of the carry-over note from 01-01 about Pydantic echoing raw input:

1. **The D-05 handler does not render Pydantic validation errors.** It emits a fixed literal body, so there is no path from a `ValidationError` into the HTTP response. FastAPI's own `RequestValidationError` handler is untouched by this plan and returns request-body detail, not settings — a Phase 3 concern once request bodies exist, not a FOUND-05 gap now.
2. **The value scrubber is a genuine backstop, not the only defense.** Config-level `hide_input_in_errors=True` stops the echo at the source; layer 3 would also catch it if it ever regressed, because `str(ValidationError)` passes through `format_exc_info` before the scrubber runs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `starlette` 1.6 `TestClient` refuses to run without `httpx2`**
- **Found during:** Task 2, RED phase
- **Issue:** `from fastapi.testclient import TestClient` raised `RuntimeError: The starlette.testclient module requires the httpx2 package to be installed.` The dependency set from plan 01-01 has no HTTP client, and neither `mcp` (not yet installed) nor `fastapi` pulls one in. Every test in this plan that touches the app object was unrunnable.
- **Fix:** `uv add --dev "httpx2==2.12.0"` — the version CLAUDE.md specifies. Pulled `httpcore2==2.12.0` and `truststore==0.10.4` transitively.
- **Why dev-only:** nothing in `backend/app/` makes an outbound HTTP call yet. Phase 3's Hevy client will move it to the runtime dependency list.
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Committed in:** `50aff73`

**2. [Rule 1 - Bug, in the plan's own test spec] The plan's `X-Request-ID` value is not a valid UUID4**
- **Found during:** Task 3
- **Issue:** The plan specifies `X-Request-ID: 11111111-1111-1111-1111-111111111111`. `asgi-correlation-id`'s default `validator` is `is_valid_uuid4`, and that string has version nibble `1`, not `4`. The middleware would silently reject it and generate a fresh id, so `test_correlation_id_links_body_to_log` would have asserted against a value the client never sent — a test that passes for the wrong reason, or fails confusingly.
- **Fix:** Used `3fa85f64-5717-4562-b3fc-2c963f66afa6` (a well-formed v4) as `REQUEST_ID`.
- **Files modified:** `backend/tests/test_secret_redaction.py`
- **Committed in:** `50aff73`

**3. [Cosmetic] Reworded the Pitfall 6 docstring so the `capture_logs` grep is exact**
- **Issue:** The plan's acceptance criterion is `grep -c 'capture_logs' ... returns 0`, but the module docstring *explaining why not to use it* contained the literal, giving a count of 1.
- **Fix:** Reworded to "``structlog.testing``'s log-capturing context manager". The warning survives; the mechanical check is now unambiguous, so a future real call site cannot hide behind prose.
- **Committed in:** `0eb8d7c`

### Additions Beyond the Plan's Minimum

The plan required three test functions. The file ships **twelve** test cases, because each leak channel deserves its own failure message rather than being buried inside one omnibus test: the three named tests plus per-channel unit tests (`test_denied_key_is_redacted`, `test_secret_inside_non_denied_value_is_redacted`, `test_secret_in_rendered_traceback_is_redacted`, `test_third_party_stdlib_logger_is_redacted` parametrized over `uvicorn.error` / `sqlalchemy.engine` / `alembic`, `test_production_renders_json_without_the_secret`, `test_correlation_id_is_attached_to_every_line`).

## Known Stubs / Carry-Forward

- **`app.main.app` has no database engine in `lifespan`.** This is deliberate and specified by the plan. **Plan 01-05** adds `app.state.engine` / `app.state.sessionmaker` and `include_router(health.router)`. The current `lifespan` logs `service_starting` / `service_stopped` and nothing else, and `app/main.py` contains zero references to `create_async_engine`.
- **`log = structlog.get_logger()` at module scope in `main.py` binds once** (`cache_logger_on_first_use=True`). In production `configure_logging` runs exactly once at import, so this is correct. Anyone writing a future test that calls `configure_logging` with *different* secret values must be aware the cached module-level logger keeps the chain it first bound. The suite here seeds one constant secret, so it is unaffected.
- **`pre-commit install` still not run** (carried from 01-01, deliberate during a parallel wave). All hooks were satisfied manually: `ruff check`, `ruff format --check`, `mypy`.

## Threat Model Coverage

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-01-07 Secret in an arbitrary log field value | mitigate | **Closed** — layer 3; mutation-verified |
| T-01-08 Secret in a rendered traceback | mitigate | **Closed** — layer 3 after `format_exc_info`; mutation-verified by reordering |
| T-01-09 Third-party stdlib loggers bypassing structlog | mitigate | **Closed** — `foreign_pre_chain=shared` + root handler replacement; mutation-verified by emptying it |
| T-01-10 Traceback in the HTTP 500 body | mitigate | **Closed** — fixed body, no env branch, `debug=True` count is 0 |
| T-01-11 Sanitized errors becoming undebuggable | mitigate | **Closed** — `test_correlation_id_links_body_to_log` asserts the same id in the body and the stream |
| T-01-12 A secret never routed through `Settings` | accept | Accepted as planned. Layer 2 covers common key names. Re-evaluate in Phase 3. |

No new threat surface was introduced. `app/main.py` adds one ASGI middleware and one exception handler; it opens no network client, reads no file, and touches no database.

## Verification Results

```
uv run pytest backend/tests -q -m "not integration"     ->  20 passed
uv run pytest backend/tests/test_secret_redaction.py -q ->  12 passed
uv run ruff check backend/app backend/tests             ->  All checks passed!
uv run ruff format --check backend/app backend/tests    ->  7 files already formatted
uv run mypy backend/app                                 ->  Success: no issues found in 4 source files
grep -rn "brett-test-secret" backend --include=*.py | grep -v tests/  ->  no matches
```

Acceptance-criteria greps for all three tasks pass, including the ordering constraint (`format_exc_info` at line 142, `make_value_scrubber(settings.secret_values())` at line 144) and the zero-counts for `basicConfig`, `debug=True`, `__test_boom__` in `main.py`, `create_async_engine`, and `capture_logs`.

## TDD Gate Compliance

Tasks 1 and 2 were both `tdd="true"` and both followed the full gate sequence with the RED failure verified before implementation:

- Task 1 RED `482241a` → failed with `ModuleNotFoundError: No module named 'app.logging'` → GREEN `d5ffe9c`, 8/8 passing.
- Task 2 RED `50aff73` → failed with `ModuleNotFoundError: No module named 'app.main'` (after the `httpx2` blocker was cleared) → GREEN `09837a9`, 12/12 passing.

No test passed unexpectedly during either RED phase.

## Next Plan Readiness

Ready. Contracts published for the rest of the phase:

- **Plan 01-03 / 01-04:** `configure_logging(settings)` is the only place handlers are installed. `alembic` and `sqlalchemy.engine` are already routed through it with redaction, so migration and engine logs are safe by construction — do **not** call `logging.basicConfig` in `migrations/env.py`.
- **Plan 01-05:** import `app` from `app.main` and add the engine to the existing `lifespan` plus `include_router(health.router)`. The exception handler and middleware are already wired; do not re-register them.
- Any new test module that calls `configure_logging` should copy the `_restore_logging` fixture pattern (snapshot root handlers, `structlog.reset_defaults()` on teardown) or it will poison the rest of the session.

## Self-Check: PASSED

All 3 created files verified present on disk; both modified files present; all 5 claimed commit hashes (`482241a`, `d5ffe9c`, `50aff73`, `09837a9`, `0eb8d7c`) verified in `git log`.

---
*Phase: 01-backend-foundation*
*Completed: 2026-08-23*

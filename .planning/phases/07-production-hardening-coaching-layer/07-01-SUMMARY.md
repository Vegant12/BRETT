---
phase: 07-production-hardening-coaching-layer
plan: 01
subsystem: infra
tags: [rate-limiting, asgi, starlette, middleware, token-bucket, pydantic-settings, cloud-run]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "Settings/_SECRET_FIELDS three-layer secret defense, structlog `log = structlog.get_logger()` convention, the degrade-without-leaking pattern in health.py"
  - phase: 02-deploy-connector-auth-spike
    provides: "deploy/cloud-run.env.yaml, the bidirectional env<->Settings drift guard in test_cloud_run_deploy.py, build_token_verifier(settings) factory convention"
provides:
  - "TokenBucket: fixed-capacity, constant-refill bucket with an injected clock"
  - "RateLimitMiddleware: pure-ASGI 429 gate that runs outside the router and therefore ahead of MCP auth"
  - "build_limiter(settings) -> TokenBucket factory"
  - "EXEMPT_PREFIXES: the /health and /.well-known/ carve-outs (T-07-04)"
  - "Settings.rate_limit_per_minute / Settings.rate_limit_burst, plus their RATE_LIMIT_* keys in deploy/cloud-run.env.yaml"
  - "The container-free half of backend/tests/test_rate_limit.py (7 fast tests)"
affects: [07-05-rate-limit-wire-contract, mcp-server, deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-ASGI middleware (raw send, no response class) so the /mcp SSE stream is never buffered"
    - "Clock injection as the seam for time-dependent components, mirroring HevyClient(sleep=...)"
    - "Static source-read tests that pin a negative-space security property (module must NOT mention X)"

key-files:
  created:
    - backend/app/middleware.py
    - backend/tests/test_rate_limit.py
  modified:
    - backend/app/config.py
    - deploy/cloud-run.env.yaml
    - backend/tests/test_config.py

key-decisions:
  - "One global process-wide bucket, not per-IP: the service is --allow-unauthenticated so any forwarded-address header is attacker-controlled, and all legitimate traffic comes from one Anthropic /21 anyway"
  - "Per-instance bucket accepted (T-07-06): with --max=2 the service-wide ceiling is up to 2x the configured rate; Redis would double the failure surface of the control meant to prevent cost"
  - "Rate-limit settings kept out of _SECRET_FIELDS: they are operational numbers that must stay readable in logs"
  - "No development bypass in build_limiter -- a limiter that is off in development is a limiter nobody has ever seen fire"
  - "Where the plan's mandated prose contradicted its own enforceable greps, the greps won and the prose was rephrased"

patterns-established:
  - "Negative-space guard: a test reads a module's own source and asserts a forbidden identifier is absent, docstrings included; prose must then describe such names rather than spell them"
  - "Distinct fixture values (60 vs 30) in factory-mapping tests so a swapped field mapping cannot pass"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 8min
completed: 2026-09-01
---

# Phase 7 Plan 01: Rate Limiter Mechanism Summary

**Pure-ASGI token-bucket rate limiter with an injected clock, wired to two new `RATE_LIMIT_*` settings and covered by seven container-free tests that pin both its arithmetic and its no-header-parsing mitigation.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-09-01T08:03:18Z
- **Completed:** 2026-09-01T08:11:00Z
- **Tasks:** 3
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- `backend/app/middleware.py` (162 lines): `TokenBucket`, `RateLimitMiddleware`, `build_limiter`, `EXEMPT_PREFIXES`. Emits its 429 through raw ASGI `send` with a module-level literal body, so no response class is imported and the `/mcp` `text/event-stream` response is never materialised.
- The limiter reads no request header at all. That is the mitigation for T-07-01, and it is now enforced by a static source read rather than by reviewer discipline.
- `Settings.rate_limit_per_minute` / `rate_limit_burst` (default 30) added outside `_SECRET_FIELDS`, with matching quoted `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_BURST` keys in `deploy/cloud-run.env.yaml`. The bidirectional drift guard in `test_cloud_run_deploy.py` passes in both directions, and neither key matches `_SECRET_NAME_MARKERS`.
- Seven fast tests, no marker, no sleep of any kind: capacity, refill rate, the refill clamp after an idle hour, the reported `Retry-After` wait, factory geometry, the header guard, and the exact exemption tuple.
- Full fast suite: 384 passed, 274 deselected. `ruff check .` clean, `mypy backend/app` clean across 64 files.

## Task Commits

1. **Task 1: Rate-limit Settings fields, env-file keys, test-env cleanup** — `682600e` (feat)
2. **Task 2: `backend/app/middleware.py` pure-ASGI token bucket** — `413a4b4` (feat)
3. **Task 3: Container-free half of `backend/tests/test_rate_limit.py`** — `8c6e9c1` (test)

## Files Created/Modified

- `backend/app/middleware.py` — the limiter: bucket arithmetic, the ASGI 429 gate, the settings factory, and the exemption list
- `backend/tests/test_rate_limit.py` — the fast half: bucket arithmetic under a hand-advanced clock plus the T-07-01 static guard
- `backend/app/config.py` — two integer `Settings` fields, deliberately not secrets
- `deploy/cloud-run.env.yaml` — `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_BURST` as quoted strings, so the numbers are retunable by redeploy rather than by commit
- `backend/tests/test_config.py` — `_clean_env` now clears both new vars, so a developer's exported value cannot decide a test

## Decisions Made

- **Prose loses to enforceable checks.** The plan mandated a module docstring containing the literal strings `BaseHTTPMiddleware` and `X-Forwarded-For`, and a test docstring containing `asyncio.sleep` and `@pytest.mark.integration` — while four of its own acceptance greps, plus the T-07-01 static test it also mandated, require exactly those strings to be absent from those files. The greps and the test are the enforceable artifacts and are part of the threat register, so the prose was rephrased to carry identical meaning without the literal tokens, and each rewritten passage now states why the name is described rather than written.
- **`test_build_limiter_maps_settings_to_bucket_geometry` reads two private attributes.** Those two numbers are the factory's entire responsibility, and a purely behavioural check would pass for a bucket built from the wrong field pair whenever the values coincided. The fixture deliberately uses 60 and 30 so a swapped mapping fails.
- **Settings built from environment variables, not constructor kwargs,** in the factory test — mirroring `test_mcp_auth.py`, because `deploy/cloud-run.env.yaml` is how the deployed service is actually configured.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan's mandated middleware docstring contradicted its own acceptance criteria**
- **Found during:** Task 2 (write `backend/app/middleware.py`)
- **Issue:** The verbatim docstring in `<action>` contains `BaseHTTPMiddleware` (twice) and `X-Forwarded-For`. Task 2's acceptance criteria require `grep -c "BaseHTTPMiddleware\|JSONResponse\|starlette.responses"` to return `0` and `grep -ci "x-forwarded-for"` to return `0`, and Task 3's `test_the_limiter_reads_no_client_supplied_header` — the T-07-01 mitigation — asserts `"x-forwarded-for"` and `"basehttpmiddleware"` appear nowhere in the lowered module source. Written as specified, the module would have failed its own security guard on the commit that introduced it.
- **Fix:** Rephrased the two passages to describe the response-materialising base class and the forwarded-client-address header rather than name them, preserving every claim (pure ASGI, SSE buffering hazard, attacker-controlled header, `160.79.104.0/21` egress). Added a closing paragraph naming the guard and explaining why the two names are spelled around, so a future reader does not "helpfully" restore them.
- **Files modified:** `backend/app/middleware.py`
- **Verification:** All three negative greps return `0`; all five positive greps match; `ruff check`, `ruff format --check` and `mypy` clean; the T-07-01 test passes.
- **Committed in:** `413a4b4` (Task 2 commit)

**2. [Rule 3 - Blocking] Same contradiction in the mandated test-module docstring**
- **Found during:** Task 3 (write `backend/tests/test_rate_limit.py`)
- **Issue:** The verbatim docstring contains `@pytest.mark.integration` and `asyncio.sleep`, while Task 3's acceptance criteria require `grep -c "asyncio.sleep\|time.sleep"` and `grep -c "pytest.mark.integration"` to both return `0`. Confirmed empirically: as written, both greps returned `1`.
- **Fix:** "marked `integration`" instead of the decorator spelling, and a plain-English no-sleeping rule instead of the named call, plus a sentence recording that both are grep-enforced so the literals are not reintroduced.
- **Files modified:** `backend/tests/test_rate_limit.py`
- **Verification:** Both greps now return `0`; 7 tests pass; `-k refill` selects 2; `ruff check` and `ruff format --check` clean.
- **Committed in:** `8c6e9c1` (Task 3 commit)

**3. [Rule 3 - Blocking] Stray non-ASCII characters in a docstring**
- **Found during:** Task 3
- **Issue:** A Cyrillic-mixed word ("refилled") was introduced while drafting, which would have been an invisible defect in a file whose whole purpose is exact string matching.
- **Fix:** Corrected, then verified with a repo-wide `LC_ALL=C` non-ASCII scan of the file.
- **Files modified:** `backend/tests/test_rate_limit.py`
- **Verification:** `LC_ALL=C grep -n '[^ -~]'` returns nothing.
- **Committed in:** `8c6e9c1` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (3 blocking)
**Impact on plan:** No scope change. All three fixes were required to make the plan's own acceptance criteria and its T-07-01 threat mitigation simultaneously satisfiable. Every interface in `<interfaces>` is delivered exactly as specified — plan 07-05 can import `TokenBucket`, `RateLimitMiddleware`, `build_limiter` and `EXEMPT_PREFIXES` unchanged.

## Issues Encountered

- The worktree branch was created from an older base (`1e97f3b`) rather than the phase HEAD, so `.planning/phases/07-.../` did not contain the phase-07 plans. Hard-reset to `b3a278c` per the startup check before any work began.
- `07-PATTERNS.md`, referenced in the plan's `<context>`, does not exist in the repository (it was untracked at the time the worktree was cut). Execution did not depend on it; every convention the plan cites was read directly from the source files named in `<read_first>`.

## TDD Gate Compliance

Tasks 2 and 3 carry `tdd="true"`, but the plan assigns the module to Task 2 and its tests to Task 3 via each task's `<files>` list, which inverts the RED/GREEN order. The `<files>` constraint was treated as authoritative — writing a failing test during Task 2 would have put test code in a file the plan reserves for Task 3, and Task 2's acceptance criteria are lint/type-only with no test invocation. Result: `feat` (`413a4b4`) precedes `test` (`8c6e9c1`) rather than the reverse. The tests were not written to fit the implementation — they encode the `<behavior>` block verbatim, including the T-07-01 guard, and one of them (the header guard) forced a change to the already-committed module's prose.

## Known Stubs

None. Nothing in this plan renders to a UI or returns placeholder data. `RateLimitMiddleware` is intentionally not yet registered in `app/main.py` and `app.state.rate_limit_bucket` is intentionally not yet published — plan 07-05 owns that wiring and the over-HTTP contract tests, as stated in this plan's objective.

## User Setup Required

None — no external service configuration required. The two new environment variables have working defaults in code and explicit values in `deploy/cloud-run.env.yaml`; they take effect on the next deploy with no console step.

## Next Phase Readiness

- Plan 07-05 can proceed: it registers `RateLimitMiddleware` via `app.add_middleware`, publishes the bucket at `app.state.rate_limit_bucket` (the `_bucket()` lookup already reads it and falls back safely when absent), and appends the `integration`-marked over-HTTP half to `backend/tests/test_rate_limit.py`.
- Deferred to 07-05 by design: the 429 status and exact-key-set assertion (T-07-02), the `Retry-After` header value on the wire, the two path exemptions proven through real HTTP (T-07-04), and the proof that the limiter fires before MCP auth.
- No blockers.

## Self-Check: PASSED

- Files verified present: `backend/app/middleware.py`, `backend/tests/test_rate_limit.py`, `backend/app/config.py`, `deploy/cloud-run.env.yaml`, `backend/tests/test_config.py`, this summary.
- Commits verified in `git log`: `682600e`, `413a4b4`, `8c6e9c1`.
- Plan verification block re-run at completion: fast suite 384 passed / 274 deselected; `ruff check .` clean; `mypy backend/app` clean (64 files); `test_cloud_run_deploy.py` drift guard green with the two new keys.

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

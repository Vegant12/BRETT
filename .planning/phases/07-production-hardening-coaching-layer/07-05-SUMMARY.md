---
phase: 07-production-hardening-coaching-layer
plan: 05
subsystem: infra
tags: [rate-limiting, asgi, starlette, middleware, fastapi, mcp, integration-tests, testcontainers]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-01's TokenBucket, RateLimitMiddleware, build_limiter and EXEMPT_PREFIXES, plus the fast half of backend/tests/test_rate_limit.py"
  - phase: 02-deploy-connector-auth-spike
    provides: "app.mount('/', mcp_app) at the FastAPI root, the RFC 9728 discovery document, the 401 + resource_metadata wire contract, and the conftest client/TestClient fixture"
  - phase: 01-backend-foundation
    provides: "CorrelationIdMiddleware registration site, /health, and the D-05 sanitized-500 exception handler"
provides:
  - "RateLimitMiddleware registered on the FastAPI app, outside the router and ahead of the MCP SDK's own auth chain"
  - "app.state.rate_limit_bucket: the single live bucket object, replaceable per test"
  - "The integration half of backend/tests/test_rate_limit.py (7 tests) pinning the 429 wire contract"
  - "All six 07-VALIDATION.md selectors for ROADMAP criterion #2 now select passing tests"
affects: [07-10-uat, deployment, mcp-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "App-level middleware registered ABOVE CorrelationIdMiddleware in source order, so add_middleware's prepend gives the limiter a correlation id while still running outside the router"
    - "A replaceable singleton published on app.state, swapped in tests through monkeypatch so pytest owns the restore"
    - "Exemption tests run against a DRAINED bucket -- the only condition under which the carve-out can fail"

key-files:
  created: []
  modified:
    - backend/app/main.py
    - backend/tests/test_rate_limit.py

key-decisions:
  - "The limiter is registered before CorrelationIdMiddleware in source order, so the correlation id is set first and rate_limit_rejected joins the same correlation trail as every other line"
  - "app.state.rate_limit_bucket is swapped via monkeypatch, not bare assignment: conftest.client hands every test the same process-global app object, so an unrestored drained bucket would 429 the rest of the session"
  - "test_over_limit_request_is_rejected_with_429 asserts the first two requests are 200 as well, so a middleware that rejects everything cannot pass"
  - "test_the_429_leaks_nothing fires twice -- good credential then a distinctive bad one -- because credential-echo is only detectable when the credential is a string nothing else emits"
  - "Where the plan's mandated prose contradicted its own enforceable greps, the greps won (same call plan 07-01 made)"

patterns-established:
  - "Negative-space guard extended to app/main.py: the response-materialising middleware base class is described, never spelled, because T-07-26's grep cannot tell a warning from a use"
  - "RED verification for a wiring task: temporarily unregister the middleware, confirm the new tests fail, restore -- a genuine RED signal even when the implementation task shipped first"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-09-01
---

# Phase 7 Plan 05: Rate Limit Wire Contract Summary

**The token-bucket limiter is now live on the FastAPI app — registered outside the router and ahead of the MCP SDK's auth chain — with seven integration tests pinning the 429's status, its one-key body, its `Retry-After`, both path exemptions under a drained bucket, and the proof that an unauthenticated flood is 429'd rather than 401'd.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-09-01T08:21:09Z
- **Completed:** 2026-09-01T08:33:20Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `backend/app/main.py` now publishes `app.state.rate_limit_bucket = build_limiter(settings)` and registers `RateLimitMiddleware` against it. Because `add_middleware` prepends, placing the limiter ABOVE the correlation-id line means the correlation id is set first, so the `rate_limit_rejected` log line carries the same `correlation_id` as everything else for that request — while the limiter still runs outside the router and therefore ahead of `app.mount("/", mcp_app)` and the SDK's `RequireAuthMiddleware`.
- Seven `integration`-marked tests appended to `backend/tests/test_rate_limit.py`, driving the real `/mcp` endpoint over HTTP. The module is now 14 tests (7 fast + 7 integration).
- **T-07-02:** the 429 body's key set is asserted to be exactly `{"error"}`, and the same request is repeated with a deliberately distinctive bad credential to prove the rejection does not echo what the caller presented.
- **T-07-24:** an unauthenticated `POST /mcp` against a drained bucket returns 429. The RED check below confirmed it returns **401** when the registration is removed, which is exactly the failure this test exists to catch.
- **T-07-04:** `/health` and `/.well-known/oauth-protected-resource/mcp` both answer 200 *with the bucket fully drained* — the only condition under which those carve-outs can fail.
- **T-07-25:** one authenticated `tools/list` against the DEFAULT bucket still returns 200 and reaches the tool surface, so a mistuned default that throttles a normal coaching turn fails the suite.
- **T-07-26:** the `/mcp` `text/event-stream` responses are driven through real HTTP in every test above; a response-buffering middleware regression would hang or truncate them. `grep -c "BaseHTTPMiddleware" backend/app/main.py` returns `0`.
- Full suite: **683 passed** (was 676 before this plan). `ruff check .` clean, `mypy backend/app` clean across 64 files. `test_mcp_auth.py` fully green (23/23) — the 401 envelope and its `resource_metadata=` are unchanged by the limiter.

## Task Commits

1. **Task 1: Register RateLimitMiddleware in `backend/app/main.py`** — `103838d` (feat)
2. **Task 2: Append the over-HTTP half to `backend/tests/test_rate_limit.py`** — `e2f0fda` (test)

## Files Created/Modified

- `backend/app/main.py` — the import, the published bucket, the registration, and the comment block explaining why the order is load-bearing in both directions
- `backend/tests/test_rate_limit.py` — the duplicated 2026-07-28 wire envelope, the `_install_frozen_bucket` / `_drain` seam, and the seven integration tests

## Decisions Made

- **`monkeypatch`, not bare assignment, for the bucket swap.** `conftest.client` does `from app.main import app`, and Python's module cache hands every test in the session the *same* object — so `app.state.rate_limit_bucket` is process-global state, not per-test state. An unrestored drained bucket would have 429'd every later `client`-using test in the run, for a reason nothing in those tests explains. `monkeypatch` restores the true previous value in its own teardown, which is the `finally` `test_mcp_mount.py::mcp_server` writes by hand for `app.state.sessionmaker`. It also raises when the attribute is missing, so a `main.py` that stopped publishing the bucket fails loudly instead of silently exercising the middleware's constructor fallback and passing.
- **`test_over_limit_request_is_rejected_with_429` asserts the first two responses are 200.** A middleware that rejected *everything* — a mis-scoped exemption check, an inverted `take()` test — satisfies a third-request-only assertion perfectly while taking the connector down completely.
- **`test_the_429_leaks_nothing` fires twice.** The plan's `<behavior>` block requires "the bad token" in the leak set while its `<action>` code block sends the good credential. Both are satisfied by making the assertion twice: once with `AUTH` exactly as the action block specifies (so only the drained bucket explains the 429), then once with a distinctive `BAD_TOKEN`. The limiter runs ahead of auth so both bodies are the same body — which is precisely why the second call is worth making, since "does the rejection echo the presented credential?" is only answerable when the credential is a string no other code path would produce.
- **`Retry-After` is parsed, not merely asserted present.** RFC 9110 also permits an HTTP-date form here, and a header in that form is a header this client cannot act on.
- **Exemption tests run against a drained bucket.** A test against a healthy bucket cannot distinguish an exemption that works from one that was never written.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `backend/app/main.py` already contained the literal `BaseHTTPMiddleware`, which Task 1's own acceptance criterion forbids**

- **Found during:** Task 1 (register the middleware)
- **Issue:** Task 1's acceptance criteria require `grep -c "BaseHTTPMiddleware" backend/app/main.py` to return `0`, and the threat register names that grep as the enforcement mechanism for T-07-26. But the pre-existing comment above `app.add_middleware(CorrelationIdMiddleware)` reads "Pure-ASGI middleware, not BaseHTTPMiddleware -- …", and the plan's `<action>` block reproduces that comment verbatim while instructing "extending (not replacing)" it and "Change nothing else." Written as specified, the file would have failed its own acceptance criterion. This is the same class of contradiction plan 07-01 hit twice and resolved the same way.
- **Fix:** Rephrased the pre-existing comment to describe the response-materialising middleware base class rather than name it, preserving every claim (pure ASGI, the ContextVar must stay readable in the exception handler) and adding the reason it now runs the downstream app in a separate task. The comment states explicitly that the name is spelled around because a crude grep guards T-07-26 and cannot tell a warning from a use, and points at `app/middleware.py` doing the same — so a future reader does not "helpfully" restore it. Verified no test reads `main.py`'s source and no other file in the repo referenced the identifier.
- **Files modified:** `backend/app/main.py`
- **Verification:** `grep -c "BaseHTTPMiddleware" backend/app/main.py` returns `0`; all three positive greps return `1`; the `awk` order check exits `0`; `ruff check`, `ruff format --check` and `mypy` clean; `test_health.py` + `test_mcp_mount.py` 12/12 green.
- **Committed in:** `103838d` (Task 1 commit)

**2. [Rule 1 - Bug] The test module's docstring asserted something that this plan makes false**

- **Found during:** Task 2 (append the integration half)
- **Issue:** Plan 07-01 closed `test_rate_limit.py`'s docstring with "…which is why neither the sleeping call nor the integration marker is spelled out literally anywhere in this module." Task 2 requires `@pytest.mark.integration` on all seven appended tests, so that sentence became untrue on the same commit that added them — a docstring stating a false invariant is worse than no docstring, because the next reader trusts it.
- **Fix:** Split the claim in two. The no-sleeping rule is still grep-enforced by both plans and is restated as still binding; the marker constraint is recorded as belonging to the era when the file held only the fast half, and explicitly spent now that the appended half carries the marker.
- **Files modified:** `backend/tests/test_rate_limit.py`
- **Verification:** `grep -c "asyncio.sleep\|time.sleep"` still returns `0`; 14/14 tests pass.
- **Committed in:** `e2f0fda` (Task 2 commit)

**3. [Rule 2 - Missing Critical] The drained bucket had to be restored, which the plan left conditional**

- **Found during:** Task 2
- **Issue:** The plan's `<action>` states restore "is unnecessary — the `client` fixture builds a fresh `TestClient` per test and `app.state.rate_limit_bucket` is reassigned at each import-time app construction", with a conditional instruction to restore "if the executor finds the `app` object is shared across tests." It is shared: `conftest.client` does `from app.main import app` and the module is imported once per session, so the import-time assignment happens exactly once and every `TestClient` wraps the same object. Without a restore, the first drained bucket would have leaked into every subsequent `client`-using test.
- **Fix:** `_install_frozen_bucket` performs the swap through `monkeypatch.setattr`, so pytest restores the true previous value at teardown. `_drain` therefore takes a `monkeypatch: pytest.MonkeyPatch` parameter in addition to the plan's `client` and `capacity` — the only signature change, and one the plan's conditional anticipated. All seven tests still take the `client: TestClient` fixture as specified.
- **Files modified:** `backend/tests/test_rate_limit.py`
- **Verification:** Full suite green at 683 passed with the rate-limit module in place; `test_an_authenticated_request_under_the_limit_still_succeeds` runs after four bucket-draining tests in file order and still returns 200, which is the direct proof the restore works.
- **Committed in:** `e2f0fda` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 blocking, 1 bug, 1 missing critical)
**Impact on plan:** No scope change. Deviation 1 was required to make Task 1's acceptance criteria and the T-07-26 mitigation simultaneously satisfiable; deviations 2 and 3 were required for the test module to be truthful and non-contaminating. Every artifact and key_link in the plan's `must_haves` is delivered as specified.

## Issues Encountered

- **The worktree branch was cut from a stale base again.** `git merge-base HEAD c57dd34` returned `1e97f3b` — a mid-Phase-2 commit, the same stale base plan 07-01 reported. Hard-reset to `c57dd34` per the mandatory startup check before any work began. This is now the second consecutive occurrence in this phase and should be treated as a worktree-creation defect rather than a coincidence.
- **`uv run ruff format --check .` reports 95 files "would be reformatted".** All of them are `.planning/**/*.md` files whose fenced Python blocks ruff formats; no `.py` file in `backend/` is affected, and both files this plan touched are format-clean. Out of scope (the plan's verification block specifies `ruff check .`, not `ruff format --check .`), pre-existing, and deliberately not fixed — it would touch ~95 planning documents that sibling wave-2 agents may also be editing.
- **`test_the_limiter_runs_before_auth` needed the RED check to be trustworthy.** With the registration removed the endpoint answers `401`, not `429` — confirming the test really distinguishes "limiter ahead of auth" from "auth ahead of limiter" rather than passing for an unrelated reason.

## TDD Gate Compliance

Task 2 carries `tdd="true"`, but its implementation dependency (Task 1's three lines in `main.py`) is a separate task in the same plan and is sequenced first by the plan's own task order and `<files>` lists. Writing the tests during Task 1 would have put test code in a file Task 1 does not own. Result: `feat` (`103838d`) precedes `test` (`e2f0fda`), inverting the strict RED→GREEN commit order — the same structural inversion plan 07-01 recorded.

A genuine RED signal was obtained instead of assumed: after the tests were written and green, `app.add_middleware(RateLimitMiddleware, …)` was temporarily removed from `main.py` and the module re-run. Four of the seven integration tests failed (`over_limit`, `leaks_nothing`, `retry_after`, `before_auth`) and `main.py` was restored with `git checkout -- backend/app/main.py`. The three that still passed are the two exemption tests and the under-limit test, which is correct and expected: with no limiter at all, `/health`, the discovery document and an authenticated call all return 200 for the trivial reason. Those three are proven by the *drained-bucket* condition rather than by RED, which is why the plan specifies that condition for them.

Gate summary: RED verified experimentally rather than by commit order; GREEN commit present; no REFACTOR commit needed.

## Known Stubs

None. Nothing in this plan renders to a UI or returns placeholder data. The limiter is fully wired and enforcing on the real endpoint.

## Threat Flags

None. This plan added no network endpoint, auth path, file access or schema change — it registered existing middleware and added tests. The 429 body is a new public output channel, but it was introduced by plan 07-01 and is already in the register as T-07-02, which this plan mitigates rather than expands.

## User Setup Required

None — no external service configuration required. `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_BURST` already have working code defaults and explicit values in `deploy/cloud-run.env.yaml` from plan 07-01; the limiter takes effect on the next deploy with no console step.

## Next Phase Readiness

- ROADMAP Phase 7 success criterion #2 is now provable end-to-end: rate limiting is applied ahead of handler work, and unauthenticated and over-limit requests are rejected without leaking detail.
- All six `07-VALIDATION.md` selectors for criterion #2 (`over_limit`, `leaks_nothing`, `retry_after`, `before_auth`, `health`, `discovery`) select passing tests. The validation matrix rows can be flipped to ✅ by whoever owns that document.
- **Deferred to plan 07-10 (UAT) by design:** the real per-turn MCP call count against the shipped 30-burst / 30-per-minute geometry. `test_an_authenticated_request_under_the_limit_still_succeeds` proves one call is not throttled; only live use can prove a whole coaching turn is not. Any 429 observed during UAT is a tuning bug, not a limiter bug — the fix is a value change in `deploy/cloud-run.env.yaml` and a redeploy, never a code change.
- **Carried forward from 07-01, unchanged:** the per-instance bucket means the service-wide ceiling is up to `--max` times the configured rate (T-07-06, accepted deliberately).
- `DEPLOY-03` is deliberately NOT marked complete in `REQUIREMENTS.md` — sibling plans elsewhere in this phase still claim it.
- No blockers.

## Self-Check: PASSED

- Files verified present: `backend/app/main.py`, `backend/tests/test_rate_limit.py`, this summary.
- Commits verified in `git log`: `103838d`, `e2f0fda`. No file deletions in either (`git diff --diff-filter=D HEAD~1 HEAD` empty for both).
- Plan verification block re-run at completion: `test_rate_limit.py` 14 passed; `test_mcp_auth.py` 23 passed; `test_cloud_run_deploy.py` 13 passed; full suite 683 passed; `ruff check .` clean; `mypy backend/app` clean (64 files).
- All Task 1 and Task 2 acceptance greps re-run and matching: `1 / 1 / 1 / 0` for Task 1, `0 / 1 / 3 / 0` for Task 2, and the `awk` registration-order check exits `0`.

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

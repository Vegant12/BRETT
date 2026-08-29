---
phase: 03-hevy-integration-normalization
plan: 01
subsystem: infra
tags: [uv, packaging, tenacity, httpx2, pytest-httpx2, structlog, redaction, test-fixtures, hevy]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "backend/app/logging.py three-layer redaction pipeline (DENY_KEYS, value scrubber) and backend/tests/conftest.py fixture conventions"
  - phase: 02-deploy-connector-auth-spike
    provides: "`[tool.uv] default-groups = []` and the Cloud Run buildpack's bare `uv sync` build contract that makes dependency-group placement load-bearing"
provides:
  - "tenacity 9.1.4 and httpx2 2.12.0 as PRODUCTION dependencies, so HevyClient's runtime imports exist in the Cloud Run image"
  - "pytest-httpx2 1.0.0 in the dev group, with its transitive respx/httpx-0.x confirmed excluded from the production export"
  - "`api-key` (Hevy's literal header spelling) on the Layer-2 log deny-list"
  - "Five schema-accurate canned Hevy responses under backend/tests/fixtures/hevy/"
  - "`hevy_fixture(name)` loader in conftest.py plus the recorded Pitfall-3 httpx/httpx2 mocking rule"
  - "test_hevy_fixtures.py — a fast-suite guard against fixture schema drift"
affects: [03-05 HevyClient, 03-06 sync service, 03-09 events drain, 03-10 resilience tests, 03-11 body measurements, 03-04 templates]

# Tech tracking
tech-stack:
  added: [tenacity==9.1.4, pytest-httpx2==1.0.0]
  patterns:
    - "Runtime-vs-dev dependency placement is a security/availability control under `default-groups = []`, verified with `uv export`, not by inspection"
    - "Canned provider responses live on disk as JSON and are loaded through a single documented helper, never inlined per test"
    - "A redaction test must isolate the layer it names — assert with a value the other layers cannot see"

key-files:
  created:
    - backend/tests/fixtures/hevy/workouts_page1.json
    - backend/tests/fixtures/hevy/workouts_page2.json
    - backend/tests/fixtures/hevy/workout_events_page1.json
    - backend/tests/fixtures/hevy/exercise_templates_page1.json
    - backend/tests/fixtures/hevy/body_measurements_page1.json
    - backend/tests/test_hevy_fixtures.py
    - .planning/phases/03-hevy-integration-normalization/deferred-items.md
  modified:
    - pyproject.toml
    - uv.lock
    - backend/app/logging.py
    - backend/tests/conftest.py
    - backend/tests/test_secret_redaction.py

key-decisions:
  - "httpx2 moved from the dev group to [project].dependencies — under `default-groups = []` a runtime import in a dev-only package is a production-only ImportError that is invisible locally (T-03-02)"
  - "Accepted respx + httpx 0.28.1 into uv.lock as dev-only transitives of pytest-httpx2, rather than hand-rolling httpx2.MockTransport; `uv export` proves they do not reach the production image"
  - "Added a second, Layer-3-isolated redaction test because the plan's specified test passes with or without the DENY_KEYS change and therefore could not guard T-03-01"
  - "Did NOT check off HEVY-08 in REQUIREMENTS.md: this plan lands only its prerequisites and four later plans (03-04, 03-05, 03-06, 03-10) also claim it"

patterns-established:
  - "Pattern: dependency-group placement verified by `uv export --no-emit-project`, which resolves exactly what a bare `uv sync` installs — the only check that catches dev/runtime misplacement before deploy"
  - "Pattern: fixtures transcribed from the LIVE provider OpenAPI doc and guarded by a shape test, so downstream tests cannot silently drift onto a schema the provider does not serve"
  - "Pattern: security-layer tests use a value the adjacent layers have never seen, so each layer's test fails independently"

requirements-completed: [HEVY-08]

# Metrics
duration: 8min
completed: 2026-08-29
---

# Phase 3 Plan 1: Hevy Prerequisites & Log Deny-List Gap Summary

**Moved httpx2 into runtime dependencies and added tenacity 9.1.4 (closing a production-only ImportError), put Hevy's literal `api-key` header on the structlog deny-list, and committed five OpenAPI-accurate Hevy response fixtures behind a `hevy_fixture()` loader and a drift guard.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-29T06:20:11Z
- **Completed:** 2026-08-29T06:27:59Z
- **Tasks:** 3 of 3
- **Files modified:** 12 (7 created, 5 modified)

## Accomplishments

- **Closed the production-only packaging failure (T-03-02).** `httpx2` was in `[dependency-groups].dev` while `HevyClient` imports it at runtime. Because `[tool.uv] default-groups = []`, the Cloud Run buildpack's bare `uv sync` would have built an image without it — and local dev (`uv sync --group dev`) would never reveal it. `uv export --no-emit-project` now resolves `httpx2==2.12.0` and `tenacity==9.1.4` into the production set and contains no `respx`, `pytest*`, or `httpx` 0.x.
- **Restored defence-in-depth on the log pipeline (T-03-01).** `DENY_KEYS` covered `api_key`, `apikey` and `x-api-key` but not `api-key` — the exact lowercase-hyphen spelling Hevy's live OpenAPI requires and the one this project will send on every request.
- **Gave the rest of Phase 3 its test data.** Five fixtures transcribed from the live OpenAPI document (parsed 2026-08-29), deliberately preserving the awkward realities: events ordered newest-first, no ids on exercises or sets, no `rir`, no `weight_unit`, and a UUID-form custom template whose muscle groups map to nothing canonical (the D-03 unmapped path).
- **Recorded the Pitfall-3 mocking rule where it will actually be read** — in `conftest.py`, next to the loader, rather than in a research document nobody consults mid-debug.

## Task Commits

1. **Task 1: Move httpx2 to runtime deps, add tenacity and pytest-httpx2** — `1927c7c` (chore)
2. **Task 2: Add `api-key` to the log deny-list and assert it** — `7a28a1c` (test, RED) → `3e67a3a` (feat, GREEN)
3. **Task 3: Commit canned Hevy fixtures and a conftest loader** — `f9938a4` (test)

Supporting: `d870e2e` (docs — deferred-items log)

_Task 2 was `tdd="true"`; RED and GREEN are separate commits. No REFACTOR commit — the change is a four-line addition with nothing to clean up._

## Files Created/Modified

- `pyproject.toml` — `httpx2==2.12.0` + `tenacity==9.1.4` moved/added to `[project].dependencies` with a comment explaining the invisible-failure mode; `pytest-httpx2==1.0.0` added to dev; `httpx2` removed from dev; mypy overrides extended with `pytest_httpx2.*` and `respx.*`
- `uv.lock` — regenerated by uv (never hand-edited, T-03-03); gains tenacity, pytest-httpx2 and the dev-only respx/httpx/httpcore/h11/certifi chain
- `backend/app/logging.py` — `"api-key"` added to `DENY_KEYS` with a comment naming Pitfall 9
- `backend/tests/test_secret_redaction.py` — two new tests plus the `UNSEEDED_KEY` constant
- `backend/tests/conftest.py` — `HEVY_FIXTURE_DIR`, `hevy_fixture()`, and the Pitfall-3 httpx/httpx2 block comment; `json` and `typing.Any` imports
- `backend/tests/test_hevy_fixtures.py` — five shape assertions guarding the fixtures against drift
- `backend/tests/fixtures/hevy/*.json` — five canned responses (workouts pages 1–2, workout events, exercise templates, body measurements)
- `.planning/phases/03-hevy-integration-normalization/deferred-items.md` — one out-of-scope finding

## Decisions Made

- **httpx2 to runtime, not a second HTTP client.** The alternative (keep httpx2 in dev, add something else at runtime) would ship two HTTP clients. `mcp==2.0.0` already requires httpx2, so it is in the tree regardless.
- **Accepted httpx 0.x into the lockfile.** `pytest-httpx2` pulls `respx` → `httpx` 0.28.1. RESEARCH offered `httpx2.MockTransport` as a zero-dependency alternative. Chose the plugin: `default-groups = []` provably keeps the chain out of production (verified by `uv export`, not assumed), and hand-rolled request recording across paginated sequences is exactly the kind of test infrastructure that rots.
- **Left HEVY-08 unchecked in REQUIREMENTS.md.** HEVY-08 is "a sync failure does not corrupt previously-synced data." This plan lands the retry library it will depend on; plans 03-05, 03-06 and 03-10 deliver the actual behaviour. Checking it off here would be false, and would also contend on REQUIREMENTS.md with sibling wave agents. `requirements-completed` in this frontmatter records the plan's claim verbatim, as the template requires.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] The plan's specified Layer-2 redaction test could not fail**

- **Found during:** Task 2 (TDD RED gate)
- **Issue:** The plan specified `test_hevy_header_key_name_is_redacted`, which logs `SEEDED` under the key `api-key` and asserts the value is absent. But `SEEDED` is seeded into `HEVY_API_KEY`, so Layer 3 (the value scrubber) redacts it **by value regardless of the key name**. Run against unmodified `logging.py`, the test passed. The plan's own docstring acknowledges Layer 3 catches it — but that makes the test non-load-bearing: delete `"api-key"` from `DENY_KEYS` again and it stays green. Threat T-03-01 carries a `mitigate` disposition whose stated mitigation is "assert redaction of a record keyed `api-key`", and an assertion that cannot fail does not mitigate anything. This is precisely the failure mode `test_secret_redaction.py`'s own module docstring warns about: "pass while proving nothing."
- **Fix:** Kept the plan's test verbatim, and added `test_hevy_header_key_name_is_redacted_by_layer_2_alone`, which logs `UNSEEDED_KEY` — a value deliberately never placed in the environment and therefore absent from `Settings.secret_values()`, so Layer 3 cannot see it. Only the key-name deny-list can redact it.
- **Files modified:** `backend/tests/test_secret_redaction.py`
- **Verification:** RED confirmed empirically before touching `logging.py` — `1 failed, 1 passed`, the failure being `AssertionError: T-03-01 violated: Layer 2 does not cover 'api-key'`. GREEN after the one-line `DENY_KEYS` addition: 14 passed.
- **Committed in:** `7a28a1c` (RED) / `3e67a3a` (GREEN)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** No scope creep — one extra test in a file the plan already modifies. It converts a decorative assertion into a real guard on the phase's only security-flagged code change. Everything else executed exactly as written.

## Issues Encountered

- **Task 1 acceptance criterion 5 is self-contradictory as written.** It requires `awk '/^dev = \[/,/^\]/' pyproject.toml | grep -q 'httpx2=='` to exit 1, but criterion 4 requires `pytest-httpx2==1.0.0` to be present in that same block — and `pytest-httpx2==1.0.0` contains the substring `httpx2==`. The two cannot both hold. Verified the criterion's evident intent instead (`grep '^ *"httpx2=='` — no bare `httpx2` entry in the dev group), which passes. The underlying goal is independently confirmed by `uv export`. No code change resulted; flagging it so the criterion can be corrected if reused.
- **`from tests.conftest import hevy_fixture` resolves and is the correct form.** The plan offered `from conftest import ...` as a fallback. `backend/tests/__init__.py` exists, so pytest imports the conftest as the package-qualified `tests.conftest`; a probe confirmed `sys.modules` holds exactly one conftest entry under that name. The fallback form would have created a *second* module object, re-running the module-scope MCP env seeding and recomputing the `_PREEXISTING_MCP_ENV` snapshot *after* seeding — which would have silently broken session teardown. Probe deleted after use.
- **Six pre-existing mypy errors in `conftest.py` (out of scope).** `The return type of an async generator function should be "AsyncGenerator"` and `Unused "type: ignore" comment` on the `engine`/`session`/`client` fixtures. Confirmed pre-existing by stashing this plan's conftest edit and re-running mypy: identical six errors at the pre-change line numbers, i.e. shifted by this plan's +33 lines, not caused by them. The repo's type gate is `mypy backend/app`, which exits 0. Logged in `deferred-items.md`.

## Known Stubs

None. This plan adds dependencies, one deny-list entry, and test data — no placeholder values, no unwired components, no TODO markers.

## Threat Flags

None. No new network endpoints, auth paths, file-access patterns, or schema changes at a trust boundary were introduced. The one new file-reading helper (`hevy_fixture`) is test-only and reads a fixed directory with names supplied as test literals.

## TDD Gate Compliance

Task 2 declared `tdd="true"` and the gate sequence is intact in git log:

1. **RED** — `7a28a1c` `test(03-01): add failing test for Hevy api-key header redaction`. Genuinely failing before implementation, verified by running the suite against unmodified `logging.py`. The fail-fast rule applied here and caught a real problem: the plan's own test passed at RED, which is what prompted the Rule-2 deviation above rather than proceeding to GREEN on a green test.
2. **GREEN** — `3e67a3a` `feat(03-01): add Hevy's literal api-key header name to the log deny-list`. 14 passed.
3. **REFACTOR** — none. A four-line frozenset addition has nothing to restructure; per the workflow, a refactor commit is only made if changes are actually needed.

## Verification Results

Plan-level `<verification>`:

| # | Check | Result |
|---|-------|--------|
| 1 | `uv sync --group dev` succeeds, `uv.lock` updated | PASS — 82 packages resolved; lock gains tenacity + pytest-httpx2 |
| 2 | `uv run pytest backend/tests -x -q -m "not integration"` | PASS — **79 passed**, 28 deselected (baseline was 72; +2 redaction, +5 fixture guards) |
| 3 | `uv run ruff check .` and `uv run mypy backend/app` | PASS — both exit 0 |
| 4 | httpx2 present in the runtime dependency block | PASS |

Plan-level `<success_criteria>`:

| Criterion | Result |
|-----------|--------|
| `tenacity` and `httpx2` importable from a no-dev-group install | PASS — `uv export --no-emit-project` contains both and excludes respx/pytest/httpx-0.x |
| A log record keyed `api-key` renders `***REDACTED***` | PASS — two tests, one of which isolates Layer 2 |
| `hevy_fixture("workouts_page1")` returns `{page, page_count, workouts}` | PASS |
| Fast suite green; ruff and mypy clean | PASS |

All `<acceptance_criteria>` across the three tasks pass, with the single documented exception of Task 1 criterion 5, verified against intent (see Issues Encountered).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Wave 1 prerequisites are in place. Specifically unblocked:

- **03-05 (HevyClient)** can `import httpx2` and `import tenacity` knowing both ship to Cloud Run, and can log request lifecycle events without a credential-leak path through the `api-key` key name.
- **03-04 / 03-06 / 03-09 / 03-10 / 03-11** can all call `hevy_fixture(...)` for schema-accurate canned responses instead of hand-writing payloads from the blueprint, which is wrong about `rir`, `weight_unit` and child-object ids.
- The Pitfall-3 rule (**responses** use `httpx.Response`, **exceptions** use `httpx2` types) is recorded in `conftest.py`, which should save the first agent that writes a retry test from an opaque `AssertionError` inside `respx/router.py`.

Concerns carried forward:

- `deferred-items.md` holds one out-of-scope item (pre-existing `conftest.py` fixture annotations). It touches shared fixtures every Phase 3 plan depends on, so it should be scheduled deliberately rather than folded into a mid-wave task.
- HEVY-08 remains unchecked in REQUIREMENTS.md by design; whichever plan actually delivers sync resilience should close it.

## Self-Check: PASSED

- **Files claimed as created/modified:** 13 of 13 found on disk (5 fixtures, `test_hevy_fixtures.py`, `deferred-items.md`, this SUMMARY, `pyproject.toml`, `uv.lock`, `logging.py`, `conftest.py`, `test_secret_redaction.py`).
- **Commits claimed:** 5 of 5 present in `git log` (`1927c7c`, `7a28a1c`, `3e67a3a`, `f9938a4`, `d870e2e`).
- **Suite re-run at self-check time:** 79 passed, 28 deselected. `ruff check .` exit 0, `mypy backend/app` exit 0.
- **No unexpected deletions:** `git diff --diff-filter=D` empty for every task commit.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-29*

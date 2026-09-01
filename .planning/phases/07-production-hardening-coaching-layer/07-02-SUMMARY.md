---
phase: 07-production-hardening-coaching-layer
plan: 02
subsystem: testing
tags: [pytest, testcontainers, respx, time-machine, mcp, sqlalchemy, postgres]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization
    provides: HevySyncService.sync_all(), the canned Hevy fixture pages, the mock-Hevy respx pattern
  - phase: 04-volume-frequency-analytics
    provides: get_weekly_volume() and the coverage/freshness metadata envelope
  - phase: 06-mcp-tools
    provides: fitness_get_weekly_volume, fitness_get_exercise_progression, Client(mcp) in-memory driving, app.state.sessionmaker wiring
provides:
  - Blueprint §43 full-chain composition test (mock-Hevy → sync → PostgreSQL → analytics → MCP tool in one run)
  - Proof that the analytics boundary and the MCP boundary report the identical hard-set figures for the same synced data
  - Wrong-typed-argument and missing-required-argument rejection tests, closing blueprint §42's "malformed parameters" row
affects: [07-verification, future-mcp-tool-additions, future-analytics-changes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition test drives Client(mcp) with app.state.sessionmaker redirected at the same testcontainer engine the sync committed through"
    - "Analytics half takes an explicit date range (no clock); MCP half runs under a frozen clock because every weeks-taking tool derives its window from local_today"
    - "Sync-committing tests wrap every body in try/finally: await _cleanup(maker) — a rollback cannot undo a commit against a session-scoped container"

key-files:
  created:
    - backend/tests/test_full_chain_end_to_end.py
  modified:
    - backend/tests/test_mcp_tool_schemas.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Helpers are COPIED from test_hevy_end_to_end.py rather than imported; no test module imports another test module, tests.conftest stays the only sanctioned cross-module import"
  - "Client(mcp) in-memory rather than a TestClient, so mcp.session_manager._has_started is never touched (07-RESEARCH.md Pitfall 11)"
  - "The composition's load-bearing assertion is equality between the two boundaries, not 'the tool returned something' — the latter would have passed throughout Phase 6"

patterns-established:
  - "_mcp_over(engine): async context manager that saves, redirects and restores app.state.sessionmaker so an MCP tool reads the container the test wrote to"
  - "Raw row count asserted first, so a hard-set total of 3 is provably an exclusion of the warm-up rather than a shortfall in the sync"
  - "coverage.sessions_in_window and freshness.resources are the proof of WHICH database answered — hard-set figures alone cannot distinguish an identically-seeded second database"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 25min
completed: 2026-09-01
---

# Phase 7 Plan 02: Full-Chain Composition & Malformed-Parameter Coverage Summary

**A single pytest run now drives mocked Hevy through sync, a real Postgres container, the analytics layer and an MCP tool, and asserts both boundaries report the identical `hard_sets` figures `[2, 1]` — plus wrong-typed and missing-required tool arguments are now proven to be rejected before any tool body runs.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-09-01T07:49:00Z
- **Completed:** 2026-09-01T08:14:00Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `backend/tests/test_full_chain_end_to_end.py` (381 lines, 3 tests) closes blueprint §43 / ROADMAP Phase 7 criterion 1: one run covers the seam between four layers that each already had their own green suite.
- The composition asserts **equality across boundaries**, not mere presence: `get_weekly_volume` over an explicit `2026-07-27..2026-08-09` range and `fitness_get_weekly_volume(weeks=2)` under a clock frozen at `2026-08-05T03:00Z` both report `hard_sets` of `2` for the week of 2026-07-27 and `1` for the week of 2026-08-03, against the same committed rows.
- The warm-up exclusion is proven end-to-end with the raw baseline pinned first: 4 `workout_sets` rows in the database, 3 hard sets at the analytics boundary, 3 hard sets at the MCP boundary.
- The tool's metadata envelope is asserted as the proof of *which* database answered — `coverage.sessions_in_window == 2` and a non-`None` `freshness.resources["workouts"]` are both impossible against the empty database a mis-wired `app.state.sessionmaker` would produce.
- Blueprint §42's "malformed parameters" row is now fully covered: over-cap (pre-existing), wrong-type (`weeks="four"`), and missing-required (`fitness_get_exercise_progression` with `{}`) all assert `is_error=True` with `structured_content is None`.
- Full suite: **656 passed** (651 pre-existing + 5 new), `ruff check .` clean, `ruff format --check` clean on both touched files.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write backend/tests/test_full_chain_end_to_end.py (blueprint §43)** — `a748903` (test)
2. **Task 2: Add the wrong-type and missing-required parameter tests** — `d0407ea` (test)

**Plan metadata:** committed with this SUMMARY (docs)

## Files Created/Modified

- `backend/tests/test_full_chain_end_to_end.py` — **created.** The §43 composition test. Copies `_no_sleep`/`_client`/`_maker`/`_service`/`_mock_hevy`/`_cleanup` from `test_hevy_end_to_end.py`, adds `_mcp_over(engine)` for the MCP half, and holds three integration tests: `test_the_full_chain_produces_the_same_answer`, `test_the_chain_excludes_warm_up_sets_at_both_boundaries`, `test_the_mcp_half_reads_the_database_the_sync_wrote`.
- `backend/tests/test_mcp_tool_schemas.py` — **modified.** Two tests appended immediately after `test_a_request_above_the_cap_is_rejected_before_the_body_runs`, plus a one-word module-docstring correction ("the one test that calls a tool" → "the three tests that call a tool"), which was no longer true after the append.
- `.planning/REQUIREMENTS.md` — **modified.** DEPLOY-03 checked off and its traceability row updated via `gsd-tools requirements mark-complete`.

## Decisions Made

- **Three shared helpers rather than three copies of the inline body shape.** `_sync_from_mocked_hevy`, `_analytics_hard_sets`, `_weekly_volume_through_mcp` and `_raw_set_row_count` are called by all three tests. The plan's `<action>` showed the wiring inline in test 1; triplicating the frozen-clock + `_mcp_over` + `Client(mcp)` sequence across three tests is precisely the kind of duplication that drifts, and a drifted clock in one of three tests would be invisible.
- **`_mock_hevy` was simplified relative to its source.** The `workout_pages` and `remote_count` parameters and the sibling `_mock_events` helper were dropped: this module never varies the pages and never goes incremental, and carrying `_mock_events` would have meant naming the events route path in a module whose contract forbids it.
- **`from tests.conftest import DEFAULT_USER_ID, hevy_fixture` is the only cross-module import.** Every sync helper is a verbatim copy with its docstring intact, per the plan's "helpers are copied, not imported" rule.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded the module docstring to drop the literal events-route path**

- **Found during:** Task 1
- **Issue:** The plan's suggested module docstring contains the literal string `/v1/workouts/events`, but the same task's acceptance criteria require `grep -c "workouts/events" backend/tests/test_full_chain_end_to_end.py` to return `0`. The plan contradicted itself.
- **Fix:** The docstring now says "the incremental events feed is deliberately NOT registered" and keeps the full explanation (respx asserts every registered route was called, so registering a route this test is right not to touch would fail on teardown). The rationale is preserved; only the path literal is gone.
- **Files modified:** `backend/tests/test_full_chain_end_to_end.py`
- **Verification:** `grep -c "workouts/events" backend/tests/test_full_chain_end_to_end.py` → `0`
- **Committed in:** `a748903`

**2. [Rule 3 - Blocking] Reworded the `TestClient` rationale for the same reason**

- **Found during:** Task 1
- **Issue:** The plan says "Do NOT build a `TestClient` in this module" and also requires `grep -c "TestClient" … == 0`. Writing that rationale into a helper docstring — the natural thing to do — breaks the criterion.
- **Fix:** The docstring now reads "Nothing in this module drives the app over HTTP. `Client(mcp)` speaks to the server in-memory and so never touches `mcp.session_manager._has_started` …", which explains the same constraint without the token.
- **Files modified:** `backend/tests/test_full_chain_end_to_end.py`
- **Verification:** `grep -c "TestClient" backend/tests/test_full_chain_end_to_end.py` → `0`
- **Committed in:** `a748903`

**3. [Rule 1 - Bug] Corrected a now-false claim in `test_mcp_tool_schemas.py`'s module docstring**

- **Found during:** Task 2
- **Issue:** The docstring stated the file is "deliberately not marked `integration`, except for the one test that calls a tool". After appending two more tool-calling tests, that sentence is false — and it is the sentence a future reader consults before deciding whether a new test needs the marker.
- **Fix:** Changed "the one test" to "the three tests".
- **Files modified:** `backend/tests/test_mcp_tool_schemas.py`
- **Verification:** `uv run ruff check backend/tests/test_mcp_tool_schemas.py` clean; all 11 tests in the module pass
- **Committed in:** `d0407ea`

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 bug)
**Impact on plan:** All three are documentation-level corrections forced by the plan's own machine-checkable acceptance criteria. No behavioural deviation, no scope creep. Every assertion the plan specified is present and passing.

## TDD Gate Compliance

Both tasks carry `tdd="true"`, but neither has a meaningful RED/GREEN split and no `feat(...)` commit exists for this plan. That is correct here, not a gap:

- The plan's own objective states "It is not a test-suite build" — every layer this plan exercises shipped in Phases 3–6, and both tasks' `<action>` blocks describe test files only. There is no production code to implement.
- Writing a deliberately-failing version of a test over already-correct behaviour would prove nothing about the behaviour and would waste a commit.
- Both commits are typed `test(...)` per the commit-type table (test-only changes). The RED gate's real purpose — proving the test can fail — is discharged instead by the tests' construction: `test_the_full_chain_produces_the_same_answer` asserts `{2026-07-27: 2, 2026-08-03: 1}`, which an empty or mis-wired database answers with `{2026-07-27: 0, 2026-08-03: 0}`. The test cannot pass vacuously.

## Issues Encountered

- **The worktree branch was based on the wrong commit.** `git merge-base HEAD b3a278c` returned `1e97f3b` ("chore(02-05): record auto-chain flag"), i.e. the worktree was cut from a mid-Phase-2 commit rather than the phase-07 HEAD. The prescribed `<worktree_branch_check>` hard reset corrected it before any work started; the working tree was clean, so nothing was lost. Worth flagging to the orchestrator in case sibling wave-1 worktrees were cut the same way.
- **`.planning/phases/07-production-hardening-coaching-layer/07-PATTERNS.md` is referenced by the plan's `<context>` but is untracked in git**, so it does not exist in this worktree. Executed without it; nothing in the plan's tasks depended on it. It should be committed on the main branch.
- **The Phase 6 baseline is 651, not the 650 recorded in `07-VALIDATION.md`.** Measured by running the suite with the new module ignored and the two new selectors deselected: 649 passed + 4 deselected (2 new + 2 pre-existing Hevy tests whose names happen to contain "malformed") = 653, minus the 2 new = 651. The suite now stands at 656. No regressions; the note in VALIDATION.md is just one stale.
- **`-k malformed` selects three tests suite-wide**, because `test_hevy_client.py::test_malformed_response_…` and `test_hevy_resilience.py::test_malformed_workout_…` predate this plan. The `07-VALIDATION.md` command is file-scoped (`backend/tests/test_mcp_tool_schemas.py -k malformed`) and selects exactly one, as required.
- **Pre-existing mypy errors in `backend/tests/conftest.py`** (6 errors on the `engine`/`session` async-generator fixtures) surface whenever any test module is type-checked. Out of scope per the scope boundary rule; not introduced or worsened here, and there is no mypy pre-commit hook.

## Known Stubs

None. Both tasks produce complete, passing tests over already-shipped behaviour; no placeholder values, no unwired data paths.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **DEPLOY-03's automated half is complete.** Blueprint §42's Hevy, analytics and MCP checklists were already covered by name across the existing suite; this plan closed the two named gaps (the §43 composition and the two malformed-parameter cases). Nothing further is required for DEPLOY-03.
- `07-VALIDATION.md` rows 1–4 are now green and their commands are exactly as written there: `pytest backend/tests/test_full_chain_end_to_end.py -x -m integration` (3 passed), `… -k same_answer -x` (1 passed), `… test_mcp_tool_schemas.py -k malformed -x` (1 passed), `… -k missing_required -x` (1 passed).
- **Note for the plan that adds rate limiting (ROADMAP-2):** `test_full_chain_end_to_end.py` drives the MCP tool through `Client(mcp)` in-memory, which bypasses the ASGI middleware stack entirely. A limiter added as Starlette middleware will not affect this module, and this module will not prove the limiter works — `test_rate_limit.py` must drive HTTP.
- **Note for anyone adding a fourteenth tool:** if it takes a `weeks`-style window, the composition test's frozen clock (`FROZEN_NOW = 2026-08-05T03:00Z`) and the fixture workouts' August 2026 dates are the pair that has to stay consistent. An unfrozen clock makes the MCP half assert against an empty window and pass for the wrong reason.

## Self-Check: PASSED

- `backend/tests/test_full_chain_end_to_end.py` — FOUND
- `backend/tests/test_mcp_tool_schemas.py` — FOUND
- `.planning/REQUIREMENTS.md` — FOUND
- `.planning/phases/07-production-hardening-coaching-layer/07-02-SUMMARY.md` — FOUND
- Commit `a748903` — FOUND
- Commit `d0407ea` — FOUND

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

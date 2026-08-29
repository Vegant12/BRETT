---
phase: 03-hevy-integration-normalization
plan: 09
subsystem: api
tags: [hevy, incremental-sync, events, pagination, postgres, sqlalchemy, savepoint, respx]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization (plan 03-05)
    provides: "HevyClient.get_workout_events, the discriminated HevyWorkoutEvent union, event_timestamp"
  - phase: 03-hevy-integration-normalization (plan 03-06)
    provides: "upsert_workout / delete_workout and the sync-driver shape"
  - phase: 03-hevy-integration-normalization (plan 03-04)
    provides: "sync_state repository: ensure_sync_state, mark_running, complete_sync(cursor_timestamp=), record_sync_error"
provides:
  - "drain_events: reads every page of /v1/workouts/events against ONE frozen `since` and returns events oldest-first"
  - "DrainResult: (events oldest-first, pages_fetched, cursor) — the cursor is max(event_timestamp), never events[-1]"
  - "apply_events: per-event SAVEPOINT application of a drained list, returning (updated, deleted, not_found)"
  - "sync_workout_events: the incremental driver — refuses without a baseline, advances the cursor exactly once"
  - "EVENT_CURSOR_OVERLAP: a five-minute deliberate re-read window biasing toward overlap over gaps"
  - "17-test suite whose ordering assertions are the counterexample to the naive drain"
affects: [04-analytics, 05-mcp-tools, hevy-scheduling, deletion-drift-reconciliation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen-cursor drain: read-all-then-apply, with the read function touching no database at all"
    - "Cursor written in the same transaction as the apply it accounts for, and only after it"
    - "Refuse-rather-than-degrade: no baseline means no drain, returned as skipped_reason not an exception"

key-files:
  created:
    - backend/app/integrations/hevy/events.py
    - backend/tests/test_hevy_events.py
  modified: []

key-decisions:
  - "The events cursor is max(event_timestamp) across the whole drain, never the clock and never events[-1] in feed order"
  - "since = baseline - EVENT_CURSOR_OVERLAP (5 min): overlap costs idempotent upserts, a gap costs a workout"
  - "baseline = cursor_timestamp or last_synced_at; with neither, the sync refuses and returns skipped_reason instead of draining from the epoch"
  - "One transaction for the whole incremental drain, unlike the full sync's per-page commit — a drain is bounded by what changed"
  - "The naive-since guard is duplicated in drain_events even though HevyClient already has it, so the failure lands before the first socket"

patterns-established:
  - "Rule 1/2/3 drain: freeze `since`, collect every page, stable-sort oldest-first before applying anything"
  - "Per-event SAVEPOINT (session.begin_nested) so one malformed snapshot is quarantined, not fatal (Pitfall 11)"
  - "Counted no-op: a delete for an unknown workout increments deletes_not_found and raises nothing"
  - "Numeric assertion of derived constants in tests (09:55:00Z) rather than recomputing from the constant under test"

requirements-completed: [HEVY-02, HEVY-04, HEVY-09]

# Metrics
duration: 34min
completed: 2026-08-29
---

# Phase 3 Plan 9: Incremental Event Sync Summary

**Frozen-cursor drain of `/v1/workouts/events` that collects every page before applying anything, applies oldest-first so a twice-edited workout keeps its newest payload, cascades deletions, and advances the checkpoint exactly once — with 17 tests written as the counterexample to the naive algorithm.**

## Performance

- **Duration:** ~34 min
- **Started:** 2026-08-29T07:31:00Z
- **Completed:** 2026-08-29T08:05:00Z
- **Tasks:** 3
- **Files modified:** 2 (both created)

## Accomplishments

- `drain_events` reads the whole feed against a single `frozen_since` bound before the loop, returns events oldest-first via a stable sort on `event_timestamp`, and reports `max(event_timestamp)` as the new cursor — with `default=frozen_since` so an empty feed leaves the checkpoint exactly where it was.
- `apply_events` walks the oldest-first list under one SAVEPOINT per event, so a single malformed workout snapshot is skipped rather than aborting the whole apply; a delete for a workout that was never stored increments `deletes_not_found` and raises nothing.
- `sync_workout_events` refuses to run without a baseline (returning `skipped_reason`, making zero HTTP requests), applies the drain and writes `cursor_timestamp` in the *same* transaction, and on failure records `status='error'` while leaving the cursor untouched.
- 17 tests, 9 of them against a real Postgres container. `test_drain_keeps_since_frozen_across_pages` inspects the three recorded requests and asserts an identical `since`; `test_multiply_updated_workout_keeps_the_newest_payload` builds Hevy's newest-first order and asserts the persisted title is `"final"`. Both fail if anyone reintroduces the naive drain.
- `test_full_then_incremental_round_trip` proves ROADMAP success criteria 1 and 2 end to end: full sync of both pages, then an incremental drain leaves workout A edited and present with one 105 kg Bench Press set, and workout B absent along with every row that hung off it.

## Task Commits

Each task was committed atomically, RED then GREEN:

1. **Task 1: The event drain — frozen cursor, all pages, oldest-first**
   - `93780ea` (test) — 8 fast tests; RED, the module did not exist
   - `4bddc11` (feat) — `drain_events`, `DrainResult`, `EVENT_CURSOR_OVERLAP`
2. **Task 2: Apply events and drive the incremental sync**
   - `dbe521c` (test) — 7 integration tests; RED, `sync_workout_events` did not exist
   - `af52732` (feat) — `apply_events`, `sync_workout_events`, `EventSyncResult`
3. **Task 3: Event ordering and deletion test suite**
   - `5d3b414` (test) — overlap-margin and full-then-incremental round-trip tests; suite complete at 17

_No REFACTOR commits: neither GREEN pass left anything to clean up._

## TDD Gate Compliance

Both TDD tasks show the full RED → GREEN sequence in `git log`:

| Gate | Task 1 | Task 2 |
|------|--------|--------|
| RED (`test(...)`, verified failing) | `93780ea` — `ModuleNotFoundError: app.integrations.hevy.events` | `dbe521c` — `ImportError: cannot import name 'sync_workout_events'` |
| GREEN (`feat(...)`, verified passing) | `4bddc11` — 8 passed | `af52732` — 15 passed |
| REFACTOR | not needed | not needed |

No test passed unexpectedly during a RED phase.

## Files Created/Modified

- `backend/app/integrations/hevy/events.py` (258 lines, created) — the incremental sync module. Module docstring quotes the 8-event research simulation verbatim, because that output is the reason the code is shaped the way it is. Holds `EVENT_CURSOR_OVERLAP`, `DrainResult`, `EventSyncResult`, `drain_events`, `apply_events`, `sync_workout_events`.
- `backend/tests/test_hevy_events.py` (689 lines, created) — 17 tests: 8 fast (mocked transport only) and 9 `@pytest.mark.integration` against the session-scoped Postgres container, each with `finally` cleanup of `workouts` and `sync_state`.

## Decisions Made

- **`baseline = cursor_timestamp or last_synced_at`.** `cursor_timestamp` is the events feed's own checkpoint and takes precedence; `last_synced_at` is the fallback for the very first incremental run after a full sync, which has no events cursor yet. With neither, the sync refuses — draining from the epoch through an endpoint that pages at 10 is a DoS on yourself (T-03-41).
- **The naive-`since` guard is duplicated** in `drain_events` even though `HevyClient.get_workout_events` already performs it. The duplication means the drain fails before the first socket rather than after it, matching the guard-not-convention pattern in `app/core/time.py`.
- **One transaction for the whole drain**, deliberately unlike `sync_workouts`' per-page commit. A drain is bounded by what changed since the last run, and a rollback simply means the next run re-reads the same window. The full sync commits per page because a full history is hundreds of requests and losing them all to a transient failure at page 40 is not acceptable.
- **`test_since_includes_the_overlap_margin` asserts the literal string `2026-08-05T09:55:00Z`** rather than recomputing `cursor - EVENT_CURSOR_OVERLAP`. Deriving the expectation from the constant under test would pass even if the subtraction were deleted.
- **`test_event_sync_skips_without_a_baseline` registers no respx routes at all.** With `assert_all_mocked=True` (the plugin default), any request the skip path made would fail as unmocked — a second, stronger assertion layered under the explicit `len(httpx2_mock.calls) == 0`.

## Deviations from Plan

None — plan executed exactly as written.

One phrasing adjustment inside a comment, made to satisfy the plan's own acceptance criterion rather than to change behaviour: a comment originally read ``` `HevyClient.get_workout_events` checks this too ```, which made `grep -c 'get_workout_events' events.py` return `2` instead of the required `1`. The comment now reads "The client's events endpoint checks this too", preserving the meaning while leaving exactly one call site in the file. No code changed.

## Issues Encountered

None. Every gate passed on the first attempt after each GREEN implementation; no auto-fix attempts were spent.

## Verification Evidence

| Gate | Command | Result |
|------|---------|--------|
| Plan suite | `uv run pytest backend/tests/test_hevy_events.py -q` | **17 passed** |
| Full suite | `uv run pytest backend/tests -q` | **266 passed** |
| Types | `uv run mypy backend/app` | Success, no issues in 39 source files |
| Lint | `uv run ruff check .` | All checks passed |
| Integration coverage | `grep -c '@pytest.mark.integration'` | **9** |
| Single call site | `grep -c 'get_workout_events' events.py` | **1** |
| No payload leak | `grep -q 'str(exc)' events.py` | exit 1 (absent) |
| Commit points | `grep -c 'await session.commit()' events.py` | **3** |

Threat-register items `T-03-38` (scoped deletion), `T-03-39` (cursor never advanced on failure), `T-03-40` (unknown event type raises), `T-03-41` (no unbounded epoch drain) and `T-03-43` (class-name-only logging) each have a named test or a grep assertion above. `T-03-42` (deletion drift) remains **accepted** per D-09 and is documented in a comment at the top of `sync_workout_events`.

## Known Stubs

None. Every function in `events.py` is wired to a real caller path and exercised against a real database.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The incremental half of HEVY-02 is complete and the full-sync → incremental round trip is proven, so the Hevy → PostgreSQL leg of the Core Value path is now end-to-end verified for both additions and deletions.
- `sync_workout_events` is ready to be wired into a CLI entrypoint and a scheduled job (the remaining Phase 3 plans), and needs nothing beyond an `HevyClient` and an `async_sessionmaker`.
- Carried-forward concern, unchanged: D-09's accepted deletion-drift risk. If a sync gap ever exceeds Hevy's event retention, a deleted workout lingers locally. The detector already exists — `sync_workouts` logs `hevy_workout_count_mismatch` against `/v1/workouts/count` — and a reconciliation sweep remains the documented follow-up if drift is observed in practice.

## Self-Check: PASSED

Files claimed as created, verified present on disk:

- `backend/app/integrations/hevy/events.py` — FOUND (258 lines)
- `backend/tests/test_hevy_events.py` — FOUND (689 lines)
- `.planning/phases/03-hevy-integration-normalization/03-09-SUMMARY.md` — FOUND

Commits claimed, verified in `git log`: `93780ea`, `4bddc11`, `dbe521c`, `af52732`, `5d3b414` — all FOUND.

Post-commit deletion check: `git diff --diff-filter=D --name-only 90dff5d..HEAD` returned nothing. No tracked file was removed by this plan.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-29*

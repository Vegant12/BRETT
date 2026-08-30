---
phase: 04-volume-frequency-analytics
plan: 04
subsystem: analytics
tags: [pydantic, sqlalchemy, postgres, sync-state, security, cross-tenant, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "local_range_bounds (04-01); CoverageMetadata / FreshnessMetadata + the six static analytics boundary assertions (04-02); golden_workout builder, GoldenSet/GoldenExercise and ANALYTICS_SECOND_USER_ID (04-03)"
  - phase: 03-hevy-integration-normalization
    provides: "sync_state table and its repository (get_sync_state, complete_sync, record_sync_error, format_sync_error, PROVIDER_HEVY, RESOURCE_* constants); workouts table with ix_workouts_user_id_start_time"
provides:
  - "backend/app/analytics/metadata.py — the freshness+coverage envelope every Phase 4/5/6 analytics response carries"
  - "INSUFFICIENT_DATA_SESSION_THRESHOLD = 2 as the single D-05 constant shared by volume, frequency and their tests"
  - "FRESHNESS_RESOURCES_WORKOUTS / FRESHNESS_RESOURCES_MUSCLE — which sync_state rows actually feed which answer"
  - "build_freshness(session, *, user_id, resources, provider) -> FreshnessMetadata (per-resource last_synced_at, None for never-synced)"
  - "build_coverage(session, *, user_id, utc_start, utc_end) -> CoverageMetadata (D-06's exact three fields)"
  - "sessions_in_window and earliest_workout_at as reusable, user-scoped, index-safe primitives"
  - "A runtime proof that sync_state.last_error cannot reach an analytics response (T-04-03)"
affects: [04-05, 04-06, 04-07, 04-08, 04-09, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Response envelope built once and constructed by every metric, rather than each metric inventing its own freshness field"
    - "Per-resource freshness map instead of a collapsed scalar, because the projection is one-way"
    - "Distinctive-sentinel leak test guarded by an explicit anti-vacuity assertion"
    - "Security guarantees stay in the fast suite (no integration marker) so Docker being down cannot skip them"

key-files:
  created:
    - backend/app/analytics/metadata.py
    - backend/tests/test_analytics_metadata.py
  modified: []

key-decisions:
  - "The leak sentinel is carried by an exception exposing safe_message, not a plain RuntimeError — format_sync_error stores the class name alone otherwise, and the plan's literal instruction would have made the test vacuous (proven, see Deviation 2)"
  - "test_earliest_data_at_is_none_without_any_workouts now seeds a DEFAULT_USER_ID workout months before the window, so the all-time lookup's user_id predicate is actually pinned (Rule 2, proven red without it)"
  - "Docstring prose refers to the bookkeeping row's 'stored error text' and 'resume cursors' rather than the column names, so the plan's own grep criteria (exactly one line naming them, zero attribute accesses) hold"
  - "requirements mark-complete deliberately not run: this plan builds the envelope, no analytics response carries it yet"

patterns-established:
  - "One shared threshold constant, imported by tests rather than restated as a literal, so revisiting D-05 is a one-line change"
  - "Every cross-tenant assertion is paired with a vacuity guard asserting the OTHER user's non-zero count"
  - "Negative control before commit: each guard is proven red against an injected violation, then reverted"

requirements-completed: []
requirements-advanced: [DQ-01, DQ-02]

# Metrics
duration: 26min
completed: 2026-08-30
---

# Phase 4 Plan 04: Freshness & Coverage Metadata Summary

**The DQ-01/DQ-02 envelope every Phase 4 response inherits: a per-resource `last_synced_at` map that structurally cannot carry `sync_state`'s error text or cursors, plus a three-field coverage block whose `insufficient_data` flag is pinned on both sides of the D-05 boundary and whose counts are proven not to cross tenants.**

## Performance

- **Duration:** 26 min
- **Started:** 2026-08-30T16:57Z (local +07)
- **Completed:** 2026-08-30T17:23:16+07:00
- **Tasks:** 3 of 3
- **Files created:** 2 (no existing file modified)

## Accomplishments

- `build_freshness` returns one `last_synced_at` per requested resource and nothing else from the row. The two live-observed timestamps (`05:43:18Z` workouts, `06:08:04Z` templates — the 25-minute drift) come back distinctly, which a single collapsed scalar could not express.
- The no-leak guarantee is proven twice and at two different layers: structurally in the fast suite (`FreshnessMetadata.model_fields == {"resources"}` plus `extra="forbid"` rejection), and at runtime by seeding a distinctive sentinel through the production `record_sync_error` writer and scanning `model_dump_json()`. The runtime test carries an explicit anti-vacuity assertion that the sentinel really did land in the column first — and that guard fired for real (see Deviation 2).
- Both sides of the D-05 boundary are pinned (1 session → `insufficient_data is True`, 2 sessions → `False`, 0 sessions → `True`), plus a fast-suite test written against the constant rather than the literal `2`, so an off-by-one in the comparison operator cannot ship.
- `earliest_data_at` is proven all-time rather than window-scoped: a workout on 2026-04-06 sits outside the requested 2026-08-24..30 window, the count stays 1, and the floor reports April. That is the distinction between "you did not train that week" and "your history does not reach back that far".
- Cross-tenant scoping is proven for **both** query functions. Three workouts for `ANALYTICS_SECOND_USER_ID` and one for `DEFAULT_USER_ID` in the same window; the counts stay 3 and 1. Dropping the `user_id` predicate from either function was injected and turns the suite red.

## Task Commits

1. **Task 1: Write app/analytics/metadata.py — DQ-01 freshness and DQ-02 coverage** — `35cf43d` (feat)
2. **Task 2: Test DQ-01 — per-resource freshness and the no-leak guarantee** — `05d42da` (test)
3. **Task 3: Test DQ-02 — D-05 boundary, earliest_data_at, cross-tenant scoping** — `b6c6dea` (test)

## Files Created/Modified

- `backend/app/analytics/metadata.py` (154 lines) — Module docstring stating all four required rules. `INSUFFICIENT_DATA_SESSION_THRESHOLD = 2`, `FRESHNESS_RESOURCES_WORKOUTS`, `FRESHNESS_RESOURCES_MUSCLE`, `is_insufficient`, `sessions_in_window`, `earliest_workout_at`, `build_freshness`, `build_coverage`. Positional `session`, keyword-only everything else. Reaches `sync_state` only through `get_sync_state` — never `select(SyncState)` — and reads only `state.last_synced_at` off the row.
- `backend/tests/test_analytics_metadata.py` (376 lines) — 11 tests. Nine carry `@pytest.mark.integration`; two (`test_freshness_model_cannot_carry_sync_state_internals`, `test_is_insufficient_boundary_is_the_shared_constant`) deliberately do not, so the MCP-06 structural guarantee and the D-05 threshold stay verifiable with Docker down.

## Decisions Made

- **The sentinel exception opts in via `safe_message`.** `format_sync_error` stores an exception's class name alone unless the exception curates a `safe_message` — that is the whole T-03-12 redaction design. A `RuntimeError(sentinel)` therefore never reaches the column, and the leak test would have proven nothing. See Deviation 2.
- **`earliest_data_at`'s user scoping got its own fixture.** See Deviation 3 — the plan's version of that test passed against an unscoped query.
- **Docstring prose avoids the column names.** The plan's verbatim comment text violated two of its own grep criteria. See Deviation 1.
- **`FRESHNESS_RESOURCES_*` are public tuples, not a computed set.** Callers in 04-06/07/08 must be able to say *which* resources their answer depends on; deriving it would put the decision in the wrong place.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Three internal contradictions between the plan's verbatim text and its own grep acceptance criteria**

- **Found during:** Tasks 1 and 2
- **Issue:**
  - The plan's verbatim `build_freshness` comment reads ``# ONLY last_synced_at. `state.last_error`, `state.status`, `state.cursor_page` and`` / ``# `state.cursor_timestamp` are internal bookkeeping;``. That is **two** lines matching `last_error\|cursor_page\|cursor_timestamp` (criterion: exactly 1) and **two** lines matching `state\.last_error\|state\.status\|state\.cursor` (criterion: 0). The specified module-docstring text ("`sync_state.last_error` is produced by `format_sync_error`") breaks both criteria again.
  - The plan's specified module docstring for the test file names `test_freshness_model_cannot_carry_sync_state_internals` in prose, making `grep -c` return 2 where the criterion demands 1.
  - This is the same substring-versus-anchored-match trap `test_analytics_isolation.py` documents and that plan 04-02 hit.
- **Fix:** Resolved toward the machine-checkable criteria, preserving the documented intent. The module docstring and the in-function comment refer to "the bookkeeping row's stored error text", "its run status" and "its two resume cursors"; a single line — `# Forbidden here: last_error, status, cursor_page, cursor_timestamp -- operator CLI only.` — names them explicitly, which is exactly what the criterion describes ("the single comment naming what is forbidden — no attribute access"). The test docstring refers to "the structural test that pins `FreshnessMetadata`'s field set".
- **Files modified:** `backend/app/analytics/metadata.py`, `backend/tests/test_analytics_metadata.py`
- **Verification:** `grep -c 'last_error\|cursor_page\|cursor_timestamp'` → 1; `grep -c 'state\.last_error\|state\.status\|state\.cursor'` → 0; `grep -c 'test_freshness_model_cannot_carry_sync_state_internals'` → 1. Every function name, signature and body is exactly as specified.
- **Committed in:** `35cf43d`, `05d42da`

**2. [Rule 1 - Bug] The plan's leak test was vacuous as literally written**

- **Found during:** Task 2
- **Issue:** The plan instructs `record_sync_error(..., exc=RuntimeError(_LEAK_SENTINEL))`. `format_sync_error` (`sync_state.py:44-56`) returns `type(exc).__name__` alone unless the exception exposes a `safe_message` attribute — that asymmetry is the deliberate T-03-12 redaction control. So the sentinel would never reach `sync_state.last_error`, the payload scan would trivially pass, and T-04-03 would be "enforced" by a test with nothing to detect. The plan's own anti-vacuity guard (`assert _LEAK_SENTINEL in state.last_error`) would have failed the test outright.
- **Fix:** Added `class _SentinelFailure(Exception)` with `safe_message = _LEAK_SENTINEL`, mirroring `test_sync_state.py::_RateLimited`. The sentinel now lands in the column as `_SentinelFailure: zz-analytics-leak-canary-9f3a` and the payload scan has something real to detect.
- **Files modified:** `backend/tests/test_analytics_metadata.py`
- **Verification:** Negative control — reverted to the plan's literal `RuntimeError(_LEAK_SENTINEL)` and ran the test: `AssertionError: the sentinel never reached sync_state -- test is vacuous / assert 'zz-analytics-leak-canary-9f3a' in 'RuntimeError'`. Restored, then injected a real leak (`out[f"{resource}:{state.last_error}"]`) into `build_freshness` and confirmed the payload assertion goes red.
- **Committed in:** `05d42da`

**3. [Rule 2 - Missing Critical] `earliest_workout_at` had no test pinning its `user_id` predicate**

- **Found during:** Task 3 negative control
- **Issue:** The plan's threat register claims T-04-02 is mitigated because "both statements filter `Workout.user_id == user_id`", enforced by `test_coverage_does_not_count_another_users_workouts`. That test only asserts `sessions_in_window` and `insufficient_data`. Deleting the `user_id` predicate from `earliest_workout_at` and running the suite: **all 11 tests still passed.** `test_earliest_data_at_is_none_without_any_workouts` created a user with no workouts in an otherwise empty table, so `min(start_time)` returned NULL regardless of scoping. A cross-tenant disclosure on the all-time lookup — the one query the window bounds do not constrain — was undetectable.
- **Fix:** That test now also builds a `DEFAULT_USER_ID` workout at `_LONG_AGO` before asserting the second user's `earliest_data_at is None`, with a failure message naming T-04-02. Test count, test names and the `-k earliest` selector are unchanged.
- **Files modified:** `backend/tests/test_analytics_metadata.py`
- **Verification:** With the predicate removed, the test fails: `assert datetime.datetime(2026, 4, 6, 2, 0, tzinfo=utc) is None`. With it restored, 11 passed.
- **Committed in:** `b6c6dea`

**4. [Rule 3 - Blocking] Created the worktree's Python environment**

- **Found during:** Pre-Task 1 setup
- **Issue:** This parallel executor runs in a fresh git worktree with no `.venv`, and every verify/acceptance command in the plan is written as `.venv/bin/python -m ...`.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree root. `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` resolves against the worktree's source, not the main checkout's. Removed before returning; never staged.
- **Files modified:** none tracked.
- **Verification:** Baseline `pytest -q -m "not integration"` → 194 passed before any source change.
- **Committed in:** n/a

**5. [Rule 3 - Blocking] Worktree branch base was stale**

- **Found during:** First action
- **Issue:** `git merge-base HEAD a3acb0ce` returned `1e97f3b` — the worktree branched from an older commit than the phase HEAD, meaning wave-1's work was absent.
- **Fix:** `git reset --hard a3acb0ce` per the startup check, verified. The worktree was clean, so nothing was lost. This is the fourth consecutive wave in this phase to hit it.
- **Files modified:** none.
- **Committed in:** n/a

---

**Total deviations:** 5 (3 blocking, 1 bug in the plan's literal instruction, 1 missing security test)
**Impact on plan:** No scope creep. Deviations 1 and 2 were forced — the plan could not be satisfied as literally written. Deviation 3 closes a hole in the plan's own threat-register claim without changing the test count or any test name. The diff touches exactly the two files the plan names; `pyproject.toml`, `resolver.py` and `exercise_map.py` are unmodified and no migration was created.

## Acceptance Criteria

### Task 1

| Criterion | Expected | Actual |
|---|---|---|
| `grep -c "INSUFFICIENT_DATA_SESSION_THRESHOLD = 2"` | 1 | 1 |
| `grep -c "^async def sessions_in_window\|^async def earliest_workout_at\|^async def build_freshness\|^async def build_coverage"` | 4 | 4 |
| `grep -c "^def is_insufficient"` | 1 | 1 |
| `grep -c "last_error\|cursor_page\|cursor_timestamp"` | 1 | 1 |
| `grep -c "state\.last_error\|state\.status\|state\.cursor"` | 0 | 0 |
| `grep -c "select(SyncState)\|import SyncState"` | 0 | 0 |
| `grep -c "requested_window\|start_day\|end_day"` | 0 | 0 |
| `grep -c "session.commit\|session.flush\|session.add"` | 0 | 0 |
| `min_lines: 90` | >= 90 | 154 |
| `pytest test_analytics_isolation.py -q` | 0 | 6 passed |
| `ruff check` / `mypy` on the module | 0 / 0 | clean / clean |

### Task 2

| Criterion | Expected | Actual |
|---|---|---|
| `pytest test_analytics_metadata.py -k freshness` | exit 0 | 4 passed |
| Structural no-leak test runs with Docker irrelevant | >= 1 passed | 1 passed (`-k cannot_carry -m "not integration"`; see note) |
| `grep -c "_LEAK_SENTINEL"` | >= 4 | 7 |
| `grep -c "model_dump_json()"` | >= 1 | 1 |
| `grep -c "test_freshness_model_cannot_carry_sync_state_internals"` | 1 | 1, no integration marker above it |
| `grep -c "ANALYTICS_SECOND_USER_ID"` | >= 3 | 12 |
| `grep -c "test is vacuous"` | >= 1 | 1 |
| `pytest test_sync_state.py test_migrations.py -q` afterwards | exit 0 | 17 passed (with this module) |
| `ruff check` on the test module | 0 | clean |

**Note on the `-k no_leak` selector.** The plan's criterion runs `pytest -k no_leak -m "not integration"`, but none of the test names the plan itself specifies contains the substring `no_leak` — pytest would collect zero tests and exit 5. Since two other criteria fix the function name (`grep -c "test_freshness_model_cannot_carry_sync_state_internals"` → 1) and the total count (11), renaming was not available. The criterion's intent — the structural guarantee runs without Docker — is verified with `-k cannot_carry -m "not integration"`, which selects exactly that test.

### Task 3

| Criterion | Expected | Actual |
|---|---|---|
| `pytest test_analytics_metadata.py -q` | exit 0, exactly 11 collected | 11 passed |
| `-k insufficient` | >= 4 passed | 4 passed |
| `-k earliest` | exactly 2 passed | 2 passed |
| `grep -c "def test_"` | 11 | 11 |
| `grep -c "INSUFFICIENT_DATA_SESSION_THRESHOLD"` | >= 3 | 4 |
| `grep -c "ASVS V4 violated"` | 1 | 1 |
| `grep -c "local_range_bounds"` | >= 1 | 7 |
| `grep -c "_LONG_AGO"` | >= 2 | 4 |
| `pytest -q` (full suite) | exit 0 | 323 passed |
| `pytest -q -m "not integration"` | exit 0 | 196 passed |
| `ruff check backend` | 0 | clean |
| `mypy backend` | 0 | **44 pre-existing errors in 13 test files, 0 from this plan** — see Deferred Issues |

## Verification Results

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_metadata.py -q` | 11 passed |
| 2 | `pytest backend/tests/test_analytics_isolation.py -q` | 6 passed — all six boundary guards still green with `metadata.py` present |
| 3 | `pytest test_analytics_metadata.py test_sync_state.py test_migrations.py -q` | 17 passed — shared container unpolluted |
| 4 | `pytest -q -m "not integration"` | 196 passed in 0.92s (baseline 194; +2 new markerless tests) |
| 5 | `pytest -q` (full suite) | **323 passed** in 8.63s (baseline 312; +11) |
| 6 | `ruff check backend` / `ruff format --check` on both files | clean / clean; `mypy backend/app` → 44 source files, no issues |
| 7 | `pyproject.toml` unmodified, no migration, `resolver.py` / `exercise_map.py` untouched | `git diff --stat` vs base shows exactly the two new files |

**Negative controls performed and reverted** (each proven red, then restored — `git status` clean afterwards):

| Injection | Result |
|---|---|
| `exc=RuntimeError(_LEAK_SENTINEL)` (the plan's literal) | vacuity guard fires: "the sentinel never reached sync_state -- test is vacuous" |
| `out[f"{resource}:{state.last_error}"] = ...` in `build_freshness` | `test_freshness_never_leaks_last_error` red on `model_dump_json()`; independence test also red |
| `Workout.user_id == user_id` removed from `sessions_in_window` | `test_coverage_does_not_count_another_users_workouts` red (`assert 4 == 3`) |
| `Workout.user_id == user_id` removed from `earliest_workout_at` | red **only after Deviation 3's fix**; passed before it |

## TDD Gate Compliance

All three tasks carried `tdd="true"`, and the plan orders implementation (Task 1) before its tests (Tasks 2–3) — the same inversion plan 04-02 recorded.

- **RED:** Confirmed before Task 1 that `from app.analytics.metadata import INSUFFICIENT_DATA_SESSION_THRESHOLD` raised `ModuleNotFoundError`. For Tasks 2 and 3 the red phase was run as a negative control: four separate violations injected one at a time (table above), each turning the intended test red, each reverted.
- **GREEN:** `35cf43d` (`feat`) is the implementation; `05d42da` and `b6c6dea` (`test`) constrain it. 11 passed after each.
- **REFACTOR:** Not needed beyond `ruff format`, applied inside Task 1 before its commit.
- **Gate commits:** a `feat(...)` commit exists and two `test(...)` commits follow it. The standard RED→GREEN commit ordering is inverted because the plan's task order is, not because a gate was skipped.

## Deferred Issues

**Pre-existing `mypy backend` errors — NOT introduced by this plan, deliberately not fixed.**

Task 3's acceptance criterion asks for `mypy backend` to exit 0. It did not hold before this plan ran: 44 errors across 13 test files (`_env_file` kwargs in `test_config.py`, missing `types-PyYAML`, `TypeEngine` attribute access in `test_db_models.py`, ASGI-callable `.state` in `test_health.py`/`test_mcp_tools.py`, and six async-generator/`type-var` errors on `conftest.py`'s untouched `engine`/`session` fixtures). Plan 04-03 measured the identical 44/13 at the base commit and deferred them for the same reasons.

The meaningful property holds: **this change adds zero new mypy errors.** `mypy backend/app` → 44 source files, no issues. `mypy backend | grep -c "test_analytics_metadata.py\|analytics/metadata.py"` → 0.

Recorded here rather than in a phase-level `deferred-items.md`, which would be an add/add merge conflict between concurrent worktree agents.

## Requirements Status

The plan frontmatter lists `requirements: [DQ-01, DQ-02]`. **Neither was marked complete in `REQUIREMENTS.md`, deliberately.**

DQ-01 is "data freshness surfaced per source so Claude knows when data may be stale". This plan builds the *builder*; no analytics response carries the envelope yet, and no MCP tool returns one. `WeeklyVolumeResult`, `MuscleGroupVolumeResult` and `TrainingFrequencyResult` all declare `coverage` and `freshness` fields (04-02), and plans **04-06, 04-07 and 04-08 carry DQ-01/DQ-02 in their own frontmatter** — they are where the envelope actually reaches a response, and where the check-off honestly belongs. Marking it here would record "freshness is surfaced" against a codebase where nothing surfaces it.

`REQUIREMENTS.md` is also a shared artifact under concurrent modification by parallel worktree agents, so writing to it from here risks a merge conflict for a claim that is not yet true. Same call as plans 04-01, 04-02 and 04-03.

**Relationship to the requirements:** DQ-01's mechanism (`build_freshness`, `FRESHNESS_RESOURCES_*`) and DQ-02's mechanism (`build_coverage`, `INSUFFICIENT_DATA_SESSION_THRESHOLD`, `is_insufficient`) are complete, tested and security-proven. Consumers need one line each.

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-03 | mitigate | **Done, both layers.** `build_freshness` reads only `state.last_synced_at` (grep: zero `state.last_*`/`state.cursor*` attribute accesses). Fast-suite structural test pins `FreshnessMetadata.model_fields == {"resources"}` and the `extra="forbid"` rejection; integration test seeds `zz-analytics-leak-canary-9f3a` through `record_sync_error` and asserts it is absent from `model_dump_json()`, guarded against vacuity. Both proven red against injections. |
| T-04-02 | mitigate | **Done, and widened.** `user_id` keyword-only with no default on all four functions; both SQL statements filter `Workout.user_id == user_id`. `test_coverage_does_not_count_another_users_workouts` pins the count (3 vs 1) and `test_earliest_data_at_is_none_without_any_workouts` now pins the all-time lookup, which the plan's own version did not (Deviation 3). |
| T-04-01 | mitigate | **Done.** Both predicates are SQLAlchemy Core expressions over bound parameters; `test_analytics_uses_no_raw_sql_text` (04-02) covers this module automatically via `rglob`. |
| T-04-06 | accept | **Unchanged, correctly.** `sessions_in_window` is a single indexed `COUNT(*)` returning one integer regardless of range. The row-producing clamp remains 04-05's (`rollup.py`). |
| T-04-07 | mitigate | **Done.** `insufficient_data` is derived from the count through `is_insufficient`, never caller-supplied; both sides of the boundary are pinned, so an off-by-one in the comparison operator cannot ship. |
| T-04-09 | mitigate | **Done.** Zero `commit`/`flush`/`add` and no write-construct import; `test_analytics_never_writes` (04-02) enforces it statically over this file. |

No new security-relevant surface: no endpoint, no auth path, no file access, no schema change, no migration. No threat flags to raise.

## Known Stubs

None. Every function queries real rows and is exercised against the container.

## Issues Encountered

- **Stale worktree base and missing `.venv`** — both documented as Deviations 4 and 5. Fourth consecutive wave hitting the stale-base issue in this phase.
- No debugging cycle was needed: `metadata.py` was green against the container on first run, and all 11 tests passed on first execution.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready for waves 3 and 4 and for Phase 6.**

Contract for 04-06, 04-07 and 04-08 (the plans that actually satisfy DQ-01/DQ-02):

```python
from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,   # per-muscle answers: workouts AND exercise_templates
    FRESHNESS_RESOURCES_WORKOUTS, # workout-only answers
    build_coverage,
    build_freshness,
    is_insufficient,              # for U-03's PER-MUSCLE insufficient_data flag
)
```

- Pass the **same** `AsyncSession` these functions receive; they never open their own, so `golden_workout`'s flushed-not-committed rows are visible.
- `utc_start`/`utc_end` must come from `local_range_bounds` (04-01) — the same helper the tests call, so a test cannot pass against a window the production code computes differently.
- Choose the freshness tuple by what the answer actually depends on. A per-muscle number that reports only the `workouts` timestamp is the exact failure DQ-01 exists to prevent.
- Use `is_insufficient` for `MuscleGroupVolume.insufficient_data` and `MuscleGroupFrequency.insufficient_data` too. A second threshold literal is how the response-level and row-level flags would eventually disagree about the same window.
- `build_coverage` issues two queries. If a caller already computed the session count, call `is_insufficient` and `earliest_workout_at` directly rather than double-counting.

**Carried forward:** the 44 pre-existing `backend/tests/` mypy errors (Deferred Issues) — a standalone cleanup candidate, not a Phase 4 analytics plan.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/metadata.py`
- FOUND: `backend/tests/test_analytics_metadata.py`

Commits verified in `git log`:

- FOUND: `35cf43d` feat(04-04): add analytics freshness and coverage metadata (DQ-01, DQ-02)
- FOUND: `05d42da` test(04-04): prove DQ-01 per-resource freshness and the no-leak guarantee
- FOUND: `b6c6dea` test(04-04): pin the D-05 boundary, all-time earliest_data_at and tenant scoping

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*

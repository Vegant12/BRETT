---
phase: 06-mcp-tools
plan: 03
subsystem: database
tags: [sqlalchemy, postgres, pytest, testcontainers, repository, mcp]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization
    provides: workouts / workout_exercises / workout_sets schema and the PROVIDER_HEVY constant
  - phase: 04-volume-frequency-analytics
    provides: the hard-set exclusion rule and the operand-presence tonnage gate this projection reuses
  - phase: 05-progression-records-recomposition-analytics
    provides: GoldenBuilder.body_measurement and the bodyweight/recomposition consumers worst_case_history seeds for
provides:
  - "recent_workout_summaries: newest-first, limit-capped per-workout summaries in one aggregate"
  - "workout_detail: the full exercise/set tree for one workout by Hevy external id, truncating from the end"
  - "hard_set_predicates as a public, importable definition of the hard-set rule"
  - "committed_history fixture: a GoldenBuilder with a scoped purge-and-commit teardown"
  - "worst_case_history fixture: 52 weeks x 5 sessions x 30 templates plus body measurements and sync_state"
affects:
  - 06-04-PLAN (fitness_get_recent_workouts / fitness_get_workout tool bodies)
  - 06-09-PLAN (the static read-only guard over app/db/repositories)
  - 06-10-PLAN (the D-13 byte-budget test, which consumes worst_case_history)
  - every later Phase 6 integration test needing committed data

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Purpose-built read-only projections in app/db/repositories/, never raw table access (MCP-03)"
    - "The hard-set rule applied as a SQL case, never a WHERE filter, so warm-up-only workouts survive"
    - "Committed-with-compensating-purge test fixtures, for code that opens its own session"

key-files:
  created:
    - backend/app/db/repositories/workouts.py
    - backend/tests/test_repository_workouts.py
  modified:
    - backend/app/analytics/rollup.py
    - backend/app/analytics/records.py
    - backend/tests/conftest.py
    - backend/tests/test_analytics_rollup.py

key-decisions:
  - "workout_detail takes a required tz keyword: WorkoutDetailRow.local_day cannot be computed without one, and a module-level default timezone is how a wrong-timezone bug passes every test"
  - "The committed_history purge uses SQLAlchemy Core delete() keyed on _MCP_PURGE_TABLES rather than text() with an interpolated table name, so no table name ever reaches the driver as a string fragment"
  - "Truncation in workout_detail drops exercises left with zero sets rather than reporting them empty, since an empty set list reads as 'performed and recorded nothing'"
  - "worst_case_history writes the workout tree with three batched inserts instead of GoldenBuilder.workout, because ~5,200 set rows one statement at a time makes the budget test unusably slow"

patterns-established:
  - "The app/db -> app.analytics import arrow is drawn exactly once, in workouts.py, to reuse hard_set_predicates rather than restate the hard-set rule"
  - "Repository rows are frozen slotted dataclasses, not Pydantic: app/mcp/tools/schemas.py owns the wire shape"
  - "Returned rows carry external_id only; the surrogate workouts.id appears in GROUP BY and joins but in no returned field (T-06-08)"

requirements-completed: [MCP-02, MCP-03, MCP-05]

# Metrics
duration: 34min
completed: 2026-08-31
---

# Phase 06 Plan 03: Recent-Workouts & Workout-Detail Repository Summary

**Two read-only SQL projections (`recent_workout_summaries`, `workout_detail`) that reuse Phase 4's hard-set and operand-presence rules by importing them, plus the committed-history test fixtures every later Phase 6 integration test depends on.**

## Performance

- **Duration:** ~34 min
- **Started:** 2026-08-31T18:47:00Z
- **Completed:** 2026-08-31T19:21:00Z
- **Tasks:** 3
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- `hard_set_predicates` is public in `rollup.py` with no stale `_hard_set_predicates` spelling anywhere in the repo, so the hard-set rule has exactly one definition shared by the analytics layer and the Phase 6 projection.
- `recent_workout_summaries` answers D-09 in a single aggregate: outer-joined so a workout with no sets still appears, hard sets and tonnage computed through `case` expressions rather than a WHERE filter, tonnage cast to `Numeric(12,3)` and reported as `None` rather than `0` when no set had both operands, ordered newest-first with an `external_id` tie-break.
- `workout_detail` answers D-11/D-12: keyed on the Hevy external id as a bound parameter, returns every set including warm-ups with `set_type` carried per set, truncates from the end at `max_sets` while `total_sets` reports the true pre-truncation count, and returns `None` for an unknown id rather than raising (Pitfall 3).
- `committed_history` and `worst_case_history` seed data a separate session can see, with a purge that was proven to leave the database clean by running the 260-workout fixture immediately before a test asserting exact two-workout set membership in the same process.
- 10 new integration tests, all green; the full suite is 503 passing.

## Task Commits

1. **Task 1: Promote hard_set_predicates and create the read-only workouts repository** - `20c666d` (feat)
2. **Task 2: Add committed_history and worst_case_history fixtures to conftest.py** - `55ff0fb` (test)
3. **Task 3: Create backend/tests/test_repository_workouts.py** - `45dd672` (test)

## Files Created/Modified

- `backend/app/db/repositories/workouts.py` (created, 366 lines) - The two projections, four frozen slotted row dataclasses, and the end-truncation helper. Imports no write construct and calls no session mutator.
- `backend/tests/test_repository_workouts.py` (created, 388 lines) - Ten integration tests over a hand-computable two-workout history.
- `backend/app/analytics/rollup.py` (modified) - `_hard_set_predicates` renamed public; docstring extended with why.
- `backend/app/analytics/records.py` (modified) - Prose reference updated to the new spelling.
- `backend/tests/conftest.py` (modified, +304 lines) - `_MCP_PURGE_TABLES`, `_mcp_purge_statements`, `committed_history`, `worst_case_history`, the `_worst_case_anchor` helper and the shape constants.
- `backend/tests/test_analytics_rollup.py` (modified) - Docstring reference updated to the new spelling.

## Decisions Made

- **`workout_detail` takes `tz`.** The plan's signature omitted it while `WorkoutDetailRow` requires a `local_day`. Adding a required `tz` keyword matches `recent_workout_summaries` and honours `app/core/time.py`'s rule that a module-level default timezone lets a wrong-timezone bug pass every test. Without it the same session would be dated differently in the list and in the detail view.
- **Core `delete()` for the purge, not `text()` with an f-string table name.** The plan sketched `text(f'DELETE FROM {table} ...')`. Ruff `S608` is enabled repo-wide and `backend/tests/*` only ignores `S101`/`S105`/`S106`, so that form needs a `noqa`. `_MCP_PURGE_TABLES` is retained as the canonical FK-child-first ORDER and the statements are looked up by name, so a dropped entry is a `KeyError` rather than a silently skipped purge.
- **`committed_history` teardown also deletes the `ANALYTICS_SECOND_USER_ID` user row.** The cross-tenant test commits a second user; without this the row outlives the test and the next module's second-user insert violates the primary key. `CASCADE` takes their whole tree, so it is one extra statement.
- **Truncation drops emptied exercises.** `_truncate_from_the_end` only runs when the true count already exceeds the cap, so an exercise left with no sets is one truncation emptied; reporting it with an empty set list would read as "you performed this exercise and recorded nothing".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `workout_detail` had no way to compute `local_day`**
- **Found during:** Task 1 (read-only workouts repository)
- **Issue:** The plan specified `workout_detail(session, *, user_id, external_id, max_sets)` while the `WorkoutDetailRow` dataclass it returns carries a required `local_day: dt.date`. `app.core.time.local_day` requires a timezone and the codebase forbids a module-level default.
- **Fix:** Added a required `tz: str` keyword parameter, matching `recent_workout_summaries`, and documented in the docstring why the two functions must agree about which local day a workout belongs to.
- **Files modified:** `backend/app/db/repositories/workouts.py`
- **Verification:** `test_local_day_uses_the_users_timezone` and `test_workout_detail_returns_every_set_including_warmups`; the plan's own test-invocation sketches elide the leading arguments with `...`, so this is compatible with the tests as specified.
- **Committed in:** `20c666d`

**2. [Rule 3 - Blocking] The purge sketch would fail lint**
- **Found during:** Task 2 (conftest fixtures)
- **Issue:** The plan's `text(f'DELETE FROM {table} WHERE user_id = :uid')` trips Ruff `S608` (hardcoded-sql-expression), which is enabled for `backend/tests/` — the per-file ignore list covers only `S101`, `S105` and `S106`.
- **Fix:** Built the eight deletes as SQLAlchemy Core `delete()` statements looked up by the names in `_MCP_PURGE_TABLES`, keeping the constant's documented ordering role and removing the string-fragment surface entirely. The two child tables without a `user_id` column are scoped through their FK chain with `select()` subqueries, exactly as the plan required.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `uv run ruff check backend/tests` passes with no `noqa`; the purge was proven effective by running the 260-workout `worst_case_history` probe immediately before `test_a_workout_with_only_warmups_still_appears`, which asserts exact `{W1, W2}` set membership, in the same pytest process.
- **Committed in:** `55ff0fb`

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking issues)
**Impact on plan:** Both were gaps in the plan's own specification, not scope changes. No new dependency, no new file, no behaviour beyond what the plan described. `git diff --stat pyproject.toml uv.lock` is empty.

## Issues Encountered

- **One acceptance criterion is arithmetically off by one.** The plan asserts `grep -c 'hard_set_predicates()' backend/app/analytics/rollup.py` returns `2`; it returns `3`. The definition line `def hard_set_predicates() -> ...` contains that substring, and under the old `_hard_set_predicates` spelling the same grep pattern would have matched the definition too — so the expected value was carried over unchanged. The criterion's intent (exactly two call sites) is satisfied: line 178 is the definition, lines 247 and 353 are the two call sites. No code change was made for this.
- **The worktree branch was based on an older commit than the plan's stated base.** Corrected with the prescribed `git reset --hard 38088b1` before any work began.
- **The worktree had no `.venv`.** `uv sync --all-groups` with `UV_LINK_MODE=copy` (the cache and the worktree are on different filesystems).
- **Six pre-existing mypy errors in `backend/tests/conftest.py`** on the untouched `engine` and `session` async-generator fixtures (`type-var` / `misc` / `unused-ignore`). Out of scope per the scope boundary — not caused by this plan's changes, and `conftest.py` is not in the plan's mypy verification scope. Left unfixed and unlogged elsewhere; noted here.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 06-04 can import `recent_workout_summaries` and `workout_detail` directly. Note the `tz` keyword on both; the tool layer supplies it from `users.timezone`.
- Plan 06-09's static read-only guard over `app/db/repositories/` will pass as written: `workouts.py` imports no `insert`/`update`/`delete` and calls no `session.commit`/`flush`/`add`/`add_all`.
- Plan 06-10's byte-budget test can depend on `worst_case_history`. Verified shape: 260 workouts, 1,300 exercises, 5,200 sets, 30 templates over 75 muscle mappings spanning all 19 canonical groups, 120 body measurements, 3 `sync_state` rows. Newest session is today; each session reports 15 hard sets and `Decimal("9310.000")` of tonnage. Seed-plus-purge costs ~3 s.
- The shape constants (`WORST_CASE_TEMPLATES`, `WORST_CASE_WEEKS`, `WORST_CASE_SESSIONS_PER_WEEK`, `WORST_CASE_EXERCISES_PER_WORKOUT`, `WORST_CASE_SETS_PER_EXERCISE`, `WORST_CASE_BODY_MEASUREMENT_DAYS`) are exported from `tests/conftest.py` so budget assertions can be written against the same numbers the fixture seeded.
- No blockers.

**`REQUIREMENTS.md` deliberately not updated.** All eleven plans in phase 06 declare the same `requirements: [MCP-02, MCP-03, MCP-05]`, so the file is a shared orchestrator artifact for this wave: eleven worktree agents checking the same three boxes is a guaranteed merge conflict on lines 63-66 and 158-160. It would also be false — MCP-02 names eleven tools and this plan ships none of them, only the two queries two of them are built on. The orchestrator should mark MCP-02, MCP-03 and MCP-05 complete once the phase closes.

## Self-Check: PASSED

- All 7 claimed files exist on disk.
- All 3 claimed commits (`20c666d`, `55ff0fb`, `45dd672`) exist in `git log`.
- No stub patterns in either created file (the single `placeholder` match is prose describing the outer join's NULL row, not unwired code).
- Plan verification block, all green: `grep -rn '_hard_set_predicates' backend/` returns nothing; `uv run ruff check backend/app backend/tests` passes; `uv run mypy backend/app/db/repositories/workouts.py backend/app/analytics/rollup.py` passes; `git diff --stat pyproject.toml uv.lock` against the plan base is empty; `uv run pytest backend/tests -q` reports 503 passed.

## Threat Flags

None. Every file touched is behind the existing trust boundaries the plan's threat register already covers; no new network endpoint, auth path, file access pattern or schema change was introduced.

---
*Phase: 06-mcp-tools*
*Completed: 2026-08-31*

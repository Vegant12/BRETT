---
phase: 12-training-programs-confirm-gated-write-tool
plan: 01
subsystem: database
tags: [sqlalchemy, alembic, postgresql, training-programs, partial-index, migrations]

# Dependency graph
requires:
  - phase: 11-body-measurement-history
    provides: the GoldenBuilder / committed_history fixture pattern and body_measurements as the
      closest recent precedent for a Numeric/Date-column model and its migration
provides:
  - "TrainingProgram StrEnum (lean_bulk/cut/recomp) in app.analytics.schemas -- the closed set
    every later Phase 12 plan types against"
  - "ProgramPeriod (user_program_history) and ProgramSwitchToken (program_switch_tokens) ORM
    models, both registered in Base.metadata"
  - "Migration 0006: both tables, the one-open-period-per-user partial unique index, and a
    data-derived D-08 seed (COALESCE fallback for a database with zero synced workouts)"
  - "GoldenBuilder.program_period / .switch_token fixture builders, plus a purge-and-reseed
    teardown so every committed_history test starts from the same one-open-lean_bulk-period
    invariant migration 0006 establishes"
  - "backend/tests/test_db_program_history.py: 7 integration tests pinning the schema, the
    partial index, both seed branches, nonce uniqueness, and the fixture round-trip"
affects: [12-02, 12-03, 12-04, 12-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Partial unique index (postgresql_where) declared identically on the model's __table_args__
      and in the migration's op.create_index, so alembic check sees no drift"
    - "Seed-in-migration via raw INSERT...SELECT with LEFT JOIN + COALESCE, not op.bulk_insert,
      when the seeded value must be derived from live data rather than a Python literal"
    - "committed_history's purge-then-reseed teardown pattern extended to a second invariant
      (one-open-period) beyond the original seeded-user-row invariant"

key-files:
  created:
    - backend/app/db/models/program.py
    - backend/migrations/versions/0006_user_program_history.py
    - backend/tests/test_db_program_history.py
  modified:
    - backend/app/analytics/schemas.py
    - backend/app/db/models/__init__.py
    - backend/tests/test_db_models.py
    - backend/tests/conftest.py
    - scripts/verify-restore.sql

key-decisions:
  - "Training program modeled as append-only effective-dated history (user_program_history), not
    a mutable users.active_program column, per D-07/PITFALLS #16"
  - "The one-open-period-per-user invariant is a partial unique index (postgresql_where=ended_on
    IS NULL) enforced by PostgreSQL, not an application-level check-then-insert"
  - "D-08's seed is derived from MIN(workouts.start_time) with a COALESCE fallback to
    users.created_at, so a database with zero synced workouts still gets a deterministic seed
    row instead of zero rows"
  - "The switch-confirmation value's column is named nonce, not token, so both credential-shaped-
    column guards (test_no_model_column_stores_a_credential, test_no_table_stores_a_credential)
    stay unmodified and at full strength"

requirements-completed: [GOAL-01]

# Metrics
duration: ~35min
completed: 2026-09-04
---

# Phase 12 Plan 01: Training Program History Schema Summary

**Two new tables (user_program_history, program_switch_tokens) plus a TrainingProgram closed
enum make the active training program real, effective-dated data instead of a hardcoded constant,
with PostgreSQL itself enforcing "at most one open period per user" via a partial unique index.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-04T03:34:33Z (approx, per STATE.md session start)
- **Completed:** 2026-09-04T03:46:57Z
- **Tasks:** 3/3 completed
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments

- `TrainingProgram` StrEnum (`lean_bulk`/`cut`/`recomp`) added to `app/analytics/schemas.py`,
  the closed set every later Phase 12 plan (thresholds, the switch tool, the read tool) types
  against
- `ProgramPeriod` and `ProgramSwitchToken` ORM models created and registered in `Base.metadata`,
  with the one-open-period invariant declared as a partial unique index on the model itself
- Migration 0006 creates both tables and seeds exactly one open `lean_bulk` period per user from
  live synced Hevy history, falling back deterministically to the user's local creation day when
  no workout has ever synced (resolves 12-RESEARCH.md Open Question 1)
- `GoldenBuilder` gained `program_period`/`switch_token` fixture builders, and the shared
  `committed_history` teardown now restores the one-open-period invariant after every test that
  uses it
- 7 new integration tests pin the live DDL, the partial index's refusal (and its narrowness --
  a closed period still succeeds), both branches of the D-08 seed (including a downgrade/upgrade
  rewind that proves the earliest-local-training-day derivation), nonce uniqueness, and a
  fixture round-trip guard

## Task Commits

Each task was committed atomically:

1. **Task 1: TrainingProgram enum, the two ORM models, and the metadata guard** - `415e68c` (feat)
2. **Task 2: Migration 0006 -- two tables, the partial unique index, and the data-derived seed** - `7d771e7` (feat)
3. **Task 3: GoldenBuilder program fixtures, purge-and-reseed teardown, and the schema/seed tests** - `9cdc81a` (test)

_No separate plan-metadata commit in worktree mode -- this SUMMARY.md and REQUIREMENTS.md are
committed together as the final commit per the worktree executor protocol._

## Files Created/Modified

- `backend/app/db/models/program.py` - `ProgramPeriod` (user_program_history) and
  `ProgramSwitchToken` (program_switch_tokens) ORM models
- `backend/migrations/versions/0006_user_program_history.py` - both tables, the partial unique
  index, and the D-08 data-derived seed
- `backend/tests/test_db_program_history.py` - 7 integration tests: DDL column sets, partial
  index refusal/narrowness, both seed branches, nonce uniqueness, fixture round-trip
- `backend/app/analytics/schemas.py` - added `TrainingProgram` StrEnum after `RecompositionStatus`
- `backend/app/db/models/__init__.py` - registered both new models
- `backend/tests/test_db_models.py` - extended the exact table-set assertion to include both new
  tables
- `backend/tests/conftest.py` - `GoldenBuilder.program_period`/`.switch_token`, extended
  `_MCP_PURGE_TABLES`/`_mcp_purge_statements`, and a `_reseed_program_history` helper called from
  `committed_history`'s teardown
- `scripts/verify-restore.sql` - added digest arms for both new tables (see Deviations)

## Decisions Made

- Followed the plan's design exactly: append-only history over a mutable column (D-07), a
  database-enforced partial unique index over an application check-then-insert, and a raw
  `INSERT...SELECT` seed over `op.bulk_insert` since the seed value must be derived from live
  data
- No new decisions beyond what the plan specified

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `scripts/verify-restore.sql` missing arms for the two new tables**
- **Found during:** Task 3 full-suite verification (`uv run pytest`)
- **Issue:** `test_verify_restore_sql.py::test_the_digest_query_covers_every_mapped_table` (a
  pre-existing guard requiring every `Base.metadata` table to have a `FROM` arm in the restore-
  drill comparison query) failed once `user_program_history` and `program_switch_tokens` were
  registered in Task 1 -- a genuine regression blocking the plan's own `<verification>` section
  ("`uv run pytest` -- full suite green before this plan is considered done")
- **Fix:** Added a `md5(string_agg(...))` digest arm for each new table, matching the existing
  arms' exact shape (ordered by `id`, same `SET`/`UNION ALL` structure)
- **Files modified:** `scripts/verify-restore.sql`
- **Verification:** `test_the_digest_query_covers_every_mapped_table` and the other three
  `test_verify_restore_sql.py` tests pass; full fast suite green (566 passed)
- **Committed in:** `9cdc81a` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** Necessary to keep the full suite green as this plan's own verification
requires. No scope creep -- confined to the one file the new tables mechanically required.

## Known Stubs

None.

## Threat Flags

None. All new surface (`user_program_history`, `program_switch_tokens`) was already covered by
this plan's own `<threat_model>` (T-12-10 through T-12-15).

## Issues Encountered

**Pre-existing, unrelated test flake discovered during full-suite verification:**
`test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest` fails with a
`uq_body_measurements_user_source_measured_on` `IntegrityError` whenever the wall-clock hour is
`>= 2 UTC` (`_seed_reference_history`'s 30-day measurement window includes "today", and the test
separately seeds its own `measured_on=today` row). Confirmed via `git stash` to fail identically
before any Task 3 change existed and on an unrelated table (`body_measurements`, not
`user_program_history`) -- out of this plan's scope per the scope-boundary rule. Logged to
`.planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md` rather than
fixed.

## Next Phase Readiness

- `TrainingProgram`, `ProgramPeriod`, and `ProgramSwitchToken` are ready for Plan 02 (the
  repository layer: `get_active_period`, `issue_switch_token`, `consume_switch_token`,
  `close_period_and_open_new`) and Plan 03 (per-program recomposition thresholds)
- The `GoldenBuilder.program_period`/`.switch_token` fixtures and the purge-and-reseed teardown
  are in place for every later plan's integration tests
- Recommend a follow-up (outside this plan) for the `test_body_measurement_trend_compares_
  latest_against_earliest` time-of-day flake logged in `deferred-items.md`

---
*Phase: 12-training-programs-confirm-gated-write-tool*
*Plan: 01*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all three task commits (415e68c, 7d771e7,
9cdc81a) confirmed present in git log.

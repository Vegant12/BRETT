---
phase: 03-hevy-integration-normalization
plan: 04
subsystem: database
tags: [postgres, sqlalchemy, alembic, asyncpg, upsert, on-conflict, migrations]

# Dependency graph
requires:
  - phase: 03-02
    provides: "workout model conventions (PGUUID PKs, named UniqueConstraints, Numeric-never-Float, TIMESTAMPTZ, no relationship()), migration chain at revision 0003, test_metadata_contains_expected_tables"
  - phase: 03-03
    provides: "CanonicalMuscleGroup / MuscleRole / MappingSource StrEnums whose .value strings exercise_muscles stores"
  - phase: 01
    provides: "Base + TimestampMixin + NAMING_CONVENTION, users table, alembic env.py wired to Base.metadata, testcontainers Postgres fixtures"
provides:
  - "exercise_templates: Hevy's raw template fields incl. the untranslated muscle strings that are the NORM-02 audit baseline"
  - "exercise_muscles: the canonical derived mapping (muscle_group, role, source) with no weight column"
  - "exercise_muscle_overrides: the manual correction layer as a SEPARATE table, so the baseline is never mutated"
  - "body_measurements: one row per (user, source, calendar date) carrying all 17 Hevy metrics"
  - "sync_state: per-(user, provider, resource) last_synced_at, events cursor, page cursor, status, redacted last_error"
  - "app.db.repositories.sync_state: get/ensure/mark_running/advance_cursor_page/complete_sync/record_sync_error + format_sync_error"
  - "migration 0004, round-tripping and drift-free against a live PostgreSQL 18"
  - "test_no_table_stores_a_credential: an information_schema guard that fails on any future credential column"
affects: [03-05, 03-06, 03-07, 03-08, 04-analytics, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Repository helpers own no session, no engine, and never commit"
    - "ON CONFLICT bound to a unique constraint BY NAME, not by column list"
    - "Exception rendering opt-in via a curated `safe_message` attribute"

key-files:
  created:
    - backend/app/db/models/exercise.py
    - backend/app/db/models/body.py
    - backend/app/db/models/sync_state.py
    - backend/app/db/repositories/__init__.py
    - backend/app/db/repositories/sync_state.py
    - backend/migrations/versions/0004_hevy_reference_tables.py
    - backend/tests/test_sync_state.py
  modified:
    - backend/app/db/models/__init__.py
    - backend/app/db/models/user.py
    - backend/tests/test_db_models.py
    - backend/tests/test_hevy_schema.py

key-decisions:
  - "No credential storage ships in Phase 3: the table is named sync_state, not external_connections, and an information_schema test fails on any credential-shaped column in any future migration"
  - "body_measurements.measured_on is a DATE, not a TIMESTAMPTZ — a calendar date is not an instant, so this is not a FOUND-04 exception"
  - "The override layer is a separate table with per-template replacement semantics, so 'this exercise does not work rear delts' is expressible"
  - "Muscle taxonomy stored as VARCHAR, never a Postgres ENUM, so a taxonomy tweak is not a migration"
  - "Every sync_state mutator is an upsert (ON CONFLICT DO UPDATE), so a first-run resource needs no prior ensure_sync_state call"
  - "updated_at is set explicitly in the ON CONFLICT SET clause — SQLAlchemy's onupdate does not fire for upserts"

patterns-established:
  - "Caller-owns-the-transaction repositories: D-08 needs the checkpoint and the page it describes in ONE commit, which a self-committing helper makes impossible"
  - "Redaction by opt-in: format_sync_error() stores a class name unless the raiser curated a safe_message, defending against pydantic.ValidationError.__str__ rendering input_value=..."
  - "Two-layer schema guards: a fast Base.metadata assertion plus a live information_schema assertion for the same invariant"

requirements-completed: [HEVY-06, HEVY-07, HEVY-09, NORM-02, NORM-03]

# Metrics
duration: 12min
completed: 2026-08-29
---

# Phase 3 Plan 04: Hevy Reference Tables and Sync Bookkeeping Summary

**Five reference tables (exercise templates, canonical muscle map, manual override layer, date-keyed body measurements, per-resource sync state) plus an upsert-based sync_state repository that never commits and never stores a credential.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-29T06:35:45Z
- **Completed:** 2026-08-29T06:47:26Z
- **Tasks:** 3
- **Files modified:** 11 (7 created, 4 modified)

## Accomplishments

- `Base.metadata` now holds the complete nine-table Phase 3 schema, and migration `0004` builds
  the five new tables, reverses cleanly to `base`, and reports zero drift under `alembic check`
  against a live PostgreSQL 18.
- HEVY-09 is answerable honestly: three `sync_state` rows for one user hold three genuinely
  independent `last_synced_at` values, proven against a real container rather than asserted.
- T-03-11 is enforced structurally rather than by review. No credential column exists, the table
  is named `sync_state` so its name cannot invite one, and `test_no_table_stores_a_credential`
  queries `information_schema.columns` so a credential column added by any *future* migration
  fails the suite.
- T-03-12 is closed: `format_sync_error()` stores only an exception class name unless the raiser
  curated a `safe_message`, so a `pydantic.ValidationError` carrying workout titles and
  body-composition numbers cannot reach the `last_error` column.
- D-08's resume checkpoint is expressible: no repository helper commits, so the caller can land
  the cursor and the page of rows it describes in one transaction.
- Full suite green: **156 passed** (integration included, Docker-backed).

## Task Commits

Each task was committed atomically. Tasks 1 and 3 were TDD, so each has a `test` (RED) commit
followed by a `feat` (GREEN) commit. Neither needed a REFACTOR pass.

1. **Task 1: Five reference models** — `66059ec` (test, RED) → `f7b0b39` (feat, GREEN)
2. **Task 2: Migration 0004 and the metadata guard update** — `930070e` (feat)
3. **Task 3: sync_state repository** — `1d0b065` (test, RED) → `b586e6e` (feat, GREEN)

## Files Created/Modified

**Created**

- `backend/app/db/models/exercise.py` — `ExerciseTemplate` (raw Hevy fields incl. the untranslated
  muscle strings), `ExerciseMuscle` (canonical mapping), `ExerciseMuscleOverride` (correction layer).
- `backend/app/db/models/body.py` — `BodyMeasurement`, keyed `(user_id, source, measured_on)` with
  all 17 metrics as nullable `Numeric`.
- `backend/app/db/models/sync_state.py` — `SyncState`, one row per `(user, provider, resource)`.
- `backend/app/db/repositories/__init__.py` — package docstring stating the no-session/no-engine rule.
- `backend/app/db/repositories/sync_state.py` — the seven bookkeeping helpers.
- `backend/migrations/versions/0004_hevy_reference_tables.py` — DDL for all five tables.
- `backend/tests/test_sync_state.py` — 10 tests (8 integration, 3 fast redaction tests).

**Modified**

- `backend/app/db/models/__init__.py` — registers the five new models (Pitfall 8: a model missing
  here makes autogenerate emit an empty migration with no error).
- `backend/app/db/models/user.py` — corrected a stale D-07 note (see Deviations).
- `backend/tests/test_db_models.py` — nine-table assertion plus eight new shape tests.
- `backend/tests/test_hevy_schema.py` — five new live-schema tests.

## Decisions Made

- **`measured_on` is a `Date`.** Hevy's field is `format: date`, the endpoint keys on it
  (`GET/PUT /v1/body_measurements/{date}`), and a `POST` 409s if an entry exists for that date.
  Storing a TIMESTAMPTZ would force the sync to invent a time of day, and two syncs of the same
  entry could then disagree about which row they mean.
- **Every mutator is an upsert, not an UPDATE.** The plan specified `on_conflict_do_nothing` for
  `ensure_sync_state`; the mutators use `on_conflict_do_update` bound to the same constraint. An
  UPDATE against a not-yet-existing row silently affects zero rows, which would make a first run
  of a new resource record no progress at all and report no error.
- **`updated_at` is written explicitly in the `ON CONFLICT ... SET` clause.** SQLAlchemy's
  `onupdate=func.now()` fires for `update()` statements but is not injected into an upsert's SET
  clause, so omitting it would freeze the audit timestamp at row creation.
- **`complete_sync` writes `cursor_timestamp` only when the caller supplies it.** Passing `None`
  through unconditionally would reset the HEVY-02 events cursor to the beginning of time on every
  completed full sync (RESEARCH Pitfall 1).
- **Constraint bound by name, not by column list.** `ON CONFLICT ON CONSTRAINT
  uq_sync_state_user_provider_resource` raises immediately if the constraint is renamed, rather
  than silently degrading into a duplicate-row insert.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Corrected a stale D-07 note that invited the credential column this plan exists to refuse**

- **Found during:** Task 1 (model creation)
- **Issue:** `backend/app/db/models/user.py` carried a comment from Phase 1 reading "the
  provider-credentials table and the `connections` link to it are deliberately absent. **They ship
  in Phase 3 alongside real encryption**". This plan decided the opposite. T-03-11's stated
  mitigation is that the table is named `sync_state` "so the name cannot invite one later" — a
  standing comment promising the credential table in this very phase directly undermines that
  mitigation and would read as a to-do to the next person in this file.
- **Fix:** Rewrote the note to record the resolution: no credential table is coming, `sync_state`
  ships instead, and `Settings.hevy_api_key` stays the env-var `SecretStr` it already is.
- **Files modified:** `backend/app/db/models/user.py`
- **Verification:** `uv run pytest backend/tests -q` (156 passed); the comment is prose only, and
  `test_no_model_column_stores_a_credential` plus `test_no_table_stores_a_credential` enforce the
  actual invariant.
- **Committed in:** `f7b0b39` (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Applied `ruff format` manually because parallel execution requires `--no-verify`**

- **Found during:** Tasks 1–3
- **Issue:** `ruff-format` is a checked-in `pre-commit` hook, but this executor runs in a worktree
  and must commit with `--no-verify` to avoid hook contention with sibling agents. Unformatted
  files would land on the branch and fail the hook for the next developer.
- **Fix:** Ran `uv run ruff format` over `backend/` before each commit.
- **Files modified:** `backend/app/db/models/exercise.py`, `backend/app/db/models/sync_state.py`,
  `backend/app/db/repositories/sync_state.py`
- **Verification:** `uv run ruff format --check` clean; `uv run ruff check .` passes.
- **Committed in:** `f7b0b39`, `b586e6e`

### Ordering adjustment (not a deviation in substance)

Task 2 specified updating `test_metadata_contains_expected_tables` to the nine-table set. That
update was made in Task 1's RED commit instead, because it *is* the first bullet of Task 1's
`<behavior>` block ("`Base.metadata.tables` gains exactly ..."). Doing it in Task 2 would have left
Task 1's commit with a knowingly-failing test. The docstring change Task 2 also asked for ("This is
the complete Phase 3 schema.") was applied in the same edit. Net content is identical.

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking)
**Impact on plan:** Both were necessary for correctness and repo hygiene. No scope creep — nothing
outside the plan's declared `files_modified` was touched except `user.py`, whose stale comment
contradicted this plan's own security decision.

## Issues Encountered

- **Alembic could not be invoked directly.** `alembic.ini` sets `script_location = migrations`
  relative to `backend/`, so `python -m alembic` from the repo root fails with "No 'script_location'
  key found in configuration". Resolved by invoking it through `subprocess.run(..., cwd="backend")`,
  which is exactly what `conftest.py`'s `alembic` fixture already does — the same entrypoint
  production uses, rather than an in-process API.
- **Autogenerate needed a live database at revision 0003.** Spun up a throwaway
  `postgres:18-alpine` container, upgraded it to `0003`, autogenerated, then hand-reviewed the
  output into project style (`op.f()` on every constraint name, `str | Sequence[str] | None`
  annotations, `collections.abc.Sequence`, explanatory comments) and removed the container.
  Autogenerate got the substance right unaided, including `sa.Date()` and
  `postgresql.ARRAY(sa.String(32))` with its `'{}'::varchar[]` server default.

## Verification Results

| Check | Result |
|---|---|
| `uv run pytest backend/tests -q` (full, Docker) | **156 passed** |
| `alembic upgrade head` → `downgrade base` → `upgrade head` | round-trips, rc 0 each |
| `alembic check` | "No new upgrade operations detected" |
| `uv run mypy backend/app` | Success, 29 source files |
| `uv run ruff check .` | All checks passed |
| `information_schema` credential-column scan | zero matches |

Success criteria from the plan, individually:

- Nine tables in `Base.metadata` and in the migrated database — verified by
  `test_metadata_contains_expected_tables` and `test_migrations_round_trip`.
- `body_measurements.measured_on` is `date` with a `(user_id, source, measured_on)` unique
  constraint and 17 nullable metric columns — verified by three tests, one of them against
  `information_schema`.
- Three `sync_state` rows hold three independent `last_synced_at` values — verified by
  `test_three_resources_have_independent_last_synced_at`.
- `format_sync_error(ValueError("secret"))` returns exactly `"ValueError"` — verified.

## Known Stubs

None. Every table this plan creates is fully defined and migrated.

`exercise_muscles` and `exercise_muscle_overrides` are created but not yet *populated* — the
override resolution semantics (per-template replacement) are implemented and tested in plan 03-07,
as the plan's threat register states for T-03-14. That is scheduled downstream work against a
complete schema, not a stub: no code path in this plan returns placeholder data.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Ready. The write targets for the rest of Phase 3 now exist:

- **Template sync (HEVY-06)** writes `exercise_templates` and recomputes `exercise_muscles` from
  `app.normalization`; the unique key `uq_exercise_templates_user_provider_external_id` is in place
  for the idempotent upsert.
- **Body-measurement sync (HEVY-07)** upserts on
  `uq_body_measurements_user_source_measured_on`, parsing with `dt.date.fromisoformat` — note
  `dt.datetime.fromisoformat("2026-08-01")` returns a *naive* datetime, which both Ruff's DTZ rules
  and `app.core.time._require_aware` correctly reject.
- **The sync service** calls `mark_running` → per-page `advance_cursor_page` (committed with the
  page) → `complete_sync`, or `record_sync_error` on failure, and owns every commit itself.

Two carry-forward notes:

- Centimetres for the seven unsuffixed Hevy fields (`abdomen`, `waist`, `hips`, `left_thigh`,
  `right_thigh`, `left_calf`, `right_calf`) remains an **assumption** — Hevy does not declare the
  unit. Confirm against the app on the first live sync. Already tracked in STATE.md as an open
  Phase 3 concern alongside the dumbbell-weight question.
- Any exception the Hevy client wants to surface in `sync_state.last_error` must expose a curated
  `safe_message`; without it only the class name is stored, by design.

## Self-Check: PASSED

All seven created files exist on disk and all five commits are present in `git log`. Verified below.

---
*Phase: 03-hevy-integration-normalization, Plan 04*
*Completed: 2026-08-29*

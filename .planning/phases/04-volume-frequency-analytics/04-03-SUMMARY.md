---
phase: 04-volume-frequency-analytics
plan: 03
subsystem: testing
tags: [pytest, pytest-asyncio, sqlalchemy, postgres, testcontainers, fixtures, decimal]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "Alembic-built test schema, session-scoped Postgres container, `session`/`engine` fixtures, seeded DEFAULT_USER_ID"
  - phase: 03-hevy-integration-normalization
    provides: "workouts/workout_exercises/workout_sets and exercise_templates/exercise_muscles/exercise_muscle_overrides models, and `app.normalization.resolver.set_override` / `effective_muscles_bulk`"
provides:
  - "`golden_workout` pytest fixture yielding a `GoldenBuilder` that writes synthetic workouts, templates, muscle mappings, overrides and extra users"
  - "`GoldenSet` / `GoldenExercise` frozen value types for describing a workout with a hand-computable answer"
  - "`ANALYTICS_SECOND_USER_ID` — the second tenant that makes a missing `user_id` predicate detectable"
  - "`ANALYTICS_ID_PREFIX` — collision-free fixture ids for the shared session-scoped container"
  - "Proof, from a second connection, that the builder never commits"
affects: [04-05, 04-06, 04-07, 04-08, 04-09, phase-05-progression-analytics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flush-and-rollback fixtures instead of compensating DELETEs"
    - "Fixture writers delegate to production writers (override() -> resolver.set_override)"
    - "Frozen slotted dataclasses as the description language for golden test data"

key-files:
  created:
    - backend/tests/test_analytics_fixtures.py
  modified:
    - backend/tests/conftest.py

key-decisions:
  - "The builder flushes and never commits; `golden_workout` rolls back in a `finally`, so the shared session-scoped container survives an assertion failure mid-test — strictly stronger than a compensating DELETE"
  - "`override()` delegates to `app.normalization.resolver.set_override` rather than inserting `ExerciseMuscleOverride` rows, so the delete-then-insert replacement rule has exactly one implementation"
  - "`GoldenSet` defaults every metric to `None` so a fixture cannot acquire a weight the exercise modality does not have"
  - "`test_golden_builder_supports_a_second_user` filters on explicit workout ids rather than `start_time >= _START`, because the shared container may hold committed rows from other modules"
  - "Pre-existing mypy errors in `backend/tests/` were left untouched — the plan forbids modifying existing fixtures, and the change introduces zero new ones"

patterns-established:
  - "Golden fixture builder: describe a workout in frozen dataclasses, build it with Core statements, read it back through the same session"
  - "Self-testing fixtures: a fixture whose correctness other tests depend on gets its own test module proving visibility, isolation, scoping and round-trip"
  - "Second-connection assertion as the proof of non-commit, rather than inspecting the session's own transaction state"

requirements-completed: []  # See "Requirements Status" — this plan builds the verification
# scaffolding for VOL-01..03 / DQ-01..02, it does not implement them. Nothing was marked
# complete in REQUIREMENTS.md.
requirements-supported: [VOL-01, VOL-02, VOL-03, DQ-01, DQ-02]

# Metrics
duration: 24min
completed: 2026-08-30
---

# Phase 4 Plan 03: Golden Analytics Fixtures Summary

**A `golden_workout` builder that constructs synthetic workouts, templates, muscle mappings, overrides and extra users with exact hand-computable contents, flushing everything and committing nothing — plus four container-backed tests proving it.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-08-30T09:42:00Z
- **Completed:** 2026-08-30T10:06:28Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `GoldenBuilder` with four async methods — `user`, `template`, `override`, `workout` — writing via explicit SQLAlchemy Core statements that mirror the Hevy sync path, including `executemany` for the high-cardinality `workout_sets` table.
- The never-commit guarantee is now *proven*, not asserted in prose: `test_golden_builder_never_commits` opens a second `AsyncSession` on the same engine and shows the builder's workout is invisible there, while the builder's own session sees exactly one row. `test_migrations.py`'s `count(*) == 1` on `users` stays green afterwards.
- `ANALYTICS_SECOND_USER_ID` plus `GoldenBuilder.user()` give the phase its only mechanism for detecting a missing `user_id` predicate (T-04-02). Plans 04-05 through 04-08 build their cross-tenant assertions on it.
- `override()` routes through `resolver.set_override`, and the self-test asserts the resolved set collapses to one `EffectiveMuscle` with `source is MappingSource.OVERRIDE` — the replacement rule, not a merge.
- `workout()` rejects a naive `start_time` at runtime, mirroring `app/core/time.py::_require_aware`, so a fixture cannot silently mis-bucket a week boundary (T-04-13).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the golden_workout builder fixture and its value types to conftest.py** — `df26d21` (feat)
2. **Task 2: Self-test the builder — visibility, rollback, second user, resolver round-trip** — `d61f114` (test)

## Files Created/Modified

- `backend/tests/conftest.py` — adds `ANALYTICS_SECOND_USER_ID`, `ANALYTICS_ID_PREFIX`, the `GoldenSet`/`GoldenExercise` value types, the `GoldenBuilder` class and the `golden_workout` fixture; module docstring extended with the fixture's never-commit contract. No existing fixture was modified.
- `backend/tests/test_analytics_fixtures.py` — four integration tests covering in-session visibility and aware-UTC round-trip, non-commit from a second connection, two-user coexistence, and resolver round-trip including override replacement.

## Decisions Made

- **Flush-and-rollback, never a compensating DELETE.** The rollback lives in the fixture's `finally`, so it runs even when an assertion raises mid-test. A DELETE would not, and it could not undo rows a committed transaction had already exposed to other connections.
- **`override()` delegates rather than duplicates.** Hand-inserting `ExerciseMuscleOverride` rows would put a second copy of the delete-then-insert replacement semantics in the test suite. When the two eventually disagreed, the fixture would be certifying the wrong per-muscle answer with a green tick. `grep -c "ExerciseMuscleOverride" backend/tests/conftest.py` returns 0 by design.
- **The builder writes the CANONICAL mapping directly, leaving `primary_muscle_group` / `secondary_muscle_groups` empty.** Those columns hold Hevy's raw strings. Translating them here would test the Hevy translation twice and the resolver — which is what Phase 4 actually reads — not at all.
- **Test 3 scopes its counts by explicit workout id, deviating from the plan's `start_time >= _START` predicate.** See Deviations below.
- **Weights are `Decimal`, never `float`,** carried through `GoldenSet` into `Numeric(7,3)` columns, so two arithmetically identical weekly tonnage totals compare equal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created the worktree's Python environment**
- **Found during:** Pre-Task 1 setup
- **Issue:** This parallel executor runs in a fresh git worktree with no `.venv`. Every verification command in the plan is `.venv/bin/python -m ...`, so nothing could be verified.
- **Fix:** `uv sync --frozen --group dev` at the worktree root. `.venv/` is already gitignored, so nothing entered the commit.
- **Files modified:** None tracked.
- **Verification:** Baseline `pytest -q -m "not integration"` → 177 passed before any source change.
- **Committed in:** N/A (untracked environment only)

**2. [Rule 1 - Bug] Dropped two unused imports the plan's action block specified**
- **Found during:** Task 1
- **Issue:** The plan listed `from dataclasses import dataclass, field` and `from sqlalchemy import insert, select`. Neither `field` nor `select` is used anywhere in `conftest.py`, and Ruff's `F401` would have failed the plan's own lint acceptance criterion.
- **Fix:** Imported only `dataclass` and `insert`.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `ruff check backend/tests/conftest.py` exits 0.
- **Committed in:** `df26d21`

**3. [Rule 1 - Bug] `override()` binds the return value before flushing**
- **Found during:** Task 1
- **Issue:** The plan's method body reads `return await set_override(...)`, *then* `await self._session.flush()` — the flush is unreachable after a `return`, so the override rows would sit unflushed in the session's pending state.
- **Fix:** Bind `written = await set_override(...)`, flush, then return `written`.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `test_golden_builder_mapping_resolves_through_the_resolver` reads the override back through `effective_muscles_bulk` and asserts `source is MappingSource.OVERRIDE`.
- **Committed in:** `df26d21`

**4. [Rule 1 - Bug] Test 3 counts by workout id, not by `start_time >= _START`**
- **Found during:** Task 2
- **Issue:** The plan's unscoped-count query filters on `Workout.start_time >= _START` and asserts the result is exactly 2. The Postgres container is session-scoped and shared, and other modules (`test_hevy_end_to_end.py`, `test_normalization_mapping.py`) do commit rows and clean them up in a `finally`. Any committed leftover dated on or after 2026-08-24 would push the count past 2 and fail this test for an unrelated module's reason — precisely the hard-to-attribute failure class this plan exists to prevent.
- **Fix:** Both counts filter on `Workout.id.in_((mine, theirs))`; the scoped one adds `Workout.user_id == DEFAULT_USER_ID`. The unscoped count is still asserted to be 2, which keeps the scoping assertion from passing vacuously.
- **Files modified:** `backend/tests/test_analytics_fixtures.py`
- **Verification:** Full suite green (295 passed), including a combined run with `test_migrations.py` and `test_time.py`.
- **Committed in:** `d61f114`

**5. [Rule 1 - Bug] `golden_workout` is annotated `AsyncIterator[GoldenBuilder]` with no `type: ignore`**
- **Found during:** Task 1
- **Issue:** The plan says to keep the existing fixtures' `# type: ignore[misc]` pattern "if mypy objects". With a correct `AsyncIterator[...]` return annotation mypy does not object, and `warn_unused_ignores = true` would have turned a defensive ignore into a fresh error.
- **Fix:** Annotated the generator properly and added no suppression.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `mypy backend/tests/test_analytics_fixtures.py` reports zero errors in the new module.
- **Committed in:** `df26d21`

---

**Total deviations:** 5 auto-fixed (1 blocking, 4 bugs in the plan's literal instructions)
**Impact on plan:** All five are corrections to instructions that would not have compiled, linted, or run deterministically. No scope creep — the diff touches exactly the two files the plan names, `pyproject.toml` is unmodified, and no migration was created.

## Deferred Issues

**Pre-existing mypy errors under `backend/tests/` — NOT introduced by this plan, and deliberately not fixed.**

The plan's acceptance criterion `mypy backend/tests/conftest.py` exits 0, and its verification step 5 asks for `mypy backend` to exit 0. Neither held *before* this plan ran:

- `mypy backend/tests/conftest.py` at base commit `a8332d7` reports the **same 6 errors** it reports now (verified by stashing the change and re-running): two `type-var`, two `misc` async-generator-annotation, two `unused-ignore`, all on the untouched `engine` and `session` fixtures at what are now lines 240–260.
- `mypy backend` reports **44 pre-existing errors across 13 test files** at base commit (`_env_file` kwargs in `test_config.py`, missing `types-PyYAML`, `TypeEngine` attribute access in `test_db_models.py`, ASGI-callable `.state` in `test_health.py` / `test_mcp_tools.py`).

Not fixed for three reasons: the plan explicitly instructs "Do not modify any existing fixture"; the scope boundary confines auto-fixes to issues caused by this task's changes; and repairing 13 test modules from inside a parallel worktree would collide with other wave-1 agents at merge time.

What *is* true and is the meaningful property: **this change adds zero new mypy errors.** `mypy backend/app` → 41 files, no issues. `mypy backend/tests/test_analytics_fixtures.py` → no errors in the new module. `ruff check backend` → clean. `ruff format --check` → clean on both files.

Recorded here rather than in a phase-level `deferred-items.md` because that file would be an add/add merge conflict between concurrent wave-1 worktree agents.

## Issues Encountered

None beyond the deviations above. The builder worked against the container on first run — all four self-tests passed without a debugging cycle.

## Verification Evidence

| Check | Result |
|---|---|
| `pytest backend/tests/test_analytics_fixtures.py -q` | 4 passed, exactly 4 collected |
| `pytest backend/tests/test_analytics_fixtures.py test_migrations.py test_time.py -q` | 21 passed — shared container provably unpolluted |
| `pytest -q -m "not integration"` | 177 passed (conftest imports cleanly for every module) |
| `pytest -q` (full suite) | **295 passed** (291 before, +4) |
| `ruff check backend` | clean |
| `ruff format --check` on both files | clean |
| `mypy backend/app` | 41 files, no issues |
| `git diff --stat` vs base | exactly `backend/tests/conftest.py` + `backend/tests/test_analytics_fixtures.py` |
| `grep -c "session.commit()" backend/tests/conftest.py` | **0** |
| `grep -c "ExerciseMuscleOverride" backend/tests/conftest.py` | **0** |
| `grep -c "set_override" backend/tests/conftest.py` | 3 (import + call + docstring) |
| `grep -c "@dataclass(frozen=True, slots=True)"` | 2 |
| `grep -c "pytest.mark.integration"` in the test module | 4 |
| `grep -c "pytest.mark.asyncio"` in the test module | 0 |

## Requirements Status

The plan frontmatter lists `requirements: [VOL-01, VOL-02, VOL-03, DQ-01, DQ-02]`. **None of them were
marked complete in `REQUIREMENTS.md`, deliberately.**

This plan ships no volume calculation, no per-muscle breakout, no frequency figure and no freshness or
coverage metadata. It ships the fixture those calculations will be *verified against*. Checking VOL-01
off now would record "weekly training volume is calculated" against a codebase where it demonstrably is
not, and the traceability table is the artifact that is supposed to make that claim trustworthy.

Plans 04-05 through 04-08 carry the same requirement IDs and do the implementing; they are the correct
place for the check-off. `REQUIREMENTS.md` is also a shared orchestrator artifact under concurrent
wave-1 modification, so writing to it from this worktree would risk a merge conflict for a claim that
is not yet true.

**Relationship to these requirements:** this plan satisfies ROADMAP success criterion 5 ("every Phase 4
calculation verified against golden fixture workouts covering warm-ups, dropsets, supersets and
bodyweight exercises") by making such fixtures constructible and trustworthy. `GoldenSet.set_type`
covers warm-ups and dropsets, `GoldenExercise.supersets_id` covers supersets, and `GoldenSet`'s
all-`None` defaults cover bodyweight and duration modalities.

## Threat Model Coverage

| Threat ID | Disposition | Status |
|---|---|---|
| T-04-02 (cross-tenant leak from a missing `user_id` predicate) | mitigate | **Mechanism delivered.** `GoldenBuilder.user()` + `ANALYTICS_SECOND_USER_ID`, proven by `test_golden_builder_supports_a_second_user`. Plans 04-05..04-08 must each add their own two-user assertion on top. |
| T-04-12 (a committing fixture corrupting the shared container) | mitigate | **Mitigated and proven.** Rollback in `finally`; zero `session.commit()` in conftest; second-connection invisibility asserted; `test_migrations.py` re-run green. |
| T-04-08 (fixture drifting from the resolver's replacement rule) | mitigate | **Mitigated.** `override()` delegates to `set_override`; zero `ExerciseMuscleOverride` references in conftest; `source is MappingSource.OVERRIDE` asserted after replacement. |
| T-04-13 (naive `start_time` mis-bucketing week boundaries) | mitigate | **Mitigated.** `workout()` raises `ValueError("naive start_time rejected: ...")`; Ruff `DTZ` rejects naive literals at lint time. |

No new security-relevant surface was introduced — this plan adds test-only code with no network endpoint, auth path, file access or schema change.

## Known Stubs

None. Every method on `GoldenBuilder` writes real rows and is exercised by the self-test.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Ready.** Plans 04-05 through 04-08 can consume `golden_workout` immediately; the fixture is proven for in-session visibility, isolation, two-user scoping and resolver round-trip.
- **Contract those plans must honour:** every analytics function must accept `session: AsyncSession` and never open its own session. A function that constructed its own `async_sessionmaker` would run in a different transaction and see none of the builder's flushed rows — the tests would fail with empty results that look like a calculation bug.
- **Carried forward for the wave-1 orchestrator:** the pre-existing `backend/tests/` mypy errors documented under Deferred Issues. They predate this phase and are a candidate for a standalone cleanup plan, not for a Phase 4 analytics plan.

## Self-Check: PASSED

- `backend/tests/conftest.py` — FOUND (modified, committed in `df26d21`)
- `backend/tests/test_analytics_fixtures.py` — FOUND (created, committed in `d61f114`)
- Commit `df26d21` — FOUND in `git log`
- Commit `d61f114` — FOUND in `git log`

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*

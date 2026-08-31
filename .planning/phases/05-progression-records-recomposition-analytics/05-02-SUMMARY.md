---
phase: 05-progression-records-recomposition-analytics
plan: 02
subsystem: analytics
tags: [sqlalchemy, postgres, asyncpg, testcontainers, pytest, analytics, multi-tenant]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "AnalyticsWindow, build_window/resolve_window, _hard_set_predicates, the GoldenBuilder fixture and the app/analytics/ read-only boundary tests"
  - phase: 03-hevy-integration-normalization
    provides: "workouts / workout_exercises / workout_sets / exercise_templates / body_measurements schema, and the deliberate absence of an FK from workout_exercises to exercise_templates"
provides:
  - "qualifying_set_rows(): the single SET-grain aggregate every Phase 5 progression, plateau, PR and comparison number folds from"
  - "QualifyingSetRow: local_day (dt.date), template_external_id, title, exercise_type, set_type, set_index, weight_kg, reps"
  - "One shared implementation of exercise-title lookup for Phase 5, removing the need to copy frequency._template_titles into new modules"
  - "GoldenBuilder.body_measurement(): flush-and-rollback seeding of body_measurements rows, with source exposed as a parameter"
affects: [05-03, 05-04, 05-05, 05-06, 05-07, 05-08, 05-09, 05-10, 06-mcp-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A second aggregate at a finer grain rather than a refinement of the existing one, when the question changed"
    - "Tenant predicate carried on the OUTER JOIN condition, not the WHERE clause"
    - "Mutation-testing a security assertion before trusting a green run"

key-files:
  created: []
  modified:
    - backend/app/analytics/rollup.py
    - backend/tests/conftest.py
    - backend/tests/test_analytics_rollup.py

key-decisions:
  - "Set grain is a SEPARATE query from weekly_set_rows, not a widening of it: D-04's per-day best-estimated-1RM and PROG-04's per-set PR scan are unrecoverable from a pre-aggregated row"
  - "The exercise_templates join is LEFT OUTER and carries its own ExerciseTemplate.user_id == user_id in the ON clause, because Hevy's built-in template ids are global"
  - "title and exercise_type are selected in the same join so Phase 5 needs neither a second query nor a copy of frequency._template_titles"
  - "template_external_ids is gated on `is not None`, so an empty list narrows to zero rows rather than being treated as 'no filter'"
  - "weight_kg is returned exactly as the driver produces it (Decimal | None), never coerced or defaulted to zero"

patterns-established:
  - "Set-grain aggregate: one indexed statement, no LIMIT, guarded upstream by MAX_ANALYTICS_WINDOW_DAYS rather than by silent truncation"
  - "Cross-tenant tests seed the SAME external id for two users with DIFFERENT payloads, so a missing predicate changes the answer instead of only leaking a label"
  - "Assertion messages name the specific wrong implementation and its measured live-data cost"

requirements-completed: [PROG-01, PROG-04]

# Metrics
duration: 9min
completed: 2026-08-31
---

# Phase 5 Plan 02: Set-Grain Aggregate & Body-Measurement Fixture Summary

**`qualifying_set_rows()` — one indexed set-grain query returning every non-warm-up set in a window with its local day, modality and title, outer-joined to `exercise_templates` under a per-tenant join predicate, plus `GoldenBuilder.body_measurement()` for seeding body-composition rows.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-08-31T02:57:41Z
- **Completed:** 2026-08-31T03:07:04Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- `QualifyingSetRow` + `qualifying_set_rows()` added to `backend/app/analytics/rollup.py` at SET grain, reusing `_hard_set_predicates()` so the warm-up exclusion still has exactly one definition in the codebase.
- The `exercise_templates` join is `LEFT OUTER` with `ExerciseTemplate.user_id == user_id` **inside the ON clause**. Both halves were mutation-tested (see Verification Evidence) — this is not a green-run-by-luck.
- `title` and `exercise_type` are carried on that join, so PROG-01/02/03/04 and CMP-01 all read one implementation instead of copying `frequency._template_titles`, which is private to its module.
- `GoldenBuilder.body_measurement()` added to `backend/tests/conftest.py` with `source` as a parameter (D-14's `hevy`-vs-`manual` same-date tie-break needs both), `Decimal` weight, and the same flush-never-commit contract as every other builder method.
- Six container-backed tests added. Full suite: **375 passed** (369 before). Fast suite unchanged at **206 passed**.

## Task Commits

1. **Task 1: Add QualifyingSetRow and qualifying_set_rows() to app/analytics/rollup.py** — `ca18f59` (feat)
2. **Task 2: Add GoldenBuilder.body_measurement() to backend/tests/conftest.py** — `474a907` (test)
3. **Task 3: Integration-test qualifying_set_rows() in test_analytics_rollup.py** — `84a72f3` (test)

## Files Created/Modified

- `backend/app/analytics/rollup.py` — +149 lines, **zero deletions**. Adds the `QualifyingSetRow` dataclass, the `qualifying_set_rows()` aggregate, and one import (`ExerciseTemplate`). `SetRollupRow`, `weekly_set_rows`, `_hard_set_predicates`, `build_window`, `resolve_window` and every fold are byte-identical to Phase 4.
- `backend/tests/conftest.py` — +40 lines, zero deletions. `GoldenBuilder.body_measurement()` plus the `BodyMeasurement` import.
- `backend/tests/test_analytics_rollup.py` — +287/−2. Six new `@pytest.mark.integration` tests, five `QSR-*` fixture ids, the `_qsr_window` helper, and a two-line module-docstring correction (the old text said "the four tests in the second half touch a container", which this plan made false).

## Output Spec Answers

The plan's `<output>` block asked for three specific facts:

**1. Observed row count and elapsed time for the set-grain query in the tenant test.**
`test_second_users_rows_and_template_are_invisible` seeds two users, two same-id templates and one set each, then queries as `DEFAULT_USER_ID`: **1 row returned** out of the 2 sets present in the table. Test call duration **0.04 s** (that figure covers the whole test body — seeding, `resolve_window`, and the aggregate — not the statement in isolation). Whole module: 17 tests in **2.38 s**. Full suite: 375 tests in **10.38 s**.

**2. The exact `set_index` values `GoldenBuilder.workout()` assigns.**
**0-based and dense**, from `enumerate(exercise.sets)` — a three-set exercise is `[0, 1, 2]`, not `[1, 2, 3]`. `exercise_index` on `workout_exercises` is likewise 0-based from `enumerate(exercises)`. This is pinned by an explicit `assert [row.set_index for row in rows] == [0, 1, 2]` in `test_qualifying_set_rows_returns_set_grain`, so a downstream plan that tie-breaks on `set_index` can rely on it.

**3. Confirmation that `volume.py`, `frequency.py`, `core/time.py` and `pyproject.toml` were untouched.**
Confirmed. `git diff --name-only 218cf81 -- pyproject.toml backend/app/analytics/volume.py backend/app/analytics/frequency.py backend/app/core/time.py backend/migrations/` returns **empty**. `git diff --stat 218cf81` lists exactly three files, all the ones this plan owns. **No Alembic migration was created.**

## Verification Evidence

A green test proves nothing about a security predicate unless the test fails when the predicate is removed. Both load-bearing assertions were mutation-tested against the live container, then the implementation was restored and re-verified:

| Mutation applied to `rollup.py` | Test | Result |
|---|---|---|
| Removed `ExerciseTemplate.user_id == user_id` from the ON clause | `test_second_users_rows_and_template_are_invisible` | **FAILED** — `{'bodyweight_weighted', 'weight_reps'} != {'weight_reps'}`; the second user's modality attached to this user's set, exactly the T-05-08 correctness bug |
| Changed `.outerjoin(...)` to `.join(...)` | `test_unsynced_template_still_returns_its_sets` | **FAILED** — `0 == 1`; the unsynced-template set vanished entirely |
| None (restored) | full module | **17 passed** |

Additionally, the compiled statement was inspected against the Postgres dialect to confirm the tenant predicate lands in the `ON` clause rather than the `WHERE` clause (where it would silently degrade the outer join to an inner one):

```
LEFT OUTER JOIN exercise_templates
  ON exercise_templates.external_id = workout_exercises.exercise_template_external_id
 AND exercise_templates.user_id = %(user_id_1)s::UUID
WHERE workouts.user_id = %(user_id_2)s::UUID AND ...
```

The timezone appears as `timezone(%(timezone_1)s, workouts.start_time)` — a bound parameter, never interpolated (T-05-09).

## Threat Model Coverage

| Threat ID | Disposition | Status |
|---|---|---|
| T-05-07 (tenant predicate on the workout aggregate) | mitigate | Implemented; `user_id` keyword-only with no default. Covered by `test_second_users_rows_and_template_are_invisible` |
| T-05-08 (tenant predicate on the template join) | mitigate | Implemented **in the ON clause**; mutation-tested |
| T-05-09 (timezone string reaching SQL) | mitigate | `func.timezone(tz, col)` bound parameter; `test_analytics_uses_no_raw_sql_text` passes |
| T-05-10 (`template_external_ids`) | mitigate | Bound `.in_(list(...))`, appended after the unconditional tenant predicate. `test_template_filter_narrows_and_binds` also pins the empty-list case |
| T-05-11 (unbounded set-grain result) | mitigate | No `LIMIT` by design; guard is `MAX_ANALYTICS_WINDOW_DAYS` upstream in `build_window` |
| T-05-12 (write path in a read-only package) | mitigate | `test_analytics_never_writes` passes; only `select` used |
| T-05-13 (body-weight fixtures in a shared container) | mitigate | `body_measurement()` flushes, never commits; `golden_workout`'s `finally: await session.rollback()` discards it |
| T-05-14 (spoofing / repudiation) | transfer | Out of scope here — enforced at the MCP boundary (Phase 2) |

No new threat surface was introduced beyond the plan's register.

## Decisions Made

None beyond the plan — every design decision listed in the frontmatter was specified by `05-02-PLAN.md` and implemented as written. The three deviations below are mechanical corrections, not design changes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's verbatim comment tripped the repo's own raw-SQL guard**
- **Found during:** Task 1
- **Issue:** The plan supplied a comment reading ``...Ruff S608 and `test_analytics_isolation.py`'s `text(` ban both enforce this.`` That guard is a regex (`_RAW_SQL_TEXT`) run over the source of every file in `app/analytics/`, and it matched the token inside its own explanatory comment. `test_analytics_uses_no_raw_sql_text` failed. This is precisely the trap `test_analytics_isolation.py`'s module docstring warns about ("a substring check would fail on the sentence documenting the boundary").
- **Fix:** Reworded to "the raw-SQL ban in `test_analytics_isolation.py`" and added a sentence explaining *why* the forbidden construct cannot be named literally at that spot, so the next author does not reintroduce it.
- **Files modified:** `backend/app/analytics/rollup.py`
- **Verification:** `pytest -q backend/tests/test_analytics_isolation.py` → 6 passed
- **Committed in:** `ca18f59`

**2. [Rule 3 - Blocking] `conftest.py` has no `from app.db.models import ...` line to extend**
- **Found during:** Task 2
- **Issue:** The plan instructed "Add `BodyMeasurement` to the existing `from app.db.models import ...` line in that file." No such line exists — `conftest.py` imports per-module (`from app.db.models.exercise import ...`, `from app.db.models.user import User`, `from app.db.models.workout import ...`), matching `frequency.py` and every other consumer in the repo.
- **Fix:** Added `from app.db.models.body import BodyMeasurement` in isort position, preserving the file's existing convention rather than introducing a second import style.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `ruff check backend/tests/conftest.py` (isort clean) → passed; fast suite 206 passed
- **Committed in:** `474a907`

**3. [Rule 1 - Bug] The plan's D-08 assertion message exceeded the 100-char line limit**
- **Found during:** Task 3
- **Issue:** `message = "D-08: only 'warmup' is excluded. An allow-list of 'normal' drops 823 live dropset sets"` compiled to 102 characters. Ruff `E501` failed.
- **Fix:** Wrapped in parentheses across two lines. The message string itself is unchanged and still matches the plan verbatim.
- **Files modified:** `backend/tests/test_analytics_rollup.py`
- **Verification:** `ruff check backend/tests/test_analytics_rollup.py` → All checks passed
- **Committed in:** `84a72f3`

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 bug). All three are mechanical; none changed the query, the schema, the fixture contract or any assertion's meaning.
**Impact on plan:** No scope creep. Every artifact, export and key-link in `must_haves` was delivered as specified.

## Issues Encountered

**Two of the plan's stated acceptance/verification criteria are not literally satisfiable. Neither indicates a defect in the delivered code.**

1. **`grep -A2 "async def body_measurement" ... | grep -q "measured_on: dt.date"` cannot pass against the plan's own code block.** In the signature the plan supplies, `measured_on` is the *third* line after `async def body_measurement(` (`self,` and `*,` come first), so `-A2` never reaches it. The substantive requirement — `measured_on` typed as `dt.date` in the signature — is satisfied and was verified with `grep -A8`. The other two arity-sensitive greps (`-A5` for `source`, `-A6` for `user_id`) do pass. No code change was made to chase a miscounted grep.

2. **Plan verification step 3 asserts `mypy backend/` exits 0. It does not, and did not before this plan.** Measured baseline at commit `218cf81` (with the pre-plan `conftest.py` swapped back in): **44 errors in 13 files across 86 source files**. After all three tasks: **44 errors in 13 files**. My changes introduced **zero** new mypy errors. Per the scope boundary, pre-existing failures in files this plan does not own were logged, not fixed. The six errors mypy reports for `conftest.py` are the pre-existing `pytest_asyncio` fixture-typing errors at the `engine`/`session` fixtures (lines 240/241/250/255/256/260 before, 241/242/251/256/257/261 after — the same six, shifted one line by the added import). `mypy backend/app/analytics/rollup.py` in isolation exits **0**, as the plan's Task 1 criterion requires.

**Execution environment note:** this worktree has no `.venv`, so the repo's `.venv/bin/{python,ruff,mypy}` were invoked by absolute path from the worktree root. `pyproject.toml`'s `pythonpath = ["backend"]` is rootdir-relative, and pytest confirmed `rootdir: .../worktrees/agent-a4b750c350659f80d` — every command ran against this worktree's source, not the main checkout.

**Worktree base correction:** the worktree branch was created from an ancestor of the expected base. Per the startup check it was hard-reset to `218cf81a5c3031218f5f79898ce370186296f360` before any file was touched.

## Requirement Status

`requirements-completed` lists `PROG-01` and `PROG-04` because they are this plan's declared requirements, **but this plan delivers substrate only, not either requirement in full.** PROG-01 is also claimed by 05-01, 05-03 and 05-04; PROG-04 by 05-03 and 05-05. Neither should be checked off in `REQUIREMENTS.md` until those plans land. `REQUIREMENTS.md` was deliberately **not** modified by this agent — the orchestrator owns that write after the wave completes.

## User Setup Required

None — no external service configuration, no new dependency, no migration.

## Next Phase Readiness

Ready. Downstream Phase 5 plans can now import from `app.analytics.rollup`:

- `qualifying_set_rows(session, *, user_id, window, template_external_ids=None) -> list[QualifyingSetRow]`
- `QualifyingSetRow(workout_id, local_day, template_external_id, title, exercise_type, set_type, set_index, weight_kg, reps)`

Contracts downstream plans can rely on:

- Rows arrive ordered by `(template_external_id, local_day, workout_id, set_index)` — a plateau streak read in this order is chronological within each exercise without re-sorting.
- `local_day` is a `dt.date` in the user's own timezone, safe to use directly as a fold key.
- `exercise_type` and `title` are `None` for an unsynced template. Treat `None` as "not `weight_reps`" rather than branching on its absence — `test_unsynced_template_still_returns_its_sets` pins this.
- `weight_kg` is `Decimal | None`. `None` means "this set has no weight", which is **not** zero kilograms; a bodyweight set and a 0 kg set are different facts.
- `set_index` is 0-based and dense.
- `GoldenBuilder.body_measurement(measured_on=..., weight_kg=..., source="hevy", user_id=...)` is available for BODY-01/BODY-02 fixtures and can seed two rows for the same date under different `source` values for D-14.

Concerns for the orchestrator/verifier:

- `rollup.py`'s **module docstring still opens with "One aggregate, at the `(week, workout_id, template_id)` grain"**, which is now one of two. It was left untouched because Task 1's acceptance criteria required an additions-only diff on that file. `QualifyingSetRow`'s own docstring states the distinction explicitly, but a later plan touching this file should consider correcting the module header.
- Pre-existing `mypy backend/` failures (44) remain and are unrelated to this plan.

## Self-Check: PASSED

Every claim above was re-verified against disk and git before this file was committed.

**Files claimed as modified — all present:**
- `backend/app/analytics/rollup.py`
- `backend/tests/conftest.py`
- `backend/tests/test_analytics_rollup.py`

**Commits claimed — all reachable from this branch:**
- `ca18f59` feat(05-02): add set-grain qualifying_set_rows aggregate to rollup
- `474a907` test(05-02): add GoldenBuilder.body_measurement fixture method
- `84a72f3` test(05-02): cover qualifying_set_rows against real PostgreSQL

**No stubs.** No hardcoded empty collection, placeholder string, TODO or FIXME was introduced. `qualifying_set_rows()` is fully wired to real tables and exercised by six container-backed tests.

**Shared orchestrator artifacts untouched:** `.planning/STATE.md`, `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` were not modified — the orchestrator owns those writes after the wave.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

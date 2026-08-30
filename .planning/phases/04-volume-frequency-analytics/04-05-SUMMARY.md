---
phase: 04-volume-frequency-analytics
plan: 05
subsystem: analytics
tags: [sqlalchemy, postgres, date-trunc, filter-aggregate, decimal, dataclasses, timezone]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    plan: 01
    provides: "local_range_bounds / snap_local_week_range / validate_timezone in app/core/time.py"
  - phase: 04-volume-frequency-analytics
    plan: 02
    provides: "app/analytics/ package boundary and the six static isolation assertions"
  - phase: 04-volume-frequency-analytics
    plan: 03
    provides: "golden_workout builder, GoldenSet/GoldenExercise, ANALYTICS_SECOND_USER_ID"
  - phase: 03-hevy-integration-normalization
    provides: "effective_muscles_bulk / apply_weights / EffectiveMuscle, and the workouts / workout_exercises / workout_sets tables with ix_workouts_user_id_start_time"
provides:
  - "AnalyticsWindow + build_window: an inclusive local date pair validated, optionally week-snapped, and converted to a half-open UTC pair with days"
  - "resolve_window: the same, reading users.timezone (FOUND-03) and raising ValueError('unknown user')"
  - "MAX_ANALYTICS_WINDOW_DAYS = 1830, the pre-query range rejection T-04-06 was transferred here from core/time.py"
  - "SetRollupRow + weekly_set_rows: the single indexed aggregate at the (local week, workout, template) grain carrying hard_sets, total_reps, tonnage_sets and tonnage_kg"
  - "resolve_row_muscles: two-query bulk muscle resolution for every template in a window"
  - "MuscleBucket + fold_weeks_by_muscle / fold_window_by_muscle / fold_window_by_template: pure, container-free fan-out accumulating workout ids into sets"
  - "COUNT_DURATION_ONLY_SETS and WARMUP_SET_TYPE as the two single-site set-inclusion policies"
affects: [04-04, 04-06, 04-07, 04-08, 04-09, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One aggregate at the finest grain any consumer needs, folded in Python rather than re-queried per metric"
    - "FILTER-gated aggregate paired with a FILTER-gated COUNT, so a NULL-skipping SUM is auditable instead of silent"
    - "cast(date_trunc(...), Date) so the week key is a datetime.date and merges against the Python week spine"
    - "Set-typed session accumulators rather than counters, making per-muscle session inflation structurally impossible"
    - "Policy encoded as one module constant checked in one predicate helper, so a product decision flips in one line"

key-files:
  created:
    - backend/app/analytics/rollup.py
  modified: []

key-decisions:
  - "The grain is (week, workout_id, template_id), not (week, template_id): the coarser grain is 16% fewer rows and makes per-muscle session counts impossible to compute at all"
  - "Tonnage is gated on operand presence (weight_kg IS NOT NULL AND reps IS NOT NULL) and never on a modality vocabulary, and tonnage_sets is returned beside tonnage_kg so 'zero kilograms' is distinguishable from 'not computable'"
  - "MAX_ANALYTICS_WINDOW_DAYS is a rejection, never a row cap: a silent truncation is a wrong answer, an over-wide request is a refused one"
  - "Imports were introduced task by task rather than all in Task 1, because the plan's single import block would have failed its own Ruff F401 acceptance gate at the Task 1 boundary"
  - "Three pieces of plan-mandated prose were rewritten because they contained the exact tokens the plan's own grep criteria require to be absent (ZoneInfo, exercise_type, a 1.0/0.5 weight literal)"

patterns-established:
  - "Analytics query substrate: resolve window -> one aggregate -> pure folds, with SQL doing the counting and Python doing the business rules"
  - "A public fold pair (weekly / whole-window) delegates to one private implementation parameterised by key shape, so the two answers cannot drift"
  - "Bound-parameter timezone via func.timezone(tz, col), with the bare indexed column left alone on the left of both window comparisons"

# Deliberately empty. This plan ships the substrate VOL-01/02/03 are computed FROM; it computes
# no weekly volume figure, no per-muscle result and no frequency rate. Plans 04-04 and 04-06..08
# produce those. See "Requirements Status".
requirements-completed: []
requirements-advanced: [VOL-01, VOL-02, VOL-03]

# Metrics
duration: 8min
completed: 2026-08-30
---

# Phase 4 Plan 05: Rollup Query Substrate Summary

**One indexed SQL aggregate at the `(local week, workout, exercise template)` grain, wrapped by a validated timezone-aware window builder and a pure Python muscle fan-out — the tier every Phase 4 metric sits on, built so that all three of the RESEARCH-measured silently-wrong-number classes are structurally impossible rather than merely tested.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-08-30T10:13:44Z
- **Completed:** 2026-08-30T10:21:21Z
- **Tasks:** 3 of 3
- **Files created:** 1 (no existing file modified)

## Accomplishments

- **The phase's one genuinely new architectural tier exists.** Before this plan, `group_by`, `date_trunc`, `func.sum`, `FILTER (WHERE ...)`, `func.timezone` and `cast(..., Date)` appeared in zero lines of application code. `backend/app/analytics/rollup.py` (385 lines) is now the single place any of them live.
- **The aggregate renders byte-for-byte as the plan's verified statement.** Confirmed by compiling against the real `postgresql` dialect and asserting on the rendered SQL and its bound parameters: `CAST(date_trunc(%(date_trunc_1)s, timezone(%(timezone_1)s, workouts.start_time)) AS DATE)`, both window comparisons against the bare `workouts.start_time`, `workout_sets.set_type != %(set_type_1)s`, and two `FILTER (WHERE workout_sets.weight_kg IS NOT NULL AND workout_sets.reps IS NOT NULL)` clauses. The timezone and the warmup literal are both bound parameters, never interpolated (T-04-01).
- **All three wrong-number classes were verified dead against a live Postgres container**, not just reasoned about (see Verification Evidence): a warmup set contributes to none of the four measures; a dropset contributes exactly like a normal set; a reps-only set counts as a hard set but not a tonnage set; a `weight_kg=0.000 / reps=10` set yields `tonnage_sets=1` and `tonnage_kg=Decimal("0.000")` while a duration-only set yields `tonnage_kg=None`; and one workout with three hamstring exercises folds to exactly one hamstring session.
- **Cross-tenant isolation proven, not assumed.** A second user's workout was built in the same window with the same start time; `weekly_set_rows` for the default user returned zero of its rows, and the same call for the second user returned exactly its one row — a non-vacuous guard (T-04-02).
- **U-02 has exactly one site.** `COUNT_DURATION_ONLY_SETS` is read only by `_hard_set_predicates`; flipping the 24-live-set decision is a one-line change with no modality list to hunt down.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the window resolution half of rollup.py** — `77c5a27` (feat)
2. **Task 2: Write the SQL aggregate — weekly_set_rows and resolve_row_muscles** — `499c4c8` (feat)
3. **Task 3: Write the pure Python muscle fan-out folds** — `9a55547` (feat)

## Files Created/Modified

- `backend/app/analytics/rollup.py` (created, 385 lines) — module docstring stating the five counter-intuitive rules; the three policy constants (`WARMUP_SET_TYPE`, `COUNT_DURATION_ONLY_SETS`, `MAX_ANALYTICS_WINDOW_DAYS`); `AnalyticsWindow`, `build_window`, `resolve_window`; `SetRollupRow`, `_hard_set_predicates`, `weekly_set_rows`, `resolve_row_muscles`; `MuscleBucket`, `_fold_by_muscle`, `fold_weeks_by_muscle`, `fold_window_by_muscle`, `fold_window_by_template`.

Nothing else in the repository changed. `git diff --name-only` against the base commit lists exactly one path.

## Decisions Made

- **`tonnage_sets` travels beside `tonnage_kg` everywhere.** SQL `SUM` drops NULL products without a word, and 543 of 7,719 live non-warmup sets produce one. Returning only the sum would hand the caller a real number computed over a silently smaller population. The paired FILTER-ed count makes that population visible, which is what lets `Decimal("0.000")` mean "zero kilograms, and we know it" while `None` means "we could not compute this".
- **The window clamp rejects rather than truncates.** `MAX_ANALYTICS_WINDOW_DAYS` fires in `build_window` before any row is materialised. A `LIMIT` would have converted an over-wide request into a confidently-presented partial answer — the exact failure mode T-04-07 exists to prevent — so the module contains no row cap at all.
- **`fold_window_by_muscle` re-folds the rows rather than summing the weekly buckets.** Summing weekly `session_ids` sizes would double-count any muscle trained in more than one week, which is most of them. Both public folds delegate to `_fold_by_muscle`, so there is no second implementation to drift.
- **Imports were introduced incrementally.** See Deviation 1.
- **Three pieces of mandated prose were rewritten.** See Deviation 2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's single import block cannot satisfy its own Task 1 lint gate**

- **Found during:** Task 1
- **Issue:** The plan places one complete import block in Task 1's `<action>`, covering symbols first used in Tasks 2 and 3 (`Date`, `and_`, `cast`, `func`, `not_`, `Decimal`, `Sequence`, `Mapping`, `field`, the workout models, `CanonicalMuscleGroup`, `MuscleRole`, `EffectiveMuscle`, `apply_weights`, `effective_muscles_bulk`). Task 1's own acceptance criteria include `ruff check backend/app/analytics/rollup.py` exits 0, and Ruff `F401` fails on every unused import. The two instructions are mutually unsatisfiable at the Task 1 commit boundary.
- **Fix:** Each task imports exactly what it uses. Task 1 added `datetime`, `uuid`, `dataclass`, `select`, `AsyncSession`, the three `core.time` helpers and `User`. Task 2 added `Sequence`, `Decimal`, `Any`, `Date/and_/cast/func/not_`, the three workout models and `EffectiveMuscle`/`effective_muscles_bulk`. Task 3 added `Mapping`, `field`, `CanonicalMuscleGroup`, `MuscleRole` and `apply_weights`. The final import block is identical to the plan's, plus `Any` (which the plan's own `_hard_set_predicates` signature requires and its import block omitted).
- **Files modified:** `backend/app/analytics/rollup.py`
- **Verification:** `ruff check` exits 0 at all three commit boundaries; `ruff format --check` reports the file already formatted at each.
- **Committed in:** `77c5a27`, `499c4c8`, `9a55547`

**2. [Rule 1 - Bug] Three pieces of plan-mandated prose contain the exact tokens the plan's own grep criteria require to be absent**

- **Found during:** Tasks 1 and 3
- **Issue:** The same substring-versus-intent trap plans 04-01 and 04-02 both hit. Three cases:
  - Task 1's mandated `build_window` comment reads "beats a ZoneInfoNotFoundError raised from inside an aggregate query", while Task 1 acceptance criterion 7 requires `grep -c "ZoneInfo"` to return **0**.
  - The mandated module docstring bullet reads "The tonnage gate is OPERAND PRESENCE, never `exercise_type`", while Task 2 acceptance criterion requires `grep -c "exercise_type"` to return **0**.
  - Task 3's mandated `_fold_by_muscle` comment reads "never a local 1.0/0.5 literal", while Task 3 acceptance criterion requires `grep -c 'Decimal("1.0")\|Decimal("0.5")\|0.5\b'` to return **0**.
- **Fix:** Resolved toward the machine-checkable criteria in all three, preserving the documented intent. Respectively: "beats an unknown-timezone failure raised from inside an aggregate query"; "never a modality allow-list … The model's own modality vocabulary had already drifted from what the provider actually sends"; "never a weight literal spelled out here -- the defaults live in the taxonomy module and the caller overrides them per query." This matches the criteria's purpose exactly — a later implementer greping this module for a timezone library, a modality vocabulary or a hardcoded weight must find nothing.
- **Files modified:** `backend/app/analytics/rollup.py`
- **Verification:** `grep -c "ZoneInfo"` → 0; `grep -c "exercise_type"` → 0; `grep -c 'Decimal("1.0")\|Decimal("0.5")\|0\.5\b'` → 0. Every other grep criterion in all three tasks passes (full table below).
- **Committed in:** `77c5a27` (case 1 and the docstring), `9a55547` (case 3)

**3. [Rule 3 - Blocking] No `.venv` in the parallel worktree**

- **Found during:** Pre-Task 1 setup
- **Issue:** Every verify and acceptance command in the plan is written against `.venv/bin/python`, and a fresh worktree has no virtualenv (`.venv` is gitignored, so it is not materialised).
- **Fix:** Symlinked the main checkout's `.venv` into the worktree root, as plan 04-02 did. `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` and `tests` resolve against the *worktree's* sources, not the main checkout's — confirmed by the RED check, which reported `No module named 'app.analytics.rollup'` before Task 1. The symlink was never staged and is removed before returning.
- **Files modified:** none tracked
- **Verification:** `git status --short` shows only `backend/app/analytics/rollup.py` at every commit boundary.
- **Committed in:** n/a

**4. [Rule 3 - Blocking] Worktree branch base was stale**

- **Found during:** Startup check
- **Issue:** `git merge-base HEAD a3acb0c` returned `1e97f3b` — the worktree branched from `chore(02-05): record auto-chain flag`, four commits before Phase 4 planning existed and eight before wave 1's output. Neither `04-05-PLAN.md` nor `app/analytics/` nor `core/time.py`'s new helpers were present. This is the fourth consecutive wave in which this has happened.
- **Fix:** `git reset --hard a3acb0ceb1229c5143bd956d09113ff4365b35ea` per the startup check, verified at `a3acb0c` before any work began. The worktree was clean, so nothing was lost.
- **Files modified:** none
- **Verification:** `git log --oneline -1` → `a3acb0c docs(phase-04): update tracking after wave 1`; all four wave-1 artifacts present.
- **Committed in:** n/a

**5. [Rule 2 - Missing Critical] Requirement IDs deliberately not checked off**

- **Found during:** Post-execution
- **Issue:** The plan frontmatter carries `requirements: [VOL-01, VOL-02, VOL-03]`. This plan computes no weekly volume figure, no per-muscle result and no frequency rate — it ships the substrate those are computed *from*. Marking them complete would assert a capability the code cannot perform, and this executor is explicitly instructed not to write shared orchestrator artifacts from a worktree.
- **Fix:** `REQUIREMENTS.md` left untouched; `requirements-completed: []` with `requirements-advanced: [VOL-01, VOL-02, VOL-03]` recorded in this summary's frontmatter instead. Consistent with the identical calls made by plans 04-01, 04-02 and 04-03.
- **Files modified:** none (the correction is the absence of a write)
- **Verification:** `git diff --name-only` against base lists only `backend/app/analytics/rollup.py`.
- **Committed in:** n/a

---

**Total deviations:** 5 auto-fixed (2 internal contradictions in the plan document, 2 worktree-environment blockers, 1 false-completion prevented)
**Impact on plan:** No scope creep and no functional drift. Deviations 1 and 2 are contradictions between the plan's mandated text and the plan's own machine-checkable gates — the code and every behavioural assertion shipped exactly as specified. Deviations 3–5 are environmental and tracking corrections. `pyproject.toml` is unmodified, zero dependencies were added, no migration was created, and `resolver.py` / `exercise_map.py` are untouched.

## TDD Gate Compliance

All three tasks carry `tdd="true"`, but the plan places this module's entire test suite in plan 04-09 (wave 3) and states explicitly that no test is to be written here. A RED-then-GREEN commit pair is therefore not expressible.

- **RED gate:** satisfied by an explicit pre-implementation check asserting the module was absent — `No module named 'app.analytics.rollup'` — recorded before Task 1, plus a full-suite baseline of 194 fast / 312 total at the base commit.
- **GREEN gate:** each task's `<verify>` block was executed and passed before its commit, and Task 2's runtime behaviour was additionally proven against a live Postgres container (see below).
- **Gate commits:** three `feat(...)` commits, no `test(...)` commit. **This is a known, intended gap** — the `test(...)` commit for `rollup.py` belongs to plan 04-09, which is the file's designated test owner. Anyone auditing gate sequence for this plan should look for `backend/tests/test_analytics_rollup.py` landing in wave 3.

## Verification Evidence

### Plan `<verification>` block — all 7 pass

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_isolation.py -q` | **6 passed** — all six boundary assertions still green with `rollup.py` present |
| 2 | `pytest -q` (full suite) | **312 passed** in 8.32s (312 at base — no regression, no new tests, as designed) |
| 3 | `pytest -q -m "not integration"` | **194 passed**, 118 deselected in 0.93s (baseline 194 in 1.03s) |
| 4 | `ruff check backend` / `mypy backend/app` | All checks passed / Success, no issues in **44** source files |
| 5 | `pyproject.toml` unmodified | unmodified — zero dependencies proposed or added |
| 6 | `resolver.py`, `exercise_map.py` unmodified; no migration | all unmodified; `backend/migrations/` clean |
| 7 | `git diff --name-only` lists only `rollup.py` | exactly `backend/app/analytics/rollup.py` |

### Container-backed behavioural proof (throwaway probe, run and deleted)

The plan defers this module's tests to 04-09, but shipping an unexecuted aggregate would have left every RESEARCH finding unverified. A throwaway integration module was written against the `golden_workout` builder, run against the real Postgres container, and deleted before commit — it appears in no commit and `git status` was confirmed clean afterwards. It passed on the first run, asserting:

| Behaviour from the plan's `<behavior>` block | Observed |
|---|---|
| `week_start` is `datetime.date`, never a naive datetime | `type(r.week_start) is dt.date` ✓ |
| Workout at `2026-08-23T17:00:00Z` + `Asia/Jakarta` → week `2026-08-24` | `dt.date(2026, 8, 24)` ✓ (not `2026-08-17`) |
| `warmup` contributes to none of the four measures | 5 sets in, `hard_sets == 4` ✓ |
| `dropset` contributes exactly like `normal` | included in the 4 ✓ |
| reps-only set: hard set and reps, but no tonnage | `tonnage_sets == 3` of 4 ✓ |
| `weight_kg=0.000, reps=10` → 1 tonnage set, `Decimal("0.000")` | `tonnage_kg == Decimal("1640.000")` including the zero ✓ |
| duration-only set: 1 hard set, `total_reps` and `tonnage_kg` stay `None` | `hard_sets == 1`, both `None` ✓ |
| Two exercises in one workout → two rows, same `workout_id` | ✓ |
| No row from another user's workouts is returned | second user's row absent from the default user's result, present in its own ✓ |
| `resolve_row_muscles` resolves the sorted distinct template ids; `[]` → `{}` | ✓ |
| `resolve_window` raises `ValueError("unknown user")` | ✓ |

### Rendered-SQL proof (no container)

Compiled against `sqlalchemy.dialects.postgresql` and asserted on the output string and bound parameters:

```
SELECT CAST(date_trunc(%(date_trunc_1)s, timezone(%(timezone_1)s, workouts.start_time)) AS DATE) AS week_start,
       workouts.id AS workout_id, workout_exercises.exercise_template_external_id AS template_id,
       count(*) AS hard_sets, sum(workout_sets.reps) AS total_reps,
       count(*) FILTER (WHERE workout_sets.weight_kg IS NOT NULL AND workout_sets.reps IS NOT NULL) AS tonnage_sets,
       sum(workout_sets.weight_kg * workout_sets.reps) FILTER (...) AS tonnage_kg
FROM workout_sets JOIN workout_exercises ON ... JOIN workouts ON ...
WHERE workouts.user_id = %(user_id_1)s::UUID AND workouts.start_time >= %(start_time_1)s
  AND workouts.start_time < %(start_time_2)s AND workout_sets.set_type != %(set_type_1)s
GROUP BY CAST(date_trunc(...) AS DATE), workouts.id, workout_exercises.exercise_template_external_id
ORDER BY CAST(date_trunc(...) AS DATE), workouts.id, workout_exercises.exercise_template_external_id
```

Bound parameters: `{'date_trunc_1': 'week', 'timezone_1': 'Asia/Jakarta', 'start_time_1': 2026-08-23T17:00Z, 'start_time_2': 2026-08-30T17:00Z, 'set_type_1': 'warmup'}`. `"LIMIT" not in sql` asserted.

### Pure-fold proof (no container)

The plan's exact Task 3 verify command prints `OK`, plus five additional cases: custom weights change `weighted_sets` (`Decimal("3.2") + Decimal("1.2")`) and leave `direct_sets`/`indirect_sets` untouched; one workout with three hamstring exercises gives `len(session_ids) == 1` and `direct_sets == 9`; an unmapped template and an empty resolved set both yield `{}` without raising; two weeks stay separate under the weekly fold and merge to `direct_sets == 7` / 2 sessions under the window fold; a two-muscle template fans out to both groups with `Decimal("4.0")` direct and `Decimal("2.0")` indirect weighted sets.

### Grep acceptance criteria — 24 of 24 pass

| Criterion | Required | Actual |
|---|---|---|
| `MAX_ANALYTICS_WINDOW_DAYS = 1830` | 1 | 1 |
| `COUNT_DURATION_ONLY_SETS = True` | 1 | 1 |
| `WARMUP_SET_TYPE = "warmup"` | 1 | 1 |
| `^def build_window\|^async def resolve_window\|^class AnalyticsWindow` | 3 | 3 |
| `validate_timezone(` | ≥1 | 1 |
| `requested analytics window exceeds the maximum span` | 1 | 1 |
| `ZoneInfo` | 0 | 0 |
| `^class SetRollupRow` | 1 | 1 |
| `^async def weekly_set_rows\|^async def resolve_row_muscles\|^def _hard_set_predicates` | 3 | 3 |
| `cast(func.date_trunc` | ≥1 | 1 |
| `func.timezone(` | ≥1 | 2 |
| `Workout.start_time >= ` | 1 | 1 |
| `Workout.start_time < ` | 1 | 1 |
| `Workout.user_id == user_id` | ≥1 | 1 |
| `set_type == ` | 0 | 0 |
| `exercise_type` | 0 | 0 |
| `effective_muscles_bulk(` | ≥1 | 1 |
| `ExerciseMuscle` | 0 | 0 |
| `f"SELECT\|f'SELECT\|text(` | 0 | 0 |
| `LIMIT\|\.limit(` | 0 | 0 |
| `^class MuscleBucket` | 1 | 1 |
| `^def fold_weeks_by_muscle\|^def fold_window_by_muscle\|^def fold_window_by_template\|^def _fold_by_muscle` | 4 | 4 |
| `session_ids.add(` / `session_ids: set[uuid.UUID]` / `apply_weights(` | 1 / 1 / 1 | 1 / 1 / 1 |
| `Decimal("1.0")\|Decimal("0.5")\|0.5\b` / `pandas\|numpy` / `: float\|float(` | 0 / 0 / 0 | 0 / 0 / 0 |

All 13 public names in the plan's success criteria are importable (`13/13`), and the file is 385 lines against a `min_lines: 190` floor.

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-01 | mitigate | **Done.** `build_window` calls `validate_timezone` before the string leaves it; the rendered SQL was asserted to carry the timezone as `%(timezone_1)s`. Zero `text(` in any spelling, enforced statically by `test_analytics_uses_no_raw_sql_text`. |
| T-04-02 | mitigate | **Done, and proven non-vacuously.** `Workout.user_id == user_id` leads the WHERE clause and `user_id` is keyword-only with no default. A second user's workout in the same window at the same instant returned zero rows for the default user and exactly its own row for its own user. |
| T-04-06 | mitigate | **Done.** `MAX_ANALYTICS_WINDOW_DAYS = 1830` rejects in `build_window` before any query runs. Boundary tested: a 1830-day inclusive span is accepted, 1831 raises. Zero `.limit(` in the module. This closes the clamp 04-01 deliberately transferred here. |
| T-04-05 | mitigate | **Done.** All four `ValueError` messages are fixed literals carrying no date, no user id and no bound parameter: `"end_day precedes start_day"`, `"requested analytics window exceeds the maximum span"`, `"unknown IANA timezone"`, `"unknown user"`. Each asserted by exact string equality. |
| T-04-07 | mitigate | **Structural on all three counts.** `tonnage_sets` beside `tonnage_kg`; `!= 'warmup'` with zero `set_type == ` in the module; `session_ids` as a `set` with exactly one `.add(` site. Each verified against the container. |
| T-04-08 | mitigate | **Done.** `resolve_row_muscles` delegates to `effective_muscles_bulk`; zero `ExerciseMuscle` identifiers, enforced statically by `test_analytics_never_names_the_muscle_tables_directly`. Plan 04-08 adds the runtime `override_changes_answer` test. |
| T-04-09 | mitigate | **Done.** The module contains only `select(...)`; `test_analytics_never_writes` is green. |

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The only user-controlled value reaching SQL is `users.timezone`, and it is validated at the boundary and bound as a parameter.

## Known Stubs

None. Every function is fully implemented and every one was executed — the three async functions against a live Postgres container, the four pure functions against hand-computed expected values.

## Requirements Status

`.planning/REQUIREMENTS.md` was **deliberately left unmodified** — VOL-01, VOL-02 and VOL-03 remain unchecked.

| Requirement | Text | Delivered here? |
|---|---|---|
| VOL-01 | *System calculates weekly training volume…* | No — this plan ships the aggregate the calculation reads. Plan 04-04 produces the figure. |
| VOL-02 | *System calculates weekly per-muscle-group volume…* | No — this plan ships `fold_weeks_by_muscle`; 04-06 assembles the result. |
| VOL-03 | *System calculates training frequency…* | No — this plan ships `fold_window_by_muscle` / `fold_window_by_template`; 04-07 divides by the window. |

The orchestrator should mark these complete once the plans that produce the actual figures land.

## Issues Encountered

- **Worktree base drift, fourth consecutive occurrence.** Documented as Deviation 4. Worth escalating as a worktree-provisioning defect rather than continuing to absorb it per-agent: every wave-1 summary records the same correction, and an agent that skipped the startup check would have silently rebuilt on a pre-Phase-4 tree.
- **No `.venv` in the worktree**, documented as Deviation 3.
- **Pre-existing `mypy backend/tests/` errors** (44 across 13 test files at base, recorded in 04-03's Deferred Issues) are untouched and out of scope. `mypy backend/app` is clean at 44 source files, up one from wave 1's 43.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready.** Plans 04-04, 04-06, 04-07 and 04-08 can import from `app.analytics.rollup` immediately. The contract those plans must honour:

- **Call `resolve_window` (or `build_window`), never construct an `AnalyticsWindow` by hand.** The three guards and the timezone read are the point.
- **Weekly (bucketed) metrics pass `snap_to_weeks=True`; frequency (rate) metrics pass `False`** and divide by `window.days`, per D-03 / U-01.
- **Call `weekly_set_rows` once and fold the result repeatedly.** Re-querying per metric defeats the whole reason the grain is this fine.
- **Project weekly results onto `local_week_spine`** — the fold emits no key for a week with no training, and a silently missing zero week is the most diagnostically interesting one Claude could have seen.
- **Never sum `len(bucket.session_ids)` across buckets** to get a window total; call `fold_window_by_muscle` on the same rows instead. This is the 4.0x inflation, re-introduced at the consumer.
- **`tonnage_kg is None` is not zero.** Carry the distinction into `schemas.py`'s `tonnage_sets` field rather than coercing.
- **Plan 04-09 owns `backend/tests/test_analytics_rollup.py`** and is the missing `test(...)` gate commit for this file. The container probe described above was deliberately not committed, so 04-09 starts from a genuinely untested module and its RED gate is real.

**Open item:** none blocking.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/rollup.py`
- FOUND: `.planning/phases/04-volume-frequency-analytics/04-05-SUMMARY.md`

Commits verified in `git log`:

- FOUND: `77c5a27` feat(04-05): add analytics window resolution to rollup.py
- FOUND: `499c4c8` feat(04-05): add the weekly set aggregate and bulk muscle resolution
- FOUND: `9a55547` feat(04-05): add the pure Python muscle fan-out folds

No file deletions in any commit (`git diff --diff-filter=D --name-only a3acb0c HEAD` empty). No untracked files left behind other than the removed `.venv` symlink.

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*

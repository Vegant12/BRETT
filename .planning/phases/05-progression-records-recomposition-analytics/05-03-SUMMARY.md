---
phase: 05-progression-records-recomposition-analytics
plan: 03
subsystem: analytics
tags: [pydantic, strenum, decimal, mappingproxytype, sqlalchemy, dq-01, dq-02, contracts]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "_AnalyticsModel base, FreshnessMetadata, CoverageMetadata, build_freshness, build_coverage, the FRESHNESS_RESOURCES_* tuple convention"
  - phase: 05-progression-records-recomposition-analytics
    provides: "05-01's NoEstimateReason StrEnum, imported by ProgressionPoint"
provides:
  - "23 Phase 5 public symbols in app.analytics.schemas: 5 StrEnums and 18 frozen return models covering PROG-01..04, CMP-01, BODY-01 and BODY-02"
  - "MeasurementCoverage, a day-grained SIBLING of CoverageMetadata (never a subclass)"
  - "FRESHNESS_RESOURCES_BODY and FRESHNESS_RESOURCES_ALL resource tuples"
  - "MEASURED_DAY_FLOORS ({7: 3, 14: 5, 30: 10}) plus is_measurement_insufficient and the pure build_measurement_coverage"
  - "earliest_measurement_at: the all-time, tenant-scoped oldest weigh-in"
  - "A dynamic fast-suite leak walk over every _AnalyticsModel subclass"
affects: [05-04, 05-05, 05-06, 05-07, 06-mcp-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Contract-first: every Phase 5 return type declared once, up front, so the six implementation plans can run in parallel against a fixed shape"
    - "Sibling-not-subclass for a differently-grained coverage type"
    - "Per-window independent data floors in an immutable MappingProxyType"
    - "Structural security guards written as a dynamic walk over the module namespace, checked against a hand-named set so the walk cannot pass vacuously"

key-files:
  created: []
  modified:
    - backend/app/analytics/schemas.py
    - backend/app/analytics/metadata.py
    - backend/tests/test_analytics_metadata.py

key-decisions:
  - "RecompositionResult.status is exempted from the forbidden-field deny-list by name and immediately re-pinned by TYPE, because blueprint 26's recomposition classification and sync_state's run status are the same word with opposite provenance"
  - "The new model walk uses a floor (>= 28) plus an explicit Phase 5 name set rather than an exact count pin, matching test_analytics_isolation.py's documented convention; the walk is over the module namespace so no model can escape it regardless"
  - "The two new freshness tuples and MEASURED_DAY_FLOORS were placed with their sibling constants near the top of metadata.py rather than appended after the function definitions"
  - "PersonalRecordType carries four members, not five: PROG-04's fifth record type is a list keyed by weight (RepsAtWeightRecord), not a scalar record"

patterns-established:
  - "Day-grained vs session-grained coverage: MeasurementCoverage counts measured DAYS and echoes window_days back, because D-15 gives each window its own floor and the flag is uninterpretable without it"
  - "build_measurement_coverage is pure and synchronous while build_coverage is async: BODY-01 fetches once and folds five ways, so an async builder per window would turn one query into five"
  - "Security guards over the analytics contract live in the FAST suite, never behind an integration marker"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-08-31
---

# Phase 5 Plan 03: Phase 5 Return Contracts & Day-Grained Coverage Summary

**All 23 Phase 5 analytics return contracts declared up front as frozen, extra-forbidding, input-hiding Pydantic types, plus a day-grained body-measurement coverage envelope with D-15's three independent per-window floors.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-08-31T03:08:00Z
- **Completed:** 2026-08-31T03:23:09Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Declared every Phase 5 public return type in one commit, so plans 05-04 through 05-07 can implement in parallel against a fixed field-name contract that Phase 6 will code against.
- Added `MeasurementCoverage` as a deliberate **sibling** of `CoverageMetadata`, keeping `insufficient_data` from meaning two different things inside a single BODY-02 response.
- Implemented D-15's three independent coverage floors in an immutable `MappingProxyType`, with a raising (not permissive) path for an unchosen window length and a value-free error message.
- Widened the leak guard from a single hand-pinned model (`FreshnessMetadata`) to a dynamic walk over **all 28** `_AnalyticsModel` subclasses, running in the fast suite so it cannot be skipped when Docker is down.

## Task Commits

1. **Task 1: Phase 5 StrEnums and return models in schemas.py** — `13dc55c` (feat)
2. **Task 2: body freshness resources and D-15 day-grained coverage in metadata.py** — `eb832e0` (feat)
3. **Task 3: D-15 floor tests and the whole-package leak guard** — `6e27d16` (test)

## Files Created/Modified

- `backend/app/analytics/schemas.py` — +434 lines. 5 StrEnums (`TrendVerdict`, `PlateauConfidence`, `ProgressionSignal`, `RecompositionStatus`, `PersonalRecordType`) and 18 return models. Module docstring widened to cover every analytics metric.
- `backend/app/analytics/metadata.py` — +81 lines. `FRESHNESS_RESOURCES_BODY`, `FRESHNESS_RESOURCES_ALL`, `MEASURED_DAY_FLOORS`, `is_measurement_insufficient`, `build_measurement_coverage`, `earliest_measurement_at`. No pre-existing symbol touched.
- `backend/tests/test_analytics_metadata.py` — +310 lines, 8 new tests (6 fast, 2 integration). No pre-existing test modified.

## Final Field List of Every New Model

Downstream plans assert against these exact names.

| Model | Fields |
|---|---|
| `MeasurementCoverage` | `window_days: int`, `measured_days_in_window: int`, `insufficient_data: bool`, `earliest_measurement_at: dt.date \| None` |
| `ProgressionPoint` | `local_day: dt.date`, `workout_id: uuid.UUID`, `sets: int`, `total_reps: int \| None`, `volume_kg: Decimal \| None`, `volume_sets: int`, `best_weight_kg: Decimal \| None`, `best_reps: int \| None`, `estimated_1rm_kg: Decimal \| None`, `no_estimate_reason: NoEstimateReason \| None` |
| `ExerciseProgressionResult` | `exercise_template_external_id: str`, `title: str \| None`, `exercise_type: str \| None`, `window_start: dt.date`, `window_end: dt.date`, `points: list[ProgressionPoint]`, `coverage: CoverageMetadata`, `freshness: FreshnessMetadata` |
| `ExerciseTrend` | `exercise_template_external_id: str`, `title: str \| None`, `verdict: TrendVerdict`, `rate_percent_per_week: Decimal \| None`, `weeks_with_data: int` |
| `ExerciseTrendsResult` | `window_start: dt.date`, `window_end: dt.date`, `exercises: list[ExerciseTrend]`, `coverage: CoverageMetadata`, `freshness: FreshnessMetadata` |
| `PlateauResult` | `exercise_template_external_id: str`, `title: str \| None`, `plateaued: bool`, `plateau_duration_days: int \| None`, `qualifying_sessions_in_streak: int`, `recent_performance_kg: Decimal \| None`, `historical_best_kg: Decimal \| None`, `confidence: PlateauConfidence`, `threshold_percent: Decimal`, `min_sessions: int`, `min_elapsed_days: int`, `lookback_start: dt.date`, `lookback_end: dt.date` |
| `PlateauReport` | `lookback_weeks: int`, `lookback_start: dt.date`, `lookback_end: dt.date`, `exercises: list[PlateauResult]`, `coverage: CoverageMetadata`, `freshness: FreshnessMetadata` |
| `PersonalRecord` | `record_type: PersonalRecordType`, `value: Decimal`, `achieved_on: dt.date`, `weight_kg: Decimal \| None`, `reps: int \| None`, `volume_sets: int \| None` |
| `RepsAtWeightRecord` | `weight_kg: Decimal`, `reps: int`, `achieved_on: dt.date` |
| `PersonalRecordsResult` | `exercise_template_external_id: str`, `title: str \| None`, `window_start: dt.date`, `window_end: dt.date`, `records: list[PersonalRecord]`, `reps_at_weight: list[RepsAtWeightRecord]`, `coverage: CoverageMetadata`, `freshness: FreshnessMetadata` |
| `ComparisonRate` | `metric: str`, `exercise_template_external_id: str \| None`, `title: str \| None`, `period_a_per_week: Decimal \| None`, `period_b_per_week: Decimal \| None`, `delta_per_week: Decimal \| None`, `delta_percent: Decimal \| None` |
| `ComparisonLevel` | `metric: str`, `exercise_template_external_id: str \| None`, `title: str \| None`, `period_a_value: Decimal \| None`, `period_b_value: Decimal \| None`, `delta: Decimal \| None`, `delta_percent: Decimal \| None` |
| `MuscleGroupComparison` | `muscle_group: CanonicalMuscleGroup`, `direct_sets: ComparisonRate`, `indirect_sets: ComparisonRate`, `weighted_sets: ComparisonRate` |
| `PeriodSummary` | `start_day: dt.date`, `end_day: dt.date`, `days: int`, `coverage: CoverageMetadata` |
| `PeriodComparisonResult` | `period_a: PeriodSummary`, `period_b: PeriodSummary`, `totals: list[ComparisonRate]`, `exercises: list[ComparisonRate]`, `exercise_levels: list[ComparisonLevel]`, `muscle_groups: list[MuscleGroupComparison]`, `freshness: FreshnessMetadata` |
| `BodyWeightTrendResult` | `anchor_day: dt.date`, `average_7d_kg: Decimal \| None`, `average_14d_kg: Decimal \| None`, `average_30d_kg: Decimal \| None`, `coverage_7d: MeasurementCoverage`, `coverage_14d: MeasurementCoverage`, `coverage_30d: MeasurementCoverage`, `trend_anchor_coverage: MeasurementCoverage`, `trend_rate_kg_per_week: Decimal \| None`, `trend_rate_percent_per_week: Decimal \| None`, `latest_week_delta_kg: Decimal \| None`, `freshness: FreshnessMetadata` |
| `AggregateProgression` | `verdict: TrendVerdict`, `signal: ProgressionSignal`, `net_score: Decimal \| None`, `classified_exercises: int`, `improving: int`, `stable: int`, `declining: int`, `unclear: int` |
| `RecompositionResult` | `status: RecompositionStatus`, `disclaimer: str`, `weight_trend: BodyWeightTrendResult`, `progression_signal: AggregateProgression`, `training_volume: WeeklyVolumeResult`, `freshness: FreshnessMetadata` |

**StrEnum members:**

- `TrendVerdict`: `IMPROVING`, `STABLE`, `DECLINING`, `UNCLEAR`
- `PlateauConfidence`: `LOW`, `MEDIUM`, `HIGH`
- `ProgressionSignal`: `POSITIVE`, `NEUTRAL`, `NEGATIVE`, `INSUFFICIENT`
- `RecompositionStatus`: `LIKELY_RECOMP_PROGRESSING`, `LIKELY_MUSCLE_GAIN`, `LIKELY_FAT_LOSS`, `WEIGHT_STABLE`, `WEIGHT_GAIN_TOO_FAST`, `WEIGHT_LOSS_TOO_FAST`, `INSUFFICIENT_DATA` (exactly seven)
- `PersonalRecordType`: `MAX_WEIGHT`, `MAX_REPS`, `ESTIMATED_1RM`, `SESSION_VOLUME`

## Answers to the Plan's Explicit Output Questions

1. **Did the existing leak test discover models dynamically or by hand?** **By hand.** The pre-existing `test_freshness_model_cannot_carry_sync_state_internals` pins exactly one model's field set (`set(FreshnessMetadata.model_fields) == {"resources"}`) and constructs one rejection case. It does not iterate. Because the plan also said "Do not modify existing tests", the walk was added as new machinery — a `_analytics_return_models()` helper that discovers every `_AnalyticsModel` subclass from the `app.analytics.schemas` namespace — and the existing test was left byte-identical.
2. **`pyproject.toml` untouched?** **Yes.** No new dependency.
3. **`backend/app/db/models/` untouched?** **Yes.** No migration was created; `BodyMeasurement` already has `user_id`, `measured_on` (a `Date`) and `weight_kg`.

`git diff --stat` against the plan base (`844d230`) shows exactly the three planned files and nothing else. `volume.py`, `frequency.py`, `rollup.py`, `estimates.py` and `core/time.py` are all untouched.

## Decisions Made

- **`RecompositionResult.status` deny-list collision, resolved by a typed exemption.** The plan's Task 1 declares `status: RecompositionStatus` and the plan's Task 3 forbids any field literally named `status`. Rather than drop `status` from the deny-list (which weakens the guard against `sync_state.status` leaking), the exemption is scoped to `RecompositionResult` **by name** and then immediately re-pinned **by type** — the test asserts `RecompositionResult.model_fields["status"].annotation is RecompositionStatus`. A sync run status arriving later under that name still fails.
- **Floor rather than exact count for the model walk.** `test_analytics_isolation.py:87-90` already establishes the convention ("The floor rises with the package on purpose"). An exact pin would break every time a later plan legitimately adds a model, and would buy nothing, because the walk is over the module namespace and no model can escape it. The vacuity risk the plan was guarding against is instead closed by asserting the 18 Phase 5 models by name.
- **Constants placed with their siblings.** `FRESHNESS_RESOURCES_BODY`, `FRESHNESS_RESOURCES_ALL` and `MEASURED_DAY_FLOORS` sit in the module's constants block beside `FRESHNESS_RESOURCES_WORKOUTS` / `_MUSCLE`, rather than being appended after the function definitions as a literal reading of "append" would have produced.
- **`BodyMeasurement` imported from `app.db.models.body`,** matching the file's existing `from app.db.models.workout import Workout` submodule-path style, rather than the package root.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wrapped the widened module docstring's opening line**

- **Found during:** Task 1
- **Issue:** The plan mandated a byte-exact 116-character opening docstring line. Ruff `E501` (line-length 100) rejected it, blocking the task's own `ruff check` acceptance criterion.
- **Fix:** Split at the parenthesis onto a second line. Every character of the mandated text is preserved; only a line break was inserted.
- **Files modified:** `backend/app/analytics/schemas.py`
- **Verification:** `ruff check backend/app/analytics/schemas.py` passes; `ruff format --check` reports the file already formatted.
- **Committed in:** `13dc55c`

**2. [Rule 1 - Bug] `PersonalRecordType` docstring said "five record types" over four members**

- **Found during:** Task 1
- **Issue:** The mandated docstring reads "PROG-04's five record types" but the enum declares four. In a module whose docstrings are explicitly the contract, an off-by-one in the count is a defect a Phase 6 reader would trip over.
- **Fix:** Kept the mandated sentence verbatim and appended a clarifying paragraph explaining that the fifth type — "max reps at a given weight" — is a list keyed by weight and therefore has its own model, `RepsAtWeightRecord`, rather than a member here.
- **Files modified:** `backend/app/analytics/schemas.py`
- **Verification:** Enum member count and values unchanged; all Task 1 acceptance greps pass.
- **Committed in:** `13dc55c`

**3. [Rule 1 - Bug] The plan's Task 3 deny-list forbade a field the plan's own Task 1 declares**

- **Found during:** Task 3
- **Issue:** `test_no_new_model_declares_a_forbidden_field` was specified to forbid the field name `status`, but `RecompositionResult.status` is blueprint 26's required recomposition classification. Written literally, the test fails against the code the same plan mandates.
- **Fix:** Added a narrow, documented `_FORBIDDEN_NAME_EXEMPTIONS` entry for `RecompositionResult` → `{"status"}`, immediately followed by an assertion that the annotation behind that name is `RecompositionStatus`. Verified non-vacuous: without the exemption the walk reports exactly one hit, `RecompositionResult: ['status']`.
- **Files modified:** `backend/tests/test_analytics_metadata.py`
- **Verification:** `pytest -q backend/tests/test_analytics_metadata.py` — 19 passed.
- **Committed in:** `6e27d16`

**4. [Rule 3 - Blocking] Two test statements reflowed to satisfy `ruff format`**

- **Found during:** Task 3
- **Issue:** `ruff check` passed but `ruff format --check` (a pre-commit hook, `ruff-format`) wanted two `golden_workout.body_measurement(...)` calls on single lines, and one assertion exceeded 100 characters.
- **Fix:** Applied the formatter's own layout.
- **Files modified:** `backend/tests/test_analytics_metadata.py`
- **Verification:** All three touched files report `already formatted`.
- **Committed in:** `6e27d16`

**5. [Rule 3 - Worktree environment] Recreated the `.venv` symlink**

- **Found during:** Task 1 setup
- **Issue:** `.venv` is gitignored and lives only in the main checkout, but every verification command in the plan invokes `.venv/bin/python`, `.venv/bin/ruff` and `.venv/bin/mypy`.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree; removed before returning. Not committed.
- **Files modified:** None tracked.

---

**Total deviations:** 5 auto-fixed (2 bugs in the plan's own specification, 3 blocking/environment)
**Impact on plan:** No scope creep. Deviations 2 and 3 are corrections to internal contradictions in the plan text; 1, 4 and 5 are lint/environment mechanics. Every mandated symbol, field name and value was delivered exactly as specified.

## Issues Encountered

**Worktree branch was cut from an ancestor commit again.** As the prompt predicted, this worktree's branch was based on `1e97f3b` (`chore(02-05): record auto-chain flag`) instead of main HEAD `844d230`, which meant Wave 1's `estimates.py` (`NoEstimateReason`, a hard dependency of `ProgressionPoint`) was absent. Corrected with `git reset --hard 844d230` before any work; the worktree was clean, so nothing was lost. This is now three-for-three across this phase's worktree agents.

**Pre-existing mypy baseline confirmed, not fixed.** `mypy backend/` reports 44 errors across 13 test modules (`test_config.py`, `test_db_models.py`, `test_mcp_tools.py`, `conftest.py` and 9 others), all predating this plan. `mypy backend/app/` exits 0 across 48 files, and `test_analytics_metadata.py` contributes **zero** errors to the baseline. Out of scope, left alone.

## Verification Results

| Check | Result |
|---|---|
| `pytest -q` (full suite) | **393 passed** |
| `pytest -q -m "not integration"` (fast suite) | **222 passed**, 171 deselected |
| `pytest -q backend/tests/test_analytics_metadata.py` | **19 passed** (11 before this plan, +8 new) |
| `pytest -q -m "not integration" backend/tests/test_analytics_metadata.py` | **8 passed** — the 6 new floor/leak/config guards all run with Docker stopped |
| `ruff check backend/` | All checks passed |
| `ruff format --check` (three touched files) | 3 files already formatted |
| `mypy backend/app/` | Success, 48 source files |
| `mypy` on the three touched files | 0 errors attributable to them |
| `git diff --stat` vs `844d230` | Exactly 3 files, 825 insertions, 4 deletions |
| Model walk | 28 `_AnalyticsModel` subclasses discovered (10 Phase 4 + 18 Phase 5) |
| Deny-list non-vacuity | Without the exemption, exactly 1 hit: `RecompositionResult: ['status']` |

## Requirements

`requirements-completed: []` — deliberately empty. This plan claims `PROG-01..04`, `CMP-01`, `BODY-01` and `BODY-02` in its frontmatter, but delivers only their **contracts**: types, coverage floors and freshness tuples. Not one of those requirements has a computation behind it yet. Following the precedent 05-01 and 05-02 set for `PROG-01`/`PROG-04`, none is checked off here; plans 05-04 through 05-07 own the implementations that complete them.

## Known Stubs

None. Every symbol this plan declares is a complete, final contract — there is no placeholder data, no empty-collection default flowing to a UI, and no `TODO`. The models are intentionally declaration-only: they are the fixed shape the six implementation plans populate, which is the plan's stated purpose rather than a stub.

## User Setup Required

None — no external service configuration, no new dependency, no migration.

## Next Phase Readiness

- Plans 05-04 through 05-07 can now run in parallel against a frozen field-name contract. Every model name, field name and field type they must produce is listed in the table above.
- `MEASURED_DAY_FLOORS`, `is_measurement_insufficient` and `build_measurement_coverage` are ready for BODY-01's single-query-folded-five-ways implementation.
- `FRESHNESS_RESOURCES_BODY` / `FRESHNESS_RESOURCES_ALL` are ready for BODY-01 and BODY-02 respectively.
- Implementers should note two constants the contracts reference but this plan does **not** define: `PLATEAU_IMPROVEMENT_TOLERANCE` (D-07a, feeds `PlateauResult.threshold_percent`) and the fixed `RecompositionResult.disclaimer` string. Both belong to their implementing plans.
- No blockers.

## Self-Check: PASSED

All three modified files exist on disk. All three task commits (`13dc55c`, `eb832e0`, `6e27d16`)
are present in `git log --all`. No claimed artifact is missing.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

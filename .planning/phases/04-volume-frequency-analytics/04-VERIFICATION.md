---
phase: 04-volume-frequency-analytics
verified: 2026-08-30T11:09:58Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 4: Volume & Frequency Analytics Verification Report

**Phase Goal:** The system can answer "how much work am I doing, and which muscles is it reaching?" from stored data, with honest metadata attached to every answer
**Verified:** 2026-08-30T11:09:58Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Weekly volume returns hard sets and reps for every Hevy exercise type, with tonnage reported only where the modality supports it, and warm-up sets excluded from every figure | ✓ VERIFIED | `get_weekly_volume` (`backend/app/analytics/volume.py:137-201`) built on `weekly_set_rows` (`rollup.py:192-266`), which filters `WorkoutSet.set_type != WARMUP_SET_TYPE` and gates tonnage on `has_tonnage = weight_kg IS NOT NULL AND reps IS NOT NULL`, returning `tonnage_kg=None` (not 0) when `tonnage_sets==0`. Proven by passing tests `test_warmup_sets_are_excluded_from_every_figure`, `test_modality_without_operands_reports_tonnage_none`, `test_duration_only_sets_count_as_hard_sets`, `test_zero_load_set_is_a_tonnage_set_contributing_zero` |
| 2 | Per-muscle-group weekly volume breaks out direct versus indirect sets using the configurable weighting, making "which muscles are undertrained" answerable | ✓ VERIFIED | `get_muscle_group_volume` (`volume.py:204-286`) returns `MuscleGroupVolume(direct_sets, indirect_sets, weighted_sets)` per muscle per week, resolved via `resolve_row_muscles` → `app.normalization.resolver.effective_muscles_bulk` (never a direct table join — statically enforced, see below). `weights` is a query-time parameter defaulting to the resolver's 1.0/0.5. Proven by `test_muscle_split_reports_direct_indirect_and_weighted_sets`, `test_custom_weights_change_weighted_sets_only`, `test_override_changes_the_per_muscle_result` |
| 3 | Training frequency per muscle group and per exercise reports sessions per week over a requested window | ✓ VERIFIED | `get_training_frequency` (`frequency.py:106-175`) computes `sessions_per_week` (exact `Decimal`, quantized) per muscle group and per exercise over the raw (non-snapped) requested window, session-deduplicated by workout id. Proven by `test_per_muscle_sessions_dedup_within_one_workout`, `test_per_muscle_sessions_count_separate_workouts_separately`, `test_sessions_per_week_over_an_arbitrary_range`, `test_per_exercise_frequency_is_reported_alongside_per_muscle` |
| 4 | Every analytics response carries freshness metadata (when the underlying data was last synced) and coverage/uncertainty metadata (sessions in window, insufficient-data flag) | ✓ VERIFIED | All three top-level result schemas (`WeeklyVolumeResult`, `MuscleGroupVolumeResult`, `TrainingFrequencyResult` in `schemas.py:94,130,157`) declare mandatory `coverage: CoverageMetadata` and `freshness: FreshnessMetadata` fields, populated by every producing function via `build_coverage`/`build_freshness` from `metadata.py`. Per-muscle rows additionally carry their own `sessions`/`insufficient_data` (U-03). Proven by `test_response_carries_freshness_and_coverage`, `test_muscle_group_volume_carries_both_freshness_resources`, `test_frequency_carries_freshness_for_workouts_and_exercise_templates`, `test_frequency_carries_the_d06_coverage_block` |
| 5 | All calculations are verified against golden fixture workouts covering warm-ups, dropsets, supersets, and bodyweight exercises | ✓ VERIFIED | `golden_workout` builder fixture (`backend/tests/conftest.py`) + dedicated tests: warm-ups (`test_warmup_sets_are_excluded_from_every_figure`), dropsets (`test_dropset_counts_as_a_hard_set`, `test_rows_exclude_warmups_and_count_dropsets`), supersets (`test_superset_grouping_changes_no_number`), bodyweight/reps-only (`test_modality_without_operands_reports_tonnage_none`, `test_duration_only_sets_count_as_hard_sets`) |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/core/time.py` | `local_range_bounds`, `snap_local_week_range`, `local_week_spine` | ✓ VERIFIED | All three present (lines 86, 108, 127), delegate to `local_day_bounds`, unit-tested in `test_time.py` (25 tests pass) |
| `backend/app/db/models/exercise.py` | Corrected `exercise_type` vocabulary comment | ✓ VERIFIED | Comment rewritten from live sync counts; phantom values (`bodyweight_reps`, `bodyweight_assisted_reps`, `weight_duration`) absent |
| `backend/app/analytics/__init__.py` | Package boundary declaration | ✓ VERIFIED | 19-line module docstring stating the one-way MCP arrow, no-integrations, no-direct-muscle-table rules |
| `backend/app/analytics/schemas.py` | 10 Pydantic return/metadata types | ✓ VERIFIED | 169 lines; `FreshnessMetadata`, `CoverageMetadata`, `WeeklyVolumeWeek/Result`, `MuscleGroupVolume/Week/Result`, `MuscleGroupFrequency`, `ExerciseFrequency`, `TrainingFrequencyResult` all present |
| `backend/app/analytics/metadata.py` | `INSUFFICIENT_DATA_SESSION_THRESHOLD`, `is_insufficient`, `sessions_in_window`, `earliest_workout_at`, `build_coverage`, `build_freshness` | ✓ VERIFIED | 154 lines, all six present, threshold constant = 2 |
| `backend/app/analytics/rollup.py` | `AnalyticsWindow`, `build_window`, `resolve_window`, `SetRollupRow`, `weekly_set_rows`, `resolve_row_muscles`, `MuscleBucket`, fold helpers | ✓ VERIFIED | 385 lines, all present; `COUNT_DURATION_ONLY_SETS` constant present |
| `backend/app/analytics/volume.py` | `get_weekly_volume` (VOL-01), `get_muscle_group_volume` (VOL-02) | ✓ VERIFIED | 286 lines, both async functions present and fully wired |
| `backend/app/analytics/frequency.py` | `get_training_frequency` (VOL-03), `sessions_per_week` | ✓ VERIFIED | 175 lines, both present |
| `backend/tests/conftest.py` | `golden_workout` builder fixture | ✓ VERIFIED | Present, flush-and-rollback pattern, self-tested |
| `backend/tests/test_analytics_isolation.py` | Static boundary tests | ✓ VERIFIED | 6 tests enforcing no `app.mcp`/`app.integrations` import, no direct muscle-table ORM reference, no raw SQL text, no session writes |
| `backend/tests/test_analytics_*.py` (fixtures, metadata, volume, frequency, rollup) | Golden-fixture + unit test coverage | ✓ VERIFIED | 73 test functions total across the 6 analytics test modules |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `volume.py::get_weekly_volume` | `rollup.py::resolve_window` | `snap_to_weeks=True` | ✓ WIRED | Confirmed at `volume.py:155-161` |
| `frequency.py::get_training_frequency` | `rollup.py::resolve_window` | `snap_to_weeks=False` | ✓ WIRED | Confirmed at `frequency.py:120-122` |
| `volume.py::get_weekly_volume` | `core/time.py::local_week_spine` | gap-free week enumeration | ✓ WIRED | Confirmed at `volume.py:170` |
| `volume.py::get_muscle_group_volume` | `rollup.py::resolve_row_muscles` → `normalization.resolver.effective_muscles_bulk` | resolver-backed, override-aware | ✓ WIRED | Confirmed at `volume.py:235`, `rollup.py:282-284`; never joins `ExerciseMuscle`/`ExerciseMuscleOverride` directly — statically enforced by `test_analytics_never_names_the_muscle_tables_directly` |
| `volume.py` / `frequency.py` | `metadata.py::build_coverage` / `build_freshness` | DQ-01/DQ-02 envelope attached to every response | ✓ WIRED | Confirmed at `volume.py:192-200,278-285`, `frequency.py:130-132,172-174` |
| `rollup.py::weekly_set_rows` | `ix_workouts_user_id_start_time` | bare `Workout.start_time` comparison (index-safe) | ✓ WIRED | Confirmed at `rollup.py:240-241`, column left bare on both sides of the comparison |
| `test_analytics_isolation.py` | `app/analytics/` | static `rglob` boundary walk | ✓ WIRED | 6 tests pass, `test_the_walk_actually_finds_files` guards against a vacuous walk |

### Data-Flow Trace (Level 4)

Not applicable in the UI sense (no frontend). Traced instead: request parameters (`user_id`, `start_day`, `end_day`) → real SQL aggregate against live schema (`weekly_set_rows`) → Python folds → Pydantic response. Verified against a **real Postgres container** (testcontainers), not a mock: `pytest -m integration` on the four analytics test modules — **45 passed**. This confirms the SQL aggregate produces real rows from the schema, not static/hardcoded values.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast suite (all analytics + time tests) | `pytest backend/tests -q -m "not integration"` | 206 passed, 163 deselected | ✓ PASS |
| Integration suite against real Postgres (testcontainers) | `pytest backend/tests/test_analytics_rollup.py test_analytics_volume.py test_analytics_frequency.py test_analytics_metadata.py -q -m integration` | 45 passed | ✓ PASS |
| Lint | `ruff check backend/app/analytics backend/app/core/time.py <test files>` | All checks passed | ✓ PASS |
| Type check | `mypy backend/app/analytics backend/app/core/time.py` | Success: no issues in 7 source files | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| VOL-01 | 04-06 | Weekly training volume (hard sets, reps, tonnage where supported), warm-ups excluded | ✓ SATISFIED | `get_weekly_volume`, marked Complete in REQUIREMENTS.md, 15 passing golden-fixture tests |
| VOL-02 | 04-08 | Weekly per-muscle-group volume, direct vs indirect | ✓ SATISFIED | `get_muscle_group_volume`, marked Complete, override-proving test present |
| VOL-03 | 04-07 | Training frequency per muscle group and exercise (sessions/week) | ✓ SATISFIED | `get_training_frequency`, marked Complete, dedup + arithmetic tests pass |
| DQ-01 | 04-04 | Freshness metadata on every analytics response | ✓ SATISFIED | `build_freshness` wired into all 3 result types, per-resource `last_synced_at` |
| DQ-02 | 04-04 | Coverage/uncertainty metadata (sessions in window, insufficient-data flag) | ✓ SATISFIED | `build_coverage` wired into all 3 result types; `INSUFFICIENT_DATA_SESSION_THRESHOLD` shared constant |

No orphaned requirements: REQUIREMENTS.md maps exactly VOL-01, VOL-02, VOL-03, DQ-01, DQ-02 to Phase 4, and all five appear in at least one plan's `requirements` frontmatter (04-01 through 04-09 collectively cover all five).

### Anti-Patterns Found

None blocking or warning-level. Two `return {}` guard clauses found (`frequency.py:96`, `rollup.py:281`) — inspected and confirmed to be legitimate empty-input short-circuits (empty template-id list), not stubs; both are followed by a real query when input is non-empty and are covered by the surrounding test suite.

Code review (`04-REVIEW.md`, standard depth, 15 files): 0 critical, 0 warning, 1 info. The info item (`IN-01`, `frequency.py:82-103` — `_template_titles` omits the `provider` predicate) is a documented forward-looking gap that is provably safe under v1's single-provider (`"hevy"`) constraint and does not affect current correctness; it does not block phase goal achievement.

### Human Verification Required

None. This phase is backend-only (SQL aggregate + Pydantic response types), with no UI, no external service call, and fully deterministic output — every behavior asserted in the ROADMAP success criteria is covered by an automated golden-fixture test that ran and passed against a real Postgres container, not a mock.

### Gaps Summary

No gaps found. All 5 ROADMAP success criteria verified against actual code with passing automated tests (206 fast-suite + 45 integration-suite, all green), lint and type checks clean, and the phase's own static isolation tests (which specifically guard against the phase's own documented failure modes — session-count inflation, tonnage-from-null coercion, warm-up/dropset misclassification, and the muscle-override replacement-vs-merge trap) all pass.

---

_Verified: 2026-08-30T11:09:58Z_
_Verifier: Claude (gsd-verifier)_

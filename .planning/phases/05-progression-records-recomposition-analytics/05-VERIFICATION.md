---
phase: 05-progression-records-recomposition-analytics
verified: 2026-08-31T12:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 5: Progression, Records & Recomposition Analytics Verification Report

**Phase Goal:** The system returns verdicts, not just numbers — whether a lift is progressing, whether it has plateaued, what the records are, and where body recomposition stands
**Verified:** 2026-08-31T12:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Exercise progression returns a weight/reps/sets time series, with e1RM only where modality/rep range make it meaningful, otherwise null-plus-reason | VERIFIED | `backend/app/analytics/estimates.py::estimate_1rm` implements Epley in exact `Decimal`, gated by `E1RM_EXERCISE_TYPE` (modality) and `MAX_TRUSTED_REPS` (rep range), returning `(None, NoEstimateReason.*)` when refused — never a bare null. `progression.py::get_exercise_progression` builds one `ProgressionPoint` per local training day (ascending, gap-omitting) with weight/reps/sets/volume plus the estimate. Confirmed by 493 passing backend tests including container-backed `test_analytics_progression.py` and fast-suite exact-Decimal tests in `test_analytics_estimates.py` |
| 2 | Each tracked exercise receives improving/stable/declining/unclear verdict from multiple sessions; plateau detection reports window+threshold alongside result | VERIFIED | `progression.py::classify_trend` requires `MIN_TREND_WEEKS` distinct weeks or returns `UNCLEAR, None`; otherwise computes an exact-Decimal OLS slope normalized by window mean, banded into IMPROVING/STABLE/DECLINING. `progression.py::get_plateaus`/`scan_plateau` returns `PlateauReport` with `lookback_start`/`lookback_end`/`lookback_weeks` and `threshold_percent` echoed on every result, seeded from history strictly before the lookback window. Verified via source read and passing `test_analytics_progression.py` (streak-scan + verdict tests) |
| 3 | Personal records (max weight, max reps at a weight, e1RM, volume, rep PR) detected with dates, excluding warm-ups | VERIFIED | `records.py::get_personal_records` runs one pass over `qualifying_set_rows` (which already excludes warm-ups in SQL via `_hard_set_predicates`), tracking five independent record accumulators (`best_weight`, `best_reps`, `best_e1rm`, `per_weight`, `best_volume` per exercise-session), each carrying the row's `local_day`. Tie-breaks resolve to the earlier date (`_better`/`_key`). Confirmed by passing `test_analytics_records.py` |
| 4 | Two time periods compared with values normalized per week so unequal-length windows don't mislead | VERIFIED | `comparison.py::compare_periods` uses `_per_week`/`sessions_per_week` for counts/sums, but keeps e1RM as a compared LEVEL (never divided by weeks) via `ComparisonLevel`. `_delta_percent` returns `None` (not an exception or silent zero) on a zero baseline. `test_unequal_length_periods_with_identical_weekly_training` (in `test_analytics_comparison.py`) directly asserts the zero-delta case from the must-haves. All tests pass |
| 5 | Body-weight trend (7/14/30-day rolling avg, weekly rate) and recomposition verdict, degrading to insufficient-data, framed as decision support | VERIFIED | `bodyweight.py::get_body_weight_trend` computes three independently-gated rolling windows plus a 4-week-smoothed rate (`None` when either sub-window lacks coverage) from real weigh-in days only (no interpolation). `recomposition.py::get_recomposition_status` combines this with `aggregate_progression` (from `get_exercise_trends`), classifies into exactly 7 `RecompositionStatus` values (verified enum has exactly 7 members), and every `RecompositionResult` carries `INTERPRETATION_DISCLAIMER` as a required field, not documentation. Live-data path confirmed returning `insufficient_data` correctly when the smoothed window lacks coverage. All tests pass |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/analytics/estimates.py` | Epley e1RM, D-02/D-03 gates | ✓ VERIFIED | 89 lines, exports `estimate_1rm`, `NoEstimateReason`, `MAX_TRUSTED_REPS`, `E1RM_EXERCISE_TYPE` — all present, no stub patterns |
| `backend/app/analytics/rollup.py` | Set-grain qualifying-set query | ✓ VERIFIED | 534 lines, `qualifying_set_rows`, `_hard_set_predicates`, tenant-scoped outer join to `exercise_templates` all present |
| `backend/app/analytics/schemas.py` | All Phase 5 return contracts | ✓ VERIFIED | 602 lines, all 21 expected exports present (`TrendVerdict`, `PlateauReport`, `PersonalRecordsResult`, `RecompositionResult`, etc.) |
| `backend/app/analytics/metadata.py` | Freshness/coverage helpers | ✓ VERIFIED | 233 lines, `FRESHNESS_RESOURCES_BODY`, `MEASURED_DAY_FLOORS`, `build_measurement_coverage` present |
| `backend/app/analytics/progression.py` | PROG-01/02/03 series, trend, plateau | ✓ VERIFIED | 779 lines, `best_set_per_day`, `get_exercise_progression`, `classify_trend`, `get_exercise_trends`, `scan_plateau`, `get_plateaus` all present |
| `backend/app/analytics/records.py` | PROG-04 record detection | ✓ VERIFIED | 282 lines, `get_personal_records` present with 5 independent record accumulators |
| `backend/app/analytics/bodyweight.py` | BODY-01 rolling averages | ✓ VERIFIED | 294 lines, `get_body_weight_trend`, `TREND_ANCHOR_WEEKS`, `MANUAL_SOURCE` present |
| `backend/app/analytics/comparison.py` | CMP-01 two-period comparison | ✓ VERIFIED | 507 lines, `compare_periods` present, level/rate split confirmed |
| `backend/app/analytics/recomposition.py` | BODY-02 status verdict | ✓ VERIFIED | 340 lines, `get_recomposition_status`, `aggregate_progression`, `classify_recomposition`, `INTERPRETATION_DISCLAIMER` all present |
| `backend/app/analytics/__init__.py` | Package docstring naming requirements | ✓ VERIFIED | 21 lines, references PROG-01 and other requirement IDs |
| 10x `backend/tests/test_analytics_*.py` | Fast-suite + container-backed coverage | ✓ VERIFIED | All exist, all pass (117 phase-5-specific tests + 35 estimates/isolation/metadata fast-suite tests) |

### Key Link Verification

Automated `gsd-tools verify key-links` produced false negatives on this phase due to two tool bugs: (1) regex patterns already escaped in PLAN frontmatter (e.g. `estimate_1rm\\(`) get double-escaped by the tool, breaking the match; (2) `file.py::function_name` source paths are not resolved to the underlying file. All 21 key links across the 10 plans were re-verified manually with `grep` against the actual source and confirmed WIRED.

| From | To | Via | Status |
|------|-----|-----|--------|
| `test_analytics_estimates.py` | `estimates.py` | import | ✓ WIRED (line 25) |
| `test_analytics_isolation.py` | `app/analytics/*.py` | `_analytics_modules()` | ✓ WIRED |
| `rollup.py::qualifying_set_rows` | `rollup.py::_hard_set_predicates` | splat | ✓ WIRED (lines 243, 349) |
| `rollup.py::qualifying_set_rows` | `exercise_templates` | tenant-scoped outerjoin | ✓ WIRED (line 382) |
| `schemas.py` | `estimates.py` | `NoEstimateReason` import | ✓ WIRED (line 36) |
| `metadata.py` | `sync_state.py` | `RESOURCE_BODY_MEASUREMENTS` | ✓ WIRED |
| `progression.py` | `estimates.py`/`rollup.py`/`metadata.py` | `estimate_1rm`/`qualifying_set_rows`/`FRESHNESS_RESOURCES_MUSCLE` | ✓ WIRED |
| `records.py` | `rollup.py`/`estimates.py` | `qualifying_set_rows`/`estimate_1rm` | ✓ WIRED |
| `bodyweight.py` | `metadata.py`/`core/time.py` | `build_measurement_coverage`/`local_day(utc_now(...))` | ✓ WIRED (lines 198, 208, 232-238) |
| `progression.py::get_exercise_trends` | `progression.py::best_set_per_day` | shared D-04 series | ✓ WIRED (line 262) |
| `progression.py` | `core/time.py` | `snap_local_week_range` | ✓ WIRED (lines 354, 361) |
| `comparison.py` | `frequency.py`/`progression.py`/`rollup.py` | `sessions_per_week`/`best_set_per_day`/`fold_window_by_template` | ✓ WIRED |
| `progression.py::get_plateaus` | `progression.py::best_set_per_day`/`metadata.py::earliest_workout_at` | shared series/history seed | ✓ WIRED (lines 687, 711) |
| `recomposition.py` | `bodyweight.py`/`progression.py`/`metadata.py` | `get_body_weight_trend`/`get_exercise_trends`/`FRESHNESS_RESOURCES_ALL` | ✓ WIRED (lines 300, 309) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast-suite tests (estimates, isolation, metadata) | `uv run pytest backend/tests/test_analytics_estimates.py test_analytics_isolation.py test_analytics_metadata.py -q` | 35 passed | ✓ PASS |
| Phase 5 container-backed suite | `uv run pytest backend/tests/test_analytics_{progression,records,bodyweight,comparison,recomposition,rollup}.py -q` | 117 passed | ✓ PASS |
| Full backend regression suite | `uv run pytest backend/tests/ -q` | 493 passed, 0 failed | ✓ PASS |
| No TODO/FIXME/placeholder in any Phase 5 module | `grep -rniE "TODO\|FIXME\|PLACEHOLDER\|not yet implemented"` across all 10 analytics files | 0 matches | ✓ PASS |
| `RecompositionStatus` has exactly 7 members (no 8th value) | source read of `schemas.py:211-225` | 7 enum members confirmed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PROG-01 | 05-01, 05-02, 05-04 (also 05-03) | Exercise progression time series with gated e1RM | ✓ SATISFIED | `get_exercise_progression` + `estimate_1rm` |
| PROG-02 | 05-07 (also 05-03) | improving/stable/declining/unclear trend verdict | ✓ SATISFIED | `classify_trend` + `get_exercise_trends` |
| PROG-03 | 05-09 (also 05-03) | Plateau detection with window+threshold reporting | ✓ SATISFIED | `scan_plateau` + `get_plateaus` |
| PROG-04 | 05-02, 05-05 (also 05-03) | Personal records with dates, warm-ups excluded | ✓ SATISFIED | `get_personal_records` |
| CMP-01 | 05-08 (also 05-03) | Two-period comparison normalized per week | ✓ SATISFIED | `compare_periods` |
| BODY-01 | 05-06 (also 05-03) | Rolling body-weight averages + weekly rate | ✓ SATISFIED | `get_body_weight_trend` |
| BODY-02 | 05-10 (also 05-03) | Recomposition status verdict, decision-support framing | ✓ SATISFIED | `get_recomposition_status` |

All 7 requirement IDs declared for this phase (PROG-01..04, CMP-01, BODY-01, BODY-02) are claimed by at least one plan and satisfied by shipped, tested code. No orphaned requirements found — cross-referenced against `.planning/REQUIREMENTS.md`'s Phase 5 mapping (7 requirements, matches).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `comparison.py` | 325-342 | Per-muscle comparison reports `None` (not `Decimal("0.00")`) when a muscle group has zero sets in one period but is trained in the other (code review WR-01) | ⚠️ Warning | Affects only the opt-in `include_muscle_groups=True` per-muscle breakdown of CMP-01, not the headline per-week comparison (which is directly tested and correct). Does not invalidate SC #4 |
| `progression.py` | 683-703, 771-773 | `PlateauReport.coverage` is computed over the wider history-seed window, not the `[lookback_start, lookback_end]` window named on the same response (code review WR-02) | ⚠️ Warning | A plateau report's `coverage.insufficient_data` can read `False` even when the actual lookback window is thin, if older history exists. Confirmed intentional-but-undocumented by an existing test comment. Does not invalidate SC #2 (window/threshold are still correctly echoed on `PlateauResult` itself) |

Both warnings originate from the `05-REVIEW.md` code review (0 critical, 2 warnings) and are data-quality/interpretation nuances in secondary/opt-in fields, not missing or stubbed functionality. Neither blocks any of the 5 roadmap success criteria. Not escalated as verification gaps — recommend addressing in a follow-up plan or Phase 6 MCP tool description, per the review's own fix suggestions.

### Human Verification Required

None. This phase is pure backend analytics logic (deterministic `Decimal` arithmetic, SQL aggregation, Pydantic contracts) with no UI, no external service integration, and no MCP-layer exposure yet (that is Phase 6's scope). All behavior is exercised by 150 phase-5-specific automated tests (117 container-backed + 35 fast-suite, all against real PostgreSQL via testcontainers, not SQLite), plus the full 493-test backend regression suite passes with zero failures.

### Gaps Summary

No gaps found. All 5 roadmap success criteria are verified against real, substantive, wired, tested code. All 7 requirement IDs are satisfied. The two code-review warnings (WR-01, WR-02) are legitimate data-quality nuances in secondary/opt-in response fields, documented and non-blocking — they do not prevent any of the phase's observable truths from holding.

---

_Verified: 2026-08-31T12:00:00Z_
_Verifier: Claude (gsd-verifier)_

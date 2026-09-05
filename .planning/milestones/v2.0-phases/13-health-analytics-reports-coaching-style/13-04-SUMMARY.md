---
phase: 13-health-analytics-reports-coaching-style
plan: 04
subsystem: analytics
tags: [health, activity, nutrition, trends, HEALTH-12, NUTR-04]
dependency-graph:
  requires: [13-03]
  provides:
    - "app.analytics.health.get_activity_trend"
    - "app.analytics.health.get_nutrition_trend"
    - "app.analytics.health.get_activity_period_summary"
    - "app.analytics.health.get_nutrition_period_summary"
    - "app.analytics.health.period_measured_day_floor"
    - "app.analytics.schemas.ActivityMetric"
    - "app.analytics.schemas.NutritionMetric"
    - "app.analytics.schemas.ActivityTrendResult"
    - "app.analytics.schemas.NutritionTrendResult"
    - "app.analytics.schemas.ActivityPeriodSummary"
    - "app.analytics.schemas.NutritionPeriodSummary"
  affects:
    - "13-05 (container-backed behavioural tests for the four public functions)"
    - "13-06/13-07 (mcp/tools/health.py wrappers for fitness_get_activity_trend / fitness_get_nutrition_trend)"
    - "13-08 (analytics/reports.py composer reuses get_activity_period_summary/get_nutrition_period_summary)"
tech-stack:
  added: []
  patterns:
    - "bodyweight.py's rolling-average/floor/one-fetch-folded-N-ways shape, extended to per-metric-independent coverage"
    - "D-15 floor generalization: ceil(0.33n) clamped to [2, n] reproduces MEASURED_DAY_FLOORS exactly for 7/14/30"
key-files:
  created:
    - backend/app/analytics/health.py
  modified:
    - backend/app/analytics/schemas.py
    - backend/tests/test_analytics_health.py
decisions:
  - "D-06 nutrition floor: reused MEASURED_DAY_FLOORS unchanged (3-of-7, 5-of-14, 10-of-30), per the plan's documented fallback in docs/health-auto-export-setup.md section 11 -- production re-query was blocked in plan 13-02, so no new numbers were invented"
  - "Rephrased the pasted D-06 decision comment away from the doc's literal '3/7, 5/14, 10/30' shorthand: that exact string trips test_analytics_isolation.py's Epley-divisor guard (a bare '/30' substring match), a false positive discovered live during this plan's execution. Decision content unchanged, wording only"
metrics:
  duration: "~55 minutes"
  completed: "2026-09-04"
---

# Phase 13 Plan 04: Activity & Nutrition Trend Analytics Summary

One-liner: `app/analytics/health.py` -- rolling 7/14/30-day activity and nutrition averages
copying `bodyweight.py`'s shape, with coverage computed independently per metric (not one
shared flag across 5 activity / 7 nutrition metrics), plus a `period_measured_day_floor`
generalization of D-15's floors that lets the same fold serve an arbitrary report period.

## What was built

**Task 1 — `backend/app/analytics/schemas.py`:** Two closed `StrEnum`s (`ActivityMetric`,
5 members; `NutritionMetric`, 7 members) declared with the exact Health Auto Export wire names
verbatim, deliberately NOT imported from `app/integrations/health_auto_export/registry.py`
(the app.analytics isolation boundary forbids it) -- drift risk closed by tests, not by import.
Two `MappingProxyType` unit maps. Seven new Pydantic models: `MetricWindowAverage`,
`MetricTrend`, `ActivityTrendResult`, `NutritionTrendResult`, `MetricPeriodSummary`,
`ActivityPeriodSummary`, `NutritionPeriodSummary`.

**Task 2 — `backend/app/analytics/health.py`:** The activity/nutrition arithmetic itself.

- `period_measured_day_floor(days_in_period)` -- a pure function generalizing
  `MEASURED_DAY_FLOORS` (`ceil(0.33n)` clamped to `[2, n]`) so a report period (1-7 or 1-31
  days) gets a defensible computed floor instead of an unsupported-window `ValueError` from
  `is_measurement_insufficient`.
- `_metric_rows` / `_fold_by_metric_day` / `_window_average` / `_window_total` /
  `_earliest_day_per_metric`: one query per concern (exactly two `select(` calls in the whole
  module), folded per metric per window in Python, summing across `source_name` per the
  registry's `aggregation="sum"` contract.
- `_trend_for` / `_period_for`: the two shared generics `get_activity_trend`,
  `get_nutrition_trend`, `get_activity_period_summary`, `get_nutrition_period_summary` all call
  into, so the rolling-window arithmetic and the closed-period arithmetic exist in exactly one
  place each.
- No `source_name != 'Hevy'` predicate: HEALTH-08's exclusion happens at ingest
  (`normalize.py::is_hevy_sourced`), confirmed and documented in the module docstring so a
  future reader does not add a redundant (and `Gymverse`/`Zing`-dropping) filter.

**Tests** — added to `backend/tests/test_analytics_health.py` (file created by plan 13-02):
17 tests total, all PURE (no container): `period_measured_day_floor`'s full behavior contract
(agreement with `MEASURED_DAY_FLOORS` via iteration, the 1-day edge case, intermediate lengths,
the `ValueError` on zero), `_fold_by_metric_day`'s multi-source-sum and metric/day separation,
`_window_average`/`_window_total`'s empty/single-value/no-rounding-drift cases, and four
registry-agreement tests (`ActivityMetric`/`NutritionMetric` value-set equality against
`METRIC_REGISTRY`, and both units maps against `METRIC_REGISTRY[...].canonical_unit`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The D-06 decision comment's literal digit-slash-digit shorthand tripped a
static guard**
- **Found during:** Task 2, first `pytest tests/test_analytics_isolation.py` run after
  writing the module docstring and the `PERIOD_FLOOR_FRACTION` comment.
- **Issue:** The plan instructed pasting `docs/health-auto-export-setup.md`'s D-06 decision
  sentence verbatim, which reads `MEASURED_DAY_FLOORS (3/7, 5/14, 10/30)`. The substring
  `10/30` matches `test_analytics_isolation.py`'s `_DIVIDE_BY_THIRTY` regex
  (`r"/\s*30\b|Decimal\s*\(\s*30\s*\)|_THIRTY"`), which exists to catch the Epley e1RM divisor
  leaking outside `estimates.py` into SQL-adjacent code (PostgreSQL integer division silently
  returns the bare weight). This module's own module docstring phrase "7/14/30-day" tripped the
  same guard for the same reason.
- **Fix:** Rephrased every affected comment/docstring to avoid a bare `/30` substring --
  "3-of-7, 5-of-14, 10-of-30" instead of "3/7, 5/14, 10/30" (matching the doc's OWN alternate
  phrasing at `docs/health-auto-export-setup.md` line 790), and "7-, 14- and 30-day" instead of
  "7/14/30-day" (matching `bodyweight.py`'s own existing docstring phrasing). Decision content
  is byte-identical; only the punctuation changed. Documented inline in the comment itself so a
  future reader understands why the wording differs from the source doc.
- **Files modified:** `backend/app/analytics/health.py`
- **Commit:** d3e668f

### No architectural changes

Nothing in this plan required a Rule 4 (architectural) decision. The module follows
`bodyweight.py`'s shape exactly as D-05/D-06 specified, reuses `metadata.py`'s
`build_measurement_coverage`/`build_freshness` unchanged, and adds no new tables, services, or
write paths.

## Known Stubs

None. Every field this plan's models declare is populated by real arithmetic over
`health_daily_metrics`; there is no hardcoded empty/placeholder value anywhere in the new code.

## Threat Flags

None. This plan adds no new network endpoint, auth path, or file-access pattern -- it is a pure
analytics module reading one existing table, matching every mitigation already listed in the
plan's own `<threat_model>` (T-13-14 through T-13-19): `user_id` keyword-only leading every
WHERE clause, the metric list a closed `StrEnum` bound `.in_()` list, no writes anywhere in the
module (verified by the isolation test suite), a fixed 30-day fetch span for the trend path and
a caller-bounded span for the period path, coverage suppression centralized in `_trend_for`/
`_period_for`, and the two floor constants carrying a comment citing the dated production
measurement attempt that set them.

## Verification

- `cd backend && uv run pytest tests/test_analytics_health.py tests/test_analytics_isolation.py -x -q` -- 25 passed
- `cd backend && uv run pytest -q` (full suite) -- 1001 passed, 11 skipped
- `cd backend && uv run mypy app/analytics/health.py app/analytics/schemas.py` -- Success, no issues found in 2 source files
- `cd backend && uv run ruff check .` -- All checks passed

## Self-Check: PASSED

- FOUND: `backend/app/analytics/health.py`
- FOUND: `backend/app/analytics/schemas.py` (modified, contains `ActivityMetric`/`NutritionMetric`/`MetricWindowAverage`/`MetricTrend`/`ActivityTrendResult`/`NutritionTrendResult`/`MetricPeriodSummary`/`ActivityPeriodSummary`/`NutritionPeriodSummary`)
- FOUND: `backend/tests/test_analytics_health.py` (modified, 17 tests, all passing)
- FOUND commit e2fd4cc: `feat(13-04): add ActivityMetric/NutritionMetric enums and six health-trend result models`
- FOUND commit d3e668f: `feat(13-04): app/analytics/health.py -- activity/nutrition trend arithmetic`

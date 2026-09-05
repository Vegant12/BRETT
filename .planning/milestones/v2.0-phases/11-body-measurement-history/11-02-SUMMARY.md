---
phase: 11-body-measurement-history
plan: 02
subsystem: analytics
tags: [sqlalchemy, postgres, pytest, decimal, body-composition, time-machine]

# Dependency graph
requires:
  - phase: 11-body-measurement-history
    plan: 01
    provides: BodyMeasurementMetric StrEnum, BodyMeasurementTrendResult schema, MEASURED_DAY_FLOORS[90]=2, earliest_metric_measurement_at
provides:
  - get_body_measurement_trend -- the one generic metric-parameterized BODY-05 analytics function
  - fold_by_day / staleness -- pure, container-free business-rule helpers
  - Delta, boundary, floor, staleness and tenant-isolation test coverage for BODY-05
affects: [11-03-body-measurement-mcp-tool]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-point latest-vs-earliest comparison over a fixed window, distinct from bodyweight.py's rolling-average shape -- same package, two calculation shapes by design (D-05)"
    - "insufficient_data and is_stale computed as two independent facts (staleness() never consults coverage, coverage never consults staleness)"
    - "No quantization on a Decimal subtraction of two already-precise Numeric(6,2)/Numeric(5,2) values -- quantization is only correct when averaging"

key-files:
  created:
    - backend/app/analytics/body_measurements.py
  modified:
    - backend/tests/test_analytics_body_measurements.py

key-decisions:
  - "test_two_metrics_on_the_same_rows_are_independent seeds neck_cm's one reading on the SAME row as one of waist_cm's three readings (not a separate row), because the table's natural key is (user_id, source, measured_on) and two rows cannot share a measured_on under the same source -- this is also the realistic shape, since Hevy writes every column on every sync"

patterns-established:
  - "_metric_readings/fold_by_day/staleness mirror bodyweight.py's _weight_rows/_dedupe_by_day plumbing shape but intentionally do NOT copy the rolling-average calculation, the _WEIGHT_QUANTUM quantization, or the manual-wins tie-break -- each omission is explained in the module docstring rather than silently absent"

requirements-completed: [BODY-05]

# Metrics
duration: ~40min
completed: 2026-09-04
---

# Phase 11 Plan 02: Body Measurement Trend Analytics Summary

**One generic `get_body_measurement_trend` function covers all 16 non-weight `body_measurements` columns with an exact `Decimal` latest-vs-earliest delta over an inclusive 90-day window, reporting `insufficient_data` and `is_stale` as two independently-gated facts.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 extended)

## Accomplishments
- `backend/app/analytics/body_measurements.py` created: `get_body_measurement_trend`, the pure helpers `fold_by_day`/`staleness`, the private query helper `_metric_readings`, and the `MetricReading` frozen dataclass — 233 lines, module docstring states the four load-bearing differences from `bodyweight.py`'s rolling-average shape
- Delta, window-boundary, null-column, and cross-metric-independence tests (Task 1) plus the coverage-floor parametrized table, the single-reading honesty case, the four-quadrant `(insufficient_data, is_stale)` load-bearing test, the strictly-greater-than-30-days staleness boundary, and a second-tenant isolation test (Task 2) — `test_analytics_body_measurements.py` grew from 117 to 462 lines
- Full backend suite: 915 passed, 11 skipped. `backend/app/analytics/bodyweight.py` has a confirmed empty diff — BODY-01 fully unregressed. `ruff check`, `ruff format --check`, and `mypy backend/app/analytics/` all clean on every file this plan touched.

## Task Commits

Each task was committed atomically:

1. **Task 1: The generic latest-vs-earliest analytics function** - `b9bfdbc` (feat)
2. **Task 2: Coverage floor and staleness — the four-quadrant proof** - `8fffb49` (test)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `backend/app/analytics/body_measurements.py` (new) - `get_body_measurement_trend`, `fold_by_day`, `staleness`, `_metric_readings`, `MetricReading`, `WINDOW_DAYS=90`, `STALE_AFTER_DAYS=30`
- `backend/tests/test_analytics_body_measurements.py` - Added delta/boundary/null/independence tests (Task 1) and floor/stale/tenant-isolation tests (Task 2), plus the `_seed` helper and `_AGREE_INSTANT`/`_ANCHOR` frozen-clock constants

## Decisions Made
- `test_two_metrics_on_the_same_rows_are_independent` seeds `neck_cm`'s single reading onto the same row as one of `waist_cm`'s three readings rather than a separate row, because `body_measurements`' natural key `(user_id, source, measured_on)` forbids two rows sharing a `measured_on` under the same source — discovered live via a `UniqueViolationError` when the plan's literal seeding shape (two independent `_seed` calls both touching offset 0) was tried first. This is also the realistic shape: Hevy writes every column on every sync, so a real row genuinely carries both metrics at once.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's literal test-seeding shape violated the table's unique constraint**
- **Found during:** Task 1 verification (`test_two_metrics_on_the_same_rows_are_independent`)
- **Issue:** The plan's action text seeds `waist_cm` at offsets `(80, 40, 0)` and `neck_cm` at offset `(0,)` as two separate `_seed(...)` calls, each inserting its own row. Both calls write to `measured_on = _ANCHOR - timedelta(days=0)` under `source='hevy'`, colliding on the table's `uq_body_measurements_user_source_measured_on` constraint and raising `IntegrityError` at test time rather than passing.
- **Fix:** Rewrote the test to seed `neck_cm`'s one reading onto the SAME row as `waist_cm`'s offset-0 reading, using three explicit `golden_workout.body_measurement(...)` calls instead of the generic `_seed` helper. Assertions and intent (waist's coverage sufficient, neck's insufficient) are unchanged.
- **Files modified:** `backend/tests/test_analytics_body_measurements.py`
- **Verification:** `uv run pytest backend/tests/test_analytics_body_measurements.py -k independent -q` → 1 passed
- **Committed in:** `b9bfdbc` (part of Task 1 commit)

**2. [Rule 1 - Bug] A docstring line exceeded Ruff's 100-character limit**
- **Found during:** Task 1 verification (`ruff check`)
- **Issue:** `test_a_null_column_is_not_a_reading`'s one-line docstring was 103 characters (E501).
- **Fix:** Wrapped the docstring onto two lines with no meaning change.
- **Files modified:** `backend/tests/test_analytics_body_measurements.py`
- **Verification:** `uv run ruff check backend/tests/test_analytics_body_measurements.py` → All checks passed
- **Committed in:** `b9bfdbc` (part of Task 1 commit)

**3. [Rule 1 - Bug] `ruff format` reflowed one line in the new module**
- **Found during:** Task 1 verification (`ruff format --check`)
- **Issue:** The final `return [...]` comprehension in `_metric_readings` was written wrapped across three lines; Ruff's formatter collapses it onto one line under the project's line-length settings.
- **Fix:** Ran `uv run ruff format backend/app/analytics/body_measurements.py`; no logic changed.
- **Files modified:** `backend/app/analytics/body_measurements.py`
- **Verification:** `uv run ruff format --check backend/app/analytics/body_measurements.py` → already formatted
- **Committed in:** `b9bfdbc` (part of Task 1 commit)

---

**Total deviations:** 3 auto-fixed (2 test bugs, 1 formatting)
**Impact on plan:** No semantic changes to the analytics function itself. Test-seeding shape and formatting only.

## Issues Encountered

**Acceptance-criteria grep mismatches (not fixed, documented only):** Two of Task 1's literal acceptance-criteria grep checks disagree with the plan's own reference implementation text, which was followed verbatim:
- `grep -c "column.is_not(None)" backend/app/analytics/body_measurements.py` returns **2**, not the criterion's expected 1 — because the plan's own `_metric_readings` docstring text (`` ``column.is_not(None)`` is in the WHERE clause rather than filtered in Python...`` ``) contains the exact substring `column.is_not(None)` a second time, in prose. The plan's own literal action text produces this same count.
- `grep -c "quantize" backend/app/analytics/body_measurements.py` returns **1**, not the criterion's expected 0 — because the plan's own inline comment (`` `# No `.quantize(...)`. Both operands are already 2-decimal...` ``) contains the substring "quantize" in prose explaining its absence.

Both are false-positive grep matches on documentation prose, not actual code violations (no code-level `.quantize()` call exists, and `column.is_not(None)` appears exactly once as executable code). Neither grep is part of the plan's automated `<verify>` block, so neither blocked execution. Not fixed, since fixing them would mean stripping the plan's own mandated explanatory prose.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03 can import `get_body_measurement_trend` directly from `app.analytics.body_measurements` with zero further analytics exploration needed — the function signature, `BodyMeasurementTrendResult` shape, `WINDOW_DAYS`/`STALE_AFTER_DAYS` constants are all stable.
- `backend/app/analytics/bodyweight.py` has a confirmed empty diff — BODY-01 fully unregressed.
- Full backend suite (`uv run pytest backend/tests -q`) passes: 915 passed, 11 skipped. Lint (`ruff check`) and `mypy backend/app/analytics/` are clean. `ruff format --check backend/` shows 18 pre-existing unrelated files needing reformatting (documented in Plan 01's summary as out of scope); both files this plan touched are already formatted.
- No blockers for Plan 03.

---
*Phase: 11-body-measurement-history*
*Completed: 2026-09-04*

## Self-Check: PASSED

`backend/app/analytics/body_measurements.py` and `backend/tests/test_analytics_body_measurements.py`
both exist on disk, and both task commits (`b9bfdbc`, `8fffb49`) are present in `git log --oneline --all`.

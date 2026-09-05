---
phase: 11-body-measurement-history
plan: 01
subsystem: analytics
tags: [pydantic, strenum, sqlalchemy, postgres, pytest, body-composition]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: MEASURED_DAY_FLOORS / is_measurement_insufficient / build_measurement_coverage coverage-floor pattern in metadata.py
  - phase: 05-progression-records-recomposition-analytics
    provides: BodyWeightTrendResult and earliest_measurement_at as the direct structural sibling this plan extends
provides:
  - BodyMeasurementMetric StrEnum (16 non-weight body_measurements columns, enum values ARE column names)
  - BodyMeasurementTrendResult Pydantic result model (latest-vs-earliest 90-day comparison shape)
  - MEASURED_DAY_FLOORS[90] = 2, a two-point-comparison coverage floor sitting beside BODY-01's untouched 7/14/30 floors
  - earliest_metric_measurement_at, a column-scoped sibling of earliest_measurement_at
  - GoldenBuilder.body_measurement() now seeds waist_cm/neck_cm/fat_percent
  - test_analytics_body_measurements.py with enum/ORM drift guards and the fixture proof
affects: [11-02-body-measurement-trend-analytics, 11-03-body-measurement-mcp-tool]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "StrEnum member values ARE the ORM column names (getattr(Model, enum.value) resolves the column with zero second mapping)"
    - "Coverage floor extension: add one MappingProxyType entry, never fork is_measurement_insufficient/build_measurement_coverage"
    - "Column-scoped earliest-date helper as a sibling function, never a modification, to the all-rows earliest-date helper"

key-files:
  created:
    - backend/tests/test_analytics_body_measurements.py
  modified:
    - backend/app/analytics/schemas.py
    - backend/app/analytics/metadata.py
    - backend/tests/test_analytics_metadata.py
    - backend/tests/conftest.py

key-decisions:
  - "Reworded BodyMeasurementTrendResult's docstring from '7/14/30-day' to '7-day, 14-day and 30-day' after it tripped test_analytics_isolation.py's Epley-divisor regex (a '/30' substring false positive), preserving meaning while keeping the drift guard's scope narrow and the fix inside the docstring only"

patterns-established:
  - "BodyMeasurementMetric / BodyMeasurementTrendResult sit immediately after BodyWeightTrendResult in schemas.py, grouping BODY-01/BODY-05 together"
  - "earliest_metric_measurement_at takes column: InstrumentedAttribute[Decimal | None] as a keyword-only parameter, letting one function serve all 16 metrics with zero per-metric duplication"

requirements-completed: [BODY-05]

# Metrics
duration: ~25min
completed: 2026-09-04
---

# Phase 11 Plan 01: Body Measurement History Foundations Summary

**Closed 16-member `BodyMeasurementMetric` StrEnum, `BodyMeasurementTrendResult` result shape, a 90-day/2-reading coverage floor, and a column-scoped earliest-ever helper — the four contracts Plan 02's analytics function and Plan 03's MCP tool both import unchanged.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-04T00:52:00Z (approx, first Read)
- **Completed:** 2026-09-04T01:04:00Z (approx, final commit b753918)
- **Tasks:** 3 completed
- **Files modified:** 4 (1 created, 3 extended)

## Accomplishments
- `BodyMeasurementMetric` (16 members) and `BodyMeasurementTrendResult` added to `analytics/schemas.py`, immediately after `BodyWeightTrendResult`, with three fast-suite drift-guard tests proving the enum is exactly the ORM's non-weight `Numeric` columns in both directions
- `MEASURED_DAY_FLOORS` extended with a `90: 2` entry (a two-point-comparison floor, not a rolling-average one) with its rationale recorded in-file; `earliest_metric_measurement_at` added as a column-scoped sibling of `earliest_measurement_at`, which stays byte-identical
- `GoldenBuilder.body_measurement()` now accepts `waist_cm`, `neck_cm`, `fat_percent`, proven at the database level (not just argument-level) with a test that also proves pre-existing weight-only call sites still write NULLs into the new columns

## Task Commits

Each task was committed atomically:

1. **Task 1: BodyMeasurementMetric enum, BodyMeasurementTrendResult, and the enum/ORM drift guards** - `b2dab7f` (feat)
2. **Task 2: 90-day coverage floor and the column-scoped earliest-ever helper** - `fa578c9` (feat)
3. **Task 3: GoldenBuilder seeds non-weight measurement columns** - `b753918` (test)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `backend/app/analytics/schemas.py` - Added `BodyMeasurementMetric` (StrEnum, 16 members) and `BodyMeasurementTrendResult` (Pydantic result model) after `BodyWeightTrendResult`
- `backend/app/analytics/metadata.py` - Added `90: 2` to `MEASURED_DAY_FLOORS`, added `earliest_metric_measurement_at` (new import: `InstrumentedAttribute`, `Decimal`)
- `backend/tests/test_analytics_body_measurements.py` (new) - Enum/ORM drift-guard tests (fast suite) plus the fixture-seeding integration test
- `backend/tests/test_analytics_metadata.py` - Updated the exact-dict floor assertion to include `90: 2`, added two boundary assertions, added `test_earliest_metric_measurement_at_is_column_scoped_and_tenant_scoped`
- `backend/tests/conftest.py` - `GoldenBuilder.body_measurement()` gained `waist_cm`/`neck_cm`/`fat_percent` optional kwargs, defaulting to `None`

## Decisions Made
- Reworded the new `BodyMeasurementTrendResult` docstring's "7/14/30-day" phrasing to "7-day, 14-day and 30-day" after discovering it tripped `test_analytics_isolation.py::test_epley_is_computed_only_in_estimates`'s `_DIVIDE_BY_THIRTY` regex (`/\s*30\b`), which scans for the Epley 1RM integer-division bug pattern outside `estimates.py`. This was a documentation-only false positive (no actual `/30` arithmetic exists), fixed by rewording without losing meaning — no code semantics changed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring text tripped an unrelated regex-based drift guard**
- **Found during:** Task 1 verification (running `test_analytics_isolation.py`)
- **Issue:** `BodyMeasurementTrendResult`'s docstring used the phrase "7/14/30-day rolling average", and the substring "/30" matched `test_analytics_isolation.py`'s `_DIVIDE_BY_THIRTY` regex (`r"/\s*30\b|Decimal\s*\(\s*30\s*\)|_THIRTY"`), which exists to catch PostgreSQL's `weight * (1 + reps/30)` integer-division bug appearing outside `estimates.py`. This was a textual false positive, not a real occurrence of the bug.
- **Fix:** Reworded the docstring to "a rolling average across the 7-day, 14-day and 30-day windows with 3, 5 and 10 measured-day floors", preserving the exact same meaning while removing the `/30` substring.
- **Files modified:** `backend/app/analytics/schemas.py`
- **Verification:** `uv run pytest backend/tests/test_analytics_isolation.py backend/tests/test_mcp_schemas.py -q` → 48 passed
- **Committed in:** `b2dab7f` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/false-positive)
**Impact on plan:** Documentation wording only; no code semantics changed. No scope creep.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 02 can now import `BodyMeasurementMetric`, `BodyMeasurementTrendResult`, `MEASURED_DAY_FLOORS[90]`, and `earliest_metric_measurement_at` directly, with zero further schema/metadata exploration needed.
- `GoldenBuilder.body_measurement()` is ready for every downstream BODY-05 integration test to seed circumference/composition values alongside weight.
- `backend/app/analytics/bodyweight.py` has a confirmed empty diff — BODY-01 is fully unregressed.
- Full backend suite (`uv run pytest backend/tests -q`) passes: 896 passed, 11 skipped. Lint (`ruff check`/`ruff format --check`) and `mypy backend/app/analytics/` are clean on every file this plan touched. (18 pre-existing files elsewhere in the repo would be reformatted by `ruff format`, unrelated to this plan's scope — not touched, per scope-boundary rules.)
- No blockers for Plan 02 or Plan 03.

---
*Phase: 11-body-measurement-history*
*Completed: 2026-09-04*

## Self-Check: PASSED

All claimed files exist (`backend/app/analytics/schemas.py`, `backend/app/analytics/metadata.py`,
`backend/tests/test_analytics_body_measurements.py`, `backend/tests/test_analytics_metadata.py`,
`backend/tests/conftest.py`, this SUMMARY.md), and all three task commits
(`b2dab7f`, `fa578c9`, `b753918`) are present in `git log --oneline --all`.

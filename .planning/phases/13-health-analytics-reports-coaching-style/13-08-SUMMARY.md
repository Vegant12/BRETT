---
phase: 13-health-analytics-reports-coaching-style
plan: 08
subsystem: analytics
tags: [pydantic, markdown, decimal, postgres, testcontainers]

# Dependency graph
requires:
  - phase: 13-health-analytics-reports-coaching-style
    provides: "plan 13-07's ReportPeriod/ReportResult schemas and compose_report composer"
provides:
  - "build_narrative(report) -- D-14's deterministic markdown narrative for the monthly report"
  - "backend/tests/test_analytics_reports.py -- the RPT-01/RPT-02 composer and narrative test suite (31 tests)"
affects: [13-09-mcp-report-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure markdown-narrative rendering as a list[str] + '\\n'.join(...), mirroring backfill.py::format_summary's shape -- no template engine"
    - "Hand-built Pydantic fixture builders with **overrides dict-merge, so each edge-case test reads as a diff from one baseline"
    - "Numeric-provenance testing: regex-extract digit tokens from generated prose and assert each is a substring of model_dump_json()"

key-files:
  created:
    - backend/tests/test_analytics_reports.py
  modified:
    - backend/app/analytics/reports.py

key-decisions:
  - "build_narrative renders every null figure as an explicit word (\"not recorded\", \"not enough weigh-ins\", \"never synced\") and never as a bare 0, matching schemas.py's tonnage_kg-is-None-vs-zero rule"
  - "The numeric-provenance test drops the sign from extracted number tokens (unsigned regex) to avoid ISO-date hyphens being misread as unary minus"
  - "Split the TDD task 1 (build_narrative + pure tests) and task 2 (container-backed compose_report tests) into two separate commits against the same file, trimming imports for the task-1-only commit so each commit is independently lint/type/test clean"

requirements-completed: [RPT-01, RPT-02]

# Metrics
duration: 55min
completed: 2026-09-04
---

# Phase 13 Plan 08: Report Narrative & Composer Test Suite Summary

**D-14's deterministic markdown narrative (`build_narrative`) for the monthly report, plus a 31-test suite proving `compose_report` end to end against both real container data and hand-built fixtures.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Added `build_narrative(report: ReportResult) -> str` to `backend/app/analytics/reports.py`: a pure, synchronous function rendering D-14's seven-section markdown narrative (Training, Strength, Body, Nutrition, Activity, Program and recomposition, Data quality) with no template engine, no I/O, and no recommendation language.
- Created `backend/tests/test_analytics_reports.py`, the Wave 0 artifact 13-VALIDATION.md names for RPT-01/RPT-02: 19 pure narrative tests (byte-identical output, banned-token scan, numeric-provenance check against `model_dump_json()`) plus 12 container-backed `compose_report` tests covering both report periods, the recomposition verdict's own anchor, PR-highlight window scoping, section-by-section degradation, and the five-resource freshness envelope.
- Proved the T-13-39 anti-drift property: `resolve_report_window`'s Monday computation agrees exactly with `app.mcp.tools._common.week_window`.

## Task Commits

Each task was committed atomically:

1. **Task 1: build_narrative — a pure, deterministic markdown template** - `c50b64f` (feat)
2. **Task 2: Container-backed tests for compose_report, both periods** - `10bf516` (test)

_Note: Task 1 was `tdd="true"`; implementation and its pure test coverage were developed together and landed in one `feat` commit containing both `build_narrative` and its 19 narrative tests, since the plan's own acceptance criteria for Task 1 require both to exist together. Task 2's container tests were then appended to the same test file in a separate `test` commit, with the module's imports/docstring restored to describe both tasks._

## Files Created/Modified
- `backend/app/analytics/reports.py` - Added `build_narrative` and its private `_period_summary_lines` helper, after `compose_report`
- `backend/tests/test_analytics_reports.py` - New file: pure `ReportResult` fixture builders + 19 narrative tests (Task 1), then 12 container-backed `compose_report` tests (Task 2)

## Decisions Made
- Rendering rules follow the plan's `<action>` block literally: `Decimal` via `str()`, dates via `.isoformat()`, `StrEnum` via `.value`, nulls as explicit words never a bare `0`.
- The plateau section's "no recorded weight" case renders the fixed phrase `weight not recorded`, replacing the whole `last lifted {X} kg` fragment rather than substituting just the number, per the plan's literal-phrase instruction.
- `build_narrative`'s docstring twice rephrases sentences that would otherwise trip this project's own static acceptance-grep patterns (the "no template engine" paragraph, which would have matched `jinja|Template`, and the Decimal-rendering paragraph, which originally wrote out `float()` literally and tripped `test_analytics_isolation.py::test_analytics_declares_no_float`) — content unchanged, wording adjusted, each documented inline with a comment explaining why.
- Task 2's `test_the_report_carries_the_recomposition_verdict_with_its_own_anchor` seeds a real four-week improving-weight training block plus a stable weigh-in trend, so the D-01 anchor-labelling property is proven against an actual (non-`insufficient_data`) verdict rather than the vacuously-true empty-database case.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `build_narrative`'s docstring tripped the project's own static float-ban guard**
- **Found during:** Task 1, full-suite verification run
- **Issue:** The docstring originally read "never `float()`, never `round()`" as literal code-formatted text; `test_analytics_isolation.py::test_analytics_declares_no_float`'s regex (`float\s*\(`) matched this prose as if it were a real `float(...)` call, failing the entire suite's static isolation guard.
- **Fix:** Reworded to "never binary-floating-point-converted, never rounded" with an inline comment explaining the rephrase is to avoid the guard, decision content unchanged. Verified `grep -n "float(" backend/app/analytics/reports.py` returns no match and `test_analytics_isolation.py` passes.
- **Files modified:** `backend/app/analytics/reports.py`
- **Verification:** Full suite re-run: `test_analytics_isolation.py::test_analytics_declares_no_float` passes; 1061 passed, 0 failed, 11 skipped.
- **Committed in:** `c50b64f` (part of Task 1 commit — caught before the commit was made)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Self-contained fix to documentation prose only; no behavior change to `build_narrative` itself. No scope creep.

## Issues Encountered
- The plan's own acceptance-criteria greps (`jinja|string.Template|render(`, `dt.date(20`) are literal substring matches, so several explanatory docstring/comment sentences that *mentioned* the forbidden patterns (to explain why they are forbidden) had to be reworded to avoid self-tripping the grep, mirroring the pattern `test_analytics_health.py`'s own module docstring already established for the literal-date grep. Resolved by rephrasing with an inline note on each occurrence; no functional impact.
- The full backend test suite (`uv run pytest -q`, 1061 tests including the real-Postgres-container integration suite) took approximately 17 minutes to complete end to end; this is a pre-existing property of the codebase's test suite size, not something introduced by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `build_narrative` and `compose_report` are both proven and available for plan 13-09 (`fitness_get_weekly_report`/`fitness_get_monthly_report` MCP tools) to consume: the monthly tool can call `build_narrative(report)` to populate its extra `narrative` field, and the weekly tool intentionally does not.
- No blockers. The full backend test suite (1061 tests, including this plan's 31) passes cleanly, and `test_analytics_isolation.py`'s five static boundary guards (no `app.mcp`/`app.integrations` import, no raw SQL text, no muscle-table joins, no writes, no float) all pass against the modified `reports.py`.

---
*Phase: 13-health-analytics-reports-coaching-style*
*Completed: 2026-09-04*

## Self-Check: PASSED

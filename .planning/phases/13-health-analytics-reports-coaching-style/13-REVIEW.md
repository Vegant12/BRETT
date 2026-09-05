---
phase: 13-health-analytics-reports-coaching-style
reviewed: 2026-09-05T04:23:45Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - backend/app/analytics/health.py
  - backend/app/analytics/metadata.py
  - backend/app/analytics/records.py
  - backend/app/analytics/reports.py
  - backend/app/analytics/schemas.py
  - backend/app/core/time.py
  - backend/app/mcp/server.py
  - backend/app/mcp/tools/_common.py
  - backend/app/mcp/tools/health.py
  - backend/app/mcp/tools/reports.py
  - backend/app/mcp/tools/schemas.py
  - backend/tests/conftest.py
  - backend/tests/test_analytics_health.py
  - backend/tests/test_analytics_metadata.py
  - backend/tests/test_analytics_records.py
  - backend/tests/test_analytics_reports.py
  - backend/tests/test_mcp_auth.py
  - backend/tests/test_mcp_isolation.py
  - backend/tests/test_mcp_mount.py
  - backend/tests/test_mcp_tool_budget.py
  - backend/tests/test_mcp_tool_schemas.py
  - backend/tests/test_mcp_tools.py
  - backend/tests/test_time.py
  - docs/coaching-instructions.md
  - docs/health-auto-export-setup.md
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-09-05T04:23:45Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Phase 13 adds the Apple-Health-backed activity/nutrition trend analytics
(`app/analytics/health.py`), the composed weekly/monthly report
(`app/analytics/reports.py` + `app/mcp/tools/reports.py`), their MCP-facing
schemas, and the two new MCP tools (`fitness_get_activity_trend`,
`fitness_get_nutrition_trend`, `fitness_get_weekly_report`,
`fitness_get_monthly_report`). The code is unusually well-documented (every
non-obvious decision carries an inline rationale tied back to a lettered
design decision), consistently uses `Decimal` instead of `float`, threads
`user_id` correctly through every query, and is backed by a large, thoughtful
test suite (pure-function tests for the floor/fold helpers, container-backed
behavioural tests for the trend/period functions, and wire-level MCP tests
for the two new report tools).

No security vulnerabilities, hardcoded secrets, SQL injection risk, or
crashes were found in the reviewed files. The one substantive issue found is
a genuine cross-module logic bug: the monthly report's markdown `narrative`
does not respect the same PR/plateau highlight caps that the structured
JSON fields in the same response enforce, which silently defeats the
project's own MCP-03 "no unbounded result sets" rule for that one field.
Two minor code-quality observations round out the review.

## Warnings

### WR-01: Monthly report narrative bypasses the PR/plateau highlight caps that the same response's structured fields enforce

**File:** `backend/app/mcp/tools/reports.py:203-226` (call site), `backend/app/analytics/reports.py:238-343` (`build_narrative`)

**Issue:**

`fitness_get_monthly_report` builds its structured fields via
`_report_body_fields(report)`, which explicitly caps `pr_highlights` at
`MAX_REPORT_PR_HIGHLIGHTS` (5) and `plateau_highlights` (filtered to
`plateaued=True`) at `MAX_REPORT_PLATEAU_HIGHLIGHTS` (5), each carrying a
`*_truncated`/`*_total` pair specifically so "an unlabelled cap" never
"reintroduces" the D-02 ambiguous-list failure mode (see
`backend/app/mcp/tools/_common.py:101-108`):

```python
pr_highlights, pr_highlights_truncated, pr_highlights_total = truncate(
    report.pr_highlights.records, MAX_REPORT_PR_HIGHLIGHTS
)
...
plateaued = [exercise for exercise in report.plateau_highlights.exercises if exercise.plateaued]
(
    plateau_highlights,
    plateau_highlights_truncated,
    plateau_highlights_total,
) = truncate(plateaued, MAX_REPORT_PLATEAU_HIGHLIGHTS)
```

But the very same call site then builds the narrative from the **untruncated**
`report` object:

```python
return MonthlyReportResponse(**_report_body_fields(report), narrative=build_narrative(report))
```

`build_narrative` (in `app/analytics/reports.py`) iterates the full,
uncapped lists directly:

```python
lines.append("- New records this period:")
for pr in report.pr_highlights.records:            # ALL records, not the capped 5
    ...
plateaued = [ex for ex in report.plateau_highlights.exercises if ex.plateaued]  # ALL, not capped
```

The result: a monthly report response can carry `pr_highlights_total: 8,
pr_highlights_truncated: true` with only 5 entries in the JSON
`pr_highlights` array, while the same response's `narrative` markdown lists
all 8 records in prose. This is inconsistent within one response, and it
specifically defeats the design intent recorded in `_common.py` ("a
coaching answer that cites more than about five individual lifts has
stopped summarizing") for the one field (`narrative`) that
`docs/coaching-instructions.md` tells Claude to quote directly ("Quote from
it; never treat it as the answer itself."). Because `pr_highlights.records`
and the plateaued-exercise list are bounded only by how many exercises a
user actually trains/PRs in a month (not by a fixed cap), the narrative's
size is not actually bounded the way `test_mcp_tool_budget.py`'s
49,152-byte `fitness_get_monthly_report` budget assumes — the current
passing measurement (31,630 bytes, 2026-09-05) reflects `worst_case_history`'s
fixed 30-template fixture, not an account with more distinct exercises PR'd
or newly plateaued in a single month.

No existing test catches this: `test_analytics_reports.py`'s narrative
tests hand-build small (2-item) `ReportResult` fixtures, so the highlight
lists never exceed the cap in that suite, and
`test_mcp_tools.py::test_report_highlights_carry_their_truncation_counts`
only asserts the structured `plateau_highlights`/`plateau_highlights_total`
fields, never the narrative text.

**Fix:** Build the narrative from the same capped/filtered lists the
structured fields use, e.g. pass the already-truncated highlight lists into
`build_narrative` (or construct a `report.model_copy(update={...})` with the
capped lists before calling it):

```python
# app/mcp/tools/reports.py
body_fields = _report_body_fields(report)
capped_report = report.model_copy(
    update={
        "pr_highlights": report.pr_highlights.model_copy(
            update={"records": body_fields["pr_highlights"]}
        ),
    }
)
return MonthlyReportResponse(**body_fields, narrative=build_narrative(capped_report))
```

or, simpler, change `build_narrative`'s signature to accept the two
pre-truncated lists as explicit parameters instead of re-deriving them from
`report`. Either way, add a regression test that seeds more than
`MAX_REPORT_PR_HIGHLIGHTS`/`MAX_REPORT_PLATEAU_HIGHLIGHTS` highlight-worthy
items and asserts the narrative lists no more than the capped count (the
existing `test_report_highlights_carry_their_truncation_counts` fixture in
`test_mcp_tools.py` already seeds `MAX_REPORT_PLATEAU_HIGHLIGHTS + 1`
plateaued exercises — it only needs a narrative-side assertion added).

## Info

### IN-01: `build_narrative` is a single ~215-line function

**File:** `backend/app/analytics/reports.py:238-452`

**Issue:** Every other section of the narrative (Training, Strength, Body,
Program/recomposition, Data quality) is inlined directly in `build_narrative`,
while only the Activity/Nutrition sections were factored out into
`_period_summary_lines` (lines 213-235). The function is well-organized and
heavily commented, but at 215 lines it is the largest function in the
reviewed set and the one most likely to grow further as new report sections
are added.

**Fix:** Consider extracting one private helper per section (e.g.
`_training_lines`, `_strength_lines`, `_body_lines`,
`_program_and_recomposition_lines`, `_data_quality_lines`), mirroring the
`_period_summary_lines` pattern already established. Purely a maintainability
suggestion; no behavioral change implied.

### IN-02: `compose_report` resolves the report window's timezone twice per call

**File:** `backend/app/analytics/reports.py:80-101, 129, 177-179`

**Issue:** `resolve_report_window` calls `resolve_window` once (via a
throwaway one-day probe window) purely to read `tz`. `compose_report` then
calls `resolve_window` a second time near the end, over the real report
window, to build `coverage`/`freshness`. Both calls read `users.timezone`
from the same session/transaction, so the two reads cannot disagree, but
it is two round trips to resolve information that is available after the
first call (the report's `start_day`/`end_day` are already known by then,
so a single `resolve_window(start_day, end_day)` call could serve both the
window resolution and the later coverage/freshness computation). This is
purely a note for future readers who might otherwise reach for `resolve_window`
a third time when extending this function; it is not flagged as a
performance issue per this review's scope, only as a small code-clarity
observation.

**Fix:** None required. If `compose_report` is revisited for other reasons,
consider computing `window` once and deriving `tz` from it instead of the
separate probe call in `resolve_report_window`.

---

_Reviewed: 2026-09-05T04:23:45Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 13-health-analytics-reports-coaching-style
plan: 03
subsystem: analytics
tags: [python, sqlalchemy, pydantic, personal-records, timezone, freshness]

# Dependency graph
requires: []
provides:
  - "app/core/time.py::local_month_start -- calendar-month boundary helper for RPT-02"
  - "app/analytics/metadata.py::FRESHNESS_RESOURCES_REPORT -- the 5-resource freshness bundle a report reads"
  - "app/analytics/records.py::get_recent_records -- cross-exercise PR scan in one query"
  - "app/analytics/schemas.py::RecentRecord, RecentRecordsResult -- the return type of get_recent_records"
affects: [13-07, 13-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cross-exercise aggregate scan: qualifying_set_rows(template_external_ids=None) plus a
      Python fold over per-template accumulators, instead of looping a per-exercise function --
      the same shape get_plateaus already uses to avoid query fan-out on a MIN_INSTANCES=0
      service."
    - "Pre-window history seeding: earliest_workout_at + a clamped [history_start, end_day]
      window, split in Python on the window boundary -- mirrors get_plateaus's idiom exactly, so
      a record must beat ALL history strictly before the window, not merely lead its own window."

key-files:
  created: []
  modified:
    - backend/app/core/time.py
    - backend/app/analytics/metadata.py
    - backend/app/analytics/schemas.py
    - backend/app/analytics/records.py
    - backend/tests/test_time.py
    - backend/tests/test_analytics_metadata.py
    - backend/tests/test_analytics_records.py

key-decisions:
  - "Built the purpose-built cross-exercise PR scan (Option 1 from 13-RESEARCH.md), not an
    e1RM/weight approximation off get_plateaus's historical_best_kg -- preserves all four
    PersonalRecordType members including MAX_REPS and SESSION_VOLUME, which the approximation
    would have silently dropped."

requirements-completed: []  # RPT-01/RPT-02 listed in this plan's frontmatter, but NOT marked
  # complete in REQUIREMENTS.md here: both requirements describe the MCP report TOOLS
  # themselves (13-07/13-08/13-09), which do not exist yet. This plan only builds prerequisites
  # (`local_month_start`, `FRESHNESS_RESOURCES_REPORT`, `get_recent_records`). Marking the
  # requirement checkboxes complete now would be factually wrong.

# Metrics
duration: 30min
completed: 2026-09-04
---

# Phase 13 Plan 03: Report Building Blocks Summary

**Calendar-month timezone helper, a 5-resource freshness bundle, and a cross-exercise personal-record scan (`get_recent_records`) that beats pre-window history in one query, not a per-exercise loop.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-09-04T07:15:00Z (approx.)
- **Completed:** 2026-09-04T07:52:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- `local_month_start` gives `analytics/reports.py` a timezone-correct calendar-month boundary,
  mirroring `local_week_start` exactly (including the UTC+7 boundary case where a naive
  server-local implementation would report the wrong month for seven hours a day).
- `FRESHNESS_RESOURCES_REPORT` names all five `(provider, resource)` pairs a report reads,
  asserted equal to the union of the three existing bundles it composes from so the two
  spellings cannot drift apart.
- `get_recent_records` answers "which PRs were set in this window, across every exercise" from
  ONE `qualifying_set_rows` call plus a Python fold, seeded from pre-window history the same way
  `get_plateaus` seeds its running best -- so a value that only led its own window (and never
  actually beat the lifter's history) is correctly NOT reported as a new record.

## Task Commits

1. **Task 1: local_month_start and FRESHNESS_RESOURCES_REPORT** - `439d657` (feat)
2. **Task 2: RecentRecord / RecentRecordsResult schemas** - `9bf5575` (feat)
3. **Task 3: get_recent_records — the cross-exercise scan, in one query** - `e9438e1` (feat)

**Plan metadata:** `9e0c484` (docs: log a pre-existing unrelated test failure)

_Note: this plan had `tdd="true"` on Tasks 1 and 3, but both were implemented and verified
against the stated `<behavior>` cases directly rather than as separate RED/GREEN/REFACTOR
commits — the plan's own `<action>` sections specified the full implementation and tests
together, and no commit history shows a separate failing-test-first commit for either task._

## Files Created/Modified

- `backend/app/core/time.py` - added `local_month_start`, mirroring `local_week_start`
- `backend/app/analytics/metadata.py` - added `FRESHNESS_RESOURCES_REPORT` (5 pairs, named not concatenated)
- `backend/app/analytics/schemas.py` - added `RecentRecord`, `RecentRecordsResult`
- `backend/app/analytics/records.py` - added `_TemplateAccumulator`, `_best_session_volume`, `get_recent_records`
- `backend/tests/test_time.py` - `test_local_month_start_uses_the_users_month`
- `backend/tests/test_analytics_metadata.py` - `test_the_report_bundle_is_the_union_of_the_three_it_replaces`
- `backend/tests/test_analytics_records.py` - 10 new tests for `get_recent_records`

## Decisions Made

- Followed the plan's Option 1 decision verbatim: a purpose-built cross-exercise scan homed in
  `records.py`, reusing `_key`/`_better`/`_SessionVolume`/`estimate_1rm` rather than re-deriving
  any comparison rule. No new decisions were required beyond what the plan already resolved.

## Deviations from Plan

None - plan executed exactly as written, with one addition beyond its explicit scope (see
"Issues Encountered" below, which documents an unrelated pre-existing test failure discovered
during full-suite verification but not fixed, since it is out of scope for this plan's files).

## Issues Encountered

`uv run pytest -q` (full suite) surfaced one pre-existing, unrelated failure:
`test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`. Reproduces
identically in isolation and with this plan's diff stashed out, so it is confirmed unrelated to
`local_month_start`, `FRESHNESS_RESOURCES_REPORT`, or `get_recent_records`. Root cause appears to
be a real-wall-clock date collision between a committed reference-history fixture and
`utc_now().date()` on the literal date 2026-09-04. Logged to
`.planning/phases/13-health-analytics-reports-coaching-style/deferred-items.md` per the
scope-boundary rule rather than fixed here.

## Requirements Note

This plan's frontmatter lists `requirements: [RPT-01, RPT-02]`, and the same two IDs also appear
in plans 13-07, 13-08 and 13-09's frontmatter. RPT-01/RPT-02 describe the MCP report TOOLS
themselves ("a new MCP tool composes a weekly/monthly report"), which do not exist until those
later plans run. Deliberately did NOT run `requirements mark-complete` for RPT-01/RPT-02 here --
doing so would have flipped `REQUIREMENTS.md`'s checkboxes to `[x] Complete` before the tools
they describe exist. (An initial attempt to do so was caught and reverted before committing;
`git diff .planning/REQUIREMENTS.md` was empty at commit time.) The plan that actually ships
`fitness_get_weekly_report`/`fitness_get_monthly_report` should mark these complete.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`local_month_start`, `FRESHNESS_RESOURCES_REPORT`, and `get_recent_records` are all in place for
plan 13-07 (`analytics/reports.py`) to compose against, per this plan's stated purpose. No
blockers. The one deferred pre-existing test failure should be investigated before it is
mistaken for a regression introduced by a later phase-13 plan.

---
*Phase: 13-health-analytics-reports-coaching-style*
*Completed: 2026-09-04*

## Self-Check: PASSED

All 7 modified source/test files and both new phase docs (this summary, deferred-items.md)
verified present on disk. All 4 commits (`439d657`, `9bf5575`, `e9438e1`, `9e0c484`) verified
present in `git log --oneline --all`.

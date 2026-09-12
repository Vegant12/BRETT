---
phase: 18-monthly-report-physique-integration
plan: 01
subsystem: analytics
tags: [pydantic, sqlalchemy, physique, reports, mcp-precursor]

# Dependency graph
requires:
  - phase: 17-physique-analytics-mcp-read-write-tools
    provides: "get_latest_physique_diff, get_physique_volume_cross_reference (app/analytics/physique.py) and get_latest_observation (app/db/repositories/physique.py), unchanged"
provides:
  - "PhysiqueSection Pydantic model (app/analytics/schemas.py)"
  - "ReportResult.physique: PhysiqueSection | None field, resolved via forward-reference + model_rebuild()"
  - "compose_report's monthly-only physique block (three Phase 17/16 calls, same session)"
  - "_physique_section()/_physique_diff()/_physique_cross_reference() test fixture helpers"
affects: [18-02-monthly-report-narrative, 18-03-mcp-wire-surface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "String forward-reference field + ReportResult.model_rebuild() for a field whose type is declared later in the same module"
    - "Monthly-only analytics block gated by `if period is ReportPeriod.MONTHLY:` inside compose_report, mirroring the existing recomposition/plateaus calls"

key-files:
  created: []
  modified:
    - backend/app/analytics/schemas.py
    - backend/app/analytics/reports.py
    - backend/tests/test_analytics_reports.py

key-decisions:
  - "PhysiqueSection embeds PhysiqueDiffResult and PhysiqueVolumeCrossReference whole (D-01), with no ratings list and no observation_id (D-05/T-18-01)"
  - "compose_report reads get_latest_observation directly for header/confounder metadata rather than widening a Phase 17 analytics signature (accepted redundant read, per 18-CONTEXT.md Integration Points)"

patterns-established:
  - "PhysiqueSection is the fourth named anchor in ReportResult's docstring, following the recomposition/plateau/measurement precedent"

requirements-completed: [RPT-04]

duration: 45min
completed: 2026-09-12
---

# Phase 18 Plan 01: PhysiqueSection Model & compose_report Wiring Summary

**`ReportResult.physique: PhysiqueSection | None` now populates for MONTHLY reports only, embedding Phase 17's diff and volume cross-reference results whole with no new analytics arithmetic.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-09-12T (session start)
- **Completed:** 2026-09-12
- **Tasks:** 3/3 completed
- **Files modified:** 3

## Accomplishments

- `PhysiqueSection` declared in `backend/app/analytics/schemas.py` with exactly nine fields
  (`observed_on`, `pose_state`, `photo_angles_present`, `leanness_notes`, `conditioning_notes`,
  `symmetry_notes`, `conditions_note`, `diff`, `cross_reference`) — no `ratings` list, no
  `observation_id`, matching D-05/T-18-01.
- `ReportResult.physique` added as a string forward-reference field, resolved by
  `ReportResult.model_rebuild()` immediately after `PhysiqueSection`'s declaration.
- `compose_report` gained a `period is ReportPeriod.MONTHLY` conditional that reads
  `get_latest_observation`, `get_latest_physique_diff` and `get_physique_volume_cross_reference`
  on the same session, producing a single consistent snapshot; `physique` stays `None` for
  `WEEKLY` and for a user with zero observations.
- Four new `@pytest.mark.integration` container tests prove: monthly populates the section with
  the full 19-row diff spine and the observation's confounder metadata; weekly never carries it
  even with the same seeded data; zero observations yields `None`; exactly one observation
  yields a section with `diff=None` but a populated `cross_reference` (D-12).
- Both committed golden narrative tests (`test_the_narrative_is_byte_identical_to_the_committed_golden`,
  both periods) remain byte-identical — this plan changes no rendered output.

## Task Commits

Each task was committed atomically:

1. **Task 1: Declare PhysiqueSection and add ReportResult.physique** - `9d0bf3b` (feat)
2. **Task 2: Populate physique in compose_report, monthly only** - `3c487b0` (feat)
3. **Task 3: Container tests — monthly populates, weekly is None, no observation is None** - `7718544` (test)

_No TDD-cycle multi-commits — all three tasks were `tdd="true"` in metadata but executed as
single atomic commits per task, matching the plan's task granularity; each task's own verify
block ran and passed before commit._

## Files Created/Modified

- `backend/app/analytics/schemas.py` - Widened the `app.db.models.physique` import to include
  `PoseState`; added `PhysiqueSection`; added `ReportResult.physique` forward-referenced field
  plus `ReportResult.model_rebuild()`; named the fourth anchor in `ReportResult`'s docstring.
- `backend/app/analytics/reports.py` - Added imports for
  `get_latest_physique_diff`/`get_physique_volume_cross_reference`/`get_latest_observation`
  and `PhysiqueSection`; added the monthly-only physique block inside `compose_report`; added
  `physique=physique` to the `ReportResult(...)` constructor; updated two docstring paragraphs
  (the "In order" call list and the "Three sections carry a DIFFERENT anchor" paragraph).
- `backend/tests/test_analytics_reports.py` - Added `_PHYSIQUE_OBSERVED_ON`/
  `_PHYSIQUE_EARLIER_OBSERVED_ON` constants; `_physique_diff()`, `_physique_cross_reference()`,
  `_physique_section()` fixture helpers; wired `physique` into `_report()`'s base dict
  (monthly-only default); added `_seed_two_observations()` and four container tests.

## Decisions Made

- Followed the plan's exact field names and structure verbatim (no deviation from the specified
  nine-field `PhysiqueSection` shape), since plans 18-02/18-03 depend on these names being
  load-bearing.
- Kept the redundant `get_latest_observation` read in `compose_report` rather than trying to
  thread the record through `analytics/physique.py`'s two functions — the plan and
  18-CONTEXT.md both name this as accepted cost, not a defect to engineer around.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - blocking] Reformatted two pre-existing lines in `reports.py` and one in
`test_analytics_reports.py` to satisfy `ruff format --check`**
- **Found during:** Task 2's and Task 3's verify steps (`uv run ruff format --check ...`)
- **Issue:** Three lines unrelated to this plan's edits (a `get_weekly_volume(...)` call, a
  `raise ValueError(...)` call in `reports.py`, and a `coverage=_measurement_coverage(...)` call
  in `test_analytics_reports.py`) were already out of step with the installed ruff formatter's
  line-wrapping (each collapses to a single line under 100 columns). Left as multi-line by a
  prior formatter version, they blocked the plan's own required `ruff format --check` command
  from exiting 0 on the files this task touches.
- **Fix:** Ran `uv run ruff format` on both files. Formatting-only; no logic, string, or
  identifier changed. Verified via `git diff` before committing that only whitespace/line-break
  changes were introduced at those two additional sites (the file's actual new content from this
  plan was formatted correctly from the start).
- **Files modified:** `backend/app/analytics/reports.py`, `backend/tests/test_analytics_reports.py`
- **Verification:** `uv run ruff format --check` exits 0 on both files; full test suite for both
  files still green afterward.
- **Committed in:** `3c487b0`, `7718544` (part of each task's own commit)

**Total deviations:** 1 auto-fixed (Rule 3, formatting-only)
**Impact on plan:** No scope creep — the fix is a mechanical reformat of lines outside this
plan's new code, required only because the plan's own verification command scans the whole file.

## Issues Encountered

- **Out-of-scope, deferred (not fixed):** `backend/app/analytics/health.py` — untouched by this
  plan — also fails `ruff format --check` at three sites (around `get_nutrition_trend`'s
  signature and two `Decimal(...)` call chains). Surfaced only because the plan's
  `<verification>` block runs `ruff format --check backend/app/analytics ...` across the whole
  package. Per the scope boundary (only fix issues directly caused by this task's changes), this
  was left as-is and logged to
  `.planning/phases/18-monthly-report-physique-integration/deferred-items.md` rather than fixed.
- **Plan/verify inconsistency (not fixed, documented):** Task 3's `<verify>` command
  `uv run pytest backend/tests/test_analytics_reports.py -q -k "physique"` is specified to match
  "4 or more" tests, but the plan's own literal test name for the fourth container test —
  `test_a_monthly_report_with_exactly_one_observation_carries_a_section_with_no_diff` — contains
  no substring `"physique"`, so only 3 of the 4 new tests match that `-k` filter (verified via
  `pytest --collect-only -k "physique"`). The plan's acceptance criteria also require this exact
  function name verbatim (grep-checked), so the two acceptance criteria are mutually
  inconsistent; renaming would violate the explicit grep check. Resolved by keeping the literal
  name the plan specifies and treating it as a plan-authoring inconsistency rather than an
  implementation defect — the stronger, unambiguous criterion (`uv run pytest
  backend/tests/test_analytics_reports.py -q` exits 0, full file, container included) passes:
  39/39 tests pass in the file, including all four new container tests.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`ReportResult.physique` is live and container-tested. Plan 18-02 (markdown narrative) and
18-03 (MCP wire surface) can now build on `PhysiqueSection`'s exact field names and on
`compose_report`'s monthly-only population rule. No blockers.

---
*Phase: 18-monthly-report-physique-integration*
*Completed: 2026-09-12*

## Self-Check: PASSED

- FOUND: backend/app/analytics/schemas.py
- FOUND: backend/app/analytics/reports.py
- FOUND: backend/tests/test_analytics_reports.py
- FOUND: .planning/phases/18-monthly-report-physique-integration/18-01-SUMMARY.md
- FOUND commit: 9d0bf3b
- FOUND commit: 3c487b0
- FOUND commit: 7718544

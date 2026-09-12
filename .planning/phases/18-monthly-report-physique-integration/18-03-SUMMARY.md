---
phase: 18-monthly-report-physique-integration
plan: 03
subsystem: mcp
tags: [pydantic, mcp-wire, physique, reports, coaching-doc]

# Dependency graph
requires:
  - phase: 18-monthly-report-physique-integration
    plan: "01"
    provides: "PhysiqueSection Pydantic model, ReportResult.physique, compose_report's monthly-only physique block"
  - phase: 18-monthly-report-physique-integration
    plan: "02"
    provides: "_physique_lines narrative builder, the eighth monthly-only _NARRATIVE_TEMPLATE entry, build_narrative's empty-body section skip"
provides:
  - "MonthlyReportResponse.physique: PhysiqueSection | None on the MCP wire"
  - "_filtered_physique(report) -- the single-call presentation narrowing to improved/regressed muscle groups, shared by the JSON field and the narrative"
  - "Structural weekly-absence proof (model_fields + a real instance)"
  - "Three end-to-end MCP tests: narrowing, narrative/JSON agreement (WR-01 twin), empty-observation case"
  - "docs/coaching-instructions.md's physique-section bullet and tool-table amendment"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Filter-once-use-twice: _filtered_physique(report) is called ONCE per request and the SAME object is passed to both the response field and capped_report, making narrative/JSON divergence structurally unreachable rather than merely tested (T-18-13)"
    - "A degraded response's new optional field sits BESIDE the shared _degraded_body_fields() dict at the call site, not inside it, mirroring how narrative already does this for the weekly/monthly split (D-14)"

key-files:
  created: []
  modified:
    - backend/app/mcp/tools/schemas.py
    - backend/app/mcp/tools/reports.py
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_tools.py
    - docs/coaching-instructions.md
    - .planning/phases/18-monthly-report-physique-integration/deferred-items.md

key-decisions:
  - "_seed_physique_pair uses Well-Developed -> Emerging for LATS (a real delta of -2) rather than the plan's stated Developed -> Emerging (delta -1, which classifies UNCHANGED under the locked PHYSIQUE_DIFF_MIN_LEVEL_DELTA=2) -- corrected so the REGRESSED verdict in the test is real, not accidental"
  - "docs/coaching-instructions.md's baseline was already within 65 characters of the 9,000-character paste ceiling before this task's required additions (~90+ chars of literal required substrings); condensed the new physique bullet plus three pre-existing verbose bullets (physique-rating-from-photo, two-anchors, training-summary-vs-reports, warm-up-sets, per-muscle-set-counts) to land at 8,976 characters with margin, preserving every literal string the plan's acceptance criteria and test_coaching_doc.py's field/tool-name checks require"

patterns-established: []

requirements-completed: [RPT-04, RPT-05]

duration: 50min
completed: 2026-09-12
---

# Phase 18 Plan 03: MCP Wire Surface for the Physique Section Summary

**`fitness_get_monthly_report` now returns a `physique` object narrowed to muscle groups that improved or regressed, with the SAME filtered object feeding both the JSON field and the narrative so the WR-01 disagreement bug class is structurally unreachable; `fitness_get_weekly_report`'s response type has no `physique` field at all.**

## Performance

- **Duration:** 50 min
- **Started:** 2026-09-12 (session start, after worktree base correction to `f972f1a`)
- **Completed:** 2026-09-12
- **Tasks:** 3/3 completed
- **Files modified:** 5 (plus one deferred-items log)

## Accomplishments

- `MonthlyReportResponse.physique: PhysiqueSection | None` added to
  `backend/app/mcp/tools/schemas.py`, with a docstring paragraph naming D-02/D-03's narrowing,
  D-04's "no comparable-count" omission, D-06's uncapped `cross_reference.flagged`, and D-11's
  "`None` does not prove weekly" caveat. `WeeklyReportResponse` was not touched.
- `_filtered_physique(report)` added to `backend/app/mcp/tools/reports.py`: returns `None` when
  `report.physique` is `None`, returns the section unchanged when `diff` is `None` (D-12, exactly
  one observation), and otherwise returns a `model_copy` whose `diff.muscle_groups` is narrowed to
  `IMPROVED`/`REGRESSED` rows only, order preserved. `cross_reference.flagged` is never touched --
  no cap, no `was_truncated`/`total` pair (D-06).
  `fitness_get_monthly_report` calls it ONCE and passes the same object into both the response
  field and `capped_report`'s `model_copy`, so the narrative and the JSON field cannot disagree by
  construction.
- `_degraded_monthly()` now carries `physique=None` beside `narrative=None`, added as an explicit
  keyword at the call site rather than inside the shared `_degraded_body_fields()` dict --
  `WeeklyReportResponse` has neither field, so putting `physique` in the shared dict would have
  been a lie about the weekly shape.
- `test_the_weekly_report_response_structurally_cannot_carry_a_physique_section` added to
  `backend/tests/test_mcp_tool_schemas.py`, asserting the absence from `model_fields` AND from a
  real `_degraded_weekly()` instance, mirroring the existing `narrative` precedent.
- Three end-to-end tests added to `backend/tests/test_mcp_tools.py`:
  `test_the_monthly_report_carries_a_physique_section_narrowed_to_changed_groups` (19-row spine
  narrowed to exactly the 2 that moved, notes round-trip as structured JSON),
  `test_the_monthly_narrative_names_exactly_the_physique_rows_the_json_field_carries` (the WR-01
  regression twin for physique -- every JSON-carried row is named in the narrative, every omitted
  group is not, and none of the four free-text notes leaks into the live narrative), and
  `test_a_monthly_report_with_no_observation_carries_no_physique_and_no_heading` (D-11/D-13 end to
  end, plus `"physique" not in` the live weekly payload).
- `docs/coaching-instructions.md` amended: the `"How was this month?"` tool-table row now also
  names `"How does my physique compare to last time?"`, and a new bullet tells Claude the monthly
  report's `physique` section exists, that the notes are JSON-only (never repeated in
  `narrative`), and that the weekly report has none.
- Whole-suite verification: 684 fast tests, 127 named-file container tests (including
  `test_analytics_reports.py`, `test_mcp_tools.py`, `test_mcp_tool_schemas.py`,
  `test_mcp_isolation.py`, `test_analytics_isolation.py`), `test_coaching_doc.py` (4/4), and
  `test_mcp_tool_budget.py` (6/6) all green.

## Task Commits

Each task was committed atomically:

1. **Task 1: The wire field, the MCP-layer filter, and the degraded path** - `c308199` (feat)
2. **Task 2: Structural absence test and the end-to-end MCP tests** - `719d66a` (test)
3. **Task 3: Coaching-doc amendment and whole-suite verification** - `46f463e` (docs)

_All three tasks declared `tdd="true"` (tasks 1-2) or plain `auto` (task 3) in metadata but were
committed once each per the plan's own task granularity, matching plans 18-01/18-02's documented
precedent -- each task's own `<verify>` block ran and passed before its commit._

## Files Created/Modified

- `backend/app/mcp/tools/schemas.py` - Added `PhysiqueSection` to the `app.analytics.schemas`
  import block (alphabetical position); added `MonthlyReportResponse.physique: PhysiqueSection |
  None` with an extended docstring; `WeeklyReportResponse` unchanged.
- `backend/app/mcp/tools/reports.py` - Added `PhysiqueDiffVerdict`/`PhysiqueSection` imports;
  added the module docstring's "unchanged and not-comparable muscle groups" paragraph;
  added `_REPORT_PHYSIQUE_VERDICTS` and `_filtered_physique`; updated `_degraded_monthly` to carry
  `physique=None`; updated `fitness_get_monthly_report` to filter once and pass the same object to
  both the response and `capped_report`.
- `backend/tests/test_mcp_tool_schemas.py` - Added
  `test_the_weekly_report_response_structurally_cannot_carry_a_physique_section`.
- `backend/tests/test_mcp_tools.py` - Added a new `RPT-04/RPT-05` section: `_seed_physique_pair`
  and three end-to-end tests (narrowing, narrative/JSON agreement, empty-observation case).
- `docs/coaching-instructions.md` - Amended the tool-answer table row for the monthly report;
  added the physique-section bullet; condensed four pre-existing verbose bullets
  (physique-rating-from-photo, two-anchors, training-summary-vs-reports, warm-up-sets,
  per-muscle-set-counts) to stay under `test_the_document_fits_a_project_custom_instruction_paste`'s
  9,000-character ceiling.
- `.planning/phases/18-monthly-report-physique-integration/deferred-items.md` - Logged a
  pre-existing, out-of-scope `ruff check` E501 in `backend/app/db/migration_preflight.py`
  (Phase 14 file, untouched by this plan) surfaced by the plan's own repo-wide verification
  command.

## Decisions Made

- Followed the plan's exact field names, docstring content and filter logic verbatim for
  `_filtered_physique`, `MonthlyReportResponse.physique`, and `_degraded_monthly`, since the
  plan's own acceptance-criteria `grep`s check for literal substrings.
- Corrected `_seed_physique_pair`'s LATS pairing from the plan's stated Developed -> Emerging
  (delta -1, classifies UNCHANGED) to Well-Developed -> Emerging (delta -2, a real REGRESSED) --
  documented above as the plan/implementation deviation this required.
- Condensed coaching-doc prose rather than adding a new section or shortening the plan's two
  required literal substrings, since the ceiling test checks the whole document's length and the
  baseline had almost no headroom left before this task's required additions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_seed_physique_pair`'s LATS pairing corrected to produce a real REGRESSED verdict**
- **Found during:** Task 2's own verify step (`uv run pytest backend/tests/test_mcp_tools.py -q -k physique`)
- **Issue:** The plan's `<action>` text for `_seed_physique_pair` specifies "LATS moves Developed
  -> Emerging (delta -2, REGRESSED)". Checking `PhysiqueRatingLevel`'s declaration order
  (`MINIMAL=0, EMERGING=1, DEVELOPED=2, WELL_DEVELOPED=3, STANDOUT=4`), Developed -> Emerging is
  actually a delta of **-1**, and `PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2` means a delta of 1
  classifies as `UNCHANGED`, not `REGRESSED`. Using the plan's literal pairing would have produced
  a test asserting `{"chest", "lats"}` as the changed set while LATS's actual verdict was
  `UNCHANGED` -- either a silently-wrong test or an assertion failure depending on ordering.
- **Fix:** Used Well-Developed -> Emerging for LATS instead (delta -2), which is a real REGRESSED
  under the locked threshold. CHEST's Emerging -> Well-Developed pairing (delta +2, a real
  IMPROVED) was kept exactly as the plan specified.
- **Files modified:** `backend/tests/test_mcp_tools.py`
- **Verification:** `uv run pytest backend/tests/test_mcp_tools.py -q -k physique` -- all 3 tests
  pass, and `test_the_monthly_report_carries_a_physique_section_narrowed_to_changed_groups`
  explicitly asserts `verdicts <= {"improved", "regressed"}` and `"unchanged" not in verdicts`.
- **Committed in:** `719d66a`

**2. [Rule 3 - blocking] Condensed coaching-doc prose to fit the 9,000-character paste ceiling**
- **Found during:** Task 3's verify step (`uv run pytest backend/tests/test_coaching_doc.py -q`)
- **Issue:** The document's pre-task-3 baseline was 8,935 characters, only 65 characters under the
  ceiling `test_the_document_fits_a_project_custom_instruction_paste` enforces. The plan's two
  required literal additions (the tool-table row amendment and the physique-section bullet, even
  in a minimal form) needed well over 65 characters, so adding them without also trimming
  elsewhere pushed the document to 9,480 characters -- 480 over.
- **Fix:** Wrote a shorter physique-section bullet that still contains both required literal
  substrings (`"How does my physique compare to last time?"` in the table row,
  `"The weekly report has no physique section."` verbatim as its own sentence), then condensed
  four pre-existing verbose bullets elsewhere in the "Things the schemas do not tell you" and
  "Units, timezone and framing" sections without dropping any tool name, field name, or required
  metadata-field mention. Final length: 8,976 characters.
- **Files modified:** `docs/coaching-instructions.md`
- **Verification:** `uv run pytest backend/tests/test_coaching_doc.py -q` -- 4/4 pass, including
  the length ceiling, the tool-registry-completeness check, and the metadata-fields check.
- **Committed in:** `46f463e`

**Total deviations:** 2 auto-fixed (Rule 1: a test-data bug that would have produced a
self-contradicting assertion; Rule 3: a blocking budget-ceiling condition forcing prose trims
elsewhere in the document).
**Impact on plan:** No scope creep. Both fixes are confined to the exact files/lines the plan
already scoped for tasks 2 and 3; no new architectural surface, no new tool, no relaxed
assertion.

## Issues Encountered

- **Out-of-scope, deferred (not fixed):** `backend/app/db/migration_preflight.py` fails
  `ruff check` (E501, one 115-character line) -- a Phase 14 file untouched by any 18-01/18-02/18-03
  task, surfaced only because the plan's own `<verification>` block runs `ruff check backend docs`
  across the whole `backend` tree. Logged to
  `.planning/phases/18-monthly-report-physique-integration/deferred-items.md` per the scope
  boundary rather than fixed.
- **Budget test observation:** `fitness_get_monthly_report`'s worst-case fixture
  (`worst_case_history`) does not seed a physique observation, so
  `test_every_tool_response_fits_its_budget` measured the monthly report at **29,164 bytes**
  against the published 49,152-byte budget with `physique=None` -- the physique field's actual
  cost is not exercised by that fixture. The test passed as written; no budget constant was
  changed. This matches the plan's own anticipation ("the budget fixture may or may not seed
  observations") and is recorded here rather than silently accepted, per the plan's instruction
  to report the measured figure.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

This plan closes the v2.1 milestone's Active requirement "Physique section in the monthly
report" (RPT-04/RPT-05). `fitness_get_monthly_report` now carries `physique` end to end --
composed by `compose_report` (18-01), narrated by `build_narrative` (18-02), and presented on the
MCP wire narrowed to changed muscle groups with no narrative/JSON divergence possible (18-03). No
blockers for the milestone's remaining phase (19: Production Deploy of Migration 0007).

---
*Phase: 18-monthly-report-physique-integration*
*Completed: 2026-09-12*

## Self-Check: PASSED

- FOUND: backend/app/mcp/tools/schemas.py
- FOUND: backend/app/mcp/tools/reports.py
- FOUND: backend/tests/test_mcp_tool_schemas.py
- FOUND: backend/tests/test_mcp_tools.py
- FOUND: docs/coaching-instructions.md
- FOUND: .planning/phases/18-monthly-report-physique-integration/deferred-items.md
- FOUND commit: c308199
- FOUND commit: 719d66a
- FOUND commit: 46f463e

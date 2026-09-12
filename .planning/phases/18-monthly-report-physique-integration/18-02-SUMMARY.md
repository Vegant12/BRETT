---
phase: 18-monthly-report-physique-integration
plan: 02
subsystem: analytics
tags: [narrative, physique, reports, provenance, determinism]

# Dependency graph
requires:
  - phase: 18-monthly-report-physique-integration
    plan: "01"
    provides: "PhysiqueSection Pydantic model, ReportResult.physique, compose_report's monthly-only physique block"
provides:
  - "_physique_lines narrative builder (backend/app/analytics/reports.py)"
  - "The eighth, monthly-only _NARRATIVE_TEMPLATE entry (## Physique)"
  - "build_narrative's empty-body section skip (D-13)"
  - "Re-captured monthly golden narrative fixture including the ## Physique block"
  - "Numeric/word-level provenance tests proving no Claude-authored free text reaches the narrative"
affects: [18-03-mcp-wire-surface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Period-restricted _NarrativeSection: a section declares `periods=(ReportPeriod.MONTHLY,)` and build_narrative's loop checks `applies_to()` before rendering"
    - "Empty-body section skip: build_narrative builds a section's lines BEFORE appending its heading, and skips both when the body is empty -- this is what lets a monthly report with no physique observation omit the ## Physique heading entirely rather than render a placeholder"
    - "Provenance dump with nested Pydantic exclude: `report.model_dump_json(exclude={\"physique\": {<note fields>}})` keeps the numeric-provenance guarantee from being weakened by free text that could otherwise launder a spurious number"
    - "Whole-token word matching via `[A-Za-z][A-Za-z_-]*` for rating/verdict provenance, deliberately avoiding substring matches that would let 'Well-Developed' satisfy an assertion about 'Developed'"

key-files:
  created: []
  modified:
    - backend/app/analytics/reports.py
    - backend/tests/test_analytics_reports.py
    - backend/tests/fixtures/reports/monthly_narrative.md

key-decisions:
  - "_physique_lines does not filter report.physique.diff.muscle_groups or cross_reference.flagged -- it renders exactly what it is given. Filtering to changed/flagged groups only is deferred to the MCP layer (plan 18-03), keeping this builder honest about what the report actually carries"
  - "Reworded a phrase in _physique_lines' docstring ('free text (D-09)') that coincidentally matched test_analytics_isolation.py's raw-SQL text() detector -- no code behavior changed, purely a docstring wording fix"

patterns-established:
  - "The physique block is the first and only period-restricted _NarrativeSection; any future monthly-only or weekly-only section follows the same two-part shape (one _NarrativeSection entry with an explicit periods tuple, plus one builder)"

requirements-completed: [RPT-05]

duration: 55min
completed: 2026-09-12
---

# Phase 18 Plan 02: Monthly Report Narrative — Physique Integration Summary

**`build_narrative` now renders a deterministic, provenance-checked `## Physique` block for monthly reports only, with zero Claude-authored free text and every rendered rating/verdict word traceable to `report.physique`'s own structured fields.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-09-12 (session start, after worktree base correction)
- **Completed:** 2026-09-12
- **Tasks:** 3/3 completed
- **Files modified:** 3

## Accomplishments

- `_physique_lines` added to `backend/app/analytics/reports.py`: renders the D-07 anchor line
  (observation date vs. report window), a `Changes since ...`/first-recorded-observation line,
  one indented row per diff entry (or `- none`), an `Underdeveloped and undertrained (...)`
  header with one indented row per volume-cross-reference flag (or `- none`), and the
  `cross_reference.disclaimer` verbatim on its own final line. No note field
  (`leanness_notes`/`conditioning_notes`/`symmetry_notes`/`conditions_note`) is interpolated
  anywhere in the module.
- `_NARRATIVE_TEMPLATE` gained its eighth entry, `_NarrativeSection("## Physique",
  _physique_lines, (ReportPeriod.MONTHLY,))` — the first and only period-restricted section.
- `build_narrative`'s loop now builds a section's body before appending its heading and skips
  both when the body is empty (D-13): a monthly report for a user with zero physique
  observations renders no `## Physique` heading and no placeholder line.
- The committed monthly golden narrative (`backend/tests/fixtures/reports/monthly_narrative.md`)
  was deliberately re-captured to include the new `## Physique` block; the weekly golden is
  byte-unchanged (confirmed both via the task's own diff-name check and a final `git diff --stat`
  against the wave's base commit).
- Ten new/renamed tests added, covering: the eight-section template contract and its lone
  period restriction, a D-13 no-op proof across every shipped builder in both periods, the
  monthly-only heading assertion, D-09's provenance exclusion and its load-bearing proof (a
  number that exists only inside a note cannot reach the provenance dump or the narrative),
  D-09's blanket no-note-leaks-to-narrative assertion, D-10's whole-token
  rating/verdict-word provenance check, D-12's first-recorded-observation line, D-13's
  no-physique-no-heading case, D-07's anchor-line wording, and D-08's verbatim/exactly-once
  disclaimer assertion.

## Task Commits

Each task was committed atomically:

1. **Task 1: `_physique_lines`, the eighth template entry, and the empty-body skip** - `da045a9` (feat)
2. **Task 2: Update the arriving-failure tests and re-capture the monthly golden** - `5660e78` (test)
3. **Task 3: Provenance and free-text tests — D-09, D-10, D-12** - `93c72a6` (test)

_Tasks 1 and 3 were `tdd="true"` in metadata but executed as single atomic commits per task,
matching plan 18-01's precedent and this plan's own task granularity (each task's own `<verify>`
block ran and passed before commit)._

## TDD Gate Compliance

Tasks 1 and 3 declared `tdd="true"` but this plan (like 18-01) committed each task once rather
than as separate RED/GREEN commits — there is no standalone `test(...)`-then-`feat(...)` pair for
task 1's `_physique_lines` (task 1's own commit is `feat` and includes no new tests; the tests
that exercise it arrive in tasks 2 and 3). This mirrors 18-01's documented precedent exactly and
is intentional given the plan's task boundaries (task 1 is pure production code, tasks 2–3 are
pure test code) rather than a missed gate.

## Files Created/Modified

- `backend/app/analytics/reports.py` - Added `_physique_lines`; registered the eighth,
  monthly-only `_NARRATIVE_TEMPLATE` entry; changed `build_narrative`'s loop to build a
  section's body before its heading and skip both when the body is empty; updated the
  `_NARRATIVE_TEMPLATE` comment, `build_narrative`'s docstring's "seven"→"eight" section-count
  reference, and reworded a docstring phrase that coincidentally tripped
  `test_analytics_isolation.py`'s raw-SQL `text()` detector.
- `backend/tests/test_analytics_reports.py` - Renamed
  `test_the_seven_section_headings_are_present` →
  `test_the_seven_shared_section_headings_are_present`; renamed and expanded
  `test_the_template_declares_the_seven_sections_in_order` →
  `test_the_template_declares_the_eight_sections_in_order`; added
  `test_every_shipped_section_builder_returns_at_least_one_line`,
  `test_the_physique_heading_is_monthly_only`,
  `_PHYSIQUE_FREE_TEXT_FIELDS`/`_PROVENANCE_EXCLUDE`/`_WORD_RE`/`_physique_block()`,
  `test_a_number_inside_a_physique_note_cannot_launder_a_narrative_number`,
  `test_no_claude_authored_note_reaches_the_narrative`,
  `test_every_rating_word_in_the_narrative_is_already_in_the_structured_fields`,
  `test_a_first_recorded_observation_renders_an_explicit_line_not_an_omission`,
  `test_a_monthly_report_with_no_physique_omits_the_heading_entirely`,
  `test_the_physique_anchor_line_names_the_observation_date_and_states_it_differs`,
  `test_the_physique_disclaimer_appears_verbatim_on_its_own_line_exactly_once`; amended
  `test_every_number_in_the_narrative_is_already_in_the_structured_fields` to run against
  `report.model_dump_json(exclude=_PROVENANCE_EXCLUDE)`.
- `backend/tests/fixtures/reports/monthly_narrative.md` - Re-captured to append the
  `## Physique` block matching the plan's exact stated shape; `weekly_narrative.md` untouched.

## Decisions Made

- Followed the plan's exact literal strings and line shapes verbatim for `_physique_lines`
  (every f-string, the `- none` and `not assessable` literals, and the first-recorded-observation
  sentence), since the plan's tests and golden fixture assert them character-for-character.
- Kept the docstring's stated non-filtering behavior of `_physique_lines` intentionally: the
  builder renders `report.physique.diff.muscle_groups`/`cross_reference.flagged` exactly as
  carried, with filtering explicitly deferred to plan 18-03's MCP layer.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - blocking] Reworded a docstring phrase that coincidentally matched a raw-SQL
detector**
- **Found during:** Task 3's verification (`uv run pytest backend/tests/test_analytics_isolation.py -q`)
- **Issue:** `_physique_lines`' docstring originally read `"Renders NO Claude-authored free text
  (D-09)."` — the substring `"text ("` matched `test_analytics_isolation.py`'s
  `_RAW_SQL_TEXT` regex (`(?<![\w.])(?:(?:sa|sqlalchemy)\.)?text\s*\(`), which exists to catch
  raw SQL built with SQLAlchemy's `text()`. This is a coincidental collision with a docstring
  sentence, not an actual SQL-injection risk (the module contains no `text()` call), and matches
  the same class of "rephrase to avoid tripping this project's own literal-substring acceptance
  grep" pattern this module's own docstring already documents elsewhere for other reasons.
- **Fix:** Reworded to `"Renders NO Claude-authored free-form prose (D-09)."` — first attempt
  (`"free-form text (D-09)"`) still matched (`"text ("` is substring-order-agnostic to the added
  word), so the second attempt removed the word "text" adjacent to an open paren entirely. No
  code behavior changed.
- **Files modified:** `backend/app/analytics/reports.py`
- **Verification:** `uv run pytest backend/tests/test_analytics_isolation.py -q` exits 0 (8
  passed); `uv run ruff check`/`format --check`/`mypy` all still pass on the file.
- **Committed in:** `93c72a6` (folded into task 3's commit, since it was surfaced by task 3's
  verification step)

**Total deviations:** 1 auto-fixed (Rule 3, docstring wording only — no logic, string constant,
or test assertion affected).
**Impact on plan:** No scope creep. The fix is confined to one docstring sentence in the function
task 1 added; every literal string task 2's golden fixture and task 3's tests assert against is
unchanged.

## Issues Encountered

None beyond the deviation above. All three tasks' own `<verify>` blocks and the plan's full
`<verification>` block pass, including the container-backed integration tests in
`test_analytics_reports.py` (48 passed total when run without the `-m` filter) and the full
non-integration/non-realfile backend suite (683 passed).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

`build_narrative` now renders the physique block deterministically and provenance-safely for
monthly reports. Plan 18-03 (MCP wire surface) can build on this: it is responsible for narrowing
`report.physique.diff.muscle_groups` to IMPROVED/REGRESSED rows and handing `build_narrative` the
already-narrowed copy, per this plan's `_physique_lines` docstring, which documents that this
builder deliberately does not filter. No blockers.

---
*Phase: 18-monthly-report-physique-integration*
*Completed: 2026-09-12*

## Self-Check: PASSED

- FOUND: backend/app/analytics/reports.py
- FOUND: backend/tests/test_analytics_reports.py
- FOUND: backend/tests/fixtures/reports/monthly_narrative.md
- FOUND: .planning/phases/18-monthly-report-physique-integration/18-02-SUMMARY.md
- FOUND commit: da045a9
- FOUND commit: 5660e78
- FOUND commit: 93c72a6

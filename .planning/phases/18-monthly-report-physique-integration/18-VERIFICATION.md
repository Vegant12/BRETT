---
phase: 18-monthly-report-physique-integration
verified: 2026-09-12T04:48:46Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
---

# Phase 18: Monthly Report Physique Integration Verification Report

**Phase Goal:** The monthly report reads across training, nutrition, measurements and visible physique in one view; the weekly report structurally cannot carry it.
**Verified:** 2026-09-12T04:48:46Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria + Plan must_haves, merged)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ReportResult.physique: PhysiqueSection \| None` populated via a one-line period conditional in `compose_report`; `fitness_get_weekly_report`'s response has no `physique` attribute at all (structural, tested absence) | ✓ VERIFIED | `backend/app/analytics/schemas.py:1152` declares `PhysiqueSection`; `ReportResult.physique` forward-ref field + `model_rebuild()`; `compose_report` (`reports.py:191-214`) gates population on `period is ReportPeriod.MONTHLY`. `WeeklyReportResponse` (`mcp/tools/schemas.py:556-562`) has no `physique` field; `MonthlyReportResponse` (line 598) does. `test_the_weekly_report_response_structurally_cannot_carry_a_physique_section` (test_mcp_tool_schemas.py) passes, asserting both `model_fields` and a real `_degraded_weekly()` instance |
| 2 | `build_narrative`'s physique section is byte-identical across repeated runs, contains none of the ten banned recommendation tokens, and every number rendered already exists in `report.model_dump_json()` | ✓ VERIFIED | `_physique_lines` (`reports.py:465-540`) interpolates only dates/enum values/numbers. `test_the_narrative_is_byte_identical_across_calls`, `test_the_narrative_contains_no_recommendation_language`, `test_every_number_in_the_narrative_is_already_in_the_structured_fields` (amended to exclude the 4 free-text fields per D-09) all pass |
| 3 | Claude-authored free-text notes (leanness/conditioning/symmetry/conditions) are structured JSON fields on the report response but never appear in `build_narrative`'s markdown | ✓ VERIFIED | `PhysiqueSection` carries all 4 note fields; `grep` for `physique.leanness_notes\|conditioning_notes\|symmetry_notes\|conditions_note` in `reports.py` returns nothing (no f-string interpolation). `test_no_claude_authored_note_reaches_the_narrative` and end-to-end `test_the_monthly_narrative_names_exactly_the_physique_rows_the_json_field_carries` (asserts none of the 4 note values leak into a live narrative) both pass |
| 4 | Every rating/verdict word rendered in the narrative matches the corresponding `.value` read directly off `report.physique`'s own fields | ✓ VERIFIED | `test_every_rating_word_in_the_narrative_is_already_in_the_structured_fields` reads the legal word set off `report.physique` itself (not the enum classes) and whole-token-matches against the rendered `## Physique` block; passes |
| 5 | Plan 18-01: monthly `compose_report` for a user with ≥1 non-superseded observation returns a populated physique section; weekly returns `None` for the same data; zero observations → `None` | ✓ VERIFIED | Container tests `test_a_monthly_report_carries_the_physique_section`, `test_a_weekly_report_never_carries_the_physique_section`, `test_a_monthly_report_with_no_observation_carries_no_physique_section` all pass against real PostgreSQL |
| 6 | Plan 18-01: physique section embeds Phase 17's diff and cross-reference results whole, carrying their own windows/disclaimers | ✓ VERIFIED | `PhysiqueSection.diff: PhysiqueDiffResult \| None` and `.cross_reference: PhysiqueVolumeCrossReference` are embedded, not flattened; container test asserts `cross_reference.observed_on`/`lookback_weeks` reach the composed report intact |
| 7 | Plan 18-01: physique section carries header/confounder metadata + 3 Claude note fields, no ratings list | ✓ VERIFIED | `PhysiqueSection` field set is exactly the 9 specified fields; `grep -A 12 "class PhysiqueSection"` shows 0 `ratings:` and 0 `observation_id` occurrences |
| 8 | Plan 18-02: monthly narrative's `## Physique` block names the observation date, states it differs from the report window, one line per diff row / per cross-ref flag, disclaimer verbatim last | ✓ VERIFIED | Re-captured golden `backend/tests/fixtures/reports/monthly_narrative.md` contains the exact block shape; `weekly_narrative.md` shows 0 occurrences of "Physique" |
| 9 | Plan 18-02: a physique-`None` monthly report renders no `## Physique` heading/placeholder; a single-observation report renders an explicit first-recorded-observation line | ✓ VERIFIED | `test_a_monthly_report_with_no_physique_omits_the_heading_entirely` and `test_a_first_recorded_observation_renders_an_explicit_line_not_an_omission` both pass |
| 10 | Plan 18-03: `fitness_get_monthly_report`'s diff is narrowed to `improved`/`regressed` only; `cross_reference.flagged` carried whole, uncapped | ✓ VERIFIED | `_filtered_physique` (`mcp/tools/reports.py:172-199`) filters `diff.muscle_groups` to `_REPORT_PHYSIQUE_VERDICTS = (IMPROVED, REGRESSED)`, never touches `flagged`. End-to-end `test_the_monthly_report_carries_a_physique_section_narrowed_to_changed_groups` confirms 19-row spine narrowed to exactly 2 changed rows, `"unchanged"`/`"not_comparable"` absent |
| 11 | Plan 18-03: degraded monthly report carries `physique=None` beside `narrative=None`; coaching doc names the physique section | ✓ VERIFIED | `_degraded_monthly()` returns `MonthlyReportResponse(**_degraded_body_fields(), narrative=None, physique=None)`; `docs/coaching-instructions.md` contains "How does my physique compare to last time?" and "The weekly report has no physique section." `test_coaching_doc.py` (4/4) passes |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/analytics/schemas.py` | `PhysiqueSection` model, `ReportResult.physique` field | ✓ VERIFIED | Class present at line 1152 with exact 9-field shape; `ReportResult.physique` resolves via `model_rebuild()`; mypy clean |
| `backend/app/analytics/reports.py` | `compose_report`'s monthly-only physique block; `_physique_lines`; 8th `_NARRATIVE_TEMPLATE` entry | ✓ VERIFIED | All present, wired, tested; `get_physique_volume_cross_reference` call confirmed |
| `backend/tests/test_analytics_reports.py` | `_physique_section()` fixture; monthly/weekly compose_report tests; narrative/provenance tests | ✓ VERIFIED | `def _physique_section` present; 48/48 tests in file pass (container included) |
| `backend/tests/fixtures/reports/monthly_narrative.md` | Re-captured golden including `## Physique` | ✓ VERIFIED | Contains block matching plan's exact stated shape |
| `backend/app/mcp/tools/schemas.py` | `MonthlyReportResponse.physique`, absent from `WeeklyReportResponse` | ✓ VERIFIED | Confirmed via grep + `model_fields` test |
| `backend/app/mcp/tools/reports.py` | `_filtered_physique`, extended `capped_report`, `_degraded_monthly`'s `physique=None` | ✓ VERIFIED | All present and wired into `fitness_get_monthly_report` |
| `backend/tests/test_mcp_tool_schemas.py` | Structural weekly-absence test | ✓ VERIFIED | `def test_the_weekly_report_response_structurally_cannot_carry_a_physique_section` present, passes |
| `backend/tests/test_mcp_tools.py` | End-to-end monthly physique test + WR-01(narrative/JSON) agreement test | ✓ VERIFIED | 3 physique-specific end-to-end tests present, pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `analytics/reports.py::compose_report` | `analytics/physique.py::get_latest_physique_diff` | monthly-only conditional, same session | ✓ WIRED | `reports.py:201` |
| `analytics/reports.py::compose_report` | `db/repositories/physique.py::get_latest_observation` | header/confounder metadata read | ✓ WIRED | `reports.py:199` |
| `analytics/schemas.py` | `db/models/physique.py::PoseState` | import | ✓ WIRED | `schemas.py:39` |
| `_NARRATIVE_TEMPLATE` | `_physique_lines` | period-restricted section entry | ✓ WIRED | `reports.py:569` |
| `_physique_lines` | `cross_reference.disclaimer` | verbatim final line | ✓ WIRED | `reports.py:540` |
| `test_analytics_reports.py` | `report.model_dump_json(exclude=...)` | D-09 4-field exclusion | ✓ WIRED | Confirmed present and passing |
| `mcp/tools/reports.py::fitness_get_monthly_report` | `_filtered_physique` | ONE filtered object for both JSON field and narrative | ✓ WIRED | `reports.py:282` (`physique = _filtered_physique(report)`), reused at both `"physique": physique` (capped_report) and the `MonthlyReportResponse(..., physique=physique)` return |
| `mcp/tools/schemas.py` | `analytics/schemas.py::PhysiqueSection` | wire reuse | ✓ WIRED | Imported and used directly, no parallel wire model |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `fitness_get_monthly_report` response `physique` field | `report.physique` → `_filtered_physique(report)` | `compose_report` → `get_latest_observation`/`get_latest_physique_diff`/`get_physique_volume_cross_reference` (real DB queries against `GoldenBuilder`-seeded PostgreSQL) | Yes | ✓ FLOWING — end-to-end test seeds two real observations via `_seed_physique_pair`, calls the live MCP tool through `Client(mcp)`, and asserts the returned JSON payload's `physique.diff.muscle_groups` matches the seeded chest/lats changes exactly |
| `## Physique` narrative block | same `physique` object, passed into `capped_report` | Same session/query as above | Yes | ✓ FLOWING — `test_the_monthly_narrative_names_exactly_the_physique_rows_the_json_field_carries` confirms narrative text is derived from the same filtered object, not a separate/static path |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast unit/schema tests pass | `uv run pytest backend/tests/test_analytics_reports.py backend/tests/test_mcp_tool_schemas.py -q -m "not integration and not realfile"` | 42 passed | ✓ PASS |
| Container-backed physique composition tests pass | `uv run pytest backend/tests/test_analytics_reports.py -q` | 48 passed | ✓ PASS |
| End-to-end MCP physique tests pass | `uv run pytest backend/tests/test_mcp_tools.py -q -k "physique"` | 3 passed | ✓ PASS |
| Isolation/coaching-doc/budget tests pass | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_analytics_isolation.py backend/tests/test_coaching_doc.py backend/tests/test_mcp_tool_budget.py -q` | 27 passed | ✓ PASS |
| Full non-integration suite has no regressions | `uv run pytest backend/tests -q -m "not integration and not realfile"` | 684 passed | ✓ PASS |
| Static analysis clean | `uv run ruff check` + `uv run mypy` on all 4 touched source files | 0 issues | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RPT-04 | 18-01, 18-03 | Monthly report carries physique section as Optional field on `ReportResult`, populated via period conditional; weekly report does not carry it | ✓ SATISFIED | Verified truths #1, #5-#7, #10 above. **Note:** `.planning/REQUIREMENTS.md` still shows RPT-04 as unchecked (`[ ]`) and "Planned" in its status table — this is a documentation-bookkeeping lag, not a code gap; both plan frontmatters (`18-01-PLAN.md`, `18-03-PLAN.md`) declare `requirements: [RPT-04]` / `[RPT-04, RPT-05]` and both SUMMARYs list `requirements-completed` including RPT-04. Recommend updating REQUIREMENTS.md's checkbox and status table as part of phase close-out |
| RPT-05 | 18-02, 18-03 | `build_narrative` renders physique under determinism contract; free-text notes travel as JSON only | ✓ SATISFIED | Verified truths #2-#4, #8-#9, #11 above. REQUIREMENTS.md already shows `[x]` for RPT-05, though its status table row still says "Planned" (same bookkeeping lag) |

No orphaned requirements: REQUIREMENTS.md maps exactly RPT-04 and RPT-05 to Phase 18, and both appear in the plans' `requirements` frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/analytics/reports.py` | 199-214 | WR-01 (from 18-REVIEW.md): three sequential, independently-snapshotted reads (`get_latest_observation`, `get_latest_physique_diff`, `get_physique_volume_cross_reference`) under `READ COMMITTED` isolation could theoretically disagree under a concurrent write, and the code comments this off as "not a real branch." If `cross_reference` unexpectedly returns `None` after `observation` was found, the code silently falls through to `physique=None` rather than failing loudly | ⚠️ Warning | Narrow race window on a single-user app with infrequent manual physique writes; operationally low risk today, but is a real inconsistency with this module's own convention elsewhere (`_body_lines` raises `ValueError` for an equivalent invariant violation). Does not block any of the phase's must-haves — all specified truths and success criteria are met either way — but is worth tracking as a follow-up hardening item, as the reviewer already recommended (raise `RuntimeError` instead of silently degrading) |
| `.planning/REQUIREMENTS.md` | 37, 109-110 | RPT-04 checkbox unchecked and both RPT-04/RPT-05 status-table rows still read "Planned" despite both requirements being implemented and tested | ℹ️ Info | Documentation lag only; does not affect functional correctness. Should be corrected during phase close-out (this is typically handled by the `docs(phase-X): evolve PROJECT.md after phase completion` step, which had not yet run for Phase 18 at verification time) |

No blockers found. No TODO/FIXME/placeholder patterns, no hardcoded empty-data stubs, and no orphaned wiring in any of the 5 files this phase modified.

### Human Verification Required

None. This phase is backend-only, fully deterministic, and covered end-to-end by automated tests (unit, container/integration, and live MCP tool call through `Client(mcp)`). No UI, no external service integration, and no behavior that requires visual or manual inspection.

### Gaps Summary

No gaps block phase goal achievement. All 4 roadmap success criteria and all plan-level must-haves (analytics composition, narrative rendering, MCP wire surface, coaching-doc amendment) are verified against real code and passing tests, including 48 container-backed tests against real PostgreSQL and 3 live end-to-end MCP tool-call tests. The one open item from code review (WR-01, a narrow race-condition edge case in `compose_report`'s physique branch) is a documented warning, not a failed must-have — the reviewer classified it as narrow-risk on a single-user app and it does not prevent the monthly report from reading across training, nutrition, measurements and physique in one view, nor does it let physique data leak onto the weekly report. Recommend tracking WR-01 as a small follow-up fix (raise `RuntimeError` on the unreachable-in-practice branch) rather than reopening this phase. The REQUIREMENTS.md checkbox/status-table lag for RPT-04/RPT-05 is a documentation housekeeping item, addressable at phase close-out.

---

_Verified: 2026-09-12T04:48:46Z_
_Verifier: Claude (gsd-verifier)_

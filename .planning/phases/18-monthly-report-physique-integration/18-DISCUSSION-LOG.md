# Phase 18: Monthly Report Physique Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-12
**Phase:** 18-monthly-report-physique-integration
**Areas discussed:** Section content depth, Narrative rendering, Thin/absent data
**Area declined:** Notes vs. provenance (delegated to Claude's discretion; recorded as D-09)

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Notes vs. provenance | Where Claude's free-text notes live, and whether their presence in `model_dump_json()` weakens the numeric-provenance test for the whole narrative | |
| Section content depth | How much of the 19-row diff and the observation reaches the report | ✓ |
| Narrative rendering | What the `## Physique` block says, the disclaimer, the fourth anchor, the word-provenance test | ✓ |
| Thin/absent data | Zero observations, one observation, and the degraded path | ✓ |

---

## Section Content Depth

### Q1 — How many diff rows reach the report's physique section?

| Option | Description | Selected |
|--------|-------------|----------|
| Only changed groups | Filter to `IMPROVED`/`REGRESSED`, mirroring `_report_body_fields`' plateau treatment | ✓ |
| All 19 rows | Carry `PhysiqueDiffResult` whole, preserving the gap-free spine its docstring defends | |
| Changed + not_comparable | Changed groups plus `NOT_COMPARABLE`, keeping abductors/adductors visible | |

**User's choice:** Only changed groups
**Notes:** Accepts that `PhysiqueDiffResult` keeps its full 19-row spine for direct callers; this is a report-layer narrowing only.

### Q2 — How much of the latest observation travels?

| Option | Description | Selected |
|--------|-------------|----------|
| Header + confounders only | `observed_on`, pose, angles, conditions, notes — no ratings list | ✓ |
| Full observation view | All 19 ratings plus confounders plus notes; self-contained but duplicates levels | |
| Header only, no confounders | Leanest; drops the PHYS-04 confounder caveat | |

**User's choice:** Header + confounders only
**Notes:** `PhysiqueDiffResult.muscle_groups` already carries `later_level` for all 19 groups, so a ratings list would ship the same levels twice.

### Q3 — What shape is `PhysiqueSection`?

| Option | Description | Selected |
|--------|-------------|----------|
| Embed results whole | Nested `PhysiqueDiffResult` / `PhysiqueVolumeCrossReference`, matching `recomposition` and `plateau_highlights` | ✓ |
| Flat projection | Flatten fields up, as `_report_body_fields` does for recomposition at the MCP layer | |
| Hybrid | Embed the two results, flatten the observation header | |

**User's choice:** Embed results whole
**Notes:** `ReportResult`'s docstring justifies embedding whole precisely when a result "carries its own window in its own fields" — true of the cross-reference's `observed_on`-anchored window.

### Q4 — Is the cross-reference `flagged` list capped?

| Option | Description | Selected |
|--------|-------------|----------|
| Carried whole, no cap | 19 is a hard ceiling; flagged is an intersection, realistically 0–5 | ✓ |
| Capped with was_truncated | `MAX_REPORT_PHYSIQUE_FLAGS` + `truncate()`, uniform with other report lists | |
| You decide | Planner's call | |

**User's choice:** Carried whole, no cap

### Follow-up Q5 — Where does the changed-groups filter run?

Raised because Q1 ("only changed groups") and Q3 ("embed whole") interact — embedding whole means all 19 rows arrive, so the filter needs a named layer.

| Option | Description | Selected |
|--------|-------------|----------|
| MCP layer (plateau precedent) | `ReportResult` embeds whole; `reports.py` filters and extends the existing `capped_report` `model_copy` | ✓ |
| Analytics layer | `compose_report` filters before building the section; simpler but breaks the "uncapped here" rule | |

**User's choice:** MCP layer (plateau precedent)

### Follow-up Q6 — Does the 19-row spine stay reachable in the report?

| Option | Description | Selected |
|--------|-------------|----------|
| Filtered only | Anyone needing all 19 calls the analytics function directly | ✓ |
| Keep a count beside it | Add a total/comparable count, mirroring `plateau_highlights_total` | |

**User's choice:** Filtered only

---

## Narrative Rendering

### Q1 — What does the `## Physique` block say?

| Option | Description | Selected |
|--------|-------------|----------|
| Observation + changes + flags | Anchor line, one line per changed group, one per flag, then the disclaimer (~4–8 lines) | ✓ |
| Changes and flags only | Drops the observation header; loses the confounder caveat from the prose | |
| Fuller block with elapsed-days context | Adds `elapsed_days` vs `min_elapsed_days` context | |

**User's choice:** Observation + changes + flags
**Notes:** The fuller elapsed-days variant was not selected, so D-07 records it as optional rather than required.

### Q2 — How does `PHYSIQUE_RATING_DISCLAIMER` render?

| Option | Description | Selected |
|--------|-------------|----------|
| Once, verbatim | One line at the end of the block, read off the embedded result — `_program_lines`' precedent | ✓ |
| Not in the narrative at all | Structured fields only; diverges from the recomposition precedent | |

**User's choice:** Once, verbatim
**Notes:** Verified during discussion that the disclaimer text contains none of the ten banned tokens.

### Q3 — How visible is the cross-reference's fourth anchor?

| Option | Description | Selected |
|--------|-------------|----------|
| Named in prose, like Program | Explicit "as of / different anchor from the period above" line | ✓ |
| Structured fields only | Window rides along on the embedded result; narrative stays silent | |

**User's choice:** Named in prose, like Program

### Q4 — Does the word-level provenance test read the report or the enums?

| Option | Description | Selected |
|--------|-------------|----------|
| Read `.value` off `report.physique` | Word-level twin of the numeric substring check; criterion #4's literal wording | ✓ |
| Scan against the enum classes | Simpler, but passes when the narrative prints a level the report never held | |

**User's choice:** Read `.value` off `report.physique`

---

## Thin/Absent Data

### Q1 — What is `physique` when no observation was ever logged?

| Option | Description | Selected |
|--------|-------------|----------|
| None | Same value the weekly report carries; criterion #1's structural test carries the weight | ✓ |
| PhysiqueSection with null sub-fields | Distinguishes "monthly, nothing logged" from "weekly, structurally absent" by value | |

**User's choice:** None

### Q2 — What renders when exactly one observation exists?

| Option | Description | Selected |
|--------|-------------|----------|
| Section renders, diff line says so | Explicit "first recorded observation" line where the changes would go | ✓ |
| Section renders, changes omitted | Shorter, but conflates "nothing changed" with "nothing to compare" | |

**User's choice:** Section renders, diff line says so

### Q3 — Does the `## Physique` heading render when `physique` is None?

| Option | Description | Selected |
|--------|-------------|----------|
| Heading omitted entirely | Needs a small change to `build_narrative`'s loop | ✓ |
| Heading renders with a "not recorded" line | Zero change to the loop; keeps the section list constant across months | |

**User's choice:** Heading omitted entirely
**Notes:** The mechanism (empty-body skip vs. a report-level predicate on `_NarrativeSection`) was left to the planner, with the constraint that it be provably a no-op for the seven shipped sections.

### Q4 — How does the degraded path carry physique?

| Option | Description | Selected |
|--------|-------------|----------|
| physique=None, like narrative=None | One more keyword on the existing `_degraded_monthly` call | ✓ |
| You decide | Planner's call | |

**User's choice:** physique=None, like narrative=None

---

## Claude's Discretion

- **Notes vs. provenance** — declined as a discussion area; recorded as D-09 with full rationale.
  Resolution: no Claude-authored free text renders in the narrative (all four fields, including
  `conditions_note`), and those four fields are excluded from the dump the numeric-provenance test
  checks against.
- **`build_narrative`'s empty-section mechanism** (D-13's implementation).
- **Where `PhysiqueSection` is defined**, and whether `MonthlyReportResponse` reuses it.
- **Exact narrative line wording** and the field names inside `PhysiqueSection`.
- **Whether the anchor line also surfaces `elapsed_days` vs `min_elapsed_days`.**

## Findings Surfaced During Discussion

- `PHYSIQUE_RATING_DISCLAIMER` contains no banned narrative token — verbatim rendering is safe.
- `"try "` is a substring of `"symmetry "`, so any narrative line rendering the word *symmetry*
  followed by a space would fail the banned-token scan with a misleading message.
- `test_the_template_declares_the_seven_sections_in_order` asserts every section has
  `periods is None` and will fail on arrival of the physique section — expected, must be updated in
  the same commit.
- `"Developed"` is a substring of `"Well-Developed"`; the word-provenance test must match whole
  rendered tokens.

## Deferred Ideas

- `fitness_get_physique_history` / ad-hoc diff read tool (already PHYS-F02).
- Minimum-elapsed-interval enforcement (already PHYS-F01).
- Any weekly-report physique summary — explicitly excluded by criterion #1.
- Widening the free-text note caps (already PHYS-F04).

# Phase 17: Physique Analytics & MCP Read/Write Tools - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-11
**Phase:** 17-physique-analytics-mcp-read-write-tools
**Areas discussed:** Volume cross-reference definition (PHYS-10), coaching-instructions.md wording

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Supersede mechanism (PHYS-08) | Parameter on the write tool vs. a dedicated tool | |
| Volume cross-reference definition (PHYS-10) | Concrete thresholds for underdeveloped/undertrained | ✓ |
| Diff/cross-reference MCP exposure | Confirm internal-only vs. exposed this phase | |
| coaching-instructions.md wording | Placement/phrasing of the anti-ratchet instruction | ✓ |

**User's choice:** Discuss only the volume cross-reference definition and the coaching-instructions.md
wording; leave the supersede mechanism and MCP exposure scope to Claude's discretion.
**Notes:** Both left-to-discretion areas are still recorded as named decisions with rationale in
CONTEXT.md (D-07, D-08), following Phase 16's precedent for user-delegated gray areas.

---

## Volume Cross-Reference Definition (PHYS-10)

### Q1: What counts as "underdeveloped"?

| Option | Description | Selected |
|--------|-------------|----------|
| Bottom 2 of 5 levels | `rating_level` in `{Minimal, Emerging}` | ✓ |
| Bottom 1 of 5 levels only | Only `Minimal` counts | |
| Self-relative (below this observation's own median) | Whatever rates below this observation's own median across its 19 groups | |

**User's choice:** Bottom 2 of 5 levels (recommended).

### Q2: What counts as "undertrained," and over what window?

| Option | Description | Selected |
|--------|-------------|----------|
| Bottom quartile of the user's own 12-week volume | Self-relative among the user's 19 muscle groups' `weighted_sets` over `RECOMP_LOOKBACK_WEEKS` | ✓ |
| Fixed absolute floor (e.g. <10 weighted sets/week) | Literature-style minimum-effective-volume cutoff | |
| Reuse existing `insufficient_data` flag | Treat "not enough session data" as "undertrained" | |

**User's choice:** Bottom quartile of the user's own 12-week volume (recommended).

### Q3: How should "Not Assessable" muscle groups be treated?

| Option | Description | Selected |
|--------|-------------|----------|
| Excluded entirely | Dropped from the underdeveloped side of the join; still counted normally on the volume side | ✓ |
| Included with a flag | Surfaced as a third "unrated but low-volume" bucket | |

**User's choice:** Excluded entirely (recommended).

### Q4: What should the cross-reference function return?

| Option | Description | Selected |
|--------|-------------|----------|
| Flagged list only | Muscle groups where underdeveloped AND undertrained both hold | ✓ |
| Full per-muscle table | Every rated group's development level + volume quartile side by side | |

**User's choice:** Flagged list only (recommended).

**Notes:** All four answers took the recommended option. Recorded as D-01 through D-04 in
CONTEXT.md.

---

## `docs/coaching-instructions.md` Wording

### Q1: Where does the Phase 15 anti-ratchet instruction (D-08 of 15-CONTEXT.md) land?

| Option | Description | Selected |
|--------|-------------|----------|
| New "Things the schemas do not tell you" bullet | Same section as the `fitness_compare_periods` date-math gotcha and the dual-anchor warning | ✓ |
| New subsection under "Decision framework" | A dedicated, more prominent single-topic subsection | |

**User's choice:** New "Things the schemas do not tell you" bullet (recommended).

### Q2: Does the doc need its own restating of PHYS-11's disclaimer framing?

| Option | Description | Selected |
|--------|-------------|----------|
| No restating needed | The required `disclaimer` field already travels every call, same posture as `RecompositionResult.disclaimer` | ✓ |
| Add one line anyway | An extra explicit reminder in the tool table row | |

**User's choice:** No restating needed (recommended).

**Notes:** Both answers took the recommended option. Recorded as D-05 and D-06 in CONTEXT.md.

---

## Claude's Discretion

- **PHYS-08 supersede mechanism:** not separately discussed. Recorded as D-07 — an optional
  parameter pair on the existing write tool (`supersedes_observation_id` + `superseded_reason`),
  not a third dedicated tool, so the write-guard target of exactly two modules
  (`program_switch.py`, `physique.py`) holds.
- **Diff/cross-reference MCP exposure:** not separately discussed. Recorded as D-08 — confirmed
  internal-only, consumed by Phase 18, per ROADMAP wording and PHYS-F02's deferred status.
- Exact function names/signatures in `analytics/physique.py`, bottom-quartile computation method
  (rank-based vs. literal percentile), exact bullet wording and table placement in
  `docs/coaching-instructions.md`, and `supersedes_observation_id` validation scope.

## Deferred Ideas

None — no scope-creep attempts arose. PHYS-F02 remains deferred exactly as REQUIREMENTS.md
already records it.

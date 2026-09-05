# Phase 12: Training Programs & Confirm-Gated Write Tool - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-04
**Phase:** 12-training-programs-confirm-gated-write-tool
**Areas discussed:** Per-program thresholds, Label-matrix behavior per program, Program history & switch semantics, Write-tool confirmation & scope hardening

---

## Per-Program Thresholds

| Option | Description | Selected |
|--------|-------------|----------|
| Claude proposes, I approve | Claude drafts evidence-based Cut/Recomp bands mirroring Lean Bulk's asymmetric-conservative pattern | ✓ |
| I'll specify the numbers | User gives exact percentages | |
| Mirror Lean Bulk exactly, sign-flipped | Cut = exact sign-flip of Bulk's numbers | |

**Follow-up:** Claude proposed —
- Cut: stable ±0.10%/wk, on-target loss -0.50% to -1.00%/wk, slow loss -0.10% to -0.50%/wk, too-fast loss < -1.00%/wk, too-fast gain > +0.25%/wk
- Recomp: stable/on-target ±0.25%/wk, too-fast gain > +0.50%/wk, too-fast loss < -0.50%/wk

| Option | Description | Selected |
|--------|-------------|----------|
| Approve as proposed | Lock in both sets of numbers exactly | ✓ |
| Approve Cut, adjust Recomp | | |
| Approve Recomp, adjust Cut | | |
| Let me give different numbers | | |

**User's choice:** Approve as proposed.
**Notes:** None.

---

## Label-Matrix Behavior Per Program

| Option | Description | Selected |
|--------|-------------|----------|
| Three separate, fully explicit tables (recommended) | Each program gets its own bucket ladder + status matrix as visible data, matching the module's existing style | ✓ |
| One shared goal-relative ladder | Abstract to toward-goal/away-from-goal, parametrized per program | |

**User's choice:** Three separate, fully explicit tables.
**Notes:** Follow-up check-in — user chose "Next area" over specifying individual cell assignments themselves; those are left to planning with Bulk's table as precedent, preserving the rule that stable-or-on-target weight + positive progression signal reads as `likely_recomp_progressing` regardless of program.

---

## Program History & Switch Semantics

### Seed data

| Option | Description | Selected |
|--------|-------------|----------|
| Lean Bulk, started when I began tracking on BRETT | Seed started_on = earliest date BRETT has real training data | ✓ |
| Lean Bulk, started on a specific date I'll give | | |
| I'm not actually on Lean Bulk right now | | |

### Backdating

| Option | Description | Selected |
|--------|-------------|----------|
| Always starts today (recommended) | started_on = local today, always; no date parameter on the write tool | ✓ |
| Allow backdating with an explicit date param | | |

### Straddling

| Option | Description | Selected |
|--------|-------------|----------|
| Classify against the current program, flag the straddle (recommended) | Use active program's thresholds, add a field naming the switch date and prior program | ✓ |
| Refuse to classify, return insufficient_data | | |

**Notes:** All three recommended defaults chosen without modification.

---

## Write-Tool Confirmation & Scope Hardening

### Token TTL

| Option | Description | Selected |
|--------|-------------|----------|
| 5 minutes (recommended) | Long enough for one conversational turn, short enough to guard against stale scrollback tokens | ✓ |
| 15 minutes | | |
| I'll give a different value | | |

### Required scopes

| Option | Description | Selected |
|--------|-------------|----------|
| Leave required_scopes=None (recommended) | Token-echo confirmation is the real gate; avoids AuthKit reconfiguration and re-consent | ✓ |
| Add a required scope for the write tool now | | |

**Notes:** Both recommended defaults chosen.

---

## Claude's Discretion

- Naming of the new history table/columns and write-tool module location/filename
- Exact field names added to `RecompositionResult` for active program and straddle caveat
- The full ~24-cell status matrix per program, beyond the one preserved rule (stable/on-target
  weight + positive signal → `likely_recomp_progressing`)
- Whether the write tool's degraded-payload wording needs program-specific phrasing

## Deferred Ideas

- Backdating a program switch's start date — declined in favor of always-today
- A required-scope gate on the write tool — declined in favor of the existing token-echo gate
- Full per-cell status assignment for all three programs' matrices beyond the one preserved rule

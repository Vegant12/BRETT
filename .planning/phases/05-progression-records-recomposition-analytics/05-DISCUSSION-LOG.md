# Phase 5: Progression, Records & Recomposition Analytics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-30
**Phase:** 05-progression-records-recomposition-analytics
**Areas discussed:** Estimated 1RM: formula & trust gate, Trend & plateau sensitivity, Personal records: which sets count, Recomposition status thresholds & your goal

---

## Estimated 1RM: formula & trust gate

| Option | Description | Selected |
|--------|-------------|----------|
| Epley | 1RM = weight × (1 + reps/30). Simplest, most widely used. | ✓ |
| Brzycki | 1RM = weight × 36/(37−reps). More accurate at very low reps but breaks down above 36 reps. | |
| Average of Epley + Brzycki | Splits the difference; more complexity for marginal gain. | |
| You decide | | |

**User's choice:** Epley

| Option | Description | Selected |
|--------|-------------|----------|
| ≤12 reps | Common convention; formula error grows fast past ~12 reps. | ✓ |
| ≤10 reps | Stricter, tighter to formulas' original validated range. | |
| No cutoff | Simpler but produces misleadingly precise-looking numbers at high reps. | |

**User's choice:** ≤12 reps

| Option | Description | Selected |
|--------|-------------|----------|
| weight_reps only | The only modality where weight and reps are both real, independent numbers. | ✓ |
| weight_reps + bodyweight_weighted | More coverage, stacks an interpolated-bodyweight estimate under the 1RM estimate. | |
| You decide | | |

**User's choice:** weight_reps only

| Option | Description | Selected |
|--------|-------------|----------|
| Highest estimated 1RM that day | "Today's best effort" by strength implied, not just heaviest weight. | ✓ |
| Heaviest weight regardless of reps | Simpler, but can under-rank a lighter-but-more-reps set. | |
| You decide | | |

**User's choice:** The set with the highest estimated 1RM that day

**Notes:** Live data cited during discussion: 7167/7984 sets are `weight_reps` modality; 270 are `bodyweight_weighted`, 503 `reps_only`, ~40 duration/distance-based. This distribution came from `backend/app/db/models/exercise.py`'s column comment (verified against a full live sync).

---

## Trend & plateau sensitivity

| Option | Description | Selected |
|--------|-------------|----------|
| 4 weeks minimum | Short enough for frequent feedback, still averages out noise. | ✓ |
| 6 weeks minimum | More conservative, slower to flag real problems. | |
| You decide | | |

**User's choice:** 4 weeks minimum

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed 4-week window for every exercise | Simple, consistent regardless of training frequency. | |
| Adaptive: N sessions of that exercise, not N weeks | Ties the window to actual training frequency per exercise. | ✓ |
| You decide | | |

**User's choice:** Adaptive: N sessions of that exercise, not N weeks

| Option | Description | Selected |
|--------|-------------|----------|
| No new estimated-1RM PR in the window | Ties plateau detection to the same 1RM estimate PROG-01/PROG-04 compute. | |
| No new weight PR at the same or higher reps | Stricter, formula-independent. | |
| You decide | | ✓ |

**User's choice:** You decide (Claude's discretion — resolved toward the est-1RM-based definition for consistency, since the following question about the session-count threshold already assumed it)

| Option | Description | Selected |
|--------|-------------|----------|
| 4 sessions | Matches the 4-week trend-classification minimum. | ✓ |
| 6 sessions | More conservative, fewer false plateau flags. | |
| You decide | | |

**User's choice:** 4 sessions

---

## Personal records: which sets count

| Option | Description | Selected |
|--------|-------------|----------|
| Include dropset + failure (exclude only warmup) | A to-failure set or dropset's heaviest portion is a real effort. | ✓ |
| Normal sets only | Cleanest, most conservative definition. | |
| You decide | | |

**User's choice:** Include dropset + failure (exclude only warmup)

| Option | Description | Selected |
|--------|-------------|----------|
| The earliest date the value was first reached | Standard "when did I first hit this" convention. | ✓ |
| The most recent date the value was reached | "When did I most recently confirm I can still do this." | |
| You decide | | |

**User's choice:** The earliest date the value was first reached

---

## Recomposition status thresholds & your goal

| Option | Description | Selected |
|--------|-------------|----------|
| Lean bulk (slow weight gain, build muscle) | Want strength/muscle up with minimal fat gain. | ✓ |
| Cut (fat loss, preserve strength) | Want weight down while training performance holds. | |
| Recomp / maintenance | Weight roughly stable, want strength up. | |

**User's choice:** Lean bulk (slow weight gain, build muscle)

| Option | Description | Selected |
|--------|-------------|----------|
| Percent of bodyweight per week | Standard evidence-based framing, scales with the person. | ✓ |
| Fixed kg/week | Simpler mental model but doesn't scale if bodyweight changes. | |
| You decide | | |

**User's choice:** Percent of bodyweight per week

| Option | Description | Selected |
|--------|-------------|----------|
| >0.5%/week | Common lean-bulk guideline. | |
| >0.25%/week | Stricter — flags a moderate bulk pace as too fast. | ✓ |
| You decide | | |

**User's choice:** >0.25%/week (weight_gain_too_fast threshold)

| Option | Description | Selected |
|--------|-------------|----------|
| >1%/week | Standard "too fast" cut threshold, reused as a general safety bound. | ✓ |
| >0.5%/week | Tighter, earlier warning. | |
| You decide | | |

**User's choice:** >1%/week (weight_loss_too_fast threshold)

| Option | Description | Selected |
|--------|-------------|----------|
| Weight trend sets direction, progression trend refines the label | Keeps weight as primary signal, strength as tiebreaker. | |
| Require BOTH signals to agree before a confident verdict | Stricter, fewer confident verdicts. | |
| You decide | | ✓ |

**User's choice:** You decide (Claude's discretion — CONTEXT.md leans toward "weight trend sets direction, progression refines" as the working default, with the exact aggregation rule left open for research/planning)

---

## Claude's Discretion

- Exact "no progress" plateau metric edge cases (how a `null`-estimated-1RM week counts toward the plateau streak)
- How PROG-02's trend aggregates into BODY-02's label (which/how many exercises' trends count)
- CMP-01 period comparison scope (which metrics beyond "normalized per week")
- BODY-01 rolling-average behavior with data gaps, and its own insufficient-data threshold
- Exact Pydantic schema shapes and module/file layout within `app/analytics/`

## Deferred Ideas

None — discussion stayed within phase scope.

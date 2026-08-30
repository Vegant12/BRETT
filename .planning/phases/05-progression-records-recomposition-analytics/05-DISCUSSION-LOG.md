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

- ~~Exact "no progress" plateau metric edge cases~~ — resolved 2026-08-30, see Critical Review below
- How PROG-02's trend aggregates into BODY-02's label (which/how many exercises' trends count) — still open
- CMP-01 period comparison scope (which metrics beyond "normalized per week") — still open
- ~~BODY-01 rolling-average behavior with data gaps, and its own insufficient-data threshold~~ — resolved 2026-08-30, see Critical Review below
- Exact Pydantic schema shapes and module/file layout within `app/analytics/` — still open

## Deferred Ideas

None — discussion stayed within phase scope.

---

## Critical Review (2026-08-30, before planning)

Before handing this phase to planning, the user asked for three of the locked decisions to be
critically re-examined — not preserved by default — prioritizing "reliable, deterministic,
explainable coaching analytics" over consistency with the original discussion. Instructed to
review canonical references and Phase 4 patterns first (blueprint §21/§25/§26,
`04-CONTEXT.md`, `app/analytics/schemas.py`/`metadata.py`) before answering.

### 1. Plateau detection — verdict: MODIFY

**Original (D-06/D-07):** adaptive session-count window (no calendar floor); a session "breaks"
the streak only by exceeding the strict all-time-max estimated 1RM; no stated handling for
sessions with a `null` estimate.

**Problems identified:**
- No noise tolerance — a lifter bouncing within ~1% of their peak (normal session variance) would
  be flagged as "no progress" purely by the exact-max test.
- Pure session-count adaptivity gives absurdly short windows for high-frequency exercises: 4
  sessions of a 3×/week bench press is ~9–13 days, far below blueprint §21's own "3–6 weeks."
- Undefined handling of `null`-e1RM sessions (high-rep weeks, non-`weight_reps` modality) risked
  falsely inflating the streak for anyone periodizing rep ranges.

**Resolved into:** D-06 (session count + 3-week calendar floor, whichever needs more evidence),
D-07 (2% tolerance band via `PLATEAU_IMPROVEMENT_TOLERANCE`), D-07a (null-e1RM sessions skipped,
neither extending nor breaking the streak), D-07b (report `recent_performance`/`historical_best`/
`confidence` per blueprint §21's return shape, not a bare boolean).

### 2. Bodyweight rolling averages — verdict: MODIFY (formalizing what was pure discretion)

**Original:** left entirely to Claude's discretion with only a pointer to Phase 4's coverage
pattern; no coverage floor, no interpolation stance, no same-day multi-source rule.

**Resolved into:** D-13 (no interpolation — actual measured rows only), D-14 (prefer `'manual'`
over `'hevy'` on a same-day collision), D-15 (independent per-window coverage floor: 7d≥3,
14d≥5, 30d≥10 measured days), D-16 (weekly rate of change = smoothed 4-week trend, not a
single-week delta), D-17 (surface the raw single-week delta too, as a secondary field, never used
for classification).

### 3. Lean-bulk weight thresholds — verdict: MODIFY (values kept, measurement basis replaced)

**Original (D-11/D-12):** `weight_gain_too_fast` > +0.25%/week, `weight_loss_too_fast` > −1%/week,
implicitly evaluated off blueprint §25's single most-recent-week delta.

**Problem identified:** a single week-over-week delta is dominated by water retention and
glycogen swings — large enough on its own to trip these percentage thresholds on pure noise,
independent of any real trend.

**Resolved into:** the numeric targets in D-11/D-12 are unchanged (they were reasonable sustained
rates, not the flaw); both are now evaluated against D-16's smoothed 4-week trend rate instead of
a single week's delta.

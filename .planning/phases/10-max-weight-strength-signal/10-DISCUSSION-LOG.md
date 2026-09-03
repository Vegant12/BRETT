# Phase 10: Max-Weight Strength Signal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 10-max-weight-strength-signal
**Areas discussed:** Plateau definition, insufficient-data gating, dead-band basis, disagreement
surfacing (all four asked under the original, pre-reversal scope) — superseded mid-session by a
scope reversal, followed by field-scope and field-semantics questions under the corrected scope.

---

## Round 1 — questions asked under the original scope (max weight as primary classifier)

These four questions were asked before the scope reversal surfaced. The plateau-definition answer
is what revealed the reversal; the other three became moot once the reversal was confirmed, but are
recorded here for the audit trail.

### Plateau Definition

| Option | Description | Selected |
|--------|-------------|----------|
| Reps-at-flat-weight breaks the streak (Recommended) | A max-weight plateau means "no PR" broadly — same weight for more reps resets the streak | |
| Only a weight increase breaks the streak | Plateau strictly means "you haven't added load" | |
| You decide | Planner picks based on live-data calibration | |

**User's answer (free text, not a listed option):** "Yes keep the current setting, what i refer to
'max weight' is that Claude uses last max weight lifted in its output (explanation) but the BRETT
system still uses e1RM as the progress indicator."

**Notes:** This answer revealed the user's actual intent was fundamentally narrower than the
question's framing assumed — see "Scope Reversal" below.

### Insufficient Data

| Option | Description | Selected |
|--------|-------------|----------|
| Keep the same week-count floor only (Recommended) | MIN_TREND_WEEKS=4 stays the sole gate | ✓ |
| Add a new gate for max weight specifically | Fresh insufficiency rule for the new classifier | |
| You decide | Planner works it out against live data | |

**User's choice:** "Keep the same week-count floor only (Recommended)"
**Notes:** Became moot once the reversal was confirmed — there is no new classifier, so no new
insufficient-data question exists.

### Band Basis

| Option | Description | Selected |
|--------|-------------|----------|
| Percentage-based, re-tuned (Recommended) | Keep the % style, recalibrate against max-weight data | |
| Increment-based | Tolerance tied to real plate/stack steps | |
| You decide | Planner picks per live-data calibration | |

**User's choice:** "lets stay as is, do not alter this"
**Notes:** In hindsight, this was an early signal of the reversal — the user did not want the
existing bands touched at all. Became fully moot once the reversal was confirmed.

### Disagreement Surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Just the two verdicts/rates as sibling fields (Recommended) | ExerciseTrend carries both signals as fields; Claude infers the disagreement itself | ✓ |
| Add an explicit computed disagreement flag | A boolean/label field set when verdicts differ | |

**User's choice:** "Just the two verdicts/rates as sibling fields (Recommended)"
**Notes:** Became moot — there is no second classifier to disagree with the first.

---

## Scope Reversal Checkpoint

Claude flagged that the Plateau Definition answer contradicted REQUIREMENTS.md (STR-01/02/04),
ROADMAP.md's Phase 10 goal, and PROJECT.md's locked v2.0 decision — all of which said max weight
should *replace* e1RM as the classifier. Asked directly which the user wanted:

| Option | Description | Selected |
|--------|-------------|----------|
| Max weight drives classification (as currently required) | Verdicts computed from max weight; e1RM becomes the secondary field | |
| e1RM keeps classifying; max weight is display-only | Classification unchanged; max weight only appears in Claude's explanatory output | ✓ |
| Something else | User describes a different intent | |

**User's choice:** "e1RM keeps classifying; max weight is display-only"

**Follow-up:** Claude asked for explicit confirmation to rewrite ROADMAP.md, REQUIREMENTS.md, and
PROJECT.md to match, rather than writing a CONTEXT.md that would contradict them.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, rewrite them to match (Recommended) | Claude rewrites Phase 10 goal/SC, STR-01/02/04, and the locked decision row | ✓ |
| No — stop here, I need to think about it | Pause without touching any files | |

**User's choice:** "Yes, rewrite them to match (Recommended)"

**Result:** ROADMAP.md, REQUIREMENTS.md, and PROJECT.md were rewritten in this session (see each
file's 2026-09-03 changes) before CONTEXT.md was written, so nothing downstream reads a
contradiction.

---

## Round 2 — questions asked under the corrected scope

### Field Scope

After investigating what's actually reachable through MCP tools (`ExerciseTrend` is never
exposed standalone; `fitness_get_exercise_progression` already returns `best_weight_kg` per day),
Claude presented the finding and asked where the display field should actually land:

| Option | Description | Selected |
|--------|-------------|----------|
| Only PlateauResult gets a max-weight field (Recommended) | The one response type with no real weight figure today | ✓ |
| PlateauResult, and also wire it into the aggregate recomposition/summary response | Bigger surface; requires picking one exercise to represent the whole account | |

**User's choice:** "Only PlateauResult gets a max-weight field (Recommended)"

### Which Weight

| Option | Description | Selected |
|--------|-------------|----------|
| Most recent training day in the window (Recommended) | Literal "last weight lifted," regardless of e1RM-streak qualification | ✓ |
| Most recent session inside the current plateau streak | Consistent with the response's other e1RM-derived fields, but can show an older weight on a deload week | |

**User's choice:** "Most recent training day in the window (Recommended)"

---

## Claude's Discretion

- Exact field name and docstring wording on `PlateauResult`
- Whether a companion `no_max_weight_reason`-style field is warranted vs. a bare `None`
- Whether `records.py`'s `PersonalRecordType.MAX_WEIGHT` docstring needs a disambiguating
  cross-reference now that `PlateauResult` also carries a weight figure

## Deferred Ideas

- Wiring a max-weight figure into `fitness_get_recomposition_status`/`fitness_get_training_summary`
  — explicitly declined; would require designing which exercise represents the whole account
- A new standalone per-exercise trends MCP tool exposing `ExerciseTrend` — mentioned only as
  context for why `ExerciseTrend` is currently unreachable, not requested

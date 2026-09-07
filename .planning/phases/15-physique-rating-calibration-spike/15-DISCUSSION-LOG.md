# Phase 15: Physique Rating Calibration Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-07
**Phase:** 15-physique-rating-calibration-spike
**Areas discussed:** Photo readiness & timing, Sample design & rigor, What the spike's constants govern

---

## Gray areas presented (not all selected)

| Area | Selected? |
|---|---|
| Spike execution mechanics | No — folded into Sample design's blindness question (D-06) |
| Photo readiness & when this runs | Yes |
| Sample design & rigor | Yes |
| What the spike's constants actually govern | Yes |

---

## Photo readiness & timing

### Q: Do you have real progress photos ready to use for this spike, and when should it actually run?

| Option | Description | Selected |
|--------|-------------|----------|
| Ready now, run it live in a future session | Photos attached when the plan's execution reaches that step, plan pauses there | ✓ |
| Not ready — plan needs a real checkpoint | Explicit human-in-the-loop gate that can sit open across sessions | |
| I'll describe conditions, no literal new photos | Reuse existing images already natural to share | |

**User's choice:** Ready now, run it live in a future session.

### Q: How should the photo(s) physically reach the rating calls without touching the repo?

| Option | Description | Selected |
|--------|-------------|----------|
| Session scratchpad only | Saved to session's private scratchpad, gitignored by construction, discarded at session end | ✓ |
| You keep photos on your machine, give me a local path | No copy into scratchpad at all | |

**User's choice:** Session scratchpad only.

---

## Sample design & rigor

### Q: How many distinct real photo-sets should the spike use?

| Option | Description | Selected |
|--------|-------------|----------|
| One photo-set, rated repeatedly | Any movement across calls IS the noise/drift signal | ✓ |
| Two photo-sets from different times | Sanity-checks response to genuinely different photos, ~2x work | |

**User's choice:** One photo-set, rated repeatedly.

### Q: How many blind repeat calls, and how many steps in the anchored "ratchet" chain?

| Option | Description | Selected |
|--------|-------------|----------|
| 5 blind + 5 anchored steps | Enough for a distribution/trend without an expensive spike | ✓ |
| 3 blind + 3 anchored | Minimal, less statistical confidence | |
| 10 blind + 10 anchored | More confidence, more time/cost | |

**User's choice:** 5 blind + 5 anchored steps.

### Q: How many of the 19 canonical muscle groups should actually get rated per call?

| Option | Description | Selected |
|--------|-------------|----------|
| Representative subset (~5) | Mixes easy/subtle groups without 19x call cost | ✓ |
| All 19 | Most rigorous, most expensive | |

**User's choice:** Representative subset (~5).

### Q: Should each blind rating be a fully isolated subagent call?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — isolated Agent() calls per blind rating | Blindness structurally guaranteed by context isolation | ✓ |
| No — same conversation, instructed to rate fresh | Blindness only a prompting convention | |

**User's choice:** Yes — isolated Agent() calls per blind rating.

---

## What the spike's constants actually govern

### Q: Given PHYS-09 locks the diff to plain ordinal comparison, what should the spike's findings have authority to change?

| Option | Description | Selected |
|--------|-------------|----------|
| Only the two open constants | Elapsed-time floor + PHYS-01 anchor wording refinement; level count and ordinal-only diff stay locked | ✓ |
| Full authority to push back on locked requirements | Evidence could override the milestone-gate decision | |
| Document only, no recommendations on locked items | Any revision happens in a separate conversation later | |

**User's choice:** Only the two open constants.

### Q: If the spike finds a real self-reinforcing ratchet, what should the record say happens next?

| Option | Description | Selected |
|--------|-------------|----------|
| Document as an accepted, monitored risk | Instruction-level mitigation (derive from photo, treat prior as sanity check) — no schema change | ✓ |
| Recommend promoting PHYS-F01 from deferred to in-scope | Build the elapsed-time floor now | |
| Flag as a blocker requiring another discuss-phase | Pause Phase 16 pending re-discussion | |

**User's choice:** Document as an accepted, monitored risk.

### Q: How should the spike's recommended values be expressed in the record?

| Option | Description | Selected |
|--------|-------------|----------|
| Named constants with concrete values | Matches recomposition.py's RECOMP_LOOKBACK_WEEKS pattern, copy-pasteable | ✓ |
| Prose recommendations only | Phase 16/17 planning derives constants later | |

**User's choice:** Named constants with concrete values.

---

## Claude's Discretion

- Exact prompt wording for rating subagents and the anchored-chain "prior observation" framing.
- Which specific ~5 muscle groups get rated.
- Layout/structure of the spike record's tables (matching 13-SPIKE-RESULT.md's rigor).
- Spike execution mechanics beyond the confirmed blind-call isolation (D-06) — the isolated-
  Agent()-call design proposed during gray-area presentation was adopted as the working approach
  since the user did not select it as a separate topic to deep-dive.

## Deferred Ideas

None — discussion stayed within phase scope.

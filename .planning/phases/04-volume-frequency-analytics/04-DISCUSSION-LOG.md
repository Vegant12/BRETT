# Phase 4: Volume & Frequency Analytics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-30
**Phase:** 04-volume-frequency-analytics
**Areas discussed:** Dumbbell tonnage convention, Time windows & week boundary, Direct/indirect volume shape, Insufficient-data thresholds

---

## Dumbbell Tonnage Convention

| Option | Description | Selected |
|--------|-------------|----------|
| ×2 for two-handed work | Tonnage reflects true total load moved (weight_kg × reps × 2), using equipment_category='dumbbell' as the discriminator | |
| Raw weight_kg × reps, no correction | Matches Hevy's own stored number exactly; understates true tonnage for two-handed dumbbell sets | ✓ |

**Follow-up:** How should single-arm/unilateral dumbbell exercises (no structured Hevy flag, only title signals it) be told apart from two-handed ones, to avoid double-counting under a ×2 rule?

| Option | Description | Selected |
|--------|-------------|----------|
| Curated exception list by title | Reuse exercise_map.py's title-matching pattern (already used for the deltoid split) to exclude known single-arm titles from the ×2 correction | ✓ (initially) |
| Skip tonnage for ambiguous dumbbell exercises | Only report tonnage for equipment with no laterality ambiguity; dumbbell tonnage returns null until curated | |

**Contradiction caught and resolved:** the user picked "no correction" for the main tonnage question and "curated exception list" for the follow-up — but an exception list has nothing to except from if no correction is ever applied. Asked directly which was intended:

| Option | Description | Selected |
|--------|-------------|----------|
| No correction anywhere — raw only | weight_kg × reps for every exercise, dumbbell included; no exception list needed; keeps tonnage consistent with Phase 5's per-limb estimated-1RM input | ✓ |
| ×2 for two-handed, exception list for single-arm | Reinstates the original pairing | |

**User's choice:** Raw `weight_kg × reps` everywhere. No dumbbell correction factor, no unilateral exception list (D-01).
**Notes:** The deciding factor was consistency with Phase 5's estimated-1RM formula, which models one limb's load — a doubled dumbbell tonnage number would be a different unit than the 1RM input.

---

## Time Windows & Week Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Calendar week, Monday start | ISO-8601 / Postgres date_trunc('week', ...) default | ✓ |
| Calendar week, Sunday start | US-convention week; requires an explicit offset | |
| Rolling 7-day window ending today | No fixed boundary; "week of Aug 10" becomes meaningless as a label | |

**User's choice:** Calendar week, Monday start, computed in the user's local timezone (Asia/Jakarta default per FOUND-03).
**Notes:** Matches `app/core/time.py::local_week_start()`, already implemented in Phase 1.

| Option | Description | Selected |
|--------|-------------|----------|
| Arbitrary start/end date range | get_training_frequency(start, end); Phase 5's CMP-01 and Phase 6's MCP tools will need arbitrary ranges regardless | ✓ |
| Fixed preset windows only (7/14/30/90-day) | Matches BODY-01's rolling-average presets; simpler surface | |

**User's choice:** Arbitrary start/end date range (D-03).

---

## Direct/Indirect Volume Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Raw counts + weighted total | direct_sets/indirect_sets unweighted, plus weighted_sets via apply_weights() | ✓ |
| Raw counts only, no blend | direct_sets/indirect_sets only; caller does any weighting math | |
| Weighted total only | One weighted_sets number per muscle; loses the raw split VOL-02 asks for | |

**User's choice:** Raw counts + weighted total (D-04).

---

## Insufficient-Data Thresholds

| Option | Description | Selected |
|--------|-------------|----------|
| Fewer than 2 sessions in-window | 1 session can't show a trend or a real weekly rate | ✓ |
| Window coverage shortfall | Flag based on data coverage of the requested window vs. actual synced history | |
| Both, as separate flags | Track session sparsity and window-coverage shortfall independently | |

**User's choice:** Fewer than 2 sessions touching the metric in-window (D-05).

**Follow-up (multiSelect):** What fields belong in the coverage/uncertainty metadata block?

| Option | Description | Selected |
|--------|-------------|----------|
| sessions_in_window (count) | Named explicitly in ROADMAP.md's Phase 4 success criteria | ✓ |
| insufficient_data (bool) | The flag itself, derived from the D-05 threshold | ✓ |
| requested_window (start/end echoed back) | Useful once Phase 6 exposes this over MCP | |
| earliest_data_at (oldest synced session) | Lets Claude distinguish "no training" from "history doesn't reach back that far" | ✓ |

**User's choice:** `sessions_in_window`, `insufficient_data`, `earliest_data_at` (D-06). `requested_window` not included.

---

## Claude's Discretion

- Exact Pydantic/dataclass shape of the analytics module's public return types
- Module location/naming under `backend/app/` (e.g. `app/analytics/`)
- Golden fixture workout design (hand-authored vs. derived from the 327 real synced workouts)
- Which `sync_state.resource` row(s) feed a given response's freshness metadata
- Whether a `local_week_bounds()` companion to `local_day_bounds()` lives in `core/time.py` or the new analytics module

## Deferred Ideas

- `requested_window` echo in coverage metadata — not selected, reconsider if Phase 6 needs it
- Per-dumbbell ×2 tonnage correction and its unilateral-exercise exception list — considered and explicitly rejected in favor of raw tonnage everywhere; the curated-title-list pattern remains available if a future milestone wants "true total load" reporting

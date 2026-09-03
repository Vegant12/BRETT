# Phase 10: Max-Weight Strength Signal - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Claude can cite the actual last weight the user lifted when explaining why an exercise is
flagged as plateaued. `PlateauResult` (`fitness_get_plateaus`) gains one new secondary display
field carrying that figure. **Trend and plateau classification stay exactly as they are today —
driven entirely by estimated-1RM.** No new classifier, no dead-band re-derivation, no change to
`recomposition.py`, no change to `ExerciseTrend` or `fitness_get_exercise_progression`.

This is a significant narrowing from how the phase was originally scoped in ROADMAP.md/
REQUIREMENTS.md before this discussion — see "Scope Reversal" below. That narrowing is itself
the main decision this session produced.

</domain>

<decisions>
## Implementation Decisions

### Scope Reversal (the central decision of this session)

- **D-01:** Estimated-1RM continues to drive `ExerciseTrend.verdict`, `PlateauResult.plateaued`,
  and `recomposition.py`'s progression input — unchanged from today, in every respect. The
  original phase scope (roadmap/requirements as written before 2026-09-03) had max-weight-lifted
  *replacing* e1RM as the primary classifier, with e1RM demoted to secondary. The user reversed
  this directly: "what i refer to 'max weight' is that Claude uses last max weight lifted in its
  output (explanation) but the BRETT system still uses e1RM as the progress indicator."
- **D-02:** Because the classifier's input never changes, none of the calibration work the
  original scope required applies: no dead-band re-derivation (was flagged as needing live-data
  calibration with no answer on paper — PITFALLS #12), no re-thinking of insufficient-data
  semantics under near-100%-coverage max weight (PITFALLS #11), no before/after verdict
  distribution recording for `recomposition.py` beyond a confirmation check (see SC#3).
- **D-03:** `progression.py`'s existing docstring arguing against max-weight-as-classifier
  (lines 7-10, the Epley rep-progression argument) does **not** need to be "answered" the way
  the original PITFALLS #10 guidance required — its argument was against replacing e1RM's
  classification role, and that replacement isn't happening. The docstring stays fully correct
  and unmodified.
- **ROADMAP.md, REQUIREMENTS.md (STR-01–STR-04), PROJECT.md** (goal text, target-features bullet,
  Active requirements bullet, and the Key Decisions table row) were all rewritten in this session
  to match this reversal, so they no longer contradict this file. See each file's 2026-09-03 edit.

### Field Scope (second decision, made after investigating what's actually reachable via MCP)

- **D-04:** `ExerciseTrend` (PROG-02's per-exercise trend verdict) is never exposed through any
  MCP tool — it only feeds the aggregate whole-account `progression_signal`/`progression_verdict`
  in `fitness_get_recomposition_status` and `fitness_get_training_summary`. Adding a max-weight
  field to it would be dead weight nothing reads. **Do not touch `ExerciseTrend`.**
- **D-05:** `fitness_get_exercise_progression` (PROG-01) already returns `best_weight_kg` per
  training day on every point. "Am I progressing on bench press?" is already answerable with the
  last weight lifted today, with zero code changes. **Do not touch `ExerciseProgressionResult`.**
- **D-06:** The only response type with a genuine gap is `PlateauResult` — every field on it
  today (`recent_performance_kg`, `historical_best_kg`, `threshold_percent`) is e1RM-derived, so
  there is no real weight figure Claude can cite when explaining *why* something is flagged
  plateaued. **This is the one and only field this phase adds.**

### Field Semantics

- **D-07:** The new field's value is the most recent *training day* for that exercise inside the
  lookback window — `series[-1].best_weight_kg` after `get_plateaus`'s existing ascending-by-
  `local_day` sort — **not** the most recent session that qualified for the e1RM plateau streak.
  These can genuinely differ (a deload or high-rep week breaks e1RM-streak membership but is
  still real, recent training), and the user explicitly chose the literal "last weight you
  lifted" reading over the streak-consistent one.
- **D-08:** Reuse `progression.py`'s existing `_NO_WEIGHT_RANK` sentinel handling so a bodyweight
  or duration-only exercise's most recent day (where `weight_kg` is `None`) reports the new field
  as `None` with a reason attached, never a literal `0 kg` presented as a real observation — same
  honesty rule the module already applies elsewhere (D-04's tie-break, `no_estimate_reason`).
- **D-09:** Source the figure from the existing `best_set_per_day` fold — `SessionBest` already
  computes `best_weight_kg` for every session, including the ~17% of exercise-sessions with no
  e1RM-qualifying set. No new query, no new fold, no second "best set" rule.

### Claude's Discretion

- Exact field name on `PlateauResult` (e.g. `last_max_weight_kg`), its docstring wording, and
  whether a `no_max_weight_reason`-style companion field is warranted or a bare `None` is
  sufficient given the surrounding fields' patterns — follow `schemas.py`'s existing conventions
  for mutually-exclusive value/reason pairs (`ProgressionPoint.estimated_1rm_kg` /
  `no_estimate_reason` is the precedent).
- Whether `records.py`'s existing `PersonalRecordType.MAX_WEIGHT` (all-time best, exposed via
  `fitness_get_personal_records`) needs any docstring cross-reference now that `PlateauResult`
  also carries a max-weight figure — they answer different questions ("ever" vs "most recently")
  and should stay distinct, but a one-line disambiguation note in whichever docstring is written
  second would help a future reader.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase boundary (this file supersedes their original Phase 10 framing)
- `.planning/ROADMAP.md` §"Phase 10: Max-Weight Strength Signal" — goal, success criteria, and
  planning notes rewritten 2026-09-03 to match this context; carries the full history of the
  scope reversal in its notes
- `.planning/REQUIREMENTS.md` §"Strength Tracking" (STR-01–STR-04) — rewritten 2026-09-03
- `.planning/PROJECT.md` — Current Milestone goal, "Target features" bullet, "Active" requirements
  bullet, and the Key Decisions table (the superseded row is struck through and kept for history,
  immediately followed by the current row) — all rewritten 2026-09-03
- `.planning/STATE.md` — Accumulated Context → Decisions and Blockers/Concerns sections updated
  2026-09-03 with the reversal and a new open item about Phase 12's stale dependency rationale

### Code this phase touches or must not regress
- `backend/app/analytics/progression.py` — `best_set_per_day`/`SessionBest` (source of the new
  field, D-04's `_NO_WEIGHT_RANK` sentinel), `scan_plateau`/`get_plateaus` (where the new field
  is populated, must not touch `PLATEAU_IMPROVEMENT_TOLERANCE`/`PLATEAU_MIN_QUALIFYING_SESSIONS`/
  `PLATEAU_MIN_ELAPSED_DAYS`/`DEFAULT_PLATEAU_LOOKBACK_WEEKS` or any classification logic), and
  the module's own docstring (lines 7-10) arguing against max-weight-as-classifier — still
  correct, do not edit
- `backend/app/analytics/schemas.py` — `PlateauResult` (where the new field is added),
  `ProgressionPoint.estimated_1rm_kg`/`no_estimate_reason` (the value/reason pattern precedent)
- `backend/app/mcp/tools/progression.py` — `fitness_get_plateaus`, `_degraded_plateaus` (the
  degraded-response constructor must also be updated for the new field)
- `backend/app/analytics/recomposition.py` — must remain untouched by this phase; confirm (not
  assume) its progression input is still e1RM-based per SC#3
- `backend/app/analytics/estimates.py` — `estimate_1rm`, `E1RM_EXERCISE_TYPE`, `NoEstimateReason`
  — unchanged, but read for the value/reason convention this phase's new field should follow

### Historical research (context for why the original scope existed — not implementation instructions)
- `.planning/research/PITFALLS.md` #10 (max-weight-as-classifier rejected by v1.0's own docstring
  evidence), #11 (max weight is ungated, insufficient-data semantics), #12 (dead-band
  recalibration) — all three describe problems that no longer arise under this phase's actual
  scope; kept for the next person who wonders why the phase was originally bigger
- `.planning/research/ARCHITECTURE.md` §3 "Max-weight-lifted as primary strength signal" — same
  caveat; describes the original (superseded) design, not this one

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SessionBest.best_weight_kg` (`progression.py`) — already computed for every session by
  `best_set_per_day`, including sessions with no e1RM-qualifying set. This is the entire data
  source for the new field; no new query is needed.
- `_NO_WEIGHT_RANK` sentinel pattern (`progression.py`) — the existing mechanism for ranking a
  missing weight below every real one, including a genuine `Decimal("0.000")`. The new field's
  None-vs-zero handling should follow the same reasoning, not reinvent it.
- `get_plateaus`'s existing ascending-by-`local_day` sort of each template's in-window series —
  the last element after that sort is exactly D-07's "most recent training day."

### Established Patterns
- Mutually-exclusive value/reason field pairs (`ProgressionPoint.estimated_1rm_kg` /
  `no_estimate_reason`) — the repo-wide convention for "here is the number, or here is why there
  isn't one." The new field should follow this shape rather than a bare nullable.
- Every analytics response echoes the parameters/thresholds that produced it as fields, never as
  documentation-only claims (`PlateauResult` already does this for `threshold_percent`,
  `min_sessions`, `min_elapsed_days`, `lookback_start`, `lookback_end`).

### Integration Points
- `backend/app/mcp/tools/progression.py::fitness_get_plateaus` is the only MCP-facing surface
  that needs a change — it already passes `PlateauResult` through via `report.exercises` with no
  field-by-field reconstruction, so a new field on the Pydantic model should flow through
  automatically; `_degraded_plateaus`'s hand-built fallback response is the one place that needs
  an explicit new value (`None`).

</code_context>

<specifics>
## Specific Ideas

No specific UI/output-phrasing examples were given beyond the general intent: Claude should be
able to name an actual weight (not just an e1RM-derived figure) when explaining a plateau
verdict. No particular sentence template was requested.

</specifics>

<deferred>
## Deferred Ideas

- **Wiring a max-weight figure into the aggregate recomposition/summary responses**
  (`fitness_get_recomposition_status`, `fitness_get_training_summary`) — considered and explicitly
  declined during discussion. Those responses are whole-account aggregates; picking a single
  exercise's weight to represent the whole account is a new design question the user did not want
  opened in this phase.
- **A new standalone per-exercise trends MCP tool** that would expose `ExerciseTrend` directly —
  came up only as context for why adding a field to `ExerciseTrend` would currently be unreachable,
  not as a request. Not scoped into this phase; would be a new capability for a future phase if
  ever wanted.

</deferred>

---

*Phase: 10-max-weight-strength-signal*
*Context gathered: 2026-09-03*

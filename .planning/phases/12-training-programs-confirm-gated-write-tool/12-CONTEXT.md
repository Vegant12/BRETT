# Phase 12: Training Programs & Confirm-Gated Write Tool - Context

**Gathered:** 2026-09-04
**Status:** Ready for planning

<domain>
## Phase Boundary

The user's active training program (Lean Bulk, Cut, or Recomp) becomes real, effective-dated
data instead of `recomposition.py`'s five hardcoded Lean Bulk constants. Recomposition verdicts
and recommendations classify against the active program's own thresholds. Exactly one narrow,
confirm-gated MCP write tool lets the program be switched — a genuine two-step confirmation
(server-issued one-time token, not a `confirm: bool`), with every other MCP tool remaining
provably read-only.

**Stale roadmap dependency, resolved:** `ROADMAP.md`'s "Depends on: Phase 10 (recomposition
thresholds settle once, not twice)" no longer applies. Phase 10 was rescoped during its own
discuss-phase session to a display-only max-weight field and never touched
`recomposition.py` or its threshold constants (see `10-CONTEXT.md` D-01–D-03). This phase is the
first and only place the recomposition thresholds are touched — nothing settled twice.

</domain>

<decisions>
## Implementation Decisions

### Per-Program Thresholds

- **D-01:** Lean Bulk's existing constants stay unchanged: stable band ±0.10%/wk,
  on-target gain 0.10–0.25%/wk, too-fast gain >0.25%/wk, too-fast loss < -1.00%/wk.
- **D-02:** Cut's thresholds (new, approved as proposed):
  - Stable band: ±0.10%/wk (same shared dead-band width as Lean Bulk)
  - On-target loss: -0.50% to -1.00%/wk (standard sustainable cut pace)
  - Slow loss (off-target, not dangerous): -0.10% to -0.50%/wk
  - Too-fast loss (danger — muscle-loss risk): faster than -1.00%/wk
  - Too-fast gain (danger — tracking/adherence problem): faster than +0.25%/wk
- **D-03:** Recomp's thresholds (new, approved as proposed):
  - Stable/on-target band: ±0.25%/wk (wider than Bulk/Cut — no directional goal, so more
    week-to-week noise is expected and should not be misread as a trend)
  - Too-fast gain: faster than +0.50%/wk (drifting into bulk territory)
  - Too-fast loss: faster than -0.50%/wk (drifting into cut territory)

### Label-Matrix Design

- **D-04:** Each program gets its own fully explicit bucket-ladder + status matrix (three
  separate tables), not one shared "goal-relative" abstraction. This matches the module's
  existing stated philosophy in `recomposition.py` — data tables over nested ifs, every
  combination visible in one place, a missing branch fails loud (`zip(..., strict=True)`) rather
  than silently falling through. Do not build a generic toward-goal/away-from-goal abstraction
  that all three programs share; write three tables.
- **D-05:** Bulk's existing bucket ladder is asymmetric (fine-grained on the gain side:
  on-target-gain vs too-fast-gain; coarse on the loss side: one "losing" catch-all) because gain
  is the goal. Cut's ladder mirrors this — fine-grained on the loss side (on-target-loss vs
  slow-loss vs too-fast-loss per D-02), coarse on the gain side (any gain beyond stable reads as
  one "gaining" catch-all until the too-fast-gain danger line). Recomp's ladder has no privileged
  direction — symmetric on both sides.
- **D-06 (Claude's discretion, precedent given):** The exact status assigned to each of the
  ~24 cells per program's table is left to planning, following Bulk's existing table as the
  precedent. In particular: preserve the existing rule that a stable-or-on-target weight
  combined with a POSITIVE progression signal reads as `likely_recomp_progressing` — this is a
  physiological observation (losing fat or holding steady while strength rises), not a
  goal-adherence judgment, so the same rule should generally hold across all three programs'
  tables where the shape allows it. No new `RecompositionStatus` enum member is being added —
  the existing seven values (blueprint 26's fixed set) are reused across all three programs'
  matrices.

### Program History & Switch Semantics

- **D-07:** Model as append-only, effective-dated history (`program_periods` or similar —
  naming left to planning), not a mutable `users.active_program` column, per PITFALLS #16. The
  switch tool closes the current period and opens a new one.
- **D-08:** Seed the initial history row as Lean Bulk, with `started_on` set to the earliest
  date BRETT has real training data for this user (found from the synced Hevy history at
  migration/seed time, not an arbitrary or today's date) — so the seed period reflects when
  training under this program actually began, not when the schema was added.
- **D-09:** The confirm-gated switch tool always starts the new period on the local today (per
  `_common.local_today`); it does not accept a backdated `started_on`. Simpler tool schema (no
  date parameter the model could get wrong), and matches the tool's narrow scope — switching, not
  correcting history. If backdating is ever needed, it is a future capability, not this phase's.
- **D-10:** When `get_recomposition_status`'s 12-week lookback window straddles a program switch,
  classify against the CURRENT (active) program's thresholds for the whole window, but surface a
  field naming the switch date and the prior program so Claude can caveat the verdict
  ("this mixes 3 weeks of Cut with 9 weeks of Lean Bulk data") rather than silently
  misrepresenting it. Do not refuse to classify / return `insufficient_data` for a straddled
  window — SC#2 requires reporting the fact, not hiding the verdict.

### Write-Tool Confirmation & Scope

- **D-11:** Confirmation token TTL is 5 minutes.
- **D-12:** `required_scopes` stays `None`, unchanged from today. The token-echo confirmation
  (PITFALLS #13) is the real gate; a scope the server never varies behaviour on is a claim, not a
  control, per the existing in-code rationale at `server.py`'s `required_scopes=None` comment.
  Do not add a WorkOS AuthKit scope reconfiguration or re-consent flow to this phase. The
  in-code note "Revisit when the first write tool ships" is explicitly NOT being acted on this
  phase — leave the note in place for a future phase to reconsider, e.g. if a second write tool
  is ever added.
- All other write-tool mechanics follow `PITFALLS.md` #13–#16 exactly as written (server-issued
  single-use token bound to the exact target state, `confirmation_token: str` not
  `confirm: bool`, atomic consume-in-same-transaction, three-state `applied`/`not_applied`/
  `unknown` result, narrow single-module write allowlist in `test_mcp_isolation.py`, own
  `ToolAnnotations` registered outside the `_TOOLS`/`READ_ONLY` loop) — see Canonical References.

### Claude's Discretion

- Exact naming of the new history table/columns, the write-tool module's filename and location
  (`app/services/programs.py` or `app/db/repositories/` per PITFALLS #14's guidance — not
  `app/analytics/`), and the exact field name(s) added to `RecompositionResult` for the active
  program and the straddle caveat (D-10) — follow `schemas.py`'s existing conventions.
- The full ~24-cell status matrix per program (D-06) beyond the one preserved rule.
- Whether the write tool's three-state result and degraded-payload wording need any
  program-specific phrasing, or can be fully generic.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition
- `.planning/ROADMAP.md` §"Phase 12: Training Programs & Confirm-Gated Write Tool" — goal,
  success criteria, and planning notes (token-based gate, append-only history, three-state
  result, tool registered outside the shared loop, all cited PITFALLS numbers)
- `.planning/REQUIREMENTS.md` §"Training Programs" (GOAL-01–GOAL-04)
- `.planning/PROJECT.md` — Current Milestone "Target features" bullet on training programs, the
  "Training programs" Active requirement bullet, and the Key Decisions table row on the
  confirm-gated write tool's two-call token design

### Pitfalls this phase exists to avoid — read in full, not just the summary
- `.planning/research/PITFALLS.md` #13 (`confirm=true` is not a gate — the token design) — the
  phase's defining success criterion
- `.planning/research/PITFALLS.md` #14 (adding one write tool disarms the guards protecting the
  other thirteen — the four-mechanism table and how each is narrowed, not weakened)
- `.planning/research/PITFALLS.md` #15 (`safe_tool` swallows write failures — the three-state
  result requirement)
- `.planning/research/PITFALLS.md` #16 (mutable active-program column retroactively rewrites
  history — the effective-dated modelling requirement, directly informs D-07/D-10)

### Superseded/resolved context from prior phases
- `.planning/phases/10-max-weight-strength-signal/10-CONTEXT.md` — confirms Phase 10 never
  touched `recomposition.py`; the stale "Depends on: Phase 10" roadmap note (see Phase Boundary
  above) traces back to this file's D-01–D-03

### Code this phase touches or must not regress
- `backend/app/analytics/recomposition.py` — the five hardcoded constants (lines ~60-90),
  `_WeightBucket`, `_weight_bucket`, `_MATRIX_ROWS`, `_LABEL_MATRIX`, `classify_recomposition`,
  `get_recomposition_status` — all become program-parametrized per D-01–D-06, D-10
- `backend/app/analytics/schemas.py` — `RecompositionResult`, `RecompositionStatus` (seven
  values, no new member per D-06), `ProgressionSignal`
- `backend/app/mcp/server.py` — `_TOOLS` loop, `READ_ONLY` annotations, `required_scopes=None`
  (D-12: leave as-is), the write tool must be registered OUTSIDE this loop with its own
  `ToolAnnotations`
- `backend/app/mcp/tools/_common.py` — `read_only_session`, `safe_tool`, `local_today` (D-09's
  "today" source) — a new `writable_session` sibling is needed per PITFALLS #14, must not modify
  `read_only_session` itself
- `backend/app/mcp/auth.py` — `AccessToken.scopes`, `AuthKitJWTVerifier` — read for context on
  D-12's decision, not modified by it
- `backend/app/db/models/user.py` — the `users` table; the new program-history table is a
  sibling, not a column added here
- `backend/app/db/repositories/` (`sync_state.py`, `workouts.py`) — existing repository pattern
  to follow for the new program-history repository/service
- Test files (read for the guard patterns to extend, not to relax): the isolation/read-only
  guard suite referenced throughout PITFALLS #14 (single-module write allowlist,
  `test_every_tool_is_annotated_read_only` exact-partition assertion)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_common.local_today` — already the sanctioned "what day is it" read; D-09's switch-always-
  starts-today rule uses this directly, no new date logic needed.
- `_common.safe_tool` — reused by the write tool per PITFALLS #15, with a three-state
  `degraded()` factory rather than a new exception-handling pattern.
- Existing repository pattern (`app/db/repositories/sync_state.py`, `workouts.py`) — the
  program-history repository/service should follow the same shape.
- `RecompositionResult`'s existing field style (required fields, no optional-by-omission) —
  the new active-program and straddle-caveat fields should follow the same convention.

### Established Patterns
- Data-table-over-nested-ifs for classification logic (`_MATRIX_ROWS`/`_LABEL_MATRIX`,
  `zip(..., strict=True)`) — D-04 explicitly continues this pattern rather than introducing a
  parametrized abstraction.
- Mutually-exclusive value/reason field pairs, and "every response echoes the parameters that
  produced it" (`PlateauResult`'s window/threshold fields) — precedent for how the straddle
  caveat (D-10) and the active-program field should be surfaced.
- Guards narrowed via explicit single-module allowlists rather than relaxed (`test_mcp_isolation.py`
  pattern already used for `test_mcp_uses_no_raw_sql_text`'s `ping.py` exemption) — the model for
  PITFALLS #14's write-tool allowlist.

### Integration Points
- `app/mcp/server.py`'s `_TOOLS` tuple and `for _fn, _description in _TOOLS` loop — the write
  tool is registered separately, immediately after this loop, not inside it.
- `get_recomposition_status` is the sole consumer of the per-program thresholds; no other module
  currently reads the five constants being replaced.

</code_context>

<specifics>
## Specific Ideas

No particular tool-output phrasing was requested beyond what's captured in the decisions above
(e.g. the straddle caveat's example wording in D-10 is illustrative, not a literal string
requirement).

</specifics>

<deferred>
## Deferred Ideas

- **Backdating a program switch's start date** — considered and declined (D-09). Every switch
  starts today; correcting history is a future capability if ever needed.
- **A required-scope gate on the write tool** — considered and declined (D-12) in favor of
  leaving `required_scopes=None`. Revisit if a second write tool is ever added, per the existing
  in-code note.
- **Full per-cell status assignment for all three programs' matrices** — not worked out in this
  session beyond the one preserved rule (D-06); left to planning with Bulk's table as precedent.

</deferred>

---

*Phase: 12-training-programs-confirm-gated-write-tool*
*Context gathered: 2026-09-04*

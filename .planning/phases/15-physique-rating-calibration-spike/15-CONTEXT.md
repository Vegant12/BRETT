# Phase 15: Physique Rating Calibration Spike - Context

**Gathered:** 2026-09-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 15 is a pure research/measurement spike — no production code, no schema, no MCP surface.
It measures how much a Claude-produced 5-level ordinal muscle-development rating moves across
repeated **blind** calls on an unchanged real photo set (test-retest noise), and across an
**anchored** chain where each call is fed the previous call's rating as "prior observation"
context (testing whether PHYS-07's anchoring mitigation causes a self-reinforcing ratchet). The
deliverable is a decision record — same evidentiary shape as
`.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md`
— that Phase 16 (schema) and Phase 17 (analytics) treat as locked constants. Phase 16's schema
work does not start until this record exists (ROADMAP success criterion #4).

</domain>

<decisions>
## Implementation Decisions

### Photo Readiness & Timing
- **D-01:** The user has real progress photos ready. The spike runs live in a **future session**
  during this phase's plan execution — the plan must include an explicit step that pauses and
  asks the user to attach/provide the photo(s) at that point. Do not assume photos are already
  available when planning starts.
- **D-02:** Photos reach the rating calls via this session's private scratchpad directory only —
  never committed to the repo, never referenced in planning docs beyond the ephemeral scratchpad
  path, and discarded when the session ends. This applies the project's "BRETT never stores an
  image" posture (see PROJECT.md milestone-gate decisions) to the spike itself, not just to
  production code.

### Sample Design & Rigor
- **D-03:** One real photo-set (e.g., front/back/side from the same real session) is rated
  repeatedly — not multiple photo-sets from different times. Since nothing changes between
  calls, any rating movement observed IS the noise/drift signal being measured.
- **D-04:** 5 independent **blind** repeat ratings of the same unchanged photo-set, plus a
  5-step **anchored** chain where each call is fed the previous call's rating as "prior
  observation" context — mirroring exactly how PHYS-07 will work in production.
- **D-05:** A representative subset of ~5 of the 19 `CanonicalMuscleGroup` values gets rated per
  call, not all 19 — e.g. chest, lats, biceps, abs, side_delts, mixing easy-to-assess and
  subtle/ambiguous groups to keep the spike tractable while still exercising different
  assessability profiles. Exact picks are Claude's discretion at execution time.
- **D-06:** Each blind rating is a fully isolated subagent (`Agent` tool) call with its own
  fresh context, reading only the photo file from the scratchpad. Blindness is structurally
  guaranteed by context isolation — not a prompting convention Claude could get wrong by
  half-remembering the conversation. The anchored chain, by contrast, deliberately feeds each
  step's prompt the previous step's rating output as explicit "prior observation" text.

### What the Spike's Constants Govern
- **D-07:** The spike's findings have authority ONLY over two open constants: (a) a recommended
  minimum-elapsed-time floor, and (b) confirming or refining PHYS-01's anchor wording. PHYS-01's
  5-level count and PHYS-09's pure-ordinal-diff design (no arithmetic beyond ordinal comparison)
  stay locked regardless of findings — the spike works within already-decided requirements, it
  does not reopen them.
- **D-08:** If the spike finds a real self-reinforcing ratchet in the anchored chain, the record
  documents it as an **accepted, monitored risk** and recommends an instruction-level mitigation:
  Claude should derive each rating primarily from the photo itself, treating the prior
  observation as a sanity check rather than a target to converge toward. This recommendation
  belongs in the eventual write-tool description and/or `docs/coaching-instructions.md` (Phase
  17/18 territory) — it is documentation/instruction-level only. It does NOT trigger: a schema
  or write-tool design change, promoting PHYS-F01 (the elapsed-time floor) out of deferred
  status, or blocking Phase 16 pending another discuss-phase.
- **D-09:** Recommended values are expressed as **named constants with concrete values and
  rationale** in the spike record — matching `backend/app/analytics/recomposition.py`'s
  `RECOMP_LOOKBACK_WEEKS`/`RECOMP_PROGRESSION_NET_BAND` pattern (a comment explaining why, then
  the literal value) — e.g. a documented `PHYSIQUE_MIN_ELAPSED_DAYS` value. Phase 16/17 should be
  able to copy these directly rather than re-deriving values from prose.

### Claude's Discretion
- Exact prompt wording given to each rating subagent, and how the anchored-chain prompt frames
  "prior observation" text, as long as it faithfully mirrors what PHYS-07's production read tool
  will eventually return.
- Which 5 (or so) muscle groups specifically get rated (D-05) — pick a mix of visually obvious
  and genuinely ambiguous groups.
- Layout/structure of the spike record's tables, as long as it matches `13-SPIKE-RESULT.md`'s
  evidentiary rigor (dated, verdict stated, raw model output quoted, reasoning shown).
- "Spike execution mechanics" as a topic was not separately selected for deep discussion by the
  user; the isolated-`Agent()`-call design proposed during gray-area presentation is adopted as
  the working approach, consistent with D-06's explicit confirmation for the blind condition.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & requirements definition
- `.planning/ROADMAP.md` (Phase 15 section, "Physique Rating Calibration Spike") — the phase
  goal, depends-on, and the four success criteria this plan must satisfy
- `.planning/REQUIREMENTS.md` — PHYS-12 (this phase's requirement); PHYS-01, PHYS-07, PHYS-09
  (locked requirements this spike works within, per D-07); PHYS-F01 (the deferred elapsed-time
  floor referenced in D-08)
- `.planning/PROJECT.md` — "Shape decided at the milestone gate" bullets (no photo storage,
  Claude-as-analyst, anchoring mitigation) and the "v2.1 milestone-gate decisions" table in
  `.planning/STATE.md`

### Precedent to mirror
- `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md`
  — the exact evidentiary format (dated table, verdict, raw quoted output, reasoning) this
  phase's spike record must match
- `backend/app/analytics/recomposition.py` (`INTERPRETATION_DISCLAIMER`, `RECOMP_LOOKBACK_WEEKS`,
  `RECOMP_PROGRESSION_NET_BAND`) — the named-constant-with-rationale-comment pattern D-09's output
  constants must follow

### Taxonomy
- `backend/app/normalization/muscles.py` (`CanonicalMuscleGroup`) — the 19-value enum to pick the
  representative ~5-group subset (D-05) from

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None directly reusable — no `app/analytics/physique.py` or physique schema exists yet (that's
  Phase 16/17). This phase produces no `backend/` code changes.

### Established Patterns
- Named module-level constants with a rationale comment above the value, never a bare magic
  number (`recomposition.py`'s `RECOMP_LOOKBACK_WEEKS`, `RECOMP_MIN_CLASSIFIED_EXERCISES`) — the
  pattern D-09's recommended constants should follow.
- Required, verbatim-travelling disclaimer/definition constants (`INTERPRETATION_DISCLAIMER`) —
  the same posture PHYS-01's anchor wording and PHYS-11's disclaimer will eventually take.
- Spike-record-as-audit-trail (`13-SPIKE-RESULT.md`): dated table with Client/Tool
  called/Verdict fields, raw quoted model output, and a "Reading" paragraph connecting evidence
  to conclusion — no vague "seems fine," always a specific artifact quoted.

### Integration Points
- Phase 16's schema constants (rating-level wording, any elapsed-day floor field) and Phase 17's
  `analytics/physique.py` constants both consume whatever named constants this spike's record
  proposes — this phase is the sole upstream input for those two phases' numeric/wording
  decisions.

</code_context>

<specifics>
## Specific Ideas

No additional "I want it like X" references beyond the decisions above — the user selected the
recommended option at every branch point during discussion.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No scope-creep attempts arose during this
discussion.

</deferred>

---

*Phase: 15-physique-rating-calibration-spike*
*Context gathered: 2026-09-07*

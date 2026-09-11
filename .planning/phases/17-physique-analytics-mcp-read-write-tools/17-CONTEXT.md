# Phase 17: Physique Analytics & MCP Read/Write Tools - Context

**Gathered:** 2026-09-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 17 delivers the MCP surface and the deterministic analytics underneath it: a single-call,
append-only write tool (`fitness_log_physique_observation`) and a read tool
(`fitness_get_latest_physique_observation`) built directly on Phase 16's
`backend/app/db/repositories/physique.py`, plus `analytics/physique.py` (per-muscle diff and a
volume cross-reference) and the write-guard suite amendments (MCP-07, MCP-08) that make the
system a truthful two-write-module one. No MCP tool for the diff or cross-reference themselves —
per ROADMAP's phase goal wording ("analytics exist underneath") and PHYS-F02's deferred status,
those two functions are consumed by Phase 18's monthly report composition, not called directly by
Claude this phase.

**User's steering for this discussion:** of four surfaced gray areas, the user chose to discuss
two — the volume cross-reference's concrete definition (PHYS-10) and where the Phase 15 anti-
ratchet instruction lands in `docs/coaching-instructions.md` — and left two to Claude's discretion
(the PHYS-08 supersede mechanism, and confirming the diff/cross-reference stay MCP-tool-free).
Both discretionary areas are still recorded below as named decisions with rationale, following
Phase 16's precedent, so the researcher and planner do not have to re-derive or silently assume
either one.

</domain>

<decisions>
## Implementation Decisions

### Volume Cross-Reference Definition (PHYS-10)
- **D-01:** "Underdeveloped" means `rating_level` in `{Minimal, Emerging}` — the bottom two of the
  five `PHYSIQUE_RATING_LEVELS`. **Rationale:** matches the ordinal scale's own bottom-half
  meaning with no new threshold to justify or defend later.
- **D-02:** "Undertrained" is self-relative, not an absolute floor: among the user's own 19
  muscle groups' `weighted_sets` over a 12-week window (reusing `RECOMP_LOOKBACK_WEEKS` from
  `recomposition.py` rather than inventing a second lookback constant), the bottom quartile counts
  as undertrained. **Rationale:** consistent with this milestone's own no-population-comparison
  ethos — PHYS-01 already forbids rating a muscle relative to anyone but this same person, and an
  absolute "sets per week" floor would be exactly the kind of external, defended-forever number
  that ethos exists to avoid on the volume side too. It also needs no separate literature citation
  the way a hardcoded sets/week minimum would.
- **D-03:** A muscle group rated `Not Assessable` is excluded entirely from the underdeveloped
  side of the join before crossing with volume — a group can't be called underdeveloped with no
  rating for it. It still participates normally in the volume-side bottom-quartile computation
  (that math is pure `weighted_sets`, unrelated to the rating). **Rationale:** keeps "the rating
  says X" and "the volume says Y" as two independently true facts rather than inventing a third
  bucket for the common case (`abductors`/`adductors` most of the time).
- **D-04:** The cross-reference function returns the flagged list only — muscle groups where
  underdeveloped AND undertrained both hold — not a full per-muscle table of every group's level
  and quartile side by side. **Rationale:** answers PHYS-10's literal question directly and
  matches this project's established pattern of narrow, purpose-built response shapes (e.g.
  `MAX_REPORT_PR_HIGHLIGHTS`) over one large dump Claude would have to re-derive the same
  conclusion from itself.
- **Claude's Discretion:** the exact function name/signature in `analytics/physique.py`, and
  whether "bottom quartile" is computed by rank (e.g. bottom ~5 of 19 by `weighted_sets`) or by a
  literal 25th-percentile cut — both satisfy D-02's self-relative framing; pick whichever composes
  more simply with the existing `MuscleGroupVolumeResult` shape.

### `docs/coaching-instructions.md` Wording (PHYS-07's anti-ratchet instruction)
- **D-05:** The Phase 15 spike's D-08 anti-ratchet instruction — derive each rating primarily
  from the photo itself, treat the prior observation as a sanity check rather than a target to
  converge toward — lands as a new bullet under the existing "Things the schemas do not tell you"
  section, in the same register as the `fitness_compare_periods` date-math gotcha and the report
  tools' dual-anchor warning. **Rationale:** it is the same category of fact ("here's what goes
  wrong if you don't know this"), not a role/objective statement, and the doc has no other
  single-topic subsection today that a new "Decision framework" entry would need to match.
- **D-06:** No separate restating of PHYS-11's "subjective model output, not measurement" framing
  is added to the doc. **Rationale:** the required `disclaimer` field already travels to Claude on
  every call — the same posture `RecompositionResult.disclaimer` already ships under, with no
  coaching-instructions.md echo today. A second copy in the doc would be redundant with a field
  whose entire purpose is to make documentation-only framing unnecessary.
- **Claude's Discretion:** exact bullet wording, and where in the "Which tool answers which
  question" table the two new physique rows sit (logically near `fitness_get_recomposition_status`
  and the report tools, which already synthesize across data sources, seems like the natural
  neighborhood but is not load-bearing).

### PHYS-08 Supersede Mechanism (Claude's Discretion, made explicit)
- **D-07:** Marking an earlier observation superseded is an optional parameter pair on the same
  `fitness_log_physique_observation` write tool — e.g. `supersedes_observation_id` +
  `superseded_reason`, both `None` by default — not a third dedicated tool.
  **Rationale:** ROADMAP's success criterion #6 for this phase targets `_WRITE_ALLOWLIST ==
  {"program_switch.py", "physique.py"}` with `len == 2` exactly. A dedicated supersede tool would
  itself need to write (it sets `superseded_at`/`superseded_reason`/`superseded_by_id` on an
  existing row), which would make it a third module touching the write guard — directly
  contradicting the two-module target this phase's own test assertions are written against.
  Folding it into the existing single-call write path keeps PHYS-06's "one write tool" framing
  literally true while still satisfying PHYS-08's "a later observation can mark an earlier one
  superseded" requirement: the later observation's own logging call is what does the marking.
- **Claude's Discretion:** whether `supersedes_observation_id` is validated against
  `get_latest_observation`'s result (i.e. can only supersede the current latest) or any prior
  observation id belonging to the user — the planner should pick whichever keeps
  `_read_observation`'s existing tenant-scoped lookup as the validation path rather than adding a
  new one.

### Diff/Cross-Reference MCP Exposure (Claude's Discretion, made explicit)
- **D-08:** `get_physique_diff` and the PHYS-10 cross-reference function are internal
  `analytics/physique.py` functions only, with no MCP tool wrapping either one this phase.
  **Rationale:** ROADMAP's Phase 17 goal statement says this analytics "exist[s] underneath"
  Claude's log/retrieve loop, and PHYS-F02 (an ad-hoc `fitness_get_physique_history`/diff read
  tool) is explicitly deferred in REQUIREMENTS.md's Future Requirements, reasoned there as
  "the monthly report plus PHYS-07's prior-observation read may already cover it." Phase 18 is the
  named consumer (its own ROADMAP entry: "needs `analytics/physique.py`'s diff and cross-reference
  functions to compose against").

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & requirements definition
- `.planning/ROADMAP.md` (Phase 17 section, "Physique Analytics & MCP Read/Write Tools") — the
  six success criteria this phase's plan(s) must satisfy verbatim, including the exact
  `_WRITE_ALLOWLIST`/`EXPECTED_WRITE_ANNOTATIONS` target state named in criterion #6
- `.planning/REQUIREMENTS.md` — PHYS-06 through PHYS-11, MCP-07, MCP-08 (this phase's
  requirements); PHYS-F02 (the deferred read tool D-08 relies on to justify no new MCP surface)
- `.planning/PROJECT.md` — "Shape decided at the milestone gate" bullets (Claude-as-analyst,
  read-only guard amended never relaxed, ratings-are-subjective-output posture) and the "v2.1
  milestone-gate decisions" table in `.planning/STATE.md`

### Locked constants and prior-phase decisions (copy verbatim, do not re-derive)
- `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` — `PHYSIQUE_RATING_LEVELS`,
  `PHYSIQUE_RATING_ANCHORS`, `PHYSIQUE_MIN_ELAPSED_DAYS`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA`; also the
  source of D-05's anti-ratchet instruction (its own D-08 finding)
- `.planning/phases/16-physique-data-model-repository/16-CONTEXT.md` — the full schema/repository
  shape this phase builds directly on top of; D-07's "always 19 rows, one level XOR one reason"
  invariant is what `get_physique_diff` relies on to avoid a three-state ambiguity

### Precedent to mirror
- `backend/app/mcp/tools/program_switch.py` — the ONLY existing write-tool precedent: module
  docstring states which write-guard tests target it by name, `@safe_tool`/`writable_session`
  usage, and how a tool documents itself as the module `_WRITE_ALLOWLIST` names. `physique.py`'s
  MCP tool module should carry an equivalent docstring naming MCP-07/MCP-08 by requirement ID.
- `backend/app/mcp/tools/_common.py` — `writable_session` (the only writable session helper;
  D-07's new physique write tool becomes its second caller), `safe_tool`, `resolve_user_id`,
  `local_today`. This module's own docstring already anticipates "exactly one tool module opens
  it" needing an update once a second write module exists.
- `backend/tests/test_mcp_isolation.py` (`_WRITE_ALLOWLIST`, `test_mcp_never_writes`,
  `test_the_write_allowlist_holds_exactly_one_module`, `test_only_one_module_opens_a_writable_session`)
  — MCP-07's exact target: widen `_WRITE_ALLOWLIST` to `frozenset({"program_switch.py",
  "physique.py"})`, `len == 2`, and update every test whose name/assertion currently says "exactly
  one" to say "exactly two" — four assertions across two test files per REQUIREMENTS.md's own count
- `backend/tests/test_mcp_tool_schemas.py` (`WRITE_TOOLS`, `test_annotations_are_an_exact_partition`,
  `test_the_write_tool_publishes_explicit_write_annotations`) — MCP-08's exact target: replace the
  uniform `destructiveHint=True`/`idempotentHint=False` assertion over `read_only_false` with a
  per-tool `EXPECTED_WRITE_ANNOTATIONS` mapping, since `fitness_log_physique_observation` must
  assert `destructiveHint=False` (non-destructive, per PHYS-06) distinctly from
  `fitness_switch_training_program`'s `destructiveHint=True`
- `backend/app/db/repositories/physique.py` — `create_observation`, `get_latest_observation`,
  `RatingEntry`, `PhysiqueObservationRecord`. Note `get_latest_observation`'s own docstring: it
  does NOT filter `superseded_at IS NULL` today — "when Phase 17 adds supersede-aware reads, this
  predicate is the thing it changes." This phase must add that filter (or an equivalent) as part
  of implementing PHYS-08's "excluded from diffs" requirement.
- `backend/app/analytics/volume.py` (`get_muscle_group_volume`, `MuscleGroupVolumeResult`,
  `MuscleGroupVolume`) — the function and schema PHYS-10's cross-reference joins against;
  `weighted_sets` is the field D-02's bottom-quartile computation reads
- `backend/app/analytics/recomposition.py` (`RECOMP_LOOKBACK_WEEKS`, `INTERPRETATION_DISCLAIMER`)
  — the 12-week window D-02 reuses, and the required-disclaimer-field pattern PHYS-11 follows
- `docs/coaching-instructions.md` — the "Which tool answers which question" table and "Things the
  schemas do not tell you" section D-05 adds a bullet to; match the existing bullet register
  exactly (declarative, one gotcha per bullet, bolded lead phrase)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/db/repositories/physique.py` (Phase 16) — `create_observation` and
  `get_latest_observation` are ready to call from the new MCP tool module with no repository
  changes needed for the write/read path itself; only the supersede-aware filter (D-08's
  requirement) touches this file
- `backend/app/mcp/tools/_common.py` — `writable_session`, `safe_tool`, `resolve_user_id`,
  `local_today` all apply directly; no new cross-cutting helper appears to be needed
- `backend/app/analytics/volume.py::get_muscle_group_volume` — already returns exactly the
  per-muscle-group `weighted_sets` data PHYS-10 needs; no new volume query required, only a new
  composed function that calls it and joins against physique ratings

### Established Patterns
- `program_switch.py` is the only precedent for a write-tool module's required docstring
  contract (which write-guard test names it, which helper it must NOT import) — `physique.py`'s
  new MCP tool module should open with an equivalent statement naming MCP-07/MCP-08
- `safe_tool`'s `degraded` factory pattern (a callable, not a static value, so the placeholder is
  built fresh per failure) — the physique write tool's degraded response needs the same shape,
  with its own `PhysiqueLogStatus`-style enum analogous to `ProgramSwitchStatus.UNKNOWN`
- `truncate()` / capped-response-with-`was_truncated`-and-`total_available` pattern — likely not
  needed here since the write tool returns one observation and the read tool returns at most one
  prior observation, but worth checking if the cross-reference's flagged list (D-04) should still
  carry a cap given only 19 muscle groups exist total (probably not — 19 is already a hard, known
  ceiling, unlike an open-ended workout list)

### Integration Points
- The new MCP tool module (likely `backend/app/mcp/tools/physique.py`) becomes the SECOND caller
  of `writable_session` and the second entry in every write-guard allowlist/annotation mapping
  MCP-07/MCP-08 touch
- Phase 18's monthly report composition (`compose_report`) will call `analytics/physique.py`'s
  diff and cross-reference functions directly, one layer downstream of this phase — those two
  functions' signatures should be designed with that caller in mind even though Phase 18 is out of
  this phase's scope

</code_context>

<specifics>
## Specific Ideas

No additional "I want it like X" references beyond the decisions above. Both discussed areas
(volume cross-reference definition, coaching-instructions.md wording) converged on the
recommended option at every branch point; the two discretionary areas (supersede mechanism, MCP
exposure scope) are recorded as named Claude's-Discretion decisions with rationale rather than
left implicit, following Phase 16's own precedent for this situation.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No scope-creep attempts arose during this
discussion. PHYS-F02 (an ad-hoc physique history/diff read tool) remains deferred exactly as
REQUIREMENTS.md already records it; D-08 above only confirms that this phase's plan should not
quietly promote it into scope by wrapping the diff function in a new MCP tool.

</deferred>

---

*Phase: 17-physique-analytics-mcp-read-write-tools*
*Context gathered: 2026-09-11*

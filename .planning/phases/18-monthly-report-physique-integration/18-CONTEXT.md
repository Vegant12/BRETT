# Phase 18: Monthly Report Physique Integration - Context

**Gathered:** 2026-09-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 18 adds a physique section to the monthly report and to its markdown narrative, consuming
Phase 17's `analytics/physique.py` functions (`get_latest_physique_diff`,
`get_physique_volume_cross_reference`, `get_latest_observation`) without adding any new analytics
arithmetic, any new SQL, or any new MCP tool. Composition and presentation only.

The weekly report must remain structurally incapable of carrying the section — not merely omitting
it by convention. `WeeklyReportResponse` has no `physique` attribute at all, asserted via a
`hasattr`/`model_fields` check, mirroring how `narrative` is already monthly-only.

**Not in scope:** PHYS-F02's `fitness_get_physique_history` read tool, PHYS-F01's minimum-elapsed
floor enforcement, any change to how observations are written or rated, and any new analytics
function. If the report needs a number the analytics layer does not already return, that is a
signal the composition is wrong, not that a new computation belongs here.

**User's steering for this discussion:** of four surfaced gray areas the user chose three —
section content depth, narrative rendering, and thin/absent-data behaviour — and left
notes-vs-provenance to Claude's discretion. Following Phase 16/17 precedent, the discretionary
area is still recorded below as a named decision with full rationale so the researcher and planner
do not have to re-derive or silently assume it.

</domain>

<decisions>
## Implementation Decisions

### Section Content Depth (RPT-04)

- **D-01:** `PhysiqueSection` **embeds the Phase 17 analytics results whole** — a
  `PhysiqueDiffResult` field and a `PhysiqueVolumeCrossReference` field, not a flattened
  projection of their contents. **Rationale:** `ReportResult`'s own docstring states the rule this
  follows — `recomposition`, `plateau_highlights` and `measurement_highlights` are embedded whole
  precisely *because* "each of those three carries its own window in its own fields … a reader must
  be able to see that the verdict beside this week's volume is not a verdict about this week."
  That is exactly true of the cross-reference, whose 12-week volume window anchors on the
  observation's `observed_on` rather than on the report window or on today. Embedding it whole
  carries `observed_on`, `lookback_weeks`, `window_start`, `window_end` and
  `undertrained_threshold_weighted_sets` along for free; a flat projection would have to hand-carry
  them or silently drop the anchor.

- **D-02:** The report's diff is **filtered to muscle groups whose verdict is `IMPROVED` or
  `REGRESSED`** — not all 19 rows, and not including `NOT_COMPARABLE`. **Rationale:** the report
  layer already made this exact narrowing decision once, for plateaus: `_report_body_fields`
  filters `plateau_highlights` to `plateaued=True` before capping, and its inline comment explains
  why ("of the 30 exercises analysed, this many are stuck"). A monthly report is a summary; 19 rows
  of mostly-unchanged is the per-week × per-muscle grid problem that `roll_up_muscles` already
  exists to avoid. `PhysiqueDiffResult` keeps its gap-free 19-row spine intact for any direct
  caller — this is a presentation narrowing, not a change to the analytics contract.

- **D-03:** The filter runs at the **MCP layer**, not in `compose_report`.
  `ReportResult.physique` carries the diff with all 19 rows; `backend/app/mcp/tools/reports.py`
  filters it, and the existing `capped_report = report.model_copy(update={...})` in
  `fitness_get_monthly_report` is **extended** with the physique update so `build_narrative`
  narrates the same filtered list the JSON fields carry. **Rationale:** byte-identical to the
  mechanism `plateau_highlights` already uses, including the reason the `capped_report` copy exists
  at all (its inline comment: passing the uncapped report would let the narrative silently outgrow
  the caps the JSON fields enforce). It also preserves `ReportResult`'s stated "Lists are UNCAPPED
  here" rule, keeping presentation decisions out of `app/analytics/`.

- **D-04:** The report shows the **filtered diff only** — no accompanying "of 19 groups, N were
  comparable" count field. **Rationale:** the user chose the leaner shape. `plateau_highlights_total`
  exists because the scanned population is open-ended and unknowable from the response; the
  physique population is a fixed, published 19 (`CanonicalMuscleGroup`), so the denominator is
  already common knowledge to any reader of this schema.

- **D-05:** The latest observation travels as **header plus confounder metadata only** —
  `observed_on`, `pose_state`, `photo_angles_present`, `conditions_note`, and the three
  Claude-authored note fields — with **no `ratings` list**. **Rationale:** `PhysiqueDiffResult`
  already carries `later_level` for all 19 groups, so a ratings list would ship the same 19 levels
  twice in one payload. The confounder fields are kept rather than trimmed because PHYS-04's whole
  point is that "the rating changed" and "conditions were comparable" must be two independently
  inspectable facts — a rise from a relaxed front-only set to a lightly-flexed three-angle set is a
  lighting-and-pose change before it is a physique change, and only these fields can say so.

- **D-06:** The cross-reference's `flagged` list is **carried whole with no cap** — no
  `MAX_REPORT_PHYSIQUE_FLAGS`, no `was_truncated`/`total` pair. **Rationale:** Phase 17's own
  context already reasoned this ("19 is already a hard, known ceiling, unlike an open-ended workout
  list"), and `flagged` is the *intersection* of two narrow sets — underdeveloped AND bottom-rank
  volume — so it is realistically 0–5. A truncation apparatus for a list that cannot exceed 19 is
  ceremony with no failure mode behind it.

### Narrative Rendering (RPT-05)

- **D-07:** The `## Physique` block renders, in order: **one anchor line, one line per changed
  muscle group, one line per cross-reference flag, then the disclaimer.** The anchor line names
  `observed_on` and states explicitly that this section's window differs from the report period
  above — the same opening move `_program_lines` already makes ("As of {date} — a different anchor
  from the {start} to {end} period above"). **Rationale:** this is the fourth distinct anchor in a
  report whose entire design discipline is "two anchors, both named on the wire"; an unnamed fourth
  anchor is the precise failure `ReportResult`'s docstring warns about. Block length lands at ~4–8
  lines in a typical month, the same altitude as Training (~4) and Program (~4).

- **D-08:** `PHYSIQUE_RATING_DISCLAIMER` renders **once, verbatim, at the end of the block** — read
  off the embedded result, not retyped. **Rationale:** `_program_lines` already appends
  `report.recomposition.disclaimer` verbatim on its own line, and `RecompositionResult`'s docstring
  calls that field "a REQUIRED FIELD, not documentation." Both the diff and the cross-reference
  carry their own identical copy; rendering both would read as a bug. **Verified during discussion:**
  the disclaimer's text contains none of the ten `_BANNED_NARRATIVE_TOKENS`, so verbatim rendering
  is safe today.

- **D-09 (Claude's discretion, made explicit — notes vs. provenance):** **No Claude-authored
  free-text field renders in `build_narrative`.** That is all four: `leanness_notes`,
  `conditioning_notes`, `symmetry_notes` and `conditions_note`. They travel as structured JSON
  fields on `PhysiqueSection` (criterion #3 requires exactly that) and are rendered nowhere in the
  narrative. The narrative renders only dates, enum `.value`s, fixed vocabularies
  (`photo_angles_present`, `pose_state`) and numbers.

  **Additionally, `test_every_number_in_the_narrative_is_already_in_the_structured_fields` must
  exclude those four fields from the dump it checks against** — e.g.
  `report.model_dump_json(exclude={...})` — before running the substring assertion.

  **Rationale:** RPT-05 names the trap precisely: "a note's own presence in `model_dump_json()`
  would make any number inside it trivially 'provable' and defeat the numeric-provenance check."
  Not rendering the notes is necessary but *not sufficient* — once a free-text field is in the
  dump, a spurious number printed anywhere else in the narrative can be laundered through it, and
  the provenance guarantee weakens for the **whole** narrative, not just the physique block.
  Excluding the four fields from the dump closes that hole at its source. `conditions_note` is
  swept in with the three rating notes rather than treated separately because it is the same class
  of object — free text supplied by Claude on the write call — and one clean rule ("no free text in
  the narrative, no free text in the provenance dump") is more durable than two rules distinguished
  by which field the text happens to sit in.

- **D-10:** Criterion #4's word-level provenance test **reads `.value` directly off
  `report.physique`'s own fields** and asserts every rating/verdict word rendered in the block
  matches one of them. **Rationale:** the user rejected the weaker alternative — scanning against
  the `PhysiqueRatingLevel`/`PhysiqueDiffVerdict` enum classes — because that variant passes even
  when the narrative prints a level the report never held, which is the failure actually worth
  catching. This is the word-level twin of the existing numeric substring check, and criterion #4
  specifies it in those literal terms.

### Thin and Absent Data

- **D-11:** When the user has **never logged an observation**, `ReportResult.physique` is
  **`None`** — the same value the weekly report carries. **Rationale:** the user chose the simpler
  shape over a `PhysiqueSection` whose every field is nullable. The consequence is explicit and
  accepted: a `None` physique no longer proves the period was weekly, so criterion #1's structural
  test must rest entirely on the `hasattr`/`model_fields` check rather than on the value — which is
  what criterion #1 already specifies in its own wording ("a structural, tested absence via
  `hasattr`/model-field-set check, not omission by convention").

- **D-12:** When **exactly one observation exists** (so `get_latest_physique_diff` returns `None`
  but `get_physique_volume_cross_reference` still works), the section **renders, with an explicit
  line where the changes would go** — naming it as a first recorded observation with no prior to
  compare against. **Rationale:** the narrative's established rule is that a null figure renders as
  an explicit word ("not recorded", "not enough weigh-ins") and never as a bare `0` or a silent
  omission. Omitting the line would leave a reader unable to distinguish "nothing changed" from
  "nothing to compare against" — the exact ambiguity `PhysiqueDiffVerdict.NOT_COMPARABLE` exists as
  a first-class value to prevent.

- **D-13:** When `physique` is `None` on a monthly report, the **`## Physique` heading is omitted
  entirely** — no heading, no placeholder line. **Rationale:** user's choice. See the implementation
  note below: this requires a small, provably-no-op change to `build_narrative`'s loop, which
  currently appends the heading unconditionally for every applying section.

- **D-14:** The degraded path carries **`physique=None`**, added to `_degraded_monthly` exactly as
  `narrative=None` already is. **Rationale:** one more keyword on an existing call;
  `data_available=False` already communicates that the server could not look.

### Claude's Discretion

- **`build_narrative`'s empty-section mechanism (D-13's implementation).** Two viable shapes:
  (a) skip a section whose builder returns an empty list, or (b) give `_NarrativeSection` an
  optional predicate over the whole `ReportResult` rather than just the period. **Constraint the
  planner must honour either way:** the change must be provably a no-op for the seven shipped
  sections — all seven builders return at least one line for any populated report, and a test
  should assert that rather than leaving it as an observation. (a) looks simpler and adds no new
  concept; (b) is more explicit. Not load-bearing.
- **Where `PhysiqueSection` is defined.** `app/analytics/schemas.py` as an `_AnalyticsModel` is the
  natural home, since it is a field of `ReportResult` and embeds two analytics models. Whether
  `MonthlyReportResponse` reuses that same class or gets a parallel `_McpModel` view is open —
  note `_report_body_fields` already reuses analytics models directly on the wire
  (`measurements: list[BodyMeasurementTrendResult]`, `activity: ActivityPeriodSummary`,
  `plateau_highlights: list[PlateauResult]`), so reuse is the established pattern here.
- **Exact wording of every narrative line**, and the exact field names inside `PhysiqueSection`
  (beyond `physique` itself, which criterion #1 names).
- **Whether the anchor line (D-07) also surfaces `elapsed_days` against `min_elapsed_days`.** Both
  numbers are already on `PhysiqueDiffResult`, so provenance holds either way. The user did not
  select the fuller variant, so treat this as optional rather than required.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase and requirements definition
- `.planning/ROADMAP.md` (Phase 18 section, "Monthly Report Physique Integration") — the four
  success criteria this phase's plan(s) must satisfy verbatim, including criterion #1's exact
  `physique: PhysiqueSection | None` field name and its `hasattr`/model-field-set test requirement
- `.planning/REQUIREMENTS.md` — RPT-04 and RPT-05 (this phase's two requirements). RPT-05's text is
  the source of D-09's reasoning and should be read in full, not summarised
- `.planning/REQUIREMENTS.md` § Future Requirements — PHYS-F01 and PHYS-F02, both deliberately out
  of scope here; do not let a "while we're in this file" impulse pull either one in

### Prior-phase decisions this phase composes against (do not re-derive)
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/17-CONTEXT.md` — D-01 through D-04
  (what "underdeveloped" and "undertrained" mean, and why the cross-reference returns the flagged
  list only), D-08 (no MCP tool wraps the diff or cross-reference; Phase 18 is their named consumer)
- `.planning/phases/16-physique-data-model-repository/16-CONTEXT.md` — D-07's "always 19 rows, one
  level XOR one reason" invariant, which is why the diff never has to decide what a missing group
  means
- `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` —
  `PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_MIN_ELAPSED_DAYS`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` (= 2)

### The code this phase edits
- `backend/app/analytics/reports.py` — `compose_report` (the one-line period conditional goes
  here), `_NarrativeSection` and its `periods` field, `_NARRATIVE_TEMPLATE`, `build_narrative`.
  **Read the `_NarrativeSection` docstring and the `_NARRATIVE_TEMPLATE` comment first** — both name
  Phase 18's monthly-only physique section explicitly and describe the intended mechanism ("one more
  entry here plus one more builder above, editing no existing section")
- `backend/app/analytics/schemas.py` — `ReportResult` (§ "Composed, never computed", "Two anchors,
  both named", "Lists are UNCAPPED here" — all three govern D-01/D-03), `PhysiqueDiffResult`,
  `PhysiqueMuscleDiff`, `PhysiqueDiffVerdict`, `PhysiqueVolumeCrossReference`, `PhysiqueVolumeFlag`
- `backend/app/mcp/tools/reports.py` — `_report_body_fields` (the shared projection RPT-04 requires
  splitting), `_degraded_monthly`, `fitness_get_monthly_report` and its `capped_report`
  `model_copy` block (D-03 extends exactly this), `fitness_get_weekly_report`
- `backend/app/mcp/tools/schemas.py` — `_ReportBody`, `WeeklyReportResponse` (note its docstring's
  "Deliberately has NO `narrative` field" — the precedent criterion #1 mirrors),
  `MonthlyReportResponse`, `PhysiqueObservationView`, `PhysiqueRatingView`

### The code this phase consumes without changing
- `backend/app/analytics/physique.py` — `get_latest_physique_diff` (entry point; PHYS-08's
  supersede exclusion is guaranteed here by construction, and calling `get_physique_diff` with
  records fetched some other way is outside that guarantee),
  `get_physique_volume_cross_reference` (note its `observed_on` anchor, which is D-07's fourth
  anchor), `UNDERDEVELOPED_LEVELS`, `_UNDERTRAINED_BOTTOM_RANKS`
- `backend/app/db/repositories/physique.py` — `get_latest_observation`, `get_recent_observations`
  (the only `superseded_at IS NULL` predicate in the repo), `PhysiqueObservationRecord`,
  `RatingEntry`
- `backend/app/db/models/physique.py` — `PHYSIQUE_RATING_DISCLAIMER` (lines 81–85; verified free of
  banned tokens), `PhysiqueRatingLevel`, `PoseState`

### Tests that define the contract
- `backend/tests/test_analytics_reports.py` — `_BANNED_NARRATIVE_TOKENS` (the ten tokens),
  `_NUMBER_RE` and `test_every_number_in_the_narrative_is_already_in_the_structured_fields` (D-09
  amends this test), `test_the_narrative_contains_no_recommendation_language`,
  `test_the_template_declares_the_seven_sections_in_order` (its trailing assertion that *every*
  section has `periods is None` **will fail** once the physique section lands and must be updated
  in the same commit), `test_a_monthly_only_section_renders_monthly_and_is_absent_weekly` (the
  forward-designed placeholder proving the mechanism already works)
- `backend/tests/test_mcp_tool_schemas.py` — where a `hasattr`/`model_fields` assertion for
  criterion #1's structural weekly absence naturally belongs
- `backend/tests/test_analytics_isolation.py` — the static no-float guard and the
  `app.analytics` ↛ `app.mcp` import rule, both of which constrain any new code in
  `analytics/reports.py`

### Project-level posture
- `.planning/PROJECT.md` — the "ratings are subjective model output" posture and the
  Claude-as-analyst framing that D-03 (no recommendation language) enforces
- `docs/coaching-instructions.md` — the "Which tool answers which question" table and the
  physique bullets Phase 17 added; check whether the monthly report's row needs amending to
  mention the physique section

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`_NarrativeSection.periods` is already built for this.** Phase 13 forward-designed the slot:
  `backend/app/analytics/reports.py:241-246` (the `_NarrativeSection` dataclass docstring) and
  `backend/app/analytics/reports.py:437-441` (the `_NARRATIVE_TEMPLATE` comment) both name
  "Phase 18's monthly-only physique section" explicitly, and
  `test_a_monthly_only_section_renders_monthly_and_is_absent_weekly` is a **passing placeholder
  test** that already proves a monthly-only section renders for `MONTHLY` and is absent for
  `WEEKLY`. Criterion #1's narrative half is close to free.
- **`capped_report = report.model_copy(update={...})` in `fitness_get_monthly_report`** is the
  exact mechanism D-03 extends — it already exists to keep the narrative narrating the same
  filtered/capped lists the JSON fields carry.
- **`_period_summary_lines`** is the precedent for a shared builder helper; the physique builder is
  a single new function alongside `_training_lines`, `_strength_lines`, etc.
- **Phase 17's analytics functions need no changes.** `get_latest_physique_diff` and
  `get_physique_volume_cross_reference` already return exactly what the section needs, already sort
  deterministically (diff by `muscle_group.value`, `flagged` by `muscle_group.value`), and already
  carry their own windows and disclaimers.

### Established Patterns

- **`plateau_highlights` is the template for D-02/D-03 end to end:** embedded whole and uncapped on
  `ReportResult`, filtered (`plateaued=True`) and capped in `_report_body_fields`, with the
  narrative fed the filtered version via `capped_report`. Physique follows the same path minus the
  cap (D-06).
- **`narrative: str | None` on `MonthlyReportResponse` and absent from `WeeklyReportResponse`** is
  the precedent criterion #1 names for `physique`. Read `WeeklyReportResponse`'s docstring — it
  states the exclusion and the reason, which the physique version should match in register.
- **Disclaimers render verbatim, never paraphrased** — `_program_lines` appends
  `recomposition.disclaimer` on its own line.
- **Null figures render as explicit words** ("not recorded", "not enough weigh-ins"), never as a
  bare `0` and never by omission — D-12 follows this.

### Integration Points

- `compose_report` gains one period conditional and one call each to
  `get_latest_physique_diff` / `get_physique_volume_cross_reference` / `get_latest_observation`,
  inside the same session so the physique section shares the report's single consistent snapshot.
  Note this adds up to three queries to an already heavy transaction (roughly nine analytics calls,
  one of which internally runs three more) — monthly only, and `get_physique_volume_cross_reference`
  itself calls `get_muscle_group_volume` a second time over a *different* window than the report's,
  so it is not shareable with the existing call.
- `_NARRATIVE_TEMPLATE` gains an eighth entry with `periods=(ReportPeriod.MONTHLY,)`, making it the
  first period-restricted section.
- `_report_body_fields` splits: the shared part stays shared, and `physique` is added only at the
  monthly call site — the same place `narrative` is already added.

### Tripwires

- **`"try "` is a substring of `"symmetry "`.** `_BANNED_NARRATIVE_TOKENS` includes `"try "` (with
  a trailing space, added to stop `"entry "` false-positiving) and the check is a plain
  `token not in lowered`. Any narrative line rendering the word *symmetry* followed by a space
  fails `test_the_narrative_contains_no_recommendation_language`. D-09 keeps symmetry notes out of
  the narrative entirely, so this should not bite — but a future `Symmetry:` label would trip it,
  and the failure message would point at "recommendation language" rather than at the real cause.
  Worth a comment at the point of temptation.
- **`test_the_template_declares_the_seven_sections_in_order` will fail on arrival.** It asserts
  both a seven-element heading list and `all(section.periods is None ...)`. Both assertions need
  updating in the same commit that adds the section — this is expected, not a regression.
- **The word "Developed" appears in two rating levels** (`Developed`, `Well-Developed`). A
  word-level provenance test (D-10) that does naive substring matching will find `Developed` inside
  `Well-Developed`; match on whole rendered tokens, not substrings.

</code_context>

<specifics>
## Specific Ideas

- The user consistently chose the option that **reuses an existing precedent verbatim** over the
  option that adds a new concept — plateau-style filtering at the MCP layer, program-style anchor
  naming, `narrative`-style `None`-when-weekly, disclaimer-verbatim. Where the planner faces a
  choice this document does not settle, "what does the nearest shipped section already do?" is the
  tiebreaker the user has been applying.
- The user rejected the weaker form of the word-provenance test (scan against the enum classes) in
  favour of the stronger one (read `.value` off the actual report), which is consistent with this
  codebase's general posture that a test which cannot fail on the realistic bug is not worth
  writing.
- The user twice preferred the leaner payload (no 19-row spine in the report, no ratings list
  beside the diff, no cap apparatus, no comparable-count field) while keeping every field that
  carries a *caveat* (confounders, disclaimer, anchor). Honesty fields stay; redundancy goes.

</specifics>

<deferred>
## Deferred Ideas

- **`fitness_get_physique_history` / ad-hoc diff read tool** — already tracked as PHYS-F02 in
  REQUIREMENTS.md § Future Requirements. This phase's report section is part of what that
  requirement is waiting to see before being scheduled.
- **Minimum-elapsed-interval enforcement** — PHYS-F01. D-07's optional `elapsed_days` vs
  `min_elapsed_days` line *surfaces* the interval but must not refuse, flag, or caveat a
  too-close comparison; that is PHYS-F01's job and it is deferred.
- **Weekly-report physique summary of any kind** — explicitly excluded by criterion #1. If it ever
  becomes wanted, it is a new phase, and it would require unwinding the structural-absence test
  this phase adds.
- **Widening the free-text note caps** — PHYS-F04. Nothing in this phase touches the 500/200
  character limits.

</deferred>

---

*Phase: 18-monthly-report-physique-integration*
*Context gathered: 2026-09-12*

# Phase 11: Body Measurement History - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Asked how a circumference or body-composition metric has changed — not just body weight —
Claude answers from data already synced from Hevy, or honestly reports insufficient coverage.
**No manual entry write path.** This is a significant narrowing from how the phase was originally
scoped in ROADMAP.md/REQUIREMENTS.md before this discussion — see "Scope Reversal" below, which
is itself the main decision this session produced (same shape as Phase 10's own reversal).

</domain>

<decisions>
## Implementation Decisions

### Scope Reversal (the central decision of this session)

- **D-01:** BODY-03 (manual measurement write path) and BODY-04 (the per-column source-merge fix
  that path would trigger) are **dropped from Phase 11 and from v2.0 entirely** — not deferred to
  a later phase. The user's actual workflow is Hevy-only: "I dont need manual entry just need to
  get normal hevy measurements into BRETT, and allow Claude to access those measurement data."
  The user also asked directly whether Hevy's app already supports this ("Manual measurements are
  recorded through Hevy, is it not possible to obtain data through the app?") — confirmed yes.
- **D-02:** Hevy's body-measurement sync (`backend/app/integrations/hevy/body.py`,
  `upsert_body_measurement`) already writes every one of the 17 `body_measurements` columns
  (weight + 16 circumference/composition fields) on every sync, with `source='hevy'`. Phase 7
  already validated 125 real body measurements synced to production. **No ingestion-side code
  changes are needed in Phase 11** — the data this phase reports on already exists in the
  database today.
- **D-03:** Because no manual rows will ever be written under this scope, `_dedupe_by_day`'s
  row-grain "manual wins" precedence bug (PITFALLS #9) stays **dormant** — exactly as it is
  today, where zero manual rows exist. No source-precedence `MappingProxyType`, no per-column
  merge logic, no multi-source regression test. This directly reverses the roadmap's original
  "BODY-04 must ship in this phase, with BODY-03, not after" instruction and PITFALLS #9's
  "Phase to address" recommendation — both are now stale for Phase 11 and should be read as
  historical context for why the phase was originally scoped that way, not as instructions.
- **D-04:** ROADMAP.md, REQUIREMENTS.md, and PROJECT.md (Target features bullet, Active
  requirements bullet, and the Key Decisions table) were all rewritten in this session to match
  this reversal, following the same precedent Phase 10 set for its own scope reversal. BODY-03
  and BODY-04 are marked **dropped** (struck through, not silently deleted) in
  REQUIREMENTS.md's traceability table; v2.0's active requirement count moves from 28 to 26.

### Trend/Comparison Analytics Design (BODY-05 — the phase's actual remaining scope)

- **D-05:** Calculation approach is **latest reading vs. earliest reading inside a fixed 90-day
  window** — NOT BODY-01's 7/14/30-day rolling-average design. Reasoning: circumference/
  composition data is measured sporadically on real data (`waist_cm` averages roughly one
  reading per 8 days across 123 days; `fat_percent`/`lean_mass_kg` currently have **zero**
  readings at all), so BODY-01's 3/5/10-measured-day floors would return `insufficient_data`
  almost universally for anything but weight. A two-point comparison over a wider window matches
  how someone actually tracks a tape-measure metric (occasional spot checks) and produces a real,
  honest answer on today's data instead of near-permanent "not enough data."
- **D-06:** The window is a **fixed 90 days** for the latest-vs-earliest comparison — not
  all-time, not 180 days. Wide enough to usually catch 2+ real readings for an occasionally-
  tracked metric, while still reading as a "recent trend" rather than an all-time comparison.
- **D-07:** A **new, lower coverage floor** tailored to spot-check metrics is required — do not
  reuse `MEASURED_DAY_FLOORS` (3/5/10) unchanged. The floor concept (extend
  `is_measurement_insufficient`/`build_measurement_coverage`'s shape in `metadata.py`, do not
  replace it) stays the same; only the numbers differ. **Exact floor value(s) are Claude's
  Discretion** (see below) — calibrate against live data during research/planning rather than
  guessing here.
- **D-08:** The response must separately flag **staleness** — when the "latest" reading itself
  is old (e.g. a days-since-last-reading figure or boolean), distinct from "insufficient data
  entirely." Mirrors BODY-01's `earliest_measurement_at` pattern of separating "no data" from
  "data too old to trust." A metric with 2+ readings that are all months old must not be
  presented as a fresh, current comparison.
- **D-09:** Architecture is **one generic metric-parameterized analytics function + one MCP
  tool**, not 16 near-duplicate per-metric functions/result types. The metric selector must be a
  `StrEnum` (matching the repo's existing `PersonalRecordType`/`TrendVerdict`/
  `RecompositionStatus` pattern in `analytics/schemas.py`), not a free string — an unrecognized
  metric name should raise, not silently return nothing or an empty result.
- **D-10:** All 16 non-weight `body_measurements` columns are in scope: 14 circumference fields
  (`neck_cm`, `shoulder_cm`, `chest_cm`, `left_bicep_cm`, `right_bicep_cm`, `left_forearm_cm`,
  `right_forearm_cm`, `abdomen_cm`, `waist_cm`, `hips_cm`, `left_thigh_cm`, `right_thigh_cm`,
  `left_calf_cm`, `right_calf_cm`) plus `fat_percent` and `lean_mass_kg`. Matches BODY-05's
  literal "not weight-only" wording. This costs nothing extra once the generic (D-09) approach is
  built — the enum simply has 16 members.

### Claude's Discretion

- Exact numeric floor(s) for "sufficient data" on spot-check metrics (D-07) — calibrate against
  live data (waist has 15 real readings across 123 days; other metrics have far fewer or zero) in
  research/planning rather than guessing a number here. A floor of "0 readings" must never be
  treated as sufficient regardless of the final number chosen.
- Exact MCP tool name (e.g. `fitness_get_body_measurement_trend`) and its Pydantic response
  schema field names — follow the value/reason and coverage-metadata conventions already
  established in `analytics/schemas.py` and `metadata.py` (see Code Context below).
- Whether the new metric-parameterized function lives in `bodyweight.py` (renamed/extended) or a
  new sibling module — `bodyweight.py`'s module docstring is written specifically about weight
  and D-05 already declares this trend does NOT follow that module's calculation shape, so a new
  sibling module is likely cleaner, but this is a structural call for research/planning to make
  after reading both.
- Whether `fitness_get_training_summary`/`fitness_get_recomposition_status` should reference the
  new tool's existence anywhere, or stay fully standalone — leaning standalone (consistent with
  Phase 10's decision to decline wiring max-weight into aggregate responses), but not locked here.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase boundary (this file supersedes the original Phase 11 framing)
- `.planning/ROADMAP.md` §"Phase 11: Body Measurement History" — goal, success criteria, and
  planning notes rewritten 2026-09-03 to match this context; carries the full history of the
  scope reversal in its notes
- `.planning/REQUIREMENTS.md` §"Body Measurements" (BODY-03, BODY-04 marked dropped; BODY-05
  redefined) — rewritten 2026-09-03; also its Traceability table and coverage counts
  (28 → 26 active)
- `.planning/PROJECT.md` — Target features bullet, Active requirements bullet, and two new Key
  Decisions table rows (one struck-through/dropped, one for the BODY-05 design choice) — all
  rewritten 2026-09-03

### Code this phase touches or must not regress
- `backend/app/analytics/bodyweight.py` — BODY-01's structural pattern to reference (windowing
  helper shape, coverage-floor pattern, freshness embedding) but explicitly NOT to copy verbatim
  for the calculation itself (D-05 changes the calc shape). Must remain unmodified/unregressed —
  this phase adds a new, separate tool.
- `backend/app/analytics/metadata.py` — `MEASURED_DAY_FLOORS`, `build_measurement_coverage`,
  `is_measurement_insufficient`, `earliest_measurement_at` — the coverage-floor pattern to
  extend with new (lower) floor constants for spot-check metrics, not replace the existing ones
  (BODY-01's weight floors must stay untouched).
- `backend/app/db/models/body.py` — `BodyMeasurement` columns are the source of truth for the 16
  in-scope metric names and their `Numeric(6, 2)` types.
- `backend/app/integrations/hevy/body.py` — confirms ingestion already writes every column
  (D-02); nothing here changes in this phase.
- `backend/app/mcp/tools/body.py` — sibling location for the new tool; follow
  `safe_tool`/`read_only_session`/`_degraded_*` conventions exactly, matching
  `fitness_get_body_weight_trend`'s shape in the same file.
- `backend/app/mcp/tools/schemas.py`, `backend/app/mcp/tools/_common.py` — response schema and
  `MAX_*` budget-constant conventions to extend, not reinvent.
- `backend/app/analytics/schemas.py` — `StrEnum` pattern (`PersonalRecordType`, `TrendVerdict`,
  `RecompositionStatus`) to follow for the new metric-selector enum; also the mutually-exclusive
  value/reason field-pair convention (`ProgressionPoint.estimated_1rm_kg`/`no_estimate_reason`).

### Historical research (context for why the phase was originally scoped differently — not implementation instructions)
- `.planning/research/PITFALLS.md` #9 — describes the merge bug this phase would have needed to
  fix if manual entry had shipped. Now moot for Phase 11 specifically, since it stays dormant
  with zero manual rows; kept for the next person who wonders why BODY-04 existed.
- `.planning/research/PITFALLS.md` #8 — `VARCHAR(16)` source-column overflow risk for a third
  source string. Also moot here: no new source string is ever written to
  `body_measurements.source` in this phase (only `'hevy'` writes to this table; Apple Health
  writes to the separate `health_daily_metrics` table).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BodyMeasurement` model columns (`backend/app/db/models/body.py`) already carry every metric
  needed — no schema/migration change required.
- `build_measurement_coverage`/`is_measurement_insufficient` shape in `metadata.py` — extend
  with new floor constants for spot-check metrics rather than replacing the existing 3/5/10
  weight floors.
- `safe_tool`/`read_only_session`/`_common.py` MCP scaffolding — no new pattern needed; this tool
  is read-only exactly like every other Phase 6–10 tool.
- `earliest_measurement_at` (`metadata.py`) — the "no data at all" signal this phase's staleness
  concept (D-08) sits alongside, not on top of.

### Established Patterns
- `StrEnum` for closed-choice fields (`PersonalRecordType`, `TrendVerdict`,
  `RecompositionStatus` in `analytics/schemas.py`) — the pattern the new metric-selector enum
  (D-09) must follow.
- Mutually-exclusive value/reason field pairs (`ProgressionPoint.estimated_1rm_kg`/
  `no_estimate_reason`) — the new trend result should likely follow this shape for "here is the
  delta, or here is why there isn't one."
- Every analytics response echoes the parameters/thresholds that produced it as fields, never as
  documentation-only claims (`PlateauResult` does this for `threshold_percent`, `min_sessions`,
  etc.) — the new tool's window (90 days) and floor should be visible fields on the response, not
  just comments in code.

### Integration Points
- The new MCP tool sits beside `fitness_get_body_weight_trend` in
  `backend/app/mcp/tools/body.py`, registered the same read-only way in `backend/app/mcp/server.py`.

</code_context>

<specifics>
## Specific Ideas

No specific UI/output-phrasing examples were given beyond the general intent already captured in
the decisions above. The user's only explicit correction was: they do not want a manual-entry
feature — everything they track already goes through Hevy, and the ask is purely "let Claude see
the circumference/composition data that's already there."

</specifics>

<deferred>
## Deferred Ideas

- **Manual measurement entry** (formerly BODY-03) and its associated per-column source-merge fix
  (formerly BODY-04) — dropped, not deferred to a specific future phase. If a future need arises
  (e.g. adopting a scale that syncs only to Apple Health rather than Hevy, or wanting to backfill
  measurements from before the user started using Hevy), this would become its own future
  phase's scope, re-evaluated from scratch rather than resurrected as-is.
- **CLI UX decisions made before the scope reversal** — one flag per metric (vs. a generic
  `--field name=value`), CSV as the bulk-import format, and basic sanity-check validation
  (reject negative/zero weight) — were discussed and recommended-selected before the pivot.
  Captured here for the record only; **moot** unless manual entry is ever revived, in which case
  these choices are a reasonable starting point rather than something to re-litigate from zero.

</deferred>

---

*Phase: 11-body-measurement-history*
*Context gathered: 2026-09-03*

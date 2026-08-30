# Phase 4: Volume & Frequency Analytics - Context

**Gathered:** 2026-08-30
**Status:** Ready for planning

<domain>
## Phase Boundary

A deterministic, testable analytics module — living outside MCP handlers, per PROJECT.md's
Active requirements — that reads synced Hevy data (workouts, workout_exercises, workout_sets,
exercise_muscles) and answers "how much work am I doing, and which muscles is it reaching?":
weekly training volume (hard sets, reps, tonnage where the modality supports it), per-muscle-
group volume split by direct/indirect role, and training frequency per muscle group and per
exercise. Every response carries freshness metadata (from `sync_state`) and coverage/uncertainty
metadata (sessions in window, insufficient-data flag).

**Explicitly NOT this phase:** Progression/plateau/PR/recomposition analytics (Phase 5). MCP
tool exposure (Phase 6) — this phase builds the analytics functions themselves, not a wire
contract for them. Manual body-measurement/nutrition entry (separate, unscoped phase). Any
change to the muscle-mapping or weighting engine itself (Phase 3) — this phase consumes
`app/normalization/resolver.py`, it doesn't modify it.

</domain>

<decisions>
## Implementation Decisions

### Tonnage Calculation
- **D-01:** Tonnage is `weight_kg × reps` for every exercise, dumbbell included — **no
  per-dumbbell ×2 correction factor anywhere in this phase.** `docs/hevy-api-observations.md`
  confirmed `weight_kg` is per-dumbbell, not the combined pair, which raised the question of
  whether two-handed dumbbell tonnage should double it to reflect true total load. The user
  chose raw `weight_kg × reps` instead, explicitly to keep one number that also serves as the
  input to Phase 5's estimated-1RM formula (which models one limb's load, not a doubled one).
  Because no correction is applied, the curated single-arm/unilateral exception list that would
  otherwise be needed (mirroring `app/normalization/exercise_map.py`'s title-based deltoid-split
  pattern) is **not needed** — there is nothing to except from.

### Time Windows & Week Boundary
- **D-02:** Weekly volume groups sets into **calendar weeks starting Monday**, computed in the
  user's **local timezone** (`users.timezone`, default `Asia/Jakarta` per FOUND-03) — never UTC.
  This matches `app/core/time.py::local_week_start()`, which already implements exactly this
  (Monday-start ISO week) — the decision confirms existing Phase 1 code rather than requiring
  new design.
- **D-03:** Training frequency (and any other windowed analytics query) takes an **arbitrary
  start/end date range** as its parameter, not a fixed preset list (7/14/30/90-day). Chosen
  because Phase 5's `CMP-01` period comparison and Phase 6's MCP tools will both need arbitrary
  ranges regardless — building the flexible shape once now avoids redoing it later.

### Muscle-Group Volume Shape
- **D-04:** Per-muscle-group weekly volume reports **three numbers**: `direct_sets` and
  `indirect_sets` as raw, unweighted counts (matches blueprint §18's literal example), plus a
  `weighted_sets` total computed via the existing `app/normalization/resolver.py::apply_weights()`
  (default 1.0 direct / 0.5 indirect, from Phase 3 — not redecided here). Both the honest raw
  split VOL-02 asks for and the single blended "how undertrained is this muscle" number are
  present; neither is dropped in favor of the other.

### Insufficient-Data & Coverage Metadata
- **D-05:** The `insufficient_data` flag (DQ-02) trips when **fewer than 2 sessions** touch the
  metric within the requested window. One session cannot support a "per week" rate or a trend
  claim; two is the minimum for that math to mean anything. One threshold, reused across both
  volume and frequency responses.
- **D-06:** Every analytics response's coverage/uncertainty metadata block includes exactly:
  `sessions_in_window` (count), `insufficient_data` (bool, derived per D-05), and
  `earliest_data_at` (timestamp of the user's oldest synced workout) — so Claude can tell "no
  training happened in this window" apart from "your synced history doesn't reach back that
  far." An option to also echo `requested_window` (start/end) back in the metadata was
  presented and **not selected** — omit it unless a later phase needs it.

### Claude's Discretion
- Exact Pydantic/dataclass shape of the analytics module's public return types (this phase
  lives outside MCP handlers; Phase 6 builds MCP tool schemas on top of whatever this phase
  returns — CLAUDE.md's "pandas/numpy" rejection already steers toward SQL aggregates +
  dataclasses/Pydantic, not a dataframe layer).
- Module location/naming under `backend/app/` (e.g. `app/analytics/`) — no analytics package
  exists yet.
- Golden fixture workout design (success criterion 5: warm-ups, dropsets, supersets, bodyweight
  exercises) — hand-authored synthetic fixtures vs. derived from the 327 real synced workouts
  already in the database from Phase 3's live sync.
- Which `sync_state.resource` row feeds a given response's freshness metadata (DQ-01) — almost
  certainly `RESOURCE_WORKOUTS` for volume/frequency, but confirm at plan/research time whether
  a response should report the single most-stale relevant resource or a per-resource breakdown.
- Whether a `local_week_bounds()` companion to `app/core/time.py::local_day_bounds()` gets added
  to that module (extending the established pattern) or lives inside the new analytics module.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope & requirements
- `.planning/PROJECT.md` — Active requirements (Analytics layer bullet: "weekly training
  volume, per-muscle-group volume with direct/indirect weighting... training frequency..."),
  Constraints (timezone Asia/Jakarta configurable and used for daily/weekly calculations;
  internal units kg/m/kcal/seconds/cm)
- `.planning/REQUIREMENTS.md` — VOL-01, VOL-02, VOL-03, DQ-01, DQ-02 (exact acceptance criteria
  for this phase)
- `.planning/ROADMAP.md` Phase 4 section — goal, 5 success criteria, requirements mapping

### Source spec (authoritative for scope/behavior; verify field names against Phase 3's live
schema, not the blueprint's assumed shape — see Phase 3 refs below)
- `BRETT blueprint.md` §16 "Analytics Layer" — backend calculates objective metrics
  deterministically; Claude must not do the arithmetic itself
- `BRETT blueprint.md` §17 "Training Volume" — `get_weekly_volume()`: sets per muscle, hard
  sets, total reps, volume load where meaningful, weekly trends; explicit warning not to treat
  volume load as directly comparable across exercises
- `BRETT blueprint.md` §18 "Muscle Group Volume" — direct/indirect set split example
  (`triceps: direct_sets=6, indirect_sets=8`), configurable weighting example (1.0 primary /
  0.5 secondary) — directly informs D-04
- `BRETT blueprint.md` §23 "Training Frequency" — `sessions_per_week`,
  `muscle_group_frequency`, `exercise_frequency`
- `BRETT blueprint.md` §39 "Data Freshness" — every data source exposes `last_synced_at`;
  "Claude should know when data may be stale" — informs D-06/DQ-01
- `BRETT blueprint.md` §40 "Time Zones" — convert to local timezone before grouping by day,
  Asia/Jakarta default but configurable — informs D-02
- `BRETT blueprint.md` §41 "Units" — kg/m/kcal/seconds/cm internal units, convert only at the
  application boundary
- `BRETT blueprint.md` §42 "Testing" → "Analytics" subsection — required test coverage
  includes weekly volume and muscle-group volume (this phase's subset; PR/progression/plateau/
  weight-trend/period-comparison tests belong to Phase 5)

### Phase 3 output this phase consumes (locked — do not re-litigate or re-derive)
- `backend/app/db/models/workout.py` — `Workout`/`WorkoutExercise`/`WorkoutSet` schema;
  `set_type` is `'normal'|'warmup'|'dropset'|'failure'` verbatim (VOL-01 excludes exactly
  `'warmup'`); `weight_kg` is `Numeric(7,3)`, never float; `ix_workouts_user_id_start_time` is
  the index this phase's date-window queries should use
- `backend/app/db/models/exercise.py` — `ExerciseTemplate`/`ExerciseMuscle`/
  `ExerciseMuscleOverride` schema
- `backend/app/normalization/resolver.py` — `effective_muscles_bulk()` (batched, two queries
  total) and `apply_weights()` (default 1.0 direct / 0.5 indirect, `Decimal`-typed) — this
  phase MUST call these for muscle resolution/weighting, never re-derive the override logic
- `backend/app/normalization/muscles.py` — `CanonicalMuscleGroup` (19-value enum),
  `MuscleRole` enum
- `backend/app/db/repositories/sync_state.py` — `get_sync_state()`, `SYNC_RESOURCES`,
  `RESOURCE_WORKOUTS` — the source for DQ-01 freshness metadata
- `backend/app/core/time.py` — `local_week_start()` (already implements D-02's Monday-start
  local week exactly), `local_day_bounds()` (the half-open-UTC-range SQL-filtering pattern a
  week-bounds equivalent should follow), `validate_timezone()`
- `docs/hevy-api-observations.md` "Dumbbell weight semantics" section — `weight_kg` is
  per-dumbbell, not combined; directly informs D-01
- `.planning/phases/03-hevy-integration-normalization/03-CONTEXT.md` — D-01 (19-group
  taxonomy), D-02/D-04 (curated mapping + override resolution), D-08 (sync checkpointing) —
  background for how the tables this phase reads were built

### Technology stack (already researched and locked — see project CLAUDE.md)
- `CLAUDE.md` → "What NOT to Use" — pandas/numpy explicitly rejected for v1 analytics;
  "SQL aggregates + plain Python keeps them trivially unit-testable" — use SQL aggregates and
  `dataclasses`/Pydantic models, not a dataframe layer
- `CLAUDE.md` → Supporting Libraries → `zoneinfo` row — Asia/Jakarta local-day/week grouping
  via `ZoneInfo(user.timezone)`, no third-party tz library (already how `core/time.py` works)
- `CLAUDE.md` → `testcontainers[postgres]` row — analytics correctness depends on
  `date_trunc`/window-function/timezone arithmetic that SQLite cannot reproduce; test against
  real Postgres

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/normalization/resolver.py::effective_muscles_bulk()` /
  `apply_weights()` — the muscle-mapping and direct/indirect weighting engine; call it, don't
  reimplement it
- `backend/app/core/time.py::local_week_start()` — already returns the Monday of a user's
  local ISO week from a UTC instant; matches D-02 exactly
- `backend/app/core/time.py::local_day_bounds()` — the half-open `[start, end)` UTC-range
  pattern for SQL-filterable date-window queries; a `local_week_bounds()` (or equivalent
  helper for arbitrary start/end ranges, per D-03) should follow the same shape
- `backend/app/db/repositories/sync_state.py::get_sync_state()` — freshness lookup by
  `(user_id, provider, resource)`; `RESOURCE_WORKOUTS` is the relevant resource for this phase
- `backend/app/db/models/workout.py` — `ix_workouts_user_id_start_time` index already built
  anticipating exactly this phase's `(user_id, date range)` filter pattern

### Established Patterns
- Every table this phase reads inherits `Base`/`TimestampMixin` and uses `TIMESTAMPTZ`-only
  timestamps (FOUND-04) — any new timestamp this phase produces (e.g. `earliest_data_at`)
  should follow the same convention
- `Decimal`, never `float`, for any value that gets summed or compared (`weight_kg`,
  `apply_weights()`'s output) — established in Phase 3's `workout.py`/`resolver.py` specifically
  to avoid binary-floating-point drift in volume/tonnage sums
- No `pandas`/`numpy` anywhere in the codebase (CLAUDE.md constraint) — aggregation is
  expected to be SQL (`date_trunc`, window functions, `generate_series`) plus plain Python

### Integration Points
- No `app/analytics/` (or equivalent) package exists yet — this phase creates it
- No API routes or MCP tools call into analytics yet (`backend/app/api/routes/` has only
  `health.py`; `backend/app/mcp/tools/` has only `ping.py`) — Phase 6 wires this phase's
  functions into MCP tools; this phase's public functions are its only contract for now

</code_context>

<specifics>
## Specific Ideas

No further specific ideas beyond the decisions above — user picked among presented options
throughout (including a clarifying round on the dumbbell-tonnage/unilateral-exception pairing,
resolved as "no correction, so no exception list needed"), confirming the researched approach
fit their intent for this phase.

</specifics>

<deferred>
## Deferred Ideas

- **`requested_window` echo in coverage metadata** — presented as an option for D-06's metadata
  block and not selected. Not lost — reconsider if Phase 6's MCP tool consumers turn out to
  need it.
- **Per-dumbbell ×2 tonnage correction and its unilateral-exercise exception list** — considered
  in depth (D-01) and explicitly rejected in favor of raw `weight_kg × reps` everywhere. If a
  future milestone wants "true total load" reporting, the curated-title-exception-list pattern
  from `app/normalization/exercise_map.py` is the template to reuse.

</deferred>

---

*Phase: 04-volume-frequency-analytics*
*Context gathered: 2026-08-30*

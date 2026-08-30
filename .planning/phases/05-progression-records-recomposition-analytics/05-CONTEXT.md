# Phase 5: Progression, Records & Recomposition Analytics - Context

**Gathered:** 2026-08-30
**Revised:** 2026-08-30 — plateau detection (D-06/D-07), body-weight rolling averages
(new D-13–D-17), and the recomposition rate-of-change basis (D-11/D-12) critically re-reviewed
before planning and replaced/tightened; see the "Revision note" at the end of each affected
subsection.
**Revised again:** 2026-08-30 — after /gsd-phase-researcher and /gsd-pattern-mapper both
independently flagged the same unresolved items, three research-recommended defaults confirmed
with the user before planning: PROG-03's max lookback bound (D-19, 12 weeks), PROG-02's trend
stable dead-band (D-18, ±0.5%/week), and BODY-02's recomposition aggregation rule (D-20,
net-progression score + `progression_signal` field).
**Status:** Ready for planning

<domain>
## Phase Boundary

The second half of the analytics layer (`backend/app/analytics/`, a sibling of Phase 4's
`volume.py`/`frequency.py`/`metadata.py`): pure, deterministic functions that read synced
workouts and body measurements and return **verdicts**, not just numbers — exercise progression
time series with an estimated 1RM where meaningful (PROG-01), a trend classification per exercise
(PROG-02), plateau detection (PROG-03), personal records (PROG-04), period comparison normalized
per week (CMP-01), body-weight rolling averages and rate of change (BODY-01), and a recomposition
status verdict (BODY-02) — explicitly framed as decision support, never a medical claim.

**Explicitly NOT this phase:** MCP tool exposure (Phase 6) — this phase builds the analytics
functions themselves, not a wire contract. Manual body-measurement/nutrition entry (separate,
unscoped phase — `BodyMeasurement.source` already supports `'manual'`, but nothing writes it
yet). Any change to volume/frequency (Phase 4, already complete) or the muscle-mapping engine
(Phase 3) — this phase consumes both, it doesn't modify them. Apple Health / steps / calories
signals in recomposition status — out of v1 scope per REQUIREMENTS.md (`RECOMP-02` is v2).

</domain>

<decisions>
## Implementation Decisions

### Estimated 1RM (PROG-01)
- **D-01:** Formula is **Epley**: `1RM = weight × (1 + reps/30)`. Chosen over Brzycki (which needs
  a hard rep cap regardless, since its denominator `37 − reps` goes negative above 36 reps) and
  over an average-of-both approach (added complexity for marginal accuracy gain at typical rep
  ranges). Use it consistently and label every value as an estimate, per blueprint §19.
- **D-02:** The estimate is only trusted for **≤12 reps**. Above that, return `null` with an
  explicit reason rather than a number that looks real but isn't — most 1RM formulas' error grows
  fast past ~12 reps as fatigue/form breakdown stops being proportional to load.
- **D-03:** The estimate is only computed for **`exercise_type == 'weight_reps'`** (7167 of 7984
  live sets). All other modalities (`bodyweight_weighted` 270, `reps_only` 503,
  `short_distance_weight`/`duration`/etc. ~40) return `null` with a reason — `bodyweight_weighted`
  was explicitly considered (joining the nearest `body_measurements.weight_kg` by date to estimate
  total load) and rejected: it would stack an interpolated-bodyweight guess under the 1RM
  estimate, and bodyweight isn't tracked per-workout, only via separate dated rows.
- **D-04:** When a session has multiple sets of the same exercise, the date's progression-series
  entry (weight/reps/estimated_1rm/volume) is drawn from **the set with the highest estimated 1RM
  that day** — not simply the heaviest weight, since a lighter set at more reps can imply more
  strength under Epley. This also directly informs PROG-04's PR detection: PRs are found by
  scanning individual qualifying sets, not by first collapsing to one per-date value.

### Trend Classification & Plateau Detection (PROG-02, PROG-03)
- **D-05:** PROG-02 requires **at least 4 weeks** of data for a given exercise before committing
  to `improving` / `stable` / `declining`. Below that threshold, the verdict is `unclear` —
  matches blueprint §20's "do not classify progression based on a single workout," scaled to a
  concrete minimum.
- **D-18 (new 2026-08-30, confirmed after research):** PROG-02's `stable` dead-band around zero
  slope is **±0.5%/week**, derived as D-07's 2% plateau tolerance ÷ D-05's 4-week minimum window —
  the same "noise floor" concept reused across the phase rather than an independent constant.
  Validated against live data: 9 improving / 9 stable / 10 declining across 28 exercises, a clean
  three-way split with no boundary crowding. Confirmed by the user at plan time
  (`TREND_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.005")`).
- **D-06 (revised 2026-08-30):** PROG-03's plateau window is **adaptive session count, bounded by
  a calendar floor**: **4 qualifying sessions of that exercise AND at least 3 weeks elapsed**
  since the streak began — whichever requires more evidence. Pure session-count adaptivity (the
  original D-06) was too permissive for high-frequency exercises: 4 sessions of a bench press
  trained 3×/week is only ~9–13 days, far below blueprint §21's own explicit "3–6 weeks" floor
  and squarely inside the "normal day-to-day fluctuation" range §21 warns against. The floor fixes
  that while still letting low-frequency accessory exercises take longer than 3 weeks to
  accumulate 4 qualifying sessions, exactly as "depending on... training frequency" intends.
- **D-07 (revised 2026-08-30):** A session **breaks** the plateau streak only if its estimated 1RM
  exceeds `historical_best × 1.02` (a 2% tolerance) — not any epsilon increase over the strict
  historical maximum. Named module-level constant, same pattern as Phase 4's
  `INSUFFICIENT_DATA_SESSION_THRESHOLD`: `PLATEAU_IMPROVEMENT_TOLERANCE = Decimal("0.02")`. A
  strict "any new max" rule (the original D-07) has no noise tolerance: a lifter clearly trending
  up but bouncing within 1% of their peak (sleep, RPE variance, normal session-to-session
  fluctuation) would get flagged as "no progress" purely on the exact-max test — precisely the
  false positive §21 warns against. This still reuses PROG-01's 1RM estimate (D-01–D-04) as the
  single "are you stronger" measure for the whole phase, only with a tolerance band instead of a
  bare `>` comparison.
- **D-07a (new 2026-08-30):** Sessions with a `null` estimated 1RM (the D-02 rep-range gate or the
  D-03 modality gate) are **skipped** when evaluating the plateau streak — they neither extend nor
  break it. Without this, anyone periodizing rep ranges (a deload week, 5/3/1-style waves, a
  higher-rep accessory day) would have those sessions silently read as "no PR," falsely inflating
  the plateau streak purely because that day's modality/rep-range made an estimate untrustworthy,
  not because training stalled.
- **D-07b (new 2026-08-30):** Every plateau result reports `recent_performance` (mean qualifying
  e1RM over the window), `historical_best`, the actual window/threshold used (session count *and*
  elapsed weeks, per D-06), and a `confidence` derived from the qualifying-session count (e.g.
  `low`/`medium`/`high`) — matching blueprint §21's return shape
  (`plateau_duration`/`recent_performance`/`historical_best`/`confidence`) instead of a bare
  boolean, which the original D-06/D-07 pair implied but didn't make explicit.
- **D-19 (new 2026-08-30, confirmed after research):** D-06 specifies minimum evidence only, with
  no maximum lookback — run over unbounded history this flags 44 of 97 exercises as plateaued with
  durations up to 402 days, including exercises abandoned months ago, which is not usable coaching
  output. PROG-03 takes a caller-supplied **`lookback_weeks` parameter, defaulting to 12 weeks**,
  echoed back in the result's window fields. A 12-week bound gives 18/29 exercises flagged at
  27–75 days on live data — a coach-readable result. Confirmed by the user at plan time.

### Personal Records (PROG-04)
- **D-08:** `'dropset'` and `'failure'` set types are **eligible for all PR types** (max weight,
  max reps at a weight, estimated-1RM PR, volume PR, rep PR) — only `'warmup'` is excluded. A
  to-failure set or a dropset's heaviest (first) portion is a real, hard effort; excluding it
  would hide legitimate PRs, and rep PRs in particular often happen ON a to-failure set by design.
- **D-09:** When two sets tie for a PR value (same max weight, or same max reps at that weight),
  the PR date recorded is **the earliest date the value was first reached** — "when did I first
  hit this" is the standard convention, not "when did I most recently reconfirm it."

### Body Weight Rolling Averages (BODY-01)
*(All five decisions below are new 2026-08-30 — the original CONTEXT.md left this entirely to
Claude's discretion with only a pointer to Phase 4's coverage pattern; these formalize it.)*
- **D-13:** No interpolation or carry-forward for missing days. Each 7/14/30-day average is
  computed from **actual `measured_on` rows only** within the window. Inventing values for
  unweighed days would bias the number on an assumption (linear fill? last-known-value?) that
  isn't a real measurement, breaking the "deterministic, explainable" bar and hiding exactly the
  sparsity Claude needs to see.
- **D-14:** If both a `'hevy'` and a `'manual'` row exist for the same `measured_on` date (the
  natural key permits this), **prefer `'manual'`** — a manual entry represents a deliberate
  correction of that day's number. Moot today (only `'hevy'` rows exist; manual entry is a
  separate, unscoped phase), but locking it now prevents silently double-counting or averaging
  two same-day values once manual entry ships.
- **D-15:** Each window has its **own independent coverage floor**, mirroring Phase 4's D-05 "why
  2 and not something else" reasoning but recalibrated from a per-session cadence to a per-day
  one: **7-day window needs ≥3 measured days, 14-day needs ≥5, 30-day needs ≥10**. Below its floor,
  that specific window's average is `null` with `insufficient_data=true` **for that window only**
  — a 30-day average can be reliable while the 7-day one isn't (or vice versa), same additive
  relationship as Phase 4's per-muscle `insufficient_data` sitting alongside the response-level
  flag rather than replacing it.
- **D-16:** The **weekly rate of change** BODY-01 reports is a **smoothed 4-week trend**, not a
  single most-recent-week delta: `(current_7d_avg − 7d_avg_from_4_weeks_ago) / 4`. Blueprint §25's
  own worked example (current 7-day avg vs. the immediately preceding 7-day avg) uses a single
  week-over-week comparison — dominated by water retention, sodium/carb intake, and glycogen
  swings, which alone can move a 70–80kg person's week-over-week number by several hundred grams,
  large enough to false-positive against BODY-02's tight percentage thresholds below. The 4-week
  window matches PROG-02's own "at least 4 weeks" minimum (D-05), keeping one "minimum meaningful
  window" concept across the phase. Gated on D-15: `null` + `insufficient_data=true` if either the
  current or the 4-weeks-ago 7-day average fails its coverage floor.
- **D-17:** The raw single most-recent-week delta (blueprint §25's literal example calculation) is
  **still surfaced**, as a clearly separate secondary field (e.g. `latest_week_delta_kg`) alongside
  the smoothed `trend_rate_percent_per_week` from D-16 — visible to Claude for context, but never
  the figure BODY-02 classifies against.
- Coverage type note for planning: `CoverageMetadata` (Phase 4) is workout-session-grained
  (`sessions_in_window`) and does not transfer verbatim to a day-grained weigh-in count — plan a
  sibling type with the same three-field philosophy (e.g. `measured_days_in_window`,
  `insufficient_data`, `earliest_measurement_at`) rather than overloading the existing one.

### Recomposition Status (BODY-02)
- **Context (not a stored field):** the user's current goal is a **lean bulk** (slow weight gain,
  build muscle). No `users.goal` column exists and none is being added this phase — this shapes
  the threshold *values* chosen below, not new schema. If the goal changes later, these constants
  are the ones to revisit.
- **D-10:** "Too fast" thresholds are expressed as **percent of bodyweight per week**, not a fixed
  kg/week number — the standard fitness-coaching convention, since a fixed kg/week doesn't scale
  if bodyweight moves meaningfully over the tracked period.
- **D-11:** `weight_gain_too_fast` triggers above **+0.25%/week** of bodyweight — the stricter end
  of the typical lean-bulk guideline (~0.25–0.5%/week), chosen to keep gains lean rather than
  tolerate a faster, fattier surplus. **Revised 2026-08-30:** the target rate itself is unchanged,
  but it is now evaluated against **D-16's smoothed 4-week trend rate**, not a single-week delta —
  the numeric threshold was never the problem, measuring it off one noisy week was.
- **D-12:** `weight_loss_too_fast` triggers above **−1%/week** of bodyweight even though loss
  isn't the current goal — any loss that fast during a bulk is a clear signal something is off
  (undereating, illness, a tracking error) and is worth surfacing regardless of the stated goal.
  **Revised 2026-08-30:** same basis change as D-11 — evaluated against D-16's smoothed trend rate.

### Claude's Discretion
- ~~Exact "no progress" plateau metric wording/edge cases~~ — **resolved 2026-08-30** by D-07/
  D-07a/D-07b (2% tolerance band, null-e1RM sessions skipped, explicit `recent_performance`/
  `historical_best`/`confidence` reporting).
- ~~BODY-01 rolling-average mechanics with data gaps~~ — **resolved 2026-08-30** by D-13–D-17
  (no interpolation, source tie-break, per-window coverage floors, smoothed 4-week trend rate plus
  a surfaced raw single-week delta).
- ~~How PROG-02's trend feeds BODY-02's label alongside the weight trend~~ — **resolved
  2026-08-30, confirmed after research, see D-20** below.

### D-20 (new 2026-08-30, confirmed after research): Recomposition status aggregation rule (BODY-02)
Weight trend (D-16's smoothed rate) sets the primary direction/threshold check (D-10–D-12).
Training-progression trend refines the label via a **net-progression score**:
`(count(improving) − count(declining)) / count(classified exercises)`, excluding `unclear`
exercises from both numerator and denominator, requiring a **minimum of 3 classified exercises**
before the score is trusted (below that, aggregate progression reads as `unclear` and the status
label falls back to a weight-only read). The score is bucketed with a **±0.25 band** (net > 0.25 →
net-positive; net < −0.25 → net-negative; between → neutral) and crossed with the weight-rate
ladder (D-10–D-12, D-16) into blueprint §26's seven-value enum. The on-target-gain-with-flat-or-
declining-lifts case maps to `likely_muscle_gain` — never overstating, since the label only claims
"gaining at a rate consistent with muscle gain" — with the nuance carried by a **required
`progression_signal` field** (the net-progression score's own classification: positive/neutral/
negative/insufficient) so Claude can qualify the label rather than the enum silently hiding
disagreement between weight and strength trends. `disclaimer` remains populated on every response
per the existing framing requirement (decision support, not a medical claim).
- **CMP-01 period comparison scope** — which specific metrics get compared (volume, frequency,
  tonnage, per-muscle, progression?) beyond "normalized per week so unequal-length windows don't
  mislead." Not discussed as its own gray area; Phase 4's D-03 (arbitrary start/end date range,
  built for exactly this) is the existing building block to reuse.
- Exact Pydantic schema shapes for all new return types (following `app/analytics/schemas.py`'s
  established `_AnalyticsModel` base, `Decimal`-not-`float`, deterministic-ordering conventions) —
  including the new `BodyMeasurementCoverage`-style sibling type flagged under BODY-01 above.
- Module/function naming and file layout within `app/analytics/` (e.g. `progression.py`,
  `records.py`, `recomposition.py` vs. fewer/more files) — no established split yet for this
  phase's five requirement areas.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope & requirements
- `.planning/PROJECT.md` — Active requirements (progression/plateau/PR/recomposition bullet),
  Constraints (units, provider isolation, data integrity)
- `.planning/REQUIREMENTS.md` — PROG-01, PROG-02, PROG-03, PROG-04, CMP-01, BODY-01, BODY-02
  (exact acceptance criteria for this phase)
- `.planning/ROADMAP.md` Phase 5 section (lines 141–153) — goal, 5 success criteria, requirements
  mapping, depends-on Phase 4

### Source spec (authoritative for scope/behavior — verify field names against the live schema
below, not the blueprint's assumed shape, exactly as Phase 4's canonical refs warned)
- `BRETT blueprint.md` §19 "Exercise Progression" — `get_exercise_progression(exercise, period)`
  return shape (date/weight/reps/sets/estimated_1rm/volume/rir — note: live schema has `rpe`, not
  `rir`, see Phase 3 schema below); "use an estimated 1RM formula consistently... do not use it
  where it would be misleading" — directly informs D-01–D-04
- `BRETT blueprint.md` §20 "Progressive Overload Detection" — improving/stable/declining/unclear;
  "do not classify progression based on a single workout" — informs D-05
- `BRETT blueprint.md` §21 "Plateau Detection" — 3–6 week configurable window; return shape
  (exercise, plateau_duration, recent_performance, historical_best, confidence) — informs
  D-06/D-07/D-07a/D-07b; its "do not immediately classify normal day-to-day fluctuations as a
  plateau" warning is the direct rationale for D-07's tolerance band
- `BRETT blueprint.md` §22 "Personal Records" — max weight, max reps at a weight, estimated-1RM
  PR, volume PR, rep PR, with dates — informs D-08/D-09
- `BRETT blueprint.md` §24 "Body Recomposition Analytics" — combines body weight, waist, body fat
  if available, training performance/volume (steps/activity/calories are v2 per REQUIREMENTS.md)
- `BRETT blueprint.md` §25 "Weight Trend" — 7/14/30-day averages, weekly rate of change, worked
  example (69.1kg vs 68.8kg → +0.3kg) — informs BODY-01
- `BRETT blueprint.md` §26 "Recomposition Status" — the status enum (`likely_recomp_progressing`,
  `likely_muscle_gain`, `likely_fat_loss`, `weight_stable`, `weight_gain_too_fast`,
  `weight_loss_too_fast`, `insufficient_data`); "not a medical or scientifically certain
  diagnosis... a fitness decision-support metric" — informs D-10–D-12 and the discretion note

### Phase 4 output this phase consumes (locked — reuse, do not re-derive)
- `.planning/phases/04-volume-frequency-analytics/04-CONTEXT.md` — D-01 (raw `weight_kg × reps`
  tonnage, no per-dumbbell correction, **chosen explicitly because it's the input Phase 5's
  estimated-1RM formula needs**), D-05/D-06 (insufficient-data threshold + coverage metadata
  shape — the pattern this phase's own D-15 per-window coverage floors and
  `PLATEAU_IMPROVEMENT_TOLERANCE` constant are modeled on)
- `backend/app/analytics/schemas.py` — `_AnalyticsModel` base (`hide_input_in_errors=True`,
  `extra="forbid"`, `frozen=True`), `FreshnessMetadata`, `CoverageMetadata` — reuse these types
  directly for every new Phase 5 return type's freshness/coverage fields
- `backend/app/analytics/metadata.py` — `INSUFFICIENT_DATA_SESSION_THRESHOLD = 2`,
  `is_insufficient()`, `build_freshness()`, `build_coverage()`, `sessions_in_window()`,
  `earliest_workout_at()` — call these, don't reimplement
- `backend/app/core/time.py` — `local_week_start()`, `local_day_bounds()`,
  `local_range_bounds()` (added in Phase 4 for arbitrary start/end ranges — exactly what CMP-01
  needs), `validate_timezone()`

### Live database schema (verify against this, not the blueprint's assumed shape)
- `backend/app/db/models/workout.py` — `WorkoutSet.set_type` is `'normal'|'warmup'|'dropset'|
  'failure'` verbatim (D-08 excludes only `'warmup'`); `weight_kg` is `Numeric(7,3)`, `reps` is
  `Integer | None`, `rpe` is `Numeric(3,1)` (blueprint's `rir` does not exist — Hevy sends `rpe`)
- `backend/app/db/models/exercise.py` — `ExerciseTemplate.exercise_type` is the modality signal
  (D-03's gate); live distribution documented in the column comment: `weight_reps` 7167,
  `reps_only` 503, `bodyweight_weighted` 270, `duration` 24, `short_distance_weight` 16,
  `bodyweight_assisted` 4, three zero-set types. **Do not hardcode an allow-list from this
  comment** — the existing warning there applies to Phase 5 too if any modality-based branching
  is needed beyond the exact-match gate in D-03.
- `backend/app/db/models/body.py` — `BodyMeasurement` (weight_kg, lean_mass_kg, fat_percent, plus
  14 circumference fields); natural key `(user_id, source, measured_on)`; `source` is `'hevy'|
  'manual'` (only `'hevy'` rows exist today — manual entry is a separate, unscoped phase);
  `measured_on` is a `Date`, not a timestamp — informs BODY-01's day-grain averaging
- `backend/app/db/repositories/sync_state.py` — `RESOURCE_BODY_MEASUREMENTS` constant already
  exists in `SYNC_RESOURCES`, ready for BODY-01/BODY-02's `FreshnessMetadata`

### Technology stack (already researched and locked — see project CLAUDE.md)
- `CLAUDE.md` → "What NOT to Use" — pandas/numpy rejected; SQL aggregates + `Decimal`/Pydantic,
  same as Phase 4
- `CLAUDE.md` → `zoneinfo` row, `testcontainers[postgres]` row — same rationale carries forward
  unchanged from Phase 4

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/analytics/metadata.py::build_freshness()` / `build_coverage()` /
  `is_insufficient()` — call directly for every new response's DQ-01/DQ-02 envelope for
  workout-grained data (progression, PRs); BODY-01/BODY-02 need a day-grained sibling per D-15,
  not a reuse of `is_insufficient()`'s session-count logic
- `backend/app/analytics/schemas.py::_AnalyticsModel` — the shared Pydantic base every new return
  type should subclass
- `backend/app/core/time.py::local_range_bounds()` — already built in Phase 4 for arbitrary
  start/end ranges; this is CMP-01's and PROG-01's date-window building block
- `backend/app/db/models/body.py::BodyMeasurement` — already has everything BODY-01/BODY-02 need
  to read (weight_kg, measured_on); no migration required

### Established Patterns
- Every Phase 4 analytics function takes `session: AsyncSession` positionally and everything else
  keyword-only, never commits (caller owns the transaction) — Phase 5 should match exactly
- `Decimal`, never `float`, for every summed/averaged magnitude (tonnage, 1RM estimates,
  bodyweight, rolling averages)
- Deterministic ordering on every returned collection (weeks ascending, muscle groups by a stated
  key) — Phase 5's exercise lists, PR lists, and comparison rows need the same discipline
- `app/analytics/` imports nothing from `app.integrations` or `app.mcp` — a static isolation test
  (`test_analytics_isolation.py`, added in Phase 4) already enforces this via `rglob` and will
  auto-cover any new Phase 5 module with no edit required

### Integration Points
- No progression/records/recomposition module exists yet under `app/analytics/` — this phase
  creates it (naming/layout is Claude's discretion, see above)
- Phase 6 (not this phase) wires these functions into MCP tools — this phase's public function
  signatures and return types ARE its contract for now, same as Phase 4

</code_context>

<specifics>
## Specific Ideas

- User's current goal is a **lean bulk**, which directly set the asymmetric BODY-02 thresholds
  (D-11 stricter on the gain side at +0.25%/week; D-12 more permissive on the unexpected-loss side
  at −1%/week since loss isn't the goal but a fast one is still worth flagging).
- The plateau definition (D-06/D-07) was deliberately tied to the same estimated-1RM measure
  PROG-01 computes (D-01–D-04), rather than introducing a second progress definition — the user
  picked this consistency explicitly when choosing "no new est-1RM PR" over a formula-independent
  weight-PR-based alternative.
- **2026-08-30 critical review:** before planning, the user asked for the plateau rule, the
  bodyweight-averaging approach, and the lean-bulk thresholds to be re-examined specifically for
  false-positive risk (normal fluctuation, exercise frequency, water/glycogen noise) rather than
  preserved as-is. All three were tightened as a result (D-06/D-07/D-07a/D-07b, new D-13–D-17,
  and D-11/D-12's evaluation basis) — see `05-DISCUSSION-LOG.md`'s "Critical Review" section for
  the full KEEP/MODIFY/REPLACE reasoning behind each change.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No new capabilities were proposed; every question
was about how to implement PROG-01..04, CMP-01, BODY-01, BODY-02, all already scoped to this
phase by ROADMAP.md.

</deferred>

---

*Phase: 05-progression-records-recomposition-analytics*
*Context gathered: 2026-08-30*

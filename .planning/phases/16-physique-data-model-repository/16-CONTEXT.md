# Phase 16: Physique Data Model & Repository - Context

**Gathered:** 2026-09-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 16 delivers ONLY the persistence layer: a `PhysiqueObservation` header row plus one
`PhysiqueRating` child row per `(observation, muscle_group)`, keyed on the existing 19-value
`CanonicalMuscleGroup` enum, readable and writable through `backend/app/db/repositories/physique.py`,
landing in migration `0007`. No MCP tool, no `analytics/physique.py` diff logic, and no write-guard
suite changes — those are Phase 17. This phase proves the shape persists correctly and round-trips
cleanly; it does not decide who is allowed to call it or what Claude sees.

**User's steering for this discussion:** the user asked to defer directly to the recommended
resolution on every gray area surfaced below, rather than discuss each individually. The four
areas were still real, consequential design decisions (no prior phase or ROADMAP line fixed the
exact answer), so each is recorded here as a named decision with rationale — Claude's Discretion,
made explicit rather than left implicit — so the researcher and planner do not have to re-derive
or silently assume any of them.

</domain>

<decisions>
## Implementation Decisions

### Migration Scope: 0007 Carries Phase 17's "Superseded" Columns Now
- **D-01:** Migration `0007` (this phase) includes the PHYS-08 supersede-tracking columns on
  `PhysiqueObservation` — `superseded_at: DateTime | None`, `superseded_reason: String(200) | None`,
  `superseded_by_id: UUID | None` (self-referential FK to `physique_observations.id`, nullable,
  `ondelete="SET NULL"`) — even though the write logic that SETS them is Phase 17 (PHYS-08), which
  Phase 16 does not implement or test beyond "the columns exist, default NULL, and round-trip."
  **Rationale:** ROADMAP never names any migration beyond `0007` anywhere in the v2.1 milestone —
  Phase 17 and 18's success criteria describe new application logic and analytics with no migration
  step of their own, and Phase 19's entire goal is "prove Phase 14's fix works by deploying **this
  milestone's own migration**" (singular, `0007`) through the new pre-deploy pipeline. Building the
  full final table shape once, in the one migration that ever reaches production, avoids either (a)
  amending an already-authored migration file in a later phase — which the project's own migration
  round-trip test (`test_migrations.py::test_migrations_round_trip`) is what catches if done
  carelessly — or (b) a second Alembic revision Phase 19's roadmap wording never anticipates.
- **Claude's Discretion:** exact FK `ondelete` behavior and index choices on the new columns are
  left to the planner; `SET NULL` above is a starting recommendation, not a hard requirement.

### Confounder Metadata Storage Shape
- **D-02:** `pose_state` is a `String`-backed `StrEnum` guarded by a named `CHECK` constraint
  (never a native PostgreSQL `ENUM`), with exactly the two values PHYS-05 names: `relaxed` and
  `lightly_flexed`. **Rationale:** this is the same "bounded enum, never native ENUM" concern
  PHYS-03 states for ratings — applying the identical posture to `pose_state` avoids a second
  `pg_type`-orphan risk class existing in the same migration under a different rule.
- **D-03:** `photo_angles_present` is `ARRAY(String(16))` with a named `CHECK` constraint
  restricting every element to a bounded set (`front`, `back`, `side`), following the existing
  `exercise_templates.secondary_muscle_groups` precedent (`ARRAY(String(32))`,
  `server_default=text("'{}'::varchar[]")` for "none recorded yet"). **Rationale:** this is an
  established, already-tested column shape in this codebase (`backend/app/db/models/exercise.py`)
  — reusing it is lower-risk than introducing a JSON column or a comma-separated string for the
  same "which of a small fixed set were present" fact.
- **Claude's Discretion:** whether a fourth `other`/`unspecified` angle value is worth adding is
  left to the planner; the three named above cover every angle mentioned anywhere in
  `15-SPIKE-RESULT.md`'s raw rating output.

### Free-Text Field Length Caps
- **D-04:** The three PHYS-04 note fields — `leanness_notes`, `conditioning_notes`,
  `symmetry_notes` — are each `String(500)`, independently capped per column (not one shared blob).
  **Rationale:** 500 characters is generous enough for real qualitative note-taking (a few
  sentences per axis) while remaining clearly bounded; no existing table has a free-text column to
  anchor a cap to, so this is a fresh, explicit choice rather than a borrowed one.
- **D-05:** The PHYS-02 `Not Assessable` per-rating `reason` field is `String(160)`. **Rationale:**
  mirrors `15-SPIKE-RESULT.md`'s own rating-prompt convention — "one sentence, 20 words maximum" —
  which the spike already proved produces usable, concrete justifications (e.g. "No photo shows
  arms raised or flexed to reveal deltoid shape or rounding").
- **D-06:** The PHYS-05 confounder `conditions_note` is `String(200)` — slightly more room than a
  single rating's reason, since it may need to cover more than one factor (lighting, water weight,
  timing relative to a workout).

### Rating Row Completeness Per Observation
- **D-07:** Every `PhysiqueObservation` writes exactly 19 `PhysiqueRating` rows — one per
  `CanonicalMuscleGroup` value, unconditionally — each either a rated level (one of
  `PHYSIQUE_RATING_LEVELS`) or `Not Assessable` with a reason. `abductors` and `adductors` are not
  excluded or special-cased at the schema or repository level; they simply end up `Not Assessable`
  in ordinary use, exactly like any other group a given photo set fails to show. **Rationale:**
  Phase 16's own ROADMAP success criterion #3 says abductors/adductors "can be recorded this way
  **without special-casing**" — that phrase only holds if the write path iterates the full 19-value
  enum uniformly rather than the caller deciding which groups to consider. It also gives Phase 17's
  diff analytics one invariant to rely on: a `(observation_id, muscle_group)` row always exists
  once an observation exists, so "missing entirely" is never a third state alongside "rated" and
  "Not Assessable."
- **D-08 (structural consequence of D-07):** `(observation_id, muscle_group)` should carry a named
  unique constraint — same posture as `ProgramPeriod`'s partial unique index — so the "exactly one
  row per group per observation" invariant is enforced by PostgreSQL, not only by repository
  discipline.

### Claude's Discretion
- Exact table/column naming beyond what's specified above (e.g. `physique_observations`,
  `physique_ratings` as table names) — follow the codebase's existing `snake_case`, singular-model /
  plural-table convention.
- Migration filename: `0007_physique_observations.py`, following the `NNNN_description.py` pattern
  of `0001`–`0006`.
- The repository's exact function surface (e.g. `create_observation`, `get_latest_observation`,
  `list_recent_observations`) beyond the ROADMAP's literal "insert and read back" requirement —
  build what a Phase 17 MCP read/write tool will plausibly need, mirroring `programs.py`'s shape
  (explicit `AsyncSession` parameter, caller owns the transaction, no in-function commits).
- Where the `PHYSIQUE_RATING_LEVELS` / `PHYSIQUE_RATING_ANCHORS` / `PHYSIQUE_MIN_ELAPSED_DAYS` /
  `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` constants physically live (a new module vs. attached to the model
  file) — copy the values verbatim from `15-SPIKE-RESULT.md` regardless of placement; only
  `PHYSIQUE_RATING_LEVELS`/`PHYSIQUE_RATING_ANCHORS` are load-bearing for Phase 16 (they define the
  rating `StrEnum`), the other two are carried forward for Phase 17 to consume.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & requirements definition
- `.planning/ROADMAP.md` (Phase 16 section, "Physique Data Model & Repository") — the five success
  criteria this phase's plan(s) must satisfy verbatim
- `.planning/REQUIREMENTS.md` — PHYS-01 through PHYS-05 (this phase's requirements); PHYS-08 (the
  Phase 17 requirement whose columns D-01 pulls forward into this phase's migration)
- `.planning/PROJECT.md` — "Shape decided at the milestone gate" bullets (no photo storage,
  Claude-as-analyst, `_report_body_fields` split note) and the "v2.1 milestone-gate decisions"
  table in `.planning/STATE.md`

### Locked constants (copy verbatim, do not re-derive)
- `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` §"Recommended
  Constants" — `PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_RATING_ANCHORS` (load-bearing for this phase's
  rating `StrEnum`), `PHYSIQUE_MIN_ELAPSED_DAYS`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` (carried forward,
  consumed by Phase 17)

### Precedent to mirror
- `backend/app/normalization/muscles.py` (`CanonicalMuscleGroup`) — the 19-value `StrEnum` this
  phase's `muscle_group` column is keyed on; no new taxonomy is introduced
- `backend/app/db/models/program.py` (`ProgramPeriod`, `ProgramSwitchToken`) — append-only /
  never-hard-deleted row posture, named partial unique index pattern (D-08 mirrors this for
  `(observation_id, muscle_group)`), `TimestampMixin` usage
- `backend/app/db/repositories/programs.py` — repository shape: explicit `AsyncSession` parameter,
  caller owns the transaction, module docstring states which module is the sole writer of which
  table (mirrors this phase's `physique.py` being the sole writer of the new tables)
- `backend/app/db/models/exercise.py` (`ExerciseTemplate.secondary_muscle_groups`) — the
  `ARRAY(String(N))` + `server_default` pattern D-03's `photo_angles_present` column reuses
  verbatim
- `backend/app/analytics/recomposition.py` (`INTERPRETATION_DISCLAIMER`,
  `RECOMP_LOOKBACK_WEEKS`) — the named-constant-with-rationale-comment pattern the four Phase 15
  constants already follow and this phase's own new constants (if any) should match
- `backend/app/db/models/body.py` (`BodyMeasurement`) — precedent for `measured_on: Date` as a
  distinct calendar-day field from `TimestampMixin.created_at`; this phase's observation header
  needs the same distinction so `PHYSIQUE_MIN_ELAPSED_DAYS` has a stable calendar-day basis in the
  user's local timezone (Asia/Jakarta), not a UTC timestamp

### Tests this phase's migration must satisfy
- `backend/tests/test_migrations.py` (`test_migrations_round_trip`) — up/down without orphaning a
  `pg_type`; this is the concrete check PHYS-03's "never a native ENUM" rule exists to pass
- `backend/tests/test_db_models.py` — the no-credential-shaped-column guard (`token`/`key`/`secret`
  naming ban); irrelevant to this phase's columns but confirm no new column name accidentally trips
  it

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CanonicalMuscleGroup` (`backend/app/normalization/muscles.py`) — the 19-value enum this phase's
  `muscle_group` column keys on directly; zero new taxonomy work needed
- `TimestampMixin`, `Base` (`backend/app/db/base.py`) — every existing model uses these; the new
  `PhysiqueObservation`/`PhysiqueRating` models should too
- `secrets`-free repository pattern from `programs.py` — directly applicable template for
  `physique.py`'s function shapes (though physique has no token/confirmation ceremony to mirror,
  per the milestone-gate decision that this write is single-call and non-destructive)

### Established Patterns
- No table in this codebase currently uses `CheckConstraint` or a `StrEnum`-backed column with an
  explicit named CHECK — `program`/`muscle_group`/`source` columns today are all plain
  `String(N)` validated only at the Pydantic/application layer. PHYS-03 introduces this pattern
  for the first time in the project; there is no existing CHECK-constraint example to copy
  mechanically, only the "named constraint, not a bare inline check" convention implied by this
  project's other named-constraint usage (e.g. `uq_user_program_history_one_open_period`,
  `uq_exercise_templates_user_provider_external_id`).
- Named module-level constants with a rationale comment above the value
  (`recomposition.py`'s `RECOMP_LOOKBACK_WEEKS`) — the pattern the four Phase 15 constants already
  follow verbatim in `15-SPIKE-RESULT.md`.
- Append-only, never-hard-deleted rows with a `superseded`/`ended_on`-style column rather than a
  `DELETE` — `ProgramPeriod.ended_on` is the direct precedent D-01's `superseded_at` mirrors.

### Integration Points
- Phase 17's MCP write/read tools will call directly into `backend/app/db/repositories/physique.py`
  functions this phase builds — no HTTP round-trip (blueprint §37), same as every other repository.
- Phase 17's `analytics/physique.py` diff logic reads rows through this phase's repository and
  relies on D-07's "always 19 rows" invariant to avoid a three-state "missing vs. not-assessable"
  ambiguity.
- Phase 18's monthly report composition reads the same repository, one layer further downstream.

</code_context>

<specifics>
## Specific Ideas

No additional "I want it like X" references beyond the decisions above. The user explicitly
delegated all four gray areas to Claude's recommendation rather than describing a specific vision,
so this section stays intentionally thin — the decisions above ARE the specifics, each with its own
stated rationale so a downstream agent can evaluate whether that rationale still holds if
circumstances change.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No scope-creep attempts arose during this discussion;
the only substantive question resolved (D-01) was a scope-boundary *clarification* within the
milestone's own already-committed schema plan, not a new capability.

</deferred>

---

*Phase: 16-physique-data-model-repository*
*Context gathered: 2026-09-09*

# Phase 16: Physique Data Model & Repository - Research

**Researched:** 2026-09-09
**Domain:** SQLAlchemy 2.0 declarative models + hand-written Alembic migration + async repository, PostgreSQL-only test suite
**Confidence:** HIGH (all load-bearing claims verified by reading this repo's own code and running a live naming-convention check; no external library research was needed — this phase adds zero new dependencies)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Migration Scope: 0007 Carries Phase 17's "Superseded" Columns Now**
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

**Confounder Metadata Storage Shape**
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

**Free-Text Field Length Caps**
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

**Rating Row Completeness Per Observation**
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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. No scope-creep attempts arose during this discussion;
the only substantive question resolved (D-01) was a scope-boundary *clarification* within the
milestone's own already-committed schema plan, not a new capability.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PHYS-01 | Claude rates each assessable muscle group on a fixed 5-level ordinal scale (Minimal, Emerging, Developed, Well-Developed, Standout), anchors stored as a single verbatim-travelling constant; level 5 defined relative to the same person only | Pattern 1 (`PhysiqueRatingLevel` StrEnum + named CHECK, values copied verbatim from `15-SPIKE-RESULT.md`'s `PHYSIQUE_RATING_LEVELS`/`PHYSIQUE_RATING_ANCHORS`); Recommended Project Structure notes where the constants should live |
| PHYS-02 | `Not Assessable` is a first-class per-muscle value carrying a short reason, never a forced numeric guess; `abductors`/`adductors` expected permanently not-assessable | Pattern 2 (sibling nullable columns + XOR CHECK), Pattern 5 (`create_observation`'s 19-row completeness validation), D-07's "no special-casing" requirement addressed directly |
| PHYS-03 | Header + one child row per `(observation, muscle_group)`, keyed on `CanonicalMuscleGroup`; ratings persist as `String`-backed `StrEnum` + named CHECK, never native `ENUM` | Pattern 1 (CHECK-not-ENUM, live-verified naming convention), Pattern 4 (header/child migration skeleton mirroring `0006`), Pitfall 1 (naming), Anti-Pattern (native ENUM `pg_type` orphan risk) |
| PHYS-04 | Three separately-capped qualitative free-text note fields (leanness, conditioning, symmetry), strictly qualitative, no numeric body-fat estimate | Pattern 4 (`String(500)` columns per D-04), Pitfall 5 (cap-transposition risk across the four similar text fields) |
| PHYS-05 | Confounder metadata as fields independent of ratings: photo angles present, pose state as a bounded enum, a short conditions note | Pattern 1 (`pose_state` CHECK), Pattern 3 (`photo_angles_present` ARRAY + `<@` CHECK), Pitfall 3 (ARRAY CHECK has no in-repo precedent, needs a negative test) |
</phase_requirements>

## Summary

Phase 16 is pure "match the house style" work: there is no new library, no new framework
decision, and no external API. Every structural question the phase raises — StrEnum-backed
`String` columns, named `CHECK` constraints, header/child table shape, `ARRAY` columns, partial
unique indexes, repository conventions, migration hand-authoring — already has at least one
precedent living in `backend/app/db/` and `backend/migrations/versions/`, with one exception:
**no table in this codebase has ever used a `CheckConstraint`.** PHYS-03/D-02 introduce that
pattern for the first time. I verified the naming-convention math for it directly (see Code
Examples) rather than trusting training-data recall, because `ck: "ck_%(table_name)s_%(constraint_name)s"`
requires the constraint's own `name=` kwarg to populate `%(constraint_name)s` — an easy detail to
get backwards from memory.

The two tables this phase adds — `physique_observations` (header) and `physique_ratings` (child,
one row per `(observation, muscle_group)`) — are a direct structural analog to
`user_program_history` / `program_switch_tokens` from migration `0006`, which is itself the most
recent and most relevant migration in the repo (hand-written, not autogenerated, for the same
reason this phase's migration must be hand-written: Alembic autogenerate does not reliably emit
`postgresql_where` partial indexes or `CheckConstraint`s in a form worth trusting blind).

**Primary recommendation:** Model `physique_observations`/`physique_ratings` on
`ProgramPeriod`/`ProgramSwitchToken`'s file and migration shape exactly — same `Base`/
`TimestampMixin` inheritance, same named-index-on-model-and-migration duplication discipline, same
hand-written `upgrade()`/`downgrade()` pair — and build `physique.py`'s repository functions on
`programs.py`'s shape (explicit `AsyncSession` param, no in-function commit, module docstring
naming itself the sole writer). The one genuinely new piece of craft is the `CheckConstraint`
syntax for (a) a scalar `StrEnum` column and (b) an `ARRAY` column's element-membership check —
both are stock PostgreSQL/SQLAlchemy, verified below, and neither needs a third-party validation
library.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Physique observation/rating schema (tables, constraints) | Database / Storage | — | DDL owns the invariants (CHECK, unique index) per FOUND-02 — "migrations are the sole authority over the schema" |
| `PhysiqueObservation`/`PhysiqueRating` SQLAlchemy models | API / Backend (data-access layer) | Database / Storage | Declarative models are Python but must byte-match the migration DDL (`alembic check` enforces this — `test_no_pending_model_drift`) |
| `backend/app/db/repositories/physique.py` (insert/read functions) | API / Backend | — | Sole writer of the two new tables, mirrors `programs.py`; no HTTP, no MCP in this phase |
| Rating/pose-state/photo-angle vocabulary (`StrEnum`s, constants) | API / Backend | Database / Storage | Defined in Python (single source of truth for wording, per `INTERPRETATION_DISCLAIMER` precedent), mirrored into the DB as a `CHECK` constraint string list |
| MCP read/write tools | *(out of scope — Phase 17)* | — | Explicitly deferred; this phase's success criteria stop at the repository boundary |

## Standard Stack

No new packages. This phase is 100% additive schema + repository code inside the stack CLAUDE.md
already pins:

### Core (already in the tree — reconfirm versions only)
| Library | Version (installed, verified) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.52 `[VERIFIED: .venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"]` | Declarative models, `CheckConstraint`, `ARRAY` | Matches CLAUDE.md's pinned stack exactly |
| Alembic | matches `backend/migrations/env.py` async template `[VERIFIED: file present, generated by `alembic init -t async`]` | Hand-written migration `0007` | Existing convention: every migration touching a partial index or a non-trivial constraint is hand-written, not autogenerated |
| Python | 3.13 (`target-version = "py313"` in `pyproject.toml`) `[VERIFIED: repo root pyproject.toml]` | `StrEnum` for the rating/pose-state vocab | `enum.StrEnum` is stdlib since 3.11; already used in `app/normalization/muscles.py` |

No installation step is needed for this phase — nothing new to add to `pyproject.toml`.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `String` + named `CHECK` for the rating/pose-state enum | Native PostgreSQL `ENUM` type | **Rejected by PHYS-03/D-02 explicitly** — a native `ENUM` orphans a `pg_type` on `DROP TABLE` in the downgrade path, breaking `test_migrations_round_trip`. Not a judgment call for the planner to revisit |
| `ARRAY(String(16))` + CHECK for `photo_angles_present` | `JSONB` column | `ARRAY` is the established precedent (`exercise_templates.secondary_muscle_groups`); JSONB would introduce a second "small fixed set" representation into the codebase for no benefit and is harder to CHECK-constrain element-by-element |
| Hand-written migration | `alembic revision --autogenerate` then hand-edit | Precedent (`0006`'s docstring) says autogenerate does not reliably emit `postgresql_where` partial indexes; the same caution applies to `CheckConstraint` — write it by hand from the start rather than autogenerating and discovering gaps |

## Architecture Patterns

### System Architecture Diagram

```
                         Migration 0007 (DDL, hand-written)
                                     │
                                     ▼
   physique_observations (header) ──1:N──► physique_ratings (child)
        │  id (PK)                              │  id (PK)
        │  leanness/conditioning/symmetry_notes  │  observation_id (FK, CASCADE)
        │  photo_angles_present ARRAY+CHECK      │  muscle_group (CanonicalMuscleGroup value)
        │  pose_state String+CHECK               │  rating_level (StrEnum value) NULLABLE
        │  conditions_note                       │  not_assessable_reason NULLABLE
        │  superseded_at/_reason/_by_id (D-01)    │  UNIQUE(observation_id, muscle_group)
        │  TimestampMixin                         │  TimestampMixin
        ▼                                          ▲
  Base.metadata (SQLAlchemy declarative models)────┘  <- must byte-match migration (alembic check)
        │
        ▼
  backend/app/db/repositories/physique.py
    ├─ create_observation(session, *, user_id, notes, confounders, ratings: 19 rows) -> PhysiqueObservation
    │     one transaction: INSERT header, then INSERT 19 child rows — caller commits
    └─ get_latest_observation(session, *, user_id) -> PhysiqueObservation | None
          read path only — no MCP caller yet (Phase 17 wires this to a tool)
```

Primary use case trace: a caller (a future test, in this phase — a repository test, not an MCP
tool) builds one header row plus exactly 19 rating rows in Python, calls
`physique.create_observation(session, ...)`, the repository issues the header INSERT then the
child INSERTs inside the same session (caller commits, per the `programs.py` convention), and
`get_latest_observation` reads the header back with its ratings eagerly loaded (or a paired
"ratings for observation X" query) — proving the full round trip with no MCP layer involved.

### Recommended Project Structure
```
backend/app/db/models/
└── physique.py              # PhysiqueObservation, PhysiqueRating, and the rating/pose-state StrEnums
backend/app/db/repositories/
└── physique.py              # sole writer of both new tables; explicit AsyncSession param
backend/migrations/versions/
└── 0007_physique_observations.py   # hand-written, mirrors 0006's structure
backend/tests/
└── test_db_physique.py      # mirrors test_db_program_history.py's split: migration-shape
                              #   assertions (information_schema) + repository behavior assertions
```
Where the `PHYSIQUE_RATING_LEVELS` / `PHYSIQUE_RATING_ANCHORS` / `PHYSIQUE_MIN_ELAPSED_DAYS` /
`PHYSIQUE_DIFF_MIN_LEVEL_DELTA` constants live is Claude's Discretion per CONTEXT.md — placing
them at the top of `backend/app/db/models/physique.py` (next to the `StrEnum` they define) mirrors
`app/normalization/muscles.py`'s own pattern of module-level constants beside the enum they
describe, and keeps Phase 17's analytics import from a stable, already-existing module rather than
inventing a new one.

### Pattern 1: StrEnum column backed by `String` + a named `CHECK` constraint (new to this codebase)
**What:** Persist an `enum.StrEnum`'s `.value` as a plain `String(N)` column, then add a
table-level `CheckConstraint` restricting it to the enum's known values. Never `sa.Enum(...)` /
`postgresql.ENUM`.
**When to use:** Every bounded-vocabulary column this phase introduces — `rating_level`,
`pose_state`.
**Verified naming-convention behavior** (ran directly against this repo's `NAMING_CONVENTION`,
not recalled from memory):
```python
# Source: live check against backend/app/db/base.py's NAMING_CONVENTION, run 2026-09-09
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {  # copied verbatim from app/db/base.py
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

class Foo(Base):
    __tablename__ = "foo"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    __table_args__ = (
        sa.CheckConstraint("level IN ('a','b')", name="valid_level"),
    )

# Result (printed): CheckConstraint ck_foo_valid_level
```
The constraint's own `name=` kwarg (`"valid_level"`) is a short, human label — the naming
convention prefixes it with `ck_<table_name>_` automatically. **Do not pre-prefix it yourself**
(e.g. do not write `name="ck_physique_ratings_valid_rating_level"`) or the final name doubles up.
This matches the existing convention every other constraint type in this repo already follows
(`UniqueConstraint(..., name="uq_program_switch_tokens_nonce")` in `program.py` — the naming
convention prepends `uq_program_switch_tokens_` too, but that one's short name happens to already
equal the column name because of how `%(column_0_name)s` resolves for single-column uniques; for
`ck`, the token is `%(constraint_name)s`, which is *always* whatever you pass as `name=`, so the
short label is fully up to the model author, unlike `uq`/`fk`/`pk`).

**Concrete column example:**
```python
# app/db/models/physique.py — pattern to write, informed by app/db/base.py + app/normalization/muscles.py
from enum import StrEnum

class PhysiqueRatingLevel(StrEnum):
    """Mirrors PHYSIQUE_RATING_LEVELS verbatim (15-SPIKE-RESULT.md `## Recommended Constants`)."""
    MINIMAL = "Minimal"
    EMERGING = "Emerging"
    DEVELOPED = "Developed"
    WELL_DEVELOPED = "Well-Developed"
    STANDOUT = "Standout"

class PoseState(StrEnum):
    RELAXED = "relaxed"
    LIGHTLY_FLEXED = "lightly_flexed"

# on PhysiqueRating:
rating_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
not_assessable_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
__table_args__ = (
    sa.CheckConstraint(
        "rating_level IN ('Minimal','Emerging','Developed','Well-Developed','Standout')",
        name="valid_rating_level",
    ),
    # PHYS-02: exactly one of {rating_level, not_assessable_reason} is set, never both, never
    # neither -- see Pattern 2 below.
)
```
In the migration, write the identical `CHECK` SQL text via `sa.CheckConstraint(..., name=op.f("ck_physique_ratings_valid_rating_level"))` inside `op.create_table(...)` — mirror `0006`'s
`name=op.f("fk_...")` usage for foreign keys and unique constraints; `op.f()` is what makes the
already-resolved (prefixed) name safe to pass literally inside a migration, where the model's
declarative naming-convention machinery is not running.

### Pattern 2: "Not Assessable" as a sibling nullable column, not a sentinel value (PHYS-02)
**What:** `rating_level: str | None` and `not_assessable_reason: str | None` as two independent
nullable columns on `PhysiqueRating`, enforced by a `CHECK` so exactly one is populated per row.
**When to use:** Any place a numeric/enum measurement needs an explicit "we have nothing, and
here's why" escape hatch — this is the same posture `BodyMeasurement` takes toward missing metrics
(all-nullable columns, no forced default), generalized to also carry a *reason* string, which
`BodyMeasurement` doesn't need but PHYS-02 does.
**Example CHECK (PostgreSQL):**
```sql
-- Source: standard Postgres XOR-via-CHECK idiom; no library involved
CHECK (
    (rating_level IS NOT NULL AND not_assessable_reason IS NULL)
    OR
    (rating_level IS NULL AND not_assessable_reason IS NOT NULL)
)
```
Give this its own named constraint (e.g. `name="rating_xor_not_assessable"` → resolves to
`ck_physique_ratings_rating_xor_not_assessable`), separate from the `valid_rating_level` vocabulary
check — two independent facts, two independent constraints, matching D-04's "two independently
inspectable facts" philosophy applied one level down into the schema itself.

### Pattern 3: `ARRAY(String(N))` + element-membership `CHECK` (D-03)
**What:** `photo_angles_present: list[str]`, `ARRAY(String(16))`, `server_default=text("'{}'::varchar[]")`
mirroring `exercise_templates.secondary_muscle_groups` exactly for the column *shape*. The
**membership check is new** — `secondary_muscle_groups` has no CHECK at all today (it's validated
only in Python), so this phase does not have a literal CHECK-on-ARRAY precedent to copy, only the
column-shape precedent.
**Verified-safe CHECK syntax (PostgreSQL `<@` "is contained by" operator on arrays):**
```sql
-- Source: PostgreSQL array operators (standard, documented in the Postgres manual's array
-- functions/operators table) -- not project-specific, but not yet used anywhere in this repo,
-- so treat this exact syntax as [CITED: PostgreSQL array operator semantics] rather than
-- [VERIFIED: this repo], since no existing migration exercises it.
CHECK (photo_angles_present <@ ARRAY['front','back','side']::varchar(16)[])
```
`<@` (contained-by) accepts the empty array and any subset of the allowed values, which matches
the server_default of `'{}'` — a fresh observation before any angle is recorded round-trips
cleanly. Confirm this specific operator against a live Postgres in the plan's verification step
(the test container is `postgres:18-alpine` per `0006`'s docstring) since it has no existing
in-repo usage to point to as proof.

### Pattern 4: Header + child table, hand-written migration (mirrors `0006` exactly)
**What:** One `op.create_table` for the header, one for the child (FK `ondelete="CASCADE"` to the
header, since child rating rows have no independent lifecycle — deleting an observation removes
its ratings; note this differs from the *observation* row's own append-only/never-hard-deleted
posture, which is enforced by the write-path never issuing a `DELETE FROM physique_observations`,
not by the schema itself), a named partial-or-plain unique index for the "exactly one row per
group per observation" invariant, then the exact mirror-image `downgrade()` dropping the child
table before the header.
**Example (skeleton, following `0006`'s literal structure):**
```python
# Source: backend/migrations/versions/0006_user_program_history.py, adapted
def upgrade() -> None:
    op.create_table(
        "physique_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),  # see D-07 canonical_ref: Date, not
                                                                 # DateTime -- same BodyMeasurement
                                                                 # argument, local calendar day
        sa.Column("leanness_notes", sa.String(length=500), nullable=True),
        sa.Column("conditioning_notes", sa.String(length=500), nullable=True),
        sa.Column("symmetry_notes", sa.String(length=500), nullable=True),
        sa.Column("photo_angles_present", sa.ARRAY(sa.String(length=16)),
                  server_default=sa.text("'{}'::varchar[]"), nullable=False),
        sa.Column("pose_state", sa.String(length=16), nullable=False),
        sa.Column("conditions_note", sa.String(length=200), nullable=True),
        # D-01 -- PHYS-08 columns, built now, written by Phase 17:
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_reason", sa.String(length=200), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "pose_state IN ('relaxed','lightly_flexed')",
            name=op.f("ck_physique_observations_valid_pose_state"),
        ),
        sa.CheckConstraint(
            "photo_angles_present <@ ARRAY['front','back','side']::varchar(16)[]",
            name=op.f("ck_physique_observations_valid_photo_angles"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                 name=op.f("fk_physique_observations_user_id_users"),
                                 ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["physique_observations.id"],
                                 name=op.f("fk_physique_observations_superseded_by_id_physique_observations"),
                                 ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_physique_observations")),
    )
    op.create_table(
        "physique_ratings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("observation_id", sa.UUID(), nullable=False),
        sa.Column("muscle_group", sa.String(length=32), nullable=False),
        sa.Column("rating_level", sa.String(length=16), nullable=True),
        sa.Column("not_assessable_reason", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating_level IN ('Minimal','Emerging','Developed','Well-Developed','Standout')",
                            name=op.f("ck_physique_ratings_valid_rating_level")),
        sa.CheckConstraint(
            "(rating_level IS NOT NULL AND not_assessable_reason IS NULL) OR "
            "(rating_level IS NULL AND not_assessable_reason IS NOT NULL)",
            name=op.f("ck_physique_ratings_rating_xor_not_assessable"),
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["physique_observations.id"],
                                 name=op.f("fk_physique_ratings_observation_id_physique_observations"),
                                 ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_physique_ratings")),
        sa.UniqueConstraint("observation_id", "muscle_group",
                             name=op.f("uq_physique_ratings_observation_id_muscle_group")),
    )

def downgrade() -> None:
    op.drop_table("physique_ratings")
    op.drop_table("physique_observations")
```
Self-referential FK caveat: `physique_observations.superseded_by_id → physique_observations.id`
must be added via `sa.ForeignKeyConstraint` **inside the same `create_table`** (as shown) — SQLite
would need `op.create_table` then a separate `op.create_foreign_key` for a self-FK, but this
project only ever runs against Postgres in tests (`test_migrations.py`'s docstring: "SQLite would
prove nothing"), so the same-table inline form is safe and is exactly the form `0006` uses for its
`program_switch_tokens → user_program_history` cross-table FK.

### Pattern 5: Repository shape (mirrors `programs.py`)
**What:** Explicit `AsyncSession` parameter, no `session.commit()` inside the module, module
docstring stating "this module is the sole writer of `physique_observations`/`physique_ratings`."
**Example:**
```python
# Source: backend/app/db/repositories/programs.py, adapted shape
async def create_observation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    observed_on: dt.date,
    notes: ObservationNotes,          # leanness/conditioning/symmetry — a small dataclass/Pydantic model
    confounders: ConfounderMetadata,  # photo_angles_present, pose_state, conditions_note
    ratings: Sequence[RatingInput],   # exactly 19 entries, one per CanonicalMuscleGroup (D-07)
) -> PhysiqueObservation:
    """INSERT the header, then INSERT all 19 child rows, in this session. Caller commits."""
    ...

async def get_latest_observation(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueObservation | None:
    """Most recent non-superseded observation with its ratings loaded. `None` if none exist yet."""
    ...
```
`create_observation` should validate `len(ratings) == len(CanonicalMuscleGroup)` and that the set
of muscle groups covers every enum value exactly once **before** issuing any INSERT — a
`ValueError` raised early is cheaper to reason about than relying on the DB's unique constraint to
catch a caller bug after a partial write. Since D-07 makes 19 rows mandatory, favor eager loading
(`selectinload(PhysiqueObservation.ratings)`) in `get_latest_observation` so the read path returns
the complete shape in one round trip rather than lazy-loading 19 rows on attribute access.

### Anti-Patterns to Avoid
- **Native PostgreSQL `ENUM` type for `rating_level`/`pose_state`:** explicitly forbidden by
  PHYS-03/D-02. Breaks `test_migrations_round_trip` because `DROP TABLE` leaves the `pg_type`
  behind — Alembic's `downgrade()` for a table with a native enum column must also
  `sa.Enum(...).drop(op.get_bind())` explicitly, and forgetting that step (easy to forget, since
  `drop_table` alone looks complete) is exactly the failure mode this project's own test exists to
  catch.
- **A single `rating_value: str` column doubling as both the level and a `"not_assessable"`
  sentinel string:** rejected by D-07/PHYS-02's own framing — "the rating changed" and "conditions
  were comparable" must stay independently inspectable, and collapsing level + not-assessable into
  one column loses the reason text and makes the CHECK constraint express less than it could.
- **Skipping the 19-row invariant at the schema level and enforcing it only in the repository:**
  D-08 explicitly wants the `(observation_id, muscle_group)` uniqueness enforced by Postgres. A
  repository-only check is a race under concurrent writes (moot for a single-user app today, but
  the codebase's own convention — see `ProgramPeriod`'s partial unique index rationale — is to
  never rely on check-then-insert when a constraint can do the job).
- **Autogenerating migration `0007` and trusting the CHECK constraints came out right:** verify by
  reading the generated file against the hand-written pattern above, or write it by hand from the
  start (recommended, matches `0006`'s own stated reasoning).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bounded-vocabulary column validation | A custom Python validator decorator or a `@validates` SQLAlchemy hook as the *only* guard | A named `CHECK` constraint (Pattern 1) as the source of truth, with Pydantic/application validation as a fast-fail layer in front of it | FOUND-02: migrations are the sole authority over the schema. A CHECK constraint holds even if a future code path bypasses the repository (a raw `INSERT`, a data-fix script) |
| "Exactly one of two columns is set" invariant | An application-level `if both or neither: raise` scattered across every write path | A single `CHECK` constraint (Pattern 2) | One place to look, enforced regardless of which code path writes the row |
| Array-of-fixed-values validation | A JSON schema validator, a `pydantic` validator run only at the API boundary, or a Python `set()` membership check as the only guard | `ARRAY(String(N))` + Postgres `<@` CHECK (Pattern 3) | Matches the existing `exercise_templates.secondary_muscle_groups` shape and keeps the constraint in the DB layer per FOUND-02 |
| "One row per (observation, muscle_group)" | A `SELECT ... FOR UPDATE` then conditional `INSERT` in the repository | A named `UniqueConstraint`/index (D-08) | Same reasoning `ProgramPeriod`'s partial unique index already documents — PostgreSQL enforces it atomically, no race window |

**Key insight:** every "don't hand-roll" item in this phase reduces to "let PostgreSQL's own
constraint system be the single source of truth for an invariant, not scattered Python checks" —
this is not a new philosophy for this codebase, it is the same one `ProgramPeriod`'s partial
unique index and `FOUND-02` already establish; this phase just applies it to two invariant types
(`CHECK`, not just `UNIQUE`) that haven't been needed here before.

## Common Pitfalls

### Pitfall 1: Getting the `CHECK` constraint naming backwards
**What goes wrong:** Passing an already-prefixed name (e.g.
`name="ck_physique_ratings_valid_rating_level"`) as the `name=` kwarg on the model's
`CheckConstraint`, producing a doubled prefix once the naming convention's `%(constraint_name)s`
token substitutes it in (`ck_physique_ratings_ck_physique_ratings_valid_rating_level`), OR
conversely writing the fully-resolved name in the model but a short name in the migration (or vice
versa), causing `alembic check` (`test_no_pending_model_drift`) to see a name mismatch and fail.
**Why it happens:** Every other constraint type in this repo's precedent (`uq`, `fk`, `pk`) has
naming-convention tokens (`%(column_0_name)s`, `%(referred_table_name)s`) that are *derived from
the column/table*, not from a user-supplied string — so a developer pattern-matching from
`UniqueConstraint`/`ForeignKeyConstraint` precedent may not realize `ck`'s token is different in
kind (it echoes back whatever you typed).
**How to avoid:** In the **model**, always pass a short, unprefixed label to `CheckConstraint(name=...)`.
In the **migration**, always wrap the fully-resolved name in `op.f(...)` (matching every existing
`op.f("fk_...")`/`op.f("pk_...")`/`op.f("uq_...")` call in `0006`) — never write the migration's
constraint name as a bare string.
**Warning signs:** `test_no_pending_model_drift` (`alembic check`) fails with a constraint-name
diff that has nothing to do with the constraint's logic.

### Pitfall 2: Forgetting to update `test_metadata_contains_expected_tables`
**What goes wrong:** `backend/tests/test_db_models.py::test_metadata_contains_expected_tables`
asserts `set(Base.metadata.tables) == {...}` as an **exact equality**, not a subset check. Adding
`physique_observations`/`physique_ratings` models without updating this set fails the fast suite
immediately, on the very commit that adds the models — before the migration is even written.
**Why it happens:** The test lives in a file this phase's plan may not think to touch, since it's
framed as "the migration's job," but the assertion runs against `Base.metadata`, which reflects
the *model* files the moment they're imported.
**How to avoid:** Add `"physique_observations"` and `"physique_ratings"` to the expected set in
the same commit/task that adds the model files, and update the test's docstring (it currently
enumerates "Phase 8's single addition, plus Phase 12's two additions" — this phase is the next
such addition and the docstring convention expects a similar note).
**Warning signs:** `test_metadata_contains_expected_tables` fails with a `set()` diff showing the
two new table names as unexpected.

### Pitfall 3: `ARRAY` CHECK constraint syntax has no in-repo precedent to copy verbatim
**What goes wrong:** Assuming `secondary_muscle_groups`' existing column shape implies a known-good
CHECK syntax for arrays exists somewhere to copy. It does not — that column has zero CHECK
constraints today (validated only in Python). The `<@` operator syntax in Pattern 3 is standard
Postgres but untested in *this* codebase's migration test harness.
**Why it happens:** D-03's CONTEXT.md wording ("an established, already-tested column shape")
refers to the `ARRAY(String(N))` + `server_default` **column shape**, not to a CHECK constraint on
top of it — easy to conflate "the column type is proven" with "the constraint I'm adding to it is
proven."
**How to avoid:** Exercise the `<@` CHECK explicitly in a repository/migration test — insert one
valid array, one array containing a disallowed value (expect `IntegrityError`), and the empty-array
default — before considering this constraint done.
**Warning signs:** A silent no-op constraint (e.g. a syntax variant that Postgres accepts but never
actually restricts anything) would only surface if a test tries to insert a bad value and expects
a failure; if no such negative test exists, a broken CHECK never gets caught.

### Pitfall 4: Self-referential FK on `superseded_by_id` needs `ondelete="SET NULL"`, not `CASCADE`
**What goes wrong:** Copying the `ondelete="CASCADE"` pattern from every other FK in this schema
onto `superseded_by_id` would mean deleting a *newer, superseding* observation cascades into
nulling or deleting the *older, superseded* one it's supposed to just reference — actively wrong
for an append-only ledger. (This project never hard-deletes observations at all, per PHYS-08/D-01,
so this is a defense-in-depth correctness question, not a day-one operational risk.)
**Why it happens:** Every other FK in this migration and in `0006` uses `CASCADE`, making it the
path of least resistance to paste.
**How to avoid:** `ondelete="SET NULL"` specifically for `superseded_by_id` (D-01 already specifies
this — the risk is a planner defaulting to the copy-pasted `CASCADE` instead of reading D-01's
exact wording).
**Warning signs:** None at the schema level (both compile and pass `alembic check`) — this is a
semantic correctness pitfall, not a test-failure pitfall, unless a plan adds an explicit test for
it.

### Pitfall 5: `Not Assessable` reason field bound to 160 chars, notes fields to 500 — don't transpose
**What goes wrong:** D-04 and D-05 specify *different* caps for superficially similar "short
free-text justification" fields — `not_assessable_reason` is `String(160)` (D-05, mirrors the
spike's "20 words maximum" rating-reason convention) while the three observation-level notes are
`String(500)` (D-04) and `conditions_note` is `String(200)` (D-06). A planner or implementer
copy-pasting one column definition for another transposes these caps.
**Why it happens:** All four are "short text explaining something" fields, differing only in
scope (per-rating vs. per-observation) and in numeric cap — an easy detail to blur when writing
four similar column declarations back to back.
**How to avoid:** Write each cap with an inline comment citing its CONTEXT.md decision ID (D-04,
D-05, D-06) directly above the column, matching this codebase's own convention of citing the
decision that justifies a magic number (see `RECOMP_LOOKBACK_WEEKS = 12` in `recomposition.py` for
the house style).
**Warning signs:** A test asserting the exact cap per column (recommended) would catch a
transposition immediately; without such a test, this only surfaces if someone hits a real 200+
character reason in production and it's silently truncated or rejected.

## Code Examples

### Verified: SQLAlchemy 2.0 naming-convention resolution for `CheckConstraint`
```python
# Source: live execution against this repo's installed SQLAlchemy 2.0.52 and
# app/db/base.py's actual NAMING_CONVENTION, run 2026-09-09 (see Pattern 1 above for full script)
# Result: CheckConstraint ck_foo_valid_level
```

### `op.f()` usage for a hand-written migration's CHECK constraint name
```python
# Source: backend/migrations/versions/0006_user_program_history.py (existing op.f() usage for
# FK/UQ/PK names), pattern extended to CheckConstraint, which 0006 does not itself use
sa.CheckConstraint(
    "pose_state IN ('relaxed','lightly_flexed')",
    name=op.f("ck_physique_observations_valid_pose_state"),
)
```

### Existing `ARRAY` + `server_default` column shape to copy verbatim (shape only, not the CHECK)
```python
# Source: backend/app/db/models/exercise.py, ExerciseTemplate.secondary_muscle_groups
secondary_muscle_groups: Mapped[list[str]] = mapped_column(
    ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
)
```

## State of the Art

Not applicable in the usual sense — this phase touches no external library whose API has
changed. The one relevant "state of the art" note is internal to the project: this is the
**first** phase in BRETT to introduce a `CheckConstraint`. Nothing is being replaced; a new
pattern is being established. Future phases needing bounded-vocabulary columns should point back
to this phase's migration as the precedent, the same way `0006` is now cited as the precedent for
hand-written partial-index migrations.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `<@` array-containment operator is the right/idiomatic Postgres syntax for an element-membership CHECK on `ARRAY(String(N))`, and Postgres 18 (the test container's version per `0006`'s docstring) supports it without extension | Pattern 3 | If wrong, the CHECK either fails to create (caught immediately by the migration test) or silently accepts invalid values (caught only by a negative test — see Pitfall 3). Low risk: `<@` is core PostgreSQL array syntax, not an extension, and has been stable for many major versions |
| A2 | `selectinload` (or equivalent eager loading) is the right choice for `get_latest_observation` returning all 19 child ratings in one round trip | Pattern 5 | Low risk / reversible: worst case is N+1 queries on read, a performance nit fixable later without a schema change |

No claim in this document is tagged `[ASSUMED]` in the sense of "unverified training-data recall
presented as fact" for anything load-bearing to PHYS-03's CHECK-not-ENUM rule or the header/child
shape — those were verified directly against this repo's code and a live naming-convention
execution. A1/A2 above are the only two claims resting on general PostgreSQL/SQLAlchemy knowledge
rather than a direct read of this repo, and both are low-risk, cheaply test-caught if wrong.

## Open Questions (RESOLVED)

1. **Exact repository function surface beyond `create_observation`/`get_latest_observation`**
   - What we know: CONTEXT.md leaves this to Claude's Discretion, suggesting it "build what a
     Phase 17 MCP read/write tool will plausibly need."
   - What's unclear: whether Phase 16's own success criteria require more than "insert and read
     back" (they don't, literally), versus whether under-building now costs Phase 17 an extra
     repository-layer PR.
   - Recommendation: build exactly `create_observation` and `get_latest_observation` (or
     `get_recent_observations(limit=N)` mirroring `programs.py`'s `get_recent_periods`) for this
     phase — matches the literal success criteria without speculatively building Phase 17's
     supersede-write or diff-read functions, which depend on requirements (PHYS-08/PHYS-09) this
     phase explicitly does not implement.
   - RESOLVED: plan 16-03 built exactly `create_observation` and `get_latest_observation` — no
     more, no less. `get_recent_observations` was deliberately deferred to Phase 17.

2. **Whether `observed_on` (or equivalent header date field) needs its own uniqueness constraint**
   - What we know: `BodyMeasurement` keys on `(user_id, source, measured_on)` as a natural key
     with a `UniqueConstraint`. `ProgramPeriod` has no such per-date uniqueness (multiple periods
     can share a date only at a switch boundary).
   - What's unclear: whether two physique observations recorded the same calendar day should be
     structurally prevented, or whether PHYS-06 (Phase 17, single-call write) plus PHYS-08
     (supersede-for-correction) already covers the "recorded twice by mistake" case without a DB
     constraint.
   - Recommendation: no `UniqueConstraint` on `(user_id, observed_on)` for this phase — PHYS-08's
     supersede mechanism (Phase 17) is the documented correction path for a duplicate, and
     ROADMAP's five success criteria for this phase do not mention same-day uniqueness. Revisit
     only if Phase 17's planner finds it genuinely needed.
   - RESOLVED: plans add no `UniqueConstraint` on `(user_id, observed_on)`. Left as a seam for
     Phase 17 to revisit if the supersede mechanism proves insufficient.

## Environment Availability

Skipped — this phase has no external tool/service dependency beyond what's already running in CI
(the `postgres:18-alpine` test container, already used by every `@pytest.mark.integration` test in
this repo) and the already-installed Python/SQLAlchemy/Alembic stack. Nothing new to probe.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio (`asyncio_mode = "auto"`), per `pyproject.toml` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`), `backend/alembic.ini` for migrations |
| Quick run command | `uv run pytest -m "not integration"` (fast suite, no container) |
| Full suite command | `uv run pytest` (includes `@pytest.mark.integration`, spins the shared session-scoped Postgres container) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PHYS-01 | `PhysiqueRatingLevel` StrEnum has exactly the 5 spike-confirmed values, no invented intermediate | unit | `pytest backend/tests/test_db_models.py -k physique -x` | ❌ Wave 0 — new file/test needed |
| PHYS-02 | A rating row with `rating_level=None, not_assessable_reason=None` (or both set) is rejected by the DB | integration | `pytest backend/tests/test_db_physique.py::test_not_assessable_xor_rating -x -m integration` | ❌ Wave 0 |
| PHYS-03 | Header + child insert/read round-trips; `rating_level` uses `String`+CHECK not native ENUM; migration `0007` up/down leaves no orphaned `pg_type` | integration | `pytest backend/tests/test_migrations.py::test_migrations_round_trip -x -m integration` | ✅ (existing test, must keep passing unchanged per phase success criterion 2) |
| PHYS-04 | Three independently-capped note fields persist and round-trip at their exact caps (500/500/500) | integration | `pytest backend/tests/test_db_physique.py::test_note_field_caps -x -m integration` | ❌ Wave 0 |
| PHYS-05 | `photo_angles_present` restricted to `{front,back,side}`; `pose_state` restricted to `{relaxed,lightly_flexed}`; `conditions_note` independent of ratings | integration | `pytest backend/tests/test_db_physique.py::test_confounder_metadata -x -m integration` | ❌ Wave 0 |
| (all) | `Base.metadata` table set includes the two new tables | unit | `pytest backend/tests/test_db_models.py::test_metadata_contains_expected_tables -x` | ✅ existing test — **must be edited**, see Pitfall 2 |
| (all) | No new column trips the credential-shaped-name guard | unit | `pytest backend/tests/test_db_models.py -k credential -x` | ✅ existing test, should pass unmodified |

### Sampling Rate
- **Per task commit:** `uv run pytest -m "not integration"` (fast feedback on model shape, no container spin-up)
- **Per wave merge:** `uv run pytest` (full suite, including the migration round-trip and any new
  `test_db_physique.py` integration tests)
- **Phase gate:** Full suite green, plus explicit confirmation that
  `test_migrations_round_trip` and `test_no_pending_model_drift` pass unchanged (phase success
  criteria 2 and 5 name these tests directly)

### Wave 0 Gaps
- [ ] `backend/tests/test_db_physique.py` — new file, covers PHYS-02/04/05 and the header/child
      round-trip (PHYS-03's non-migration half)
- [ ] `backend/app/db/models/physique.py` — new model file (not a test gap, but a prerequisite the
      above tests import)
- [ ] `backend/app/db/repositories/physique.py` — new repository file, same prerequisite note
- [ ] `backend/tests/test_db_models.py::test_metadata_contains_expected_tables` — existing test,
      needs its expected-table set and docstring updated (Pitfall 2), not created fresh
- [ ] A `GoldenBuilder`-style fixture helper for constructing a full 19-rating observation in
      tests, mirroring `conftest.py`'s existing `golden_workout`/`GoldenBuilder` pattern — check
      whether `conftest.py` already has room for this or whether it needs a small addition; not
      strictly required (tests can hand-build 19 rows inline) but reduces repetition across the
      PHYS-02/04/05 test cases above

## Security Domain

`security_enforcement` is absent from `.planning/config.json` — treated as enabled per the
project's own default.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase has no MCP/API surface at all (explicit boundary) |
| V3 Session Management | No | Same reason |
| V4 Access Control | Yes | Every repository function must take `user_id` and scope every query/insert to it — mirrors `programs.py`'s explicit `user_id` predicate on every statement, and the module docstring note in `programs.py` about ASVS V4 belt-and-braces scoping |
| V5 Input Validation | Yes | `CHECK` constraints (Patterns 1-3) are the DB-layer control; Pydantic-level validation of the same vocab at the future MCP boundary (Phase 17) is the second layer, not this phase's job to build but the schema must not preclude it |
| V6 Cryptography | No | No secrets, tokens, or cryptographic material anywhere in this phase's schema (confirmed by the `token`/`key`/`secret` naming-guard test already in the fast suite, which the phase's new columns must not trip) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant read/write (a future multi-user query missing a `user_id` predicate) | Elevation of Privilege / Information Disclosure | Every `physique.py` function takes `user_id` explicitly and includes it in every WHERE/JOIN predicate — schema must not preclude multi-user later (REQUIREMENTS.md "Out of Scope" table), even though v1 has exactly one seeded user |
| Free-text note fields used as an injection vector | Tampering | Not applicable at the SQL layer — SQLAlchemy's parameterized `insert()`/`values()` (already the exclusive pattern in `programs.py`) prevents SQL injection by construction; the only "injection"-adjacent risk is Phase 18's narrative-rendering rule (RPT-05) that Claude-authored notes must never be echoed into `build_narrative`'s output — out of this phase's scope but worth naming so a future note-handling change doesn't accidentally violate it |
| A CHECK constraint that silently fails to restrict (Pitfall 3) | Tampering (data integrity) | Explicit negative-path tests (insert a disallowed value, expect `IntegrityError`) rather than trusting the constraint compiles |

## Sources

### Primary (HIGH confidence — direct repo reads and live execution)
- `backend/app/db/base.py` — `NAMING_CONVENTION`, `Base`, `TimestampMixin`
- `backend/app/db/models/program.py` — `ProgramPeriod`/`ProgramSwitchToken`, partial unique index precedent
- `backend/app/db/repositories/programs.py` — repository shape, sole-writer docstring convention
- `backend/app/db/models/exercise.py` — `ARRAY(String(32))` + `server_default` column shape
- `backend/app/db/models/body.py` — nullable-metrics / `Date` vs `DateTime` precedent
- `backend/app/normalization/muscles.py` — `CanonicalMuscleGroup` (19 values), `StrEnum` usage pattern
- `backend/app/analytics/recomposition.py` — `INTERPRETATION_DISCLAIMER`/`RECOMP_LOOKBACK_WEEKS` named-constant convention
- `backend/migrations/versions/0006_user_program_history.py` — hand-written migration precedent, `op.f()` usage
- `backend/tests/test_migrations.py` — `test_migrations_round_trip`, `test_no_pending_model_drift`
- `backend/tests/test_db_models.py` — `test_metadata_contains_expected_tables` (exact-equality gotcha), credential-shaped-column guard
- `backend/tests/test_db_program_history.py` — repository test shape to mirror
- `backend/tests/test_mcp_isolation.py` — `_WRITE_ALLOWLIST`, `_WRITE_IMPORT` (confirms this phase's "no MCP surface" boundary is real and enforced elsewhere)
- `backend/tests/conftest.py` — fixture conventions (`alembic`, `restore_schema`, `engine`, `GoldenBuilder`)
- `pyproject.toml` (repo root) — pytest markers, `asyncio_mode`, Ruff target
- Live execution: `.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"` → `2.0.52`
- Live execution: naming-convention resolution script (Pattern 1) → `CheckConstraint ck_foo_valid_level`
- `.planning/phases/16-physique-data-model-repository/16-CONTEXT.md` — all D-01 through D-08 decisions, canonical refs
- `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` — `PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_RATING_ANCHORS`, `PHYSIQUE_MIN_ELAPSED_DAYS`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA`
- `.planning/REQUIREMENTS.md` — PHYS-01 through PHYS-08 exact wording
- `.planning/STATE.md` — milestone-gate decisions table

### Secondary (MEDIUM confidence)
- None needed — no WebSearch/Context7 lookups were required for this phase; everything load-bearing came from direct repo inspection or live code execution.

### Tertiary (LOW confidence — flagged, not authoritative)
- Postgres `<@` array-containment operator as the CHECK syntax for `photo_angles_present`
  (Pattern 3, Assumption A1) — standard PostgreSQL syntax, `[CITED: PostgreSQL array operators]`
  from training knowledge, not verified by running it against this repo's actual Postgres
  container in this research session. Verify in the plan's own test-writing step.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all versions confirmed against the live venv
- Architecture (header/child, repository shape, migration structure): HIGH — every pattern has a
  direct, currently-passing precedent in this repo (`0006`, `programs.py`, `ProgramPeriod`)
- CHECK constraint mechanics (naming, XOR pattern): HIGH for naming (live-verified), MEDIUM for the
  array `<@` operator specifically (correct per general Postgres knowledge, not yet exercised in
  this codebase — flag for the plan's verification step)
- Pitfalls: HIGH — Pitfalls 1, 2, 4, 5 are derived directly from reading this repo's own
  conventions and test assertions, not speculation

**Research date:** 2026-09-09
**Valid until:** No expiry driven by external library drift (nothing external was researched).
Re-verify only if `backend/app/db/base.py`'s `NAMING_CONVENTION` or the SQLAlchemy version changes
before this phase is planned.

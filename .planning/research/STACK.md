# Stack Research

**Domain:** Longitudinal physique-observation ledger (BRETT v2.1) — a new table + a new MCP write
tool storing Claude-produced per-muscle-group ratings and free-text notes; no image ever touches
the backend.
**Researched:** 2026-09-05
**Confidence:** HIGH — every claim below is backed by either (a) reading this codebase's own
precedents and their docstrings, (b) executing the actual installed `mcp==2.0.0` +
`pydantic==2.13.4` in this project's venv and inspecting real generated JSON Schema and real
validation errors, or (c) current official Alembic/SQLAlchemy documentation and GitHub issue
threads, dated and quoted.

## Headline Finding: No New Dependency

**Zero new runtime dependencies are needed for this feature.** `SQLAlchemy 2.0.52` +
`PostgreSQL` (Neon) + `Pydantic 2.13.4` + `mcp==2.0.0`, already in `pyproject.toml`, are
sufficient for storage, validation, MCP schema generation, and deterministic diff analytics.
No JSONB, no Postgres `ENUM` type, no image/vision/storage library (excluded by the milestone
gate and confirmed unnecessary independently below), no new third-party package of any kind.
The only new artifacts are: one Alembic migration, one or two new SQLAlchemy models, a handful
of new `Pydantic`/`StrEnum` types in `app/analytics/schemas.py`, and a new
`app/analytics/physique.py` module — all authored against existing library versions.

## Recommended Stack

### Core Technologies — unchanged, reused

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SQLAlchemy 2.0 (`Mapped[]`) | 2.0.52 (pinned) | New `physique_observations` + `physique_observation_ratings` tables | Already the ORM for every other table; no reason to reach for anything else |
| PostgreSQL (Neon) | current | Storage, `CHECK` constraint enforcement | Already the sole datastore; the feature needs no new extension, no `pgvector`, no full-text search |
| Pydantic 2.13.4 (`StrEnum`) | 2.13.4 (pinned) | Rating enum, MCP tool I/O schemas | Identical pattern to `TrendVerdict`, `RecompositionStatus`, `TrainingProgram` already in `app/analytics/schemas.py` |
| Alembic 1.19.1 | 1.19.1 (pinned) | One new migration for two tables | Same `op.create_table` idiom as `0006_user_program_history.py`; nothing version-specific is required beyond what's already pinned |
| `mcp==2.0.0` | 2.0.0 (pinned) | New write tool `fitness_record_physique_observation` (name TBD) + a read tool for history/diff | Verified directly (see Question 2 below) to generate correct, enforced JSON Schema for the exact shapes this feature needs |

### Supporting Libraries — none new

No new supporting library is required. `decimal.Decimal` (stdlib), `enum.StrEnum` (stdlib), and
the project's existing `_AnalyticsModel` base in `app/analytics/schemas.py` cover every need.

### Development Tools — unchanged

`pytest` + `pytest-asyncio` + `testcontainers[postgres]` + `time-machine`, already pinned, are
sufficient: the new migration gets the same real-Postgres round-trip test as every prior one
(`test_migrations_round_trip`), and the diff analytics get the same time-machine-frozen,
known-fixture unit tests as `plateaus.py`/`recomposition.py`.

## Installation

```bash
# Nothing to add. pyproject.toml and uv.lock are unchanged by this milestone.
```

## Answers to the Research Questions

### Q1 — Storage shape for ~19 per-observation ratings

**Recommendation: one row per `(observation_id, muscle_group)` in a child table — the
`health_daily_metrics` precedent, not the `body_measurements` precedent. No JSONB. No Postgres
`ENUM`. A plain `String` column for the rating, the same way `health_daily_metrics.metric` and
`user_program_history.program` are plain `String` columns validated only at the application
layer.**

**Why the EAV/child-table (`health_daily_metrics`) shape fits, not the wide-row
(`body_measurements`) shape:**

`body_measurements`'s own docstring gives the exact condition under which a wide row is correct:
*"Hevy's `/v1/body_measurements` returns one object per calendar date carrying all 17 metrics
and has NO id field at all... the date IS the identity."* The wide row is a direct mirror of one
external API's fixed-shape payload. Physique ratings have no such source: they are Claude's own
judgement, muscle-by-muscle, and nothing guarantees every observation rates all 19 groups (a
photo may not show calves, or the model may decline to rate a muscle it can't see). A wide row
with 19 nullable columns would need `NULL` to mean two different things — "not rated this time"
vs. "rated as the lowest category" — the exact ambiguity `body_measurements` avoids only because
Hevy's payload always carries all-or-nothing columns per date.

`health_daily_metrics`'s docstring states the shape this feature actually needs: *"ONE row per
(user, source, metric, ..., local_day)"* with a `String(64) metric` column and explicitly **NO
Postgres enum**, chosen because the metric vocabulary is a closed, evolving list validated in
Python, not in the database schema. A `physique_observation_ratings` child table with columns
`(id, observation_id FK, muscle_group String, rating String)` gives:

- **Partial observations for free** — a photo that doesn't show forearms simply has no row for
  `forearms`; no sentinel value, no nullable-column ambiguity.
- **No migration when the taxonomy is revisited** — `CanonicalMuscleGroup` in
  `app/normalization/muscles.py` already carries the warning *"Changing this enum after data
  exists costs a data migration of exercise_muscles — it is not a free edit"* for the 19-value
  taxonomy. A wide-column table would compound that cost with a second migration (add/rename a
  column) every time the taxonomy changes; a child table absorbs a taxonomy change as an
  application-layer enum edit only, exactly as `health_daily_metrics.metric` already does for
  Apple Health's evolving metric list.
- **Direct queryability for diff analytics** — `analytics/physique.py`'s per-muscle
  improved/unchanged/regressed diff is naturally `SELECT muscle_group, rating FROM
  physique_observation_ratings WHERE observation_id = :prev` joined against the same for
  `:current`. A JSONB blob would need `jsonb_each`/path-extraction to get the same join, adding
  complexity with no benefit since there is no unstructured or variable-key data here — the key
  set (19 canonical muscle groups) is exactly what a relational column already models.
- **Reuse of the existing enum, not a new one** — `muscle_group` should be typed against the
  *existing* `CanonicalMuscleGroup` from `app/normalization/muscles.py`, the same enum
  `exercise_muscles` already uses, so "which muscles are undertrained" (volume) and "which
  muscles are underdeveloped" (physique) are answerable against one shared vocabulary rather
  than two that could drift apart. This is also why `analytics/physique.py`'s cross-reference
  against `fitness_get_muscle_group_volume` is a plain join on `muscle_group`, not a translation
  layer.

**Why JSONB is the wrong choice here specifically (not a general JSONB-is-bad claim):** JSONB is
the right tool when the key set is genuinely open-ended or sparse in a way relational columns
model poorly. Here the key set is a *closed, already-enumerated* 19-value taxonomy the project
maintains as code — the textbook case for normalized rows, not a schemaless blob. A JSONB column
also cannot carry a column-level `CHECK`/foreign-key-style guarantee that every key is one of the
19 canonical values or that every value is one of the rating levels; enforcing that inside JSONB
needs a Postgres `CHECK` with a `jsonb` path/`?`-operator expression per key, which is more
migration and query complexity than the child table for no corresponding benefit, and would be
new ground for a project that has never used a JSONB column (`grep` across `app/db/models/`
confirms zero existing JSONB columns).

**A Postgres `ENUM` type is also the wrong choice — reuse the plain-`String` + app-enum
pattern the codebase already uses three times over, with zero exceptions.** See Q4 below for the
concrete Alembic/Postgres reason this is not just stylistic consistency but avoids a real,
documented migration hazard.

**Recommended shape:**

```
physique_observations
  id UUID PK
  user_id UUID FK -> users.id
  observed_on DATE NOT NULL         -- calendar day, mirrors measured_on/started_on precedent
  leanness_notes VARCHAR(N) NULL    -- bounded free text
  conditioning_notes VARCHAR(N) NULL
  symmetry_notes VARCHAR(N) NULL
  created_at / updated_at (TimestampMixin)

physique_observation_ratings
  id UUID PK
  observation_id UUID FK -> physique_observations.id ON DELETE CASCADE
  muscle_group String(24) NOT NULL   -- CanonicalMuscleGroup.value, reused, not re-declared
  rating String(24) NOT NULL         -- new DevelopmentRating StrEnum, see Q3
  UNIQUE (observation_id, muscle_group)
```

This mirrors `user_program_history` + `program_switch_tokens`'s parent/child pattern
structurally (one parent event row, a related table for its fine-grained detail) as much as it
mirrors `health_daily_metrics` for the per-metric-row shape — both existing precedents agree.

### Q2 — `mcp==2.0.0` schema generation for enum-keyed inputs/outputs (verified against the
installed package, not training data)

Ran real schema-generation and real tool-call validation against this project's own
`.venv` (`mcp==2.0.0`, `pydantic==2.13.4`) via `uv run python`. Three candidate shapes for "a set
of ~19 (muscle_group, rating) pairs" were tested end-to-end through `MCPServer.tool()`,
`list_tools()`, and `call_tool()`:

**1. `dict[MuscleGroup, DevelopmentRating]`** — generates valid but *unusual* JSON Schema:

```json
"ratings": {
  "type": "object",
  "propertyNames": { "$ref": "#/$defs/MuscleGroup" },
  "additionalProperties": { "$ref": "#/$defs/DevelopmentRating" }
}
```

This **does** work end-to-end in this project's own venv: an invalid key (`"bogus_muscle"`) or
an invalid value (`"super_jacked"`) both correctly raised a `ToolError` server-side with a clear
Pydantic enum-validation message before any handler code ran. So the SDK-and-Pydantic pairing
itself has no bug here. **The risk is upstream of the SDK**, at the client: `propertyNames` +
`$ref` is an uncommon JSON Schema combination, and there is a live, currently-unresolved
`modelcontextprotocol/python-sdk` issue (**#1373**, opened 2025-09-17, still open/unconfirmed as
of this research) reporting that **`$ref`-based enum schemas specifically** can produce
client-side quoting/parsing mismatches with Claude Desktop, as opposed to `Literal`-based
(inlined) enum schemas, which do not hit the same code path. A `propertyNames`-constrained dict
is `$ref`-based by construction (see the schema above), so it inherits whatever risk plain
`$ref` enums carry, on top of being a rarer schema shape overall. **Do not use this shape for the
tool's input.**

**2. `list[tuple[MuscleGroup, DevelopmentRating]]`** — generates positional-tuple JSON Schema
(`prefixItems`, `minItems`/`maxItems: 2`) — also verified to parse and validate correctly, but
`prefixItems` tuples are unfriendly for a model to *produce* (no field names to anchor a
description on) and equally exotic as a schema shape. **Not recommended.**

**3. `list[MuscleRating]` where `MuscleRating` is a small Pydantic model with two named enum
fields (`muscle_group`, `rating`)** — generates the plainest possible schema: an array of
`$ref`-to-object, each object with two named, described, `$ref`-to-enum properties. No
`propertyNames`, no `prefixItems`, no dict-shaped surface at all. This is **structurally
identical** to the schema shape `BodyMeasurementMetric` and `TrainingProgram` already produce
today for a *single* enum-typed argument, scaled up to a list of small objects — not a new kind
of schema this codebase or this SDK version has never exercised, just more of the same kind.
Verified: `model_json_schema()` output is a standard array-of-objects schema with clean
`$defs`/`$ref` for the two enums nested one level inside each list item, not on the
`propertyNames` axis.

**Recommendation: use shape 3 — `list[MuscleRating]` (a list of small `{muscle_group, rating}`
objects) — for both the write tool's input and any response type that echoes ratings back
(e.g., "prior observation" context).** This is the shape least likely to intersect the one
concretely documented client-side enum-schema fragility (#1373) in the wild, is the most
model-friendly to produce (named fields with per-field descriptions vs. positional tuples or
free-form object keys), requires no unusual JSON Schema keyword, and needs no code this SDK
version doesn't already prove works for `Annotated[StrEnum, Field(...)]` arguments — see
`fitness_switch_training_program`'s `program: Annotated[TrainingProgram, Field(...)]`, already
live in production and proven end-to-end against a real Claude Desktop connector in Phase 12
(`.planning/PROJECT.md` Key Decisions).

**A general enum-in-tool-schema caution worth flagging for the roadmapper, independent of this
specific shape decision:** issue **#1373** and a second, separately-verified issue
(**anthropics/claude-ai-mcp#408**) both document real fragility in how Claude's MCP connector
handles enum-bearing tool schemas — #1373 is a client quoting mismatch on `$ref`-based enums,
#408 is Claude.ai's connector rejecting a call and *misreporting* an unrelated field as the
invalid enum. Neither is disqualifying (this project already ships a live `StrEnum` write-tool
argument successfully), but both argue for **testing the actual new tool's schema against a real
Claude Desktop/Web session before considering it done**, the same spike discipline Phase 12 and
Phase 13 already applied to this project's other novel MCP surfaces (`13-SPIKE-RESULT.md`).

### Q3 — Ordinal rating scale: `SmallInteger` + `CHECK`, or a `StrEnum` + `String`?

**Recommendation: a `StrEnum`-backed `String` column (e.g. `DevelopmentRating` with members like
`UNDERDEVELOPED` / `LAGGING` / `ADEQUATE` / `WELL_DEVELOPED` / `STRENGTH`, exact labels TBD at
requirements stage) — not a raw `SmallInteger` scale — because the feature never needs numeric
averaging or a difference computed by subtraction.**

The milestone's diff analytics are explicitly **"improved / unchanged / regressed per muscle
group"** — a three-way categorical *comparison between two observations*, not an arithmetic
delta and not an average across many observations. Every other categorical classification
output in this codebase (`TrendVerdict`, `PlateauConfidence`, `ProgressionSignal`,
`RecompositionStatus`) is a labelled `StrEnum`, never a raw integer scale, specifically because
(their own docstrings) the label itself is part of the contract Claude reads and narrates —
`RecompositionStatus`'s docstring: *"Exactly seven values — an eighth would change the
contract."* A bare `1..5` integer would need a translation layer back to words for the
narrative anyway (`build_narrative`'s existing banned-token/determinism constraints), so the enum
*is* the natural representation, not an intermediate one.

**Ordinal comparison without arithmetic:** `improved`/`unchanged`/`regressed` needs only that the
rating enum have a defined *order*, not that it be numeric. This is exactly how
`app/normalization/muscles.py` already handles a similar need — `MuscleRole`'s
`DIRECT`/`INDIRECT` distinction and its "1.0/0.5 weighting lives here as a DEFAULT, never as a
stored column" comment demonstrate the project's established pattern: rank/weight mappings live
in **Python code in the analytics layer**, not in the stored column. `analytics/physique.py`
should hold a `_RATING_RANK: Mapping[DevelopmentRating, int]` (plain `int`, not `Decimal` — see
next paragraph for why that's fine) and diff by comparing two looked-up ranks, exactly the shape
`recomposition.py`'s existing label-matrix pattern already takes for turning several classified
inputs into one classified output.

**Does this ever get averaged, and does the no-float guard apply?** No — and this is worth
stating plainly because it's a genuine, checkable non-finding rather than an assumption. The
milestone's stated analytics are a **pairwise diff between exactly two observations** (the
current one and "its last observation," per the milestone's drift-mitigation design), not a
rolling average, weekly aggregate, or trend-line the way `bodyweight.py`'s 7/14/30-day averages
are. There is therefore no place in this feature where a rating scale would ever be summed and
divided. If a future milestone *did* want to average ratings across many observations, the
project's existing no-float discipline (`test_analytics_declares_no_float`, a static regex guard
over `app/analytics/*.py` banning `float(`, `: float`, `-> float`) would require whatever numeric
representation is chosen for that future average to be `Decimal`, matching every other averaged
quantity in the codebase (`body_measurements`' `Numeric` columns, `HealthDailyMetric.value`'s
`Numeric(14, 4)`) — but that need does not exist in this milestone's stated scope, so introducing
a numeric column now to pre-empt it would be exactly the kind of premature schema commitment
`body_measurements`' own "manual entry column exists now so that phase needs no migration"
precedent argues *for* only when a near-certain future need is already known; here it is not
stated as scope at all.

**Net: no `SmallInteger`, no `CHECK` numeric-range constraint, no `Decimal` column for the
rating itself.** A `String` column validated by a `StrEnum`, ranked by a Python-side lookup
table local to `analytics/physique.py`, is both sufficient and the pattern already proven
everywhere else in this codebase.

### Q4 — Alembic: adding this table, and whether a `CHECK`/`ENUM` choice affects reversibility

**No Postgres `ENUM` type, for a concrete, verified reason beyond "stay consistent with
precedent": `DROP TABLE` does not drop a Postgres `ENUM` type it was using, and this project's
own `test_migrations_round_trip` test (`downgrade base` → re-`upgrade head` in the same test
session, asserting `downgrade base` leaves *only* `alembic_version`) would break on exactly this
gap.** This is a long-standing, still-open, well-documented Alembic limitation — confirmed via
`sqlalchemy/alembic` GitHub issues **#754** ("Alembic is not dropping enums") and **#886**
("Migration downgrade doesn't drop type created by Enum"), both about the same root cause:
`op.drop_table()` removes the table but leaves the `CREATE TYPE ... AS ENUM (...)` object behind
in `pg_type`, so a subsequent `upgrade head` in the same database fails with
`DuplicateObject: type "..." already exists`. Third-party packages
(`alembic-postgresql-enum`) exist specifically to paper over this gap because Alembic core does
not — evidence that this is a real, common footgun, not a theoretical one. Using a plain
`String` column sidesteps the entire class of problem: a `String` column is dropped completely
and cleanly the moment its table is, with nothing left in the catalog, exactly like every other
`String`-typed closed-vocabulary column in this schema today (`source`, `metric`, `program`).

**A `CHECK` constraint, by contrast, is low-friction and genuinely worth adding here as
defense-in-depth — verified against the actual pinned Alembic 1.19.1 docs, not assumed.**
Alembic's own current documentation states autogenerate **does** detect the addition/removal of
a **named** `CHECK` constraint (unnamed ones are invisible to it, which is why this project's
`db/base.py` naming convention already reserves a `ck` token —
`"ck": "ck_%(table_name)s_%(constraint_name)s"` — even though **zero** `CHECK` constraints exist
in the codebase yet, confirmed by grep across every model and migration file). The one real
limitation — autogenerate cannot detect a *change to the expression text* of an existing
same-named `CHECK` constraint, only its addition/removal — does not bite on a brand-new table's
brand-new constraint. And because a `CHECK` constraint (unlike an `ENUM` type) is dropped
automatically as part of `DROP TABLE`, it introduces no analog of the `ENUM` reversibility trap:
`downgrade()` here is just `op.drop_table(...)`, same one-line shape as `0006`'s `downgrade()`.

**Recommendation:** add `CHECK (rating IN ('underdeveloped', 'lagging', 'adequate',
'well_developed', ...))` and `CHECK (muscle_group IN (...19 values...))` as named constraints on
`physique_observation_ratings`, hand-written in the migration (matching `0006`'s
already-established practice of hand-writing anything autogenerate is unreliable for — partial
indexes there, and here a `CHECK` whose value list must exactly track two Python enums rather
than being independently reinvented). This is a genuine improvement over the existing
`health_daily_metrics`/`user_program_history` precedent, not just a repeat of it: those tables
rely on app-layer validation alone because their vocabularies (`metric`, `program`) are either
externally sourced or small; this feature's two vocabularies are entirely BRETT's own and are
the sole write surface of a subjective, Claude-authored value, so a second line of defense at
the database layer is cheap and appropriate. It must not be the *only* line of defense — the
`DevelopmentRating`/`CanonicalMuscleGroup` `StrEnum`s at the MCP/Pydantic layer remain the
primary gate, exactly as `TrainingProgram`'s docstring frames it: *"a hallucinated fourth program
is rejected at the schema layer before any code in this repo runs."*

**Net Alembic guidance:** `alembic revision --autogenerate` will correctly emit `create_table`
for both new tables and correctly emit the two named `CHECK` constraints as long as they are
declared on the SQLAlchemy model (not just hand-added to the migration) — same discipline
`user_program_history`'s partial-unique-index comment already documents: *"declared... on the
model as well as in the migration so `alembic check` sees no divergence."* No `sa.Enum`, no
autogenerate special-casing, no non-reversible migration risk exists in this design.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|--------------|-------------|--------------------------|
| Child table, one row per `(observation, muscle_group)` | JSONB column on one wide observation row | Only if the rated-muscle set became genuinely open-ended/user-defined rather than the fixed 19-value taxonomy this project already maintains as code — not the case here |
| Child table (EAV-style) | Wide row, 19 nullable columns (the `body_measurements` shape) | Only if every observation always rated every one of a small, permanently-fixed set of columns sourced from one external fixed-shape API — the opposite of "Claude may not rate every muscle every time" |
| `String` + app-layer `StrEnum` + a named `CHECK` constraint | Postgres native `ENUM` type | Never, for the concrete `DROP TABLE`-leaves-orphaned-type reason in Q4 — this is not a style preference, it is a documented Alembic/Postgres interaction that breaks this project's own migration round-trip test |
| `list[MuscleRating]` (list of small `{muscle_group, rating}` objects) for MCP I/O | `dict[MuscleGroup, DevelopmentRating]` | Only if the client-side enum-schema fragility in modelcontextprotocol/python-sdk#1373 is confirmed resolved for `propertyNames`+`$ref` dict schemas specifically — unverified as of this research |
| `StrEnum` rating with a Python-side rank lookup for diffing | `SmallInteger` + `CHECK (rating BETWEEN 1 AND 5)` | Only if the narrative/response layer wanted to expose a numeric score directly (e.g., "3.2/5") rather than a named category — not implied by "improved/unchanged/regressed" or by any other categorical output in this codebase |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Postgres native `ENUM` type (`sa.Enum(..., native_enum=True)` or `postgresql.ENUM`) | `DROP TABLE` does not drop the underlying `pg_type`; verified via `sqlalchemy/alembic` issues #754 and #886. Breaks this project's own `test_migrations_round_trip` (`downgrade base` → `upgrade head` in one session) with `DuplicateObject: type already exists` on the second upgrade | `String` column + Python `StrEnum` validation at the Pydantic/MCP layer, exactly like `source`, `metric`, `program` today |
| JSONB column for the rating set | The key set (19 canonical muscle groups) is closed and already enumerated in code — the textbook normalized-row case, not the schemaless-blob case; also loses the direct-join queryability `analytics/physique.py`'s diff and cross-reference need, and no JSONB column exists anywhere else in this schema | A child table, one row per `(observation_id, muscle_group)` |
| `dict[MuscleGroup, DevelopmentRating]` as a top-level MCP tool argument or return field | Generates `propertyNames`/`additionalProperties`+`$ref` JSON Schema — verified to work in this SDK version, but an uncommon shape that inherits the unresolved `$ref`-enum client fragility documented in python-sdk#1373 | `list[MuscleRating]` — a list of small named-field objects, the same schema shape `BodyMeasurementMetric`/`TrainingProgram` already prove works live |
| `SmallInteger` + numeric `CHECK` for the rating scale | No averaging or subtraction ever happens on it (diff is a 3-way categorical comparison, not arithmetic); every other categorical classification in this codebase is a labelled `StrEnum`, and the narrative layer needs words, not numbers, anyway | `StrEnum`-backed `String` column + a Python-side rank lookup local to `analytics/physique.py`, mirroring `muscles.py`'s existing direct/indirect weighting pattern |
| Any image-handling, object-storage, or server-side vision/AI library (Pillow, GCS client, Anthropic SDK, etc.) | Explicitly out of scope per the milestone gate — BRETT never receives or stores an image; confirmed independently here too, since nothing in the storage/MCP/analytics design touched above requires one | N/A — the milestone's "no image ever" boundary holds all the way through the stack |

## Stack Patterns by Variant

**If a future milestone wants a numeric physique score (not just a category) shown in the
narrative:**
- Add a `Decimal`-typed derived score computed in `analytics/physique.py` from the rank lookup,
  never a `float`, and never a stored column — same "derived at query time, not persisted" stance
  `muscles.py` already takes for direct/indirect weighting.

**If the muscle taxonomy changes before this feature ships:**
- The child-table design absorbs it as a one-line `CanonicalMuscleGroup` edit plus (per that
  enum's own docstring) a data migration for any already-rated muscle groups — no schema change
  to `physique_observation_ratings` itself, unlike the wide-row alternative.

**If Anthropic resolves modelcontextprotocol/python-sdk#1373 (the `$ref`-enum client quoting
issue) with a documented fix:**
- Re-evaluate whether `dict[MuscleGroup, DevelopmentRating]` becomes viable for a more compact
  wire format; until then, the list-of-objects shape recommended above is the safer default and
  costs nothing in expressiveness.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `mcp==2.0.0` | `pydantic==2.13.4` | Verified live in this project's venv: `StrEnum`-keyed `dict`, `list[tuple[Enum, Enum]]`, and `list[BaseModel-with-enum-fields]` all produce valid JSON Schema and all correctly reject invalid enum keys/values with a `ToolError` at the MCP layer before any tool code runs |
| Alembic `1.19.1` | PostgreSQL (Neon, current major) | Autogenerate detects add/remove of a **named** `CHECK` constraint (verified against the pinned version's own docs); does not detect an expression-text change on an existing same-named constraint — irrelevant for a brand-new table's brand-new constraint |
| SQLAlchemy `2.0.52` native `postgresql.ENUM`/`sa.Enum` | Alembic `1.19.1` `op.drop_table` | **Incompatible in the sense that matters here** — dropping the table does not drop the type, confirmed via `sqlalchemy/alembic` #754/#886, both still open. Do not introduce a native enum type into this schema |

## Sources

- This repo, read directly: `backend/app/db/models/health.py`, `backend/app/db/models/body.py`,
  `backend/app/db/models/program.py`, `backend/app/db/base.py`, `backend/app/analytics/schemas.py`,
  `backend/app/normalization/muscles.py`, `backend/app/mcp/tools/program_switch.py`,
  `backend/app/mcp/tools/body.py`, `backend/tests/test_migrations.py`,
  `backend/tests/test_analytics_isolation.py`, `backend/migrations/versions/0006_user_program_history.py`
  — HIGH, primary evidence for every precedent-based claim above
- `uv run python` against the installed `mcp==2.0.0` + `pydantic==2.13.4` in this project's own
  `.venv`: `MCPServer.tool()`, `list_tools()`, `call_tool()` exercised directly for
  `dict[Enum, Enum]`, `list[tuple[Enum, Enum]]`, and `list[BaseModel]` shapes, including
  deliberately invalid inputs — HIGH, direct execution against the exact pinned versions this
  project ships
- `grep` across `backend/app/db/models/*.py` and `backend/migrations/versions/*.py` for
  `CheckConstraint`, `postgresql.ENUM`, `sa.Enum`, `JSONB` — zero matches, confirmed 2026-09-05 —
  HIGH, exhaustive over the actual current schema
- https://alembic.sqlalchemy.org/en/latest/autogenerate.html (matches pinned `1.19.1`) — named
  `CHECK` constraint add/remove detection, and the same-name-expression-change blind spot — HIGH
- https://github.com/sqlalchemy/alembic/issues/754 and
  https://github.com/sqlalchemy/alembic/issues/886 — `DROP TABLE` not dropping a Postgres
  `ENUM` type, both issues still open — HIGH (primary GitHub issue text)
- https://github.com/modelcontextprotocol/python-sdk/issues/1373 — `$ref`-based `StrEnum`
  schemas vs. inlined `Literal` schemas, Claude Desktop quoting mismatch, opened 2025-09-17,
  unresolved as of this research — MEDIUM (single unconfirmed report, but specific and
  reproducible per the reporter; treated as a caution, not a proven blocker, since this
  project's own live `TrainingProgram` enum argument already works against a real Claude Desktop
  connector)
- https://github.com/anthropics/claude-ai-mcp/issues/408 — Claude.ai MCP connector
  client-side-rejecting-before-reaching-server with a misattributed enum-field error — MEDIUM
  (illustrates real, if narrow, fragility in enum-bearing tool schemas on Claude's connector
  side; not directly about this project's shape, used only to justify the "spike the real tool
  against a real session before calling it done" recommendation)

---
*Stack research for: BRETT v2.1 Longitudinal Physique Analysis — physique-observation storage,
MCP tool schema shape, and migration mechanics*
*Researched: 2026-09-05*

# Phase 16: Physique Data Model & Repository - Pattern Map

**Mapped:** 2026-09-09
**Files analyzed:** 6 (2 new source modules, 1 migration, 1 test file, 2 existing files requiring edits)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `backend/app/db/models/physique.py` | model | CRUD | `backend/app/db/models/program.py` (`ProgramPeriod`/`ProgramSwitchToken`) | exact (header/child, append-only, `TimestampMixin`, named partial-unique posture) |
| `backend/app/db/repositories/physique.py` | service (repository) | CRUD | `backend/app/db/repositories/programs.py` | exact (explicit `AsyncSession` param, no in-function commit, sole-writer docstring) |
| `backend/migrations/versions/0007_physique_observations.py` | migration | batch (DDL) | `backend/migrations/versions/0006_user_program_history.py` | exact (hand-written header+child `create_table`, `op.f()` naming, mirror-image `downgrade()`) |
| `backend/tests/test_db_physique.py` | test | CRUD / batch | `backend/tests/test_db_program_history.py` | exact (migration-shape assertions via `information_schema` + repository behavior assertions via `GoldenBuilder`/fixtures) |
| `backend/app/db/models/__init__.py` | config (model registry) | — | same file, existing pattern | exact — mechanical addition, no new pattern needed |
| `backend/tests/test_db_models.py` | test | — | same file, existing pattern (`test_metadata_contains_expected_tables`) | exact — mechanical edit, no new pattern needed |

No component/controller/route/hook/provider/store files — this phase has zero MCP or HTTP surface (explicit boundary per CONTEXT.md).

## Pattern Assignments

### `backend/app/db/models/physique.py` (model, CRUD)

**Analog:** `backend/app/db/models/program.py` (structure), `backend/app/db/models/exercise.py` (ARRAY column shape), `backend/app/db/models/body.py` (`Date` vs `DateTime` precedent), `backend/app/normalization/muscles.py` (`StrEnum` + module-level constant convention), `backend/app/db/base.py` (`Base`/`TimestampMixin`/`NAMING_CONVENTION`)

**Imports pattern** (`backend/app/db/models/program.py` lines 19-26):
```python
import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
```
Add `CheckConstraint` from `sqlalchemy` and `ARRAY` from `sqlalchemy.dialects.postgresql` (see `exercise.py` lines 22-33) and `from enum import StrEnum` (see `muscles.py` line 19) — new to this file, not present in `program.py`.

**Base/mixin pattern** (`backend/app/db/base.py` lines 18-50, verbatim):
```python
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```
Both `PhysiqueObservation` and `PhysiqueRating` inherit `Base, TimestampMixin` exactly like `ProgramPeriod`/`ProgramSwitchToken` (`program.py` line 29, 63).

**Core header/child model pattern** (`backend/app/db/models/program.py` lines 29-92, structure to mirror):
```python
class ProgramPeriod(Base, TimestampMixin):
    __tablename__ = "user_program_history"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    program: Mapped[str] = mapped_column(String(16), nullable=False)
    started_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index(
            "uq_user_program_history_one_open_period",
            "user_id",
            unique=True,
            postgresql_where=text("ended_on IS NULL"),
        ),
        Index("ix_user_program_history_user_id_started_on", "user_id", "started_on"),
    )
```
`PhysiqueObservation` (header) takes this exact shape: `id`/`user_id` identical, `observed_on: Mapped[dt.date]` mirrors `started_on`/`BodyMeasurement.measured_on` (below), and `__table_args__` carries the new `CheckConstraint`s (Pattern block next) instead of a partial-unique `Index` — this phase has no "exactly one open X" invariant on the header.

`PhysiqueRating` (child) mirrors `ProgramSwitchToken`'s cross-table-FK shape (`program.py` lines 63-92) for its FK-to-header column and its `UniqueConstraint` declaration style:
```python
class ProgramSwitchToken(Base, TimestampMixin):
    __tablename__ = "program_switch_tokens"
    ...
    from_period_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_program_history.id", ondelete="CASCADE"),
        nullable=False,
    )
    ...
    __table_args__ = (UniqueConstraint("nonce", name="uq_program_switch_tokens_nonce"),)
```
Apply the same `UniqueConstraint(..., name=...)` idiom to `(observation_id, muscle_group)` per D-08: `UniqueConstraint("observation_id", "muscle_group", name="uq_physique_ratings_observation_id_muscle_group")`.

**New-to-codebase CheckConstraint pattern** (no direct in-repo precedent; naming-convention behavior live-verified in 16-RESEARCH.md Pattern 1, reproduced here verbatim):
```python
NAMING_CONVENTION = {  # from app/db/base.py, unchanged
    ...
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    ...
}
# CheckConstraint(..., name="valid_level") on table `foo`
# -> resolves to `ck_foo_valid_level`
```
**Critical naming rule (Pitfall 1):** pass a SHORT, unprefixed label to `CheckConstraint(name=...)` in the model (e.g. `name="valid_rating_level"`, NOT `name="ck_physique_ratings_valid_rating_level"`) — the naming convention prefixes it automatically. This differs from `uq`/`fk`/`pk`, where the token is column/table-derived, not user-supplied.

Concrete columns to add, from 16-RESEARCH.md Pattern 1/2/3 (copy verbatim — this is a locked constant + a verified-safe syntax, not exploratory):
```python
from enum import StrEnum

# LOCKED by PHYS-01/D-07 — copy verbatim from 15-SPIKE-RESULT.md "## Recommended Constants".
PHYSIQUE_RATING_LEVELS = (
    "Minimal", "Emerging", "Developed", "Well-Developed", "Standout",
)
PHYSIQUE_RATING_ANCHORS = (
    "1. Minimal - the group shows little visible development; its outline is not apparent "
    "in this photo set. "
    "2. Emerging - the group's outline is visible but shallow; shape is suggested rather "
    "than defined. "
    "3. Developed - the group has clear shape and visible separation from adjacent groups. "
    "4. Well-Developed - the group is clearly fuller or more defined than the average group "
    "on THIS person's own body. "
    "5. Standout - the group is among the most developed on THIS person's own body; it is "
    "the group a viewer would notice first."
)
# Carried forward for Phase 17 (not load-bearing here, but co-located per RESEARCH's
# "Recommended Project Structure" note).
PHYSIQUE_MIN_ELAPSED_DAYS = 30
PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2

class PoseState(StrEnum):
    RELAXED = "relaxed"
    LIGHTLY_FLEXED = "lightly_flexed"

# On PhysiqueRating:
rating_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
not_assessable_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)  # D-05
__table_args__ = (
    sa.CheckConstraint(
        "rating_level IN ('Minimal','Emerging','Developed','Well-Developed','Standout')",
        name="valid_rating_level",
    ),
    sa.CheckConstraint(
        "(rating_level IS NOT NULL AND not_assessable_reason IS NULL) OR "
        "(rating_level IS NULL AND not_assessable_reason IS NOT NULL)",
        name="rating_xor_not_assessable",
    ),
    UniqueConstraint("observation_id", "muscle_group", name="uq_physique_ratings_observation_id_muscle_group"),
)
```

**ARRAY column shape to copy verbatim** (`backend/app/db/models/exercise.py` lines 85-87 — shape only, CHECK is new per Pitfall 3):
```python
secondary_muscle_groups: Mapped[list[str]] = mapped_column(
    ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
)
```
Apply as `photo_angles_present: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, server_default=text("'{}'::varchar[]"))` plus a NEW `CheckConstraint("photo_angles_present <@ ARRAY['front','back','side']::varchar(16)[]", name="valid_photo_angles")` (Postgres `<@` operator — verify with a live-Postgres negative test per Pitfall 3, since no existing migration exercises this operator).

**`Date` vs `DateTime` precedent** (`backend/app/db/models/body.py` lines 56-57, module docstring lines 12-16):
```python
# `measured_on` is a `Date`, not a TIMESTAMPTZ. Hevy's field is `format: date`; storing a
# timestamp would require inventing a time of day. This does not violate FOUND-04 -- a
# calendar date is not an instant.
measured_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
```
Apply identically to `PhysiqueObservation.observed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)`.

**Free-text note field caps (D-04/D-05/D-06) — do not transpose (Pitfall 5):**
```python
leanness_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)      # D-04
conditioning_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)  # D-04
symmetry_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)      # D-04
conditions_note: Mapped[str | None] = mapped_column(String(200), nullable=True)     # D-06
# not_assessable_reason (on PhysiqueRating) = String(160)                            # D-05
```

**Supersede columns (D-01, Pitfall 4 — self-referential FK):**
```python
superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
superseded_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
    PGUUID(as_uuid=True),
    ForeignKey("physique_observations.id", ondelete="SET NULL"),  # SET NULL, NOT CASCADE — Pitfall 4
    nullable=True,
)
```

**StrEnum + module-constant convention** (`backend/app/normalization/muscles.py` lines 23-48, and `backend/app/analytics/recomposition.py` lines 104-111):
```python
# muscles.py: comment-above-enum convention
class CanonicalMuscleGroup(StrEnum):
    """The project's muscle vocabulary. Provider-neutral by construction."""
    CHEST = "chest"
    ...

# recomposition.py: named-constant-with-rationale-comment convention
RECOMP_LOOKBACK_WEEKS = 12
INTERPRETATION_DISCLAIMER = (
    "Decision support from body-weight trend and training progression only. "
    "Not a medical or diagnostic claim, and not a body-composition measurement."
)
```
`PHYSIQUE_RATING_LEVELS`/`PHYSIQUE_RATING_ANCHORS`/etc. should sit at the top of `physique.py`, next to the `PoseState`/rating-vocab `StrEnum`, following this exact "constant beside the enum it describes" placement.

`CanonicalMuscleGroup` itself (`muscles.py` lines 26-47) is imported and reused directly — no new taxonomy:
```python
from app.normalization.muscles import CanonicalMuscleGroup
# PhysiqueRating.muscle_group: Mapped[str] = mapped_column(String(32), nullable=False)
# — stores `.value`, exactly like `ExerciseMuscle.muscle_group` (exercise.py line 124)
```

---

### `backend/app/db/repositories/physique.py` (service/repository, CRUD)

**Analog:** `backend/app/db/repositories/programs.py`

**Module docstring / sole-writer convention** (`programs.py` lines 1-15):
```python
"""Read and write the active training program's history (GOAL-01, GOAL-03, D-07).

D-07: this module is the append-only history's ONE writer. ... Every function takes an
`AsyncSession` positionally and never commits. The CALLER owns the transaction ...
"""
```
`physique.py`'s docstring should state it is the sole writer of `physique_observations`/`physique_ratings`, mirroring this exactly (per RESEARCH's Architectural Responsibility Map).

**Imports pattern** (`programs.py` lines 17-26):
```python
import datetime as dt
import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import TrainingProgram
from app.db.models.program import ProgramPeriod, ProgramSwitchToken
```
`physique.py` needs `selectinload` from `sqlalchemy.orm` additionally (per RESEARCH Pattern 5's `get_latest_observation` eager-load recommendation) — no existing repository in this codebase currently uses `selectinload` since none has a real child-collection read path; this is new but low-risk, standard SQLAlchemy.

**Repository function signature shape** (`programs.py` lines 38-45, `74-93`):
```python
async def get_active_period(session: AsyncSession, *, user_id: uuid.UUID) -> ProgramPeriod | None:
    """..."""
    return await session.scalar(
        select(ProgramPeriod).where(
            ProgramPeriod.user_id == user_id, ProgramPeriod.ended_on.is_(None)
        )
    )

async def get_recent_periods(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 2
) -> Sequence[ProgramPeriod]:
    """..."""
    stmt = (
        select(ProgramPeriod)
        .where(ProgramPeriod.user_id == user_id)
        .order_by(ProgramPeriod.started_on.desc(), ProgramPeriod.ended_on.is_(None).desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()
```
Build `get_latest_observation(session, *, user_id) -> PhysiqueObservation | None` and (optionally) `get_recent_observations(session, *, user_id, limit=N)` in this exact shape: keyword-only params after `session`, explicit `AsyncSession`, no commit, docstring explaining the `None`/ordering semantics precisely (per RESEARCH Open Question 1 recommendation — build only `create_observation`/`get_latest_observation` for this phase).

**Multi-row insert pattern (header + N children in one transaction, no commit)** — closest analog is `close_period_and_open_new` (`programs.py` lines 174-228) for "insert header, do dependent work, return the object," and `GoldenBuilder.template`'s multi-row child insert (`conftest.py` lines 436-450) for the *executemany* shape:
```python
# programs.py lines 216-227 — single-row insert-then-refetch shape
new_period_id = uuid.uuid4()
insert_stmt = insert(ProgramPeriod).values(
    id=new_period_id, user_id=user_id, program=to_program.value, started_on=today, ended_on=None,
)
await session.execute(insert_stmt)
new_period = await session.get(ProgramPeriod, new_period_id)
if new_period is None:  # pragma: no cover
    raise RuntimeError("close_period_and_open_new: newly inserted period not found")
return new_period
```
```python
# conftest.py lines 436-450 — executemany shape for the 19 child rows
await self._session.execute(
    insert(ExerciseMuscle),
    [
        {"id": uuid.uuid4(), "user_id": user_id, ...}
        for muscle_group, role in muscles
    ],
)
```
`create_observation` should: (1) validate `len(ratings) == len(CanonicalMuscleGroup)` and full coverage BEFORE any INSERT (raise `ValueError` early, per RESEARCH Pattern 5), (2) `insert(PhysiqueObservation).values(...)` for the header, (3) `session.execute(insert(PhysiqueRating), [...])` (executemany) for the 19 children, (4) return the header object via `session.get(...)` — caller commits, exactly like every function in `programs.py`.

**Eager-load read pattern (new to this codebase — no repository currently loads a child collection):**
```python
from sqlalchemy.orm import selectinload
# get_latest_observation:
stmt = (
    select(PhysiqueObservation)
    .where(PhysiqueObservation.user_id == user_id)
    .options(selectinload(PhysiqueObservation.ratings))
    .order_by(PhysiqueObservation.observed_on.desc())
    .limit(1)
)
return await session.scalar(stmt)
```
Note: this requires a `relationship()` on the model, which conflicts with the codebase-wide "no `relationship()` anywhere" rule asserted by `test_reference_models_declare_no_relationships` (`test_db_models.py` lines 204-223, `programs.py`/`program.py` have zero `relationship()` declarations). **Resolve by NOT adding a `relationship()`** — instead have `get_latest_observation` issue two queries (header, then `select(PhysiqueRating).where(observation_id == ...)`) in the same session, or a single `JOIN` returning both header and child columns. Flag this for the planner: `selectinload` is RESEARCH's suggestion but is incompatible with an established repo-wide guard unless `test_reference_models_declare_no_relationships`'s target list is deliberately left unchanged (recommended) and physique models are simply excluded from a `relationship()`-based eager load.

**ASVS V4 tenant-scoping convention** (`programs.py`'s `user_id` predicate on every statement, e.g. lines 41-45, 61-69, 161-167): every `physique.py` function must take `user_id` explicitly and include it in every WHERE/JOIN predicate, with the same "belt-and-braces" framing as `consume_switch_token`'s docstring (lines 155-157).

---

### `backend/migrations/versions/0007_physique_observations.py` (migration, batch/DDL)

**Analog:** `backend/migrations/versions/0006_user_program_history.py`

**Header/revision boilerplate** (`0006` lines 1-29):
```python
"""training programs: effective-dated history + a switch-confirmation token (GOAL-01, D-07, D-08)
...
Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```
`0007_physique_observations.py` mirrors this exactly: `revision = "0007"`, `down_revision = "0006"`.

**Full header+child `create_table` skeleton with `op.f()` naming — copy this structure verbatim, substituting columns** (`0006` lines 32-144, and the fully-worked physique version already drafted in 16-RESEARCH.md "Pattern 4"):
```python
def upgrade() -> None:
    op.create_table(
        "user_program_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("program", sa.String(length=16), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_user_program_history_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_program_history")),
    )
```
16-RESEARCH.md's Pattern 4 already contains the complete, ready-to-copy `physique_observations`/`physique_ratings` `op.create_table(...)` calls including both `CheckConstraint`s (`ck_physique_observations_valid_pose_state`, `ck_physique_observations_valid_photo_angles`, `ck_physique_ratings_valid_rating_level`, `ck_physique_ratings_rating_xor_not_assessable`), the self-referential `superseded_by_id` FK (declared INSIDE the same `create_table`, per the self-FK caveat), and the `uq_physique_ratings_observation_id_muscle_group` unique constraint — use that block directly rather than re-deriving it.

**`op.f()` usage for CHECK names (Pitfall 1's migration-side half):**
```python
sa.CheckConstraint(
    "pose_state IN ('relaxed','lightly_flexed')",
    name=op.f("ck_physique_observations_valid_pose_state"),
)
```
Always wrap the FULLY-RESOLVED name in `op.f(...)` in the migration (unlike the model, where the short label goes unwrapped into `name=`).

**Downgrade — exact mirror image, FK-child table first** (`0006` lines 147-154):
```python
def downgrade() -> None:
    op.drop_table("program_switch_tokens")
    op.drop_index("ix_user_program_history_user_id_started_on", table_name="user_program_history")
    op.drop_index("uq_user_program_history_one_open_period", table_name="user_program_history")
    op.drop_table("user_program_history")
```
`0007`'s `downgrade()`: `op.drop_table("physique_ratings")` then `op.drop_table("physique_observations")` — no separate `op.drop_index` calls needed if the unique/check constraints were declared inline inside `create_table` (they drop automatically with the table), unlike `0006`'s partial index which was created via a separate `op.create_index` call.

**Anti-pattern reminder:** no native `sa.Enum(...)`/`postgresql.ENUM` anywhere in this migration — `rating_level`/`pose_state` are `String` + `CheckConstraint` only (PHYS-03/D-02, Anti-Pattern in RESEARCH). A native enum would require an explicit `.drop(op.get_bind())` in `downgrade()` that is easy to forget and breaks `test_migrations_round_trip`.

---

### `backend/tests/test_db_physique.py` (test, CRUD/batch)

**Analog:** `backend/tests/test_db_program_history.py` (repository/migration-shape split), `backend/tests/test_migrations.py` (round-trip pattern), `backend/tests/conftest.py` (`GoldenBuilder`, `DEFAULT_USER_ID`, `ANALYTICS_SECOND_USER_ID`, `committed_history`/`session`/`engine` fixtures)

**Migration-shape assertion via `information_schema`, not `Base.metadata`** (`test_db_program_history.py` lines 42-82):
```python
@pytest.mark.integration
async def test_migration_creates_both_tables_with_the_expected_columns(engine: AsyncEngine) -> None:
    """Queried from `information_schema`, not from `Base.metadata`: the model asserting
    against itself proves nothing about the DDL migrations actually produced."""
    async with engine.connect() as conn:
        period_columns = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'user_program_history'"
                )
            )
        ).all()
    assert {row[0] for row in period_columns} == {...}
```

**CHECK constraint negative-path test pattern (new to this codebase, model it on the existing `IntegrityError` idiom)** (`test_db_program_history.py` lines 85-119):
```python
@pytest.mark.integration
async def test_migration_partial_index_refuses_a_second_open_period(engine: AsyncEngine) -> None:
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(ProgramPeriod).values(...))
        async with engine.begin() as conn:
            await conn.execute(sa.insert(ProgramPeriod).values(...))  # the succeeding case, in the SAME test
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.delete(ProgramPeriod).where(...))
```
Apply this exact "raise-then-succeed-then-cleanup, both asserted in one test" shape to:
- `test_not_assessable_xor_rating` — one insert with `rating_level` and `not_assessable_reason` both NULL (expect `IntegrityError`), one with exactly one set (expect success)
- `test_confounder_metadata` — one insert with a disallowed `pose_state`/`photo_angles_present` element (expect `IntegrityError`), one with valid values including the empty-array default (expect success) — this is Pitfall 3's mandated negative test for the untested `<@` operator

**Repository round-trip test pattern** (`test_db_program_history.py` lines 264-316, `GoldenBuilder` fixture usage):
```python
@pytest.mark.integration
async def test_fixture_builders_round_trip_a_period_and_a_token(
    committed_history: GoldenBuilder, session: AsyncSession, engine: AsyncEngine,
) -> None:
    ...
    closed_period_id = await committed_history.program_period(program="cut", started_on=..., ended_on=...)
    ...
    await session.commit()
    async with engine.connect() as conn:
        period_rows = (await conn.execute(sa.select(...))).all()
    ...
```
If a `GoldenBuilder.physique_observation(...)` helper is added to `conftest.py` (RESEARCH's Wave 0 Gaps suggests this, not strictly required), mirror `GoldenBuilder.program_period`'s signature style (`conftest.py` lines 563-588) — keyword-only params, `DEFAULT_USER_ID` default, flush not commit, returns the new row's id.

**Tenant-scoping test pattern** (`test_db_program_history.py` lines 431-461, `test_period_reads_are_scoped_to_the_user`):
```python
async def test_period_reads_are_scoped_to_the_user(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    other_period_id = await committed_history.program_period(..., user_id=ANALYTICS_SECOND_USER_ID)
    await session.commit()
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active.id != other_period_id
```
Apply identically to `get_latest_observation` — seed a second user's observation, assert the default user's read never sees it (ASVS V4, per RESEARCH's Known Threat Patterns table).

**Migration round-trip test — MUST keep passing unchanged, do not duplicate its logic** (`test_migrations.py` lines 36-55):
```python
@pytest.mark.integration
async def test_migrations_round_trip(
    engine: AsyncEngine, alembic: Callable[..., subprocess.CompletedProcess[str]], restore_schema: None,
) -> None:
    assert alembic("upgrade", "head").returncode == 0
    ...
    result = alembic("downgrade", "base")
    assert result.returncode == 0, result.stderr
    assert await _tables(engine) == ["alembic_version"]
    assert alembic("upgrade", "head").returncode == 0
```
This existing test automatically covers `physique_observations`/`physique_ratings` once migration `0007` exists — no new test needed for the round-trip itself, only for the CHECK-constraint negative paths (which this test does not exercise).

---

## Shared Patterns

### Declarative Base + Naming Convention
**Source:** `backend/app/db/base.py` lines 1-51
**Apply to:** `PhysiqueObservation`, `PhysiqueRating` (both models)
```python
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
```
Every model in this codebase inherits `Base, TimestampMixin` with zero exceptions — no deviation here.

### CheckConstraint Naming (new pattern, first use in this codebase)
**Source:** 16-RESEARCH.md Pattern 1 (live-verified against `backend/app/db/base.py`'s `NAMING_CONVENTION`)
**Apply to:** every `CheckConstraint` in `physique.py` (model) and `0007_physique_observations.py` (migration)
- Model: short unprefixed `name=` (e.g. `"valid_rating_level"`)
- Migration: `name=op.f("ck_<table>_<short_name>")`
Getting this backwards fails `test_no_pending_model_drift` (`alembic check`) with a constraint-name diff.

### Repository Sole-Writer Convention
**Source:** `backend/app/db/repositories/programs.py` lines 1-15
**Apply to:** `backend/app/db/repositories/physique.py`
- Explicit `AsyncSession` positional/keyword param, never `session.commit()` inside the module
- Module docstring names itself the sole writer of its tables
- Every function takes `user_id` explicitly and scopes every query to it (ASVS V4)

### `StrEnum`-backed `String` column, never native `ENUM`
**Source:** `backend/app/normalization/muscles.py` lines 26-54 (`CanonicalMuscleGroup`, `MuscleRole`), `backend/app/db/models/exercise.py` line 124 comment
**Apply to:** `rating_level`, `pose_state`, and the existing `muscle_group` (reused directly, not redefined)
```python
# exercise.py line 121-124
# One of the 19 `CanonicalMuscleGroup` values, stored as its `.value` string.
# Deliberately NOT a Postgres ENUM: changing a PG enum requires a migration for
# every taxonomy tweak.
muscle_group: Mapped[str] = mapped_column(String(32), nullable=False)
```

### Named-Constant-With-Rationale-Comment
**Source:** `backend/app/analytics/recomposition.py` lines 104-111
**Apply to:** `PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_RATING_ANCHORS`, `PHYSIQUE_MIN_ELAPSED_DAYS`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` (copy verbatim from `15-SPIKE-RESULT.md`, including its rationale comments — do not paraphrase the comments, they carry decision provenance)

### Model Registry
**Source:** `backend/app/db/models/__init__.py` (entire file)
**Apply to:** add `from app.db.models.physique import PhysiqueObservation, PhysiqueRating` and both names to `__all__` — every existing model is registered here, and `migrations/env.py` depends on this import for autogenerate/`alembic check` to see the models at all.

### Fast-suite Metadata Guard (must edit, not just add to)
**Source:** `backend/tests/test_db_models.py` lines 26-53 (`test_metadata_contains_expected_tables`)
**Apply to:** add `"physique_observations"` and `"physique_ratings"` to the expected `set()` literal AND extend the docstring's "Phase 8's single addition, plus Phase 12's two additions" convention with a Phase 16 note — this is an EXACT-equality assertion; a missed edit fails the fast suite immediately (Pitfall 2).

## No Analog Found

None — every file this phase touches has a direct, currently-passing precedent in this repo. The one genuinely novel mechanic (`CheckConstraint` naming/syntax, both scalar and `ARRAY`-membership) is covered above as a "new pattern, first use" rather than a missing analog, since 16-RESEARCH.md already verified its naming-convention behavior live against this repo's own `NAMING_CONVENTION`.

## Metadata

**Analog search scope:** `backend/app/db/`, `backend/app/normalization/`, `backend/app/analytics/`, `backend/migrations/versions/`, `backend/tests/`
**Files scanned/read in full:** `backend/app/db/base.py`, `backend/app/db/models/program.py`, `backend/app/db/models/exercise.py`, `backend/app/db/models/body.py`, `backend/app/db/models/__init__.py`, `backend/app/db/repositories/programs.py`, `backend/app/normalization/muscles.py`, `backend/app/analytics/recomposition.py` (excerpt), `backend/migrations/versions/0006_user_program_history.py`, `backend/tests/test_migrations.py`, `backend/tests/test_db_models.py`, `backend/tests/test_db_program_history.py`, `backend/tests/conftest.py` (excerpts), `backend/tests/test_mcp_isolation.py` (excerpt, confirms out-of-MCP-scope boundary)
**Pattern extraction date:** 2026-09-09

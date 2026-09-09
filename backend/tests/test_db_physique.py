"""PHYS-01..PHYS-05's proof at the DATABASE layer.

Asserted against `information_schema` and against live `INSERT`s, never against
`Base.metadata` -- a model asserting against itself proves nothing about the DDL the
migration actually produced (the same argument `test_db_program_history.py` makes).

Four of these tests exist specifically because 16-RESEARCH.md Pitfall 3 flags that a CHECK
constraint can compile, pass `alembic check`, and restrict nothing. The `<@` array-containment
operator in particular has no other use anywhere in this repository, so
`test_confounder_metadata` is its only proof.

Plan 03 appends the repository round-trip and tenant-scoping tests to this file.
"""

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models.physique import PhysiqueObservation, PhysiqueRating
from app.normalization.muscles import CanonicalMuscleGroup
from tests.conftest import DEFAULT_USER_ID

_OBSERVED_ON = dt.date(2026, 3, 1)


async def _insert_observation(engine: AsyncEngine, **overrides: object) -> uuid.UUID:
    """One committed `physique_observations` row with valid defaults. Caller deletes it."""
    observation_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": observation_id,
        "user_id": DEFAULT_USER_ID,
        "observed_on": _OBSERVED_ON,
        "photo_angles_present": ["front", "back", "side"],
        "pose_state": "relaxed",
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(sa.insert(PhysiqueObservation).values(**values))
    return observation_id


async def _delete_observation(engine: AsyncEngine, observation_id: uuid.UUID) -> None:
    # `physique_ratings` rows disappear with the parent via `ON DELETE CASCADE`, so deleting
    # the header is sufficient cleanup for both tables.
    async with engine.begin() as conn:
        await conn.execute(
            sa.delete(PhysiqueObservation).where(PhysiqueObservation.id == observation_id)
        )


@pytest.mark.integration
async def test_migration_creates_both_tables_with_the_expected_columns(engine: AsyncEngine) -> None:
    """Queried from `information_schema`, not from `Base.metadata`: the model asserting
    against itself proves nothing about the DDL the migration actually produced.

    The three supersede columns are asserted present although nothing in Phase 16 writes them
    (D-01), so their removal by a later "unused column" cleanup fails here.
    """
    async with engine.connect() as conn:
        observation_columns = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'physique_observations'"
                )
            )
        ).all()
        rating_columns = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'physique_ratings'"
                )
            )
        ).all()
    assert {row[0] for row in observation_columns} == {
        "id",
        "user_id",
        "observed_on",
        "leanness_notes",
        "conditioning_notes",
        "symmetry_notes",
        "photo_angles_present",
        "pose_state",
        "conditions_note",
        "superseded_at",
        "superseded_reason",
        "superseded_by_id",
        "created_at",
        "updated_at",
    }
    assert {row[0] for row in rating_columns} == {
        "id",
        "observation_id",
        "muscle_group",
        "rating_level",
        "not_assessable_reason",
        "created_at",
        "updated_at",
    }


@pytest.mark.integration
async def test_migration_declares_no_native_enum_type(engine: AsyncEngine) -> None:
    """PHYS-03's `pg_type` guarantee, checked directly rather than only inferred from the
    round-trip test.

    A native enum type here would survive `DROP TABLE` and break `test_migrations_round_trip`
    in a way whose error message names neither this phase nor this column.
    """
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "select typname from pg_type where typtype = 'e' "
                    "and typnamespace = 'public'::regnamespace"
                )
            )
        ).all()
    assert [row[0] for row in rows] == []


@pytest.mark.integration
async def test_not_assessable_xor_rating(engine: AsyncEngine) -> None:
    """PHYS-02: `Not Assessable` is a first-class value carrying a reason, not a numeric guess
    and not a sentinel string in `rating_level`; `abductors` uses the same path as every other
    group, with no special-casing anywhere.
    """
    observation_id = await _insert_observation(engine)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueRating).values(
                        id=uuid.uuid4(),
                        observation_id=observation_id,
                        muscle_group=CanonicalMuscleGroup.ABDUCTORS.value,
                        rating_level=None,
                        not_assessable_reason=None,
                    )
                )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueRating).values(
                        id=uuid.uuid4(),
                        observation_id=observation_id,
                        muscle_group=CanonicalMuscleGroup.ABDUCTORS.value,
                        rating_level="Developed",
                        not_assessable_reason="Both set, refused.",
                    )
                )
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueRating).values(
                    id=uuid.uuid4(),
                    observation_id=observation_id,
                    muscle_group=CanonicalMuscleGroup.ABDUCTORS.value,
                    rating_level="Developed",
                    not_assessable_reason=None,
                )
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueRating).values(
                        id=uuid.uuid4(),
                        observation_id=observation_id,
                        muscle_group=CanonicalMuscleGroup.CHEST.value,
                        rating_level="Excellent",
                        not_assessable_reason=None,
                    )
                )
    finally:
        await _delete_observation(engine, observation_id)


@pytest.mark.integration
async def test_ratings_are_unique_per_observation_and_muscle_group(engine: AsyncEngine) -> None:
    """D-08: the constraint is on the PAIR, not on `observation_id` alone."""
    observation_id = await _insert_observation(engine)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueRating).values(
                    id=uuid.uuid4(),
                    observation_id=observation_id,
                    muscle_group=CanonicalMuscleGroup.CHEST.value,
                    rating_level="Developed",
                    not_assessable_reason=None,
                )
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueRating).values(
                        id=uuid.uuid4(),
                        observation_id=observation_id,
                        muscle_group=CanonicalMuscleGroup.CHEST.value,
                        rating_level="Standout",
                        not_assessable_reason=None,
                    )
                )
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueRating).values(
                    id=uuid.uuid4(),
                    observation_id=observation_id,
                    muscle_group=CanonicalMuscleGroup.LATS.value,
                    rating_level="Developed",
                    not_assessable_reason=None,
                )
            )
    finally:
        await _delete_observation(engine, observation_id)


@pytest.mark.integration
async def test_confounder_metadata(engine: AsyncEngine) -> None:
    """PHYS-05/D-03/D-02: Pitfall 3's mandated proof that the `<@` CHECK restricts anything
    at all -- the operator has no other use anywhere in this repository.
    """
    cleanup: list[uuid.UUID] = []
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueObservation).values(
                        id=uuid.uuid4(),
                        user_id=DEFAULT_USER_ID,
                        observed_on=_OBSERVED_ON,
                        photo_angles_present=["front", "three_quarter"],
                        pose_state="relaxed",
                    )
                )

        full_angles_id = await _insert_observation(
            engine, photo_angles_present=["front", "back", "side"]
        )
        cleanup.append(full_angles_id)

        empty_angles_id = await _insert_observation(engine, photo_angles_present=[])
        cleanup.append(empty_angles_id)

        omitted_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueObservation).values(
                    id=omitted_id,
                    user_id=DEFAULT_USER_ID,
                    observed_on=_OBSERVED_ON,
                    pose_state="relaxed",
                )
            )
        cleanup.append(omitted_id)
        async with engine.connect() as conn:
            omitted_angles = (
                await conn.execute(
                    sa.select(PhysiqueObservation.photo_angles_present).where(
                        PhysiqueObservation.id == omitted_id
                    )
                )
            ).scalar_one()
        assert omitted_angles == []

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueObservation).values(
                        id=uuid.uuid4(),
                        user_id=DEFAULT_USER_ID,
                        observed_on=_OBSERVED_ON,
                        photo_angles_present=["front"],
                        pose_state="fully_flexed",
                    )
                )

        lightly_flexed_id = await _insert_observation(
            engine,
            pose_state="lightly_flexed",
            conditions_note="Evening, post-workout, dehydrated.",
        )
        cleanup.append(lightly_flexed_id)

        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueRating).values(
                    id=uuid.uuid4(),
                    observation_id=lightly_flexed_id,
                    muscle_group=CanonicalMuscleGroup.CHEST.value,
                    rating_level="Developed",
                    not_assessable_reason=None,
                )
            )
        async with engine.connect() as conn:
            observation_row = (
                await conn.execute(
                    sa.select(
                        PhysiqueObservation.conditions_note, PhysiqueObservation.pose_state
                    ).where(PhysiqueObservation.id == lightly_flexed_id)
                )
            ).one()
            rating_row = (
                await conn.execute(
                    sa.select(PhysiqueRating.rating_level).where(
                        PhysiqueRating.observation_id == lightly_flexed_id
                    )
                )
            ).one()
        assert observation_row.conditions_note == "Evening, post-workout, dehydrated."
        assert observation_row.pose_state == "lightly_flexed"
        assert rating_row.rating_level == "Developed"
    finally:
        for observation_id in cleanup:
            await _delete_observation(engine, observation_id)


@pytest.mark.integration
async def test_note_field_caps(engine: AsyncEngine) -> None:
    """PHYS-04/D-04/D-05/D-06: the four similar text fields carry three different caps --
    exactly the kind of detail a copy-paste transposes (16-RESEARCH.md Pitfall 5).
    """
    observation_id = await _insert_observation(
        engine,
        leanness_notes="a" * 500,
        conditioning_notes="a" * 500,
        symmetry_notes="a" * 500,
        conditions_note="b" * 200,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(PhysiqueRating).values(
                    id=uuid.uuid4(),
                    observation_id=observation_id,
                    muscle_group=CanonicalMuscleGroup.CHEST.value,
                    rating_level=None,
                    not_assessable_reason="c" * 160,
                )
            )
        async with engine.connect() as conn:
            observation_row = (
                await conn.execute(
                    sa.select(
                        PhysiqueObservation.leanness_notes,
                        PhysiqueObservation.conditioning_notes,
                        PhysiqueObservation.symmetry_notes,
                        PhysiqueObservation.conditions_note,
                    ).where(PhysiqueObservation.id == observation_id)
                )
            ).one()
            rating_row = (
                await conn.execute(
                    sa.select(PhysiqueRating.not_assessable_reason).where(
                        PhysiqueRating.observation_id == observation_id
                    )
                )
            ).one()
        assert len(observation_row.leanness_notes) == 500
        assert len(observation_row.conditioning_notes) == 500
        assert len(observation_row.symmetry_notes) == 500
        assert len(observation_row.conditions_note) == 200
        assert len(rating_row.not_assessable_reason) == 160

        with pytest.raises(sa.exc.DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(PhysiqueObservation).values(
                        id=uuid.uuid4(),
                        user_id=DEFAULT_USER_ID,
                        observed_on=_OBSERVED_ON,
                        photo_angles_present=["front"],
                        pose_state="relaxed",
                        leanness_notes="a" * 501,
                    )
                )
    finally:
        await _delete_observation(engine, observation_id)

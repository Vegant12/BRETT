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
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models.physique import (
    PHYSIQUE_MIN_ELAPSED_DAYS,
    PhysiqueObservation,
    PhysiqueRating,
    PhysiqueRatingLevel,
    PoseState,
)
from app.db.repositories.physique import (
    PhysiqueObservationRecord,
    RatingEntry,
    create_observation,
    get_latest_observation,
)
from app.normalization.muscles import CanonicalMuscleGroup
from tests.conftest import ANALYTICS_SECOND_USER_ID, DEFAULT_USER_ID, GoldenBuilder

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


# ---------------------------------------------------------------------------
# Repository behavior (ROADMAP criteria 1 and 3). Everything above this line
# asserts the DDL; everything below asserts app/db/repositories/physique.py.
# ---------------------------------------------------------------------------

# The five groups the Phase 15 spike actually rated, given real levels; every other group
# takes the Not Assessable path -- which is the ordinary case, not an edge case.
_SPIKE_RATED = {
    CanonicalMuscleGroup.CHEST: PhysiqueRatingLevel.DEVELOPED,
    CanonicalMuscleGroup.LATS: PhysiqueRatingLevel.EMERGING,
    CanonicalMuscleGroup.BICEPS: PhysiqueRatingLevel.DEVELOPED,
    CanonicalMuscleGroup.TRICEPS: PhysiqueRatingLevel.EMERGING,
    CanonicalMuscleGroup.ABS: PhysiqueRatingLevel.MINIMAL,
}


def _repository_source() -> str:
    """Sync helper so the file read stays out of an async test body (Ruff ASYNC240)."""
    return (Path(__file__).resolve().parents[1] / "app/db/repositories/physique.py").read_text()


def _full_rating_set(
    *, omit: CanonicalMuscleGroup | None = None, duplicate: CanonicalMuscleGroup | None = None
) -> list[RatingEntry]:
    """All 19 canonical groups. `omit`/`duplicate` construct the two invalid inputs."""
    entries = [
        RatingEntry(muscle_group=group, rating_level=_SPIKE_RATED[group])
        if group in _SPIKE_RATED
        else RatingEntry(
            muscle_group=group,
            not_assessable_reason="No photo angle in this set shows the group.",
        )
        for group in CanonicalMuscleGroup
        if group is not omit
    ]
    if duplicate is not None:
        entries.append(
            RatingEntry(muscle_group=duplicate, rating_level=PhysiqueRatingLevel.MINIMAL)
        )
    return entries


@pytest.mark.integration
async def test_create_observation_round_trips_all_nineteen_ratings(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """ROADMAP criterion 1: a header plus one child row per rated muscle group can be
    inserted and read back through the repository, in canonical order, with every
    note/confounder field intact.
    """
    del committed_history  # fixture used only for its purge-on-teardown side effect
    await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=dt.date(2026, 3, 1),
        ratings=_full_rating_set(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=["front", "back", "side"],
        leanness_notes="Visibly leaner than last month.",
        conditioning_notes="Good vascularity in arms.",
        symmetry_notes="Left side slightly more developed.",
        conditions_note="Morning, fasted, consistent lighting.",
    )
    await session.commit()

    record = await get_latest_observation(session, user_id=DEFAULT_USER_ID)

    assert isinstance(record, PhysiqueObservationRecord)
    assert record is not None
    assert len(record.ratings) == 19
    assert [entry.muscle_group for entry in record.ratings] == list(CanonicalMuscleGroup)
    assert record.leanness_notes == "Visibly leaner than last month."
    assert record.conditioning_notes == "Good vascularity in arms."
    assert record.symmetry_notes == "Left side slightly more developed."
    assert record.conditions_note == "Morning, fasted, consistent lighting."
    assert record.pose_state is PoseState.RELAXED
    assert record.photo_angles_present == ("front", "back", "side")
    # D-01: the columns exist and default NULL; nothing in Phase 16 writes them.
    assert record.superseded_at is None
    assert record.superseded_reason is None
    assert record.superseded_by_id is None

    by_group = {entry.muscle_group: entry for entry in record.ratings}
    for group, level in _SPIKE_RATED.items():
        assert by_group[group].rating_level == level
        assert by_group[group].not_assessable_reason is None


@pytest.mark.integration
async def test_abductors_and_adductors_take_the_not_assessable_path_without_special_casing(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """ROADMAP criterion 3: abductors/adductors are permanently not-assessable from standard
    photos (PHYS-02), and the proof that there is no special-casing is that the SAME
    `create_observation` call, with no group-specific argument, produces them. The source file
    is grepped directly so "no special-casing" is a verifiable fact, not a claim.
    """
    del committed_history
    await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=dt.date(2026, 3, 1),
        ratings=_full_rating_set(),
        pose_state=PoseState.RELAXED,
    )
    await session.commit()

    record = await get_latest_observation(session, user_id=DEFAULT_USER_ID)
    assert record is not None
    by_group = {entry.muscle_group: entry for entry in record.ratings}

    for group in (CanonicalMuscleGroup.ABDUCTORS, CanonicalMuscleGroup.ADDUCTORS):
        assert by_group[group].rating_level is None
        assert by_group[group].not_assessable_reason

    source = _repository_source()
    assert "abductor" not in source.lower()
    assert "adductor" not in source.lower()


@pytest.mark.integration
async def test_create_observation_refuses_an_incomplete_rating_set(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """D-07: fewer than 19 rows is refused before any INSERT, leaving zero rows behind."""
    del committed_history
    with pytest.raises(ValueError, match="missing rating rows") as exc_info:
        await create_observation(
            session,
            user_id=DEFAULT_USER_ID,
            observed_on=dt.date(2026, 3, 1),
            ratings=_full_rating_set(omit=CanonicalMuscleGroup.CALVES),
            pose_state=PoseState.RELAXED,
        )
    assert "calves" in str(exc_info.value)
    assert await get_latest_observation(session, user_id=DEFAULT_USER_ID) is None


@pytest.mark.integration
async def test_create_observation_refuses_a_duplicated_muscle_group(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """D-08: a duplicated group is refused before any INSERT, leaving zero rows behind."""
    del committed_history
    with pytest.raises(ValueError, match="duplicate rating rows") as exc_info:
        await create_observation(
            session,
            user_id=DEFAULT_USER_ID,
            observed_on=dt.date(2026, 3, 1),
            ratings=_full_rating_set(duplicate=CanonicalMuscleGroup.CHEST),
            pose_state=PoseState.RELAXED,
        )
    assert "chest" in str(exc_info.value)
    assert await get_latest_observation(session, user_id=DEFAULT_USER_ID) is None


@pytest.mark.integration
async def test_create_observation_refuses_a_rating_that_is_both_or_neither(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """PHYS-02 at the repository layer: the DB CHECK is the backstop for writers that bypass
    this module; this is the first line of defence for writers that do not.
    """
    del committed_history
    both_set = _full_rating_set()
    both_set[0] = RatingEntry(
        muscle_group=both_set[0].muscle_group,
        rating_level=PhysiqueRatingLevel.DEVELOPED,
        not_assessable_reason="Both set, should be refused.",
    )
    with pytest.raises(ValueError, match="exactly one of rating_level or not_assessable_reason"):
        await create_observation(
            session,
            user_id=DEFAULT_USER_ID,
            observed_on=dt.date(2026, 3, 1),
            ratings=both_set,
            pose_state=PoseState.RELAXED,
        )

    neither_set = _full_rating_set()
    neither_set[0] = RatingEntry(muscle_group=neither_set[0].muscle_group)
    with pytest.raises(ValueError, match="exactly one of rating_level or not_assessable_reason"):
        await create_observation(
            session,
            user_id=DEFAULT_USER_ID,
            observed_on=dt.date(2026, 3, 1),
            ratings=neither_set,
            pose_state=PoseState.RELAXED,
        )


@pytest.mark.integration
async def test_get_latest_observation_returns_none_when_the_user_has_none(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """The empty-but-valid read Phase 17's read tool depends on."""
    del committed_history
    assert await get_latest_observation(session, user_id=DEFAULT_USER_ID) is None


@pytest.mark.integration
async def test_get_latest_observation_returns_the_most_recent_observed_on(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """Two observations `PHYSIQUE_MIN_ELAPSED_DAYS` apart, inserted OLDER-last, so a naive
    "last inserted wins" implementation fails.
    """
    del committed_history
    later_on = dt.date(2026, 3, 1)
    earlier_on = later_on - dt.timedelta(days=PHYSIQUE_MIN_ELAPSED_DAYS)

    await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=later_on,
        ratings=_full_rating_set(),
        pose_state=PoseState.RELAXED,
    )
    await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=earlier_on,
        ratings=_full_rating_set(),
        pose_state=PoseState.RELAXED,
    )
    await session.commit()

    record = await get_latest_observation(session, user_id=DEFAULT_USER_ID)
    assert record is not None
    assert record.observed_on == later_on


@pytest.mark.integration
async def test_observation_reads_are_scoped_to_the_user(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """ASVS V4: there is one user today; the query that forgets the `user_id` predicate is the
    one still there when there are two.
    """
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    other_record = await create_observation(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        observed_on=dt.date(2026, 3, 1),
        ratings=_full_rating_set(),
        pose_state=PoseState.RELAXED,
    )
    await session.commit()

    assert await get_latest_observation(session, user_id=DEFAULT_USER_ID) is None
    mine = await get_latest_observation(session, user_id=ANALYTICS_SECOND_USER_ID)
    assert mine is not None
    assert mine.id == other_record.id

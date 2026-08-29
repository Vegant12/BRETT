"""HEVY-03 persistence primitives against a real Postgres container.

SQLite would prove nothing here: ON CONFLICT, ON DELETE CASCADE and TIMESTAMPTZ are exactly
what these assertions are about.

The sync path commits by design, so every test cleans up in a `finally`. The container is
session-scoped and shared, and `test_migrations` asserts `count(*) == 1` on `users` -- a leaked
row breaks a later test for a reason that has nothing to do with that test.
"""

from copy import deepcopy
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import SyncState, Workout, WorkoutExercise, WorkoutSet
from app.db.session import make_sessionmaker
from app.integrations.hevy.schemas import HevyWorkout, PaginatedWorkouts
from app.integrations.hevy.workouts import delete_workout, persist_workout_page, upsert_workout
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

# Overflows `Numeric(7, 3)` (precision 7, scale 3 -- four integer digits at most), so the
# INSERT fails inside PostgreSQL rather than inside a mock somebody wrote.
OVERFLOW_WEIGHT = 99999999


def _workouts(name: str) -> list[HevyWorkout]:
    return PaginatedWorkouts.model_validate(hevy_fixture(name)).workouts


def _workout(name: str, index: int = 0) -> HevyWorkout:
    return _workouts(name)[index]


def _raw_workout(name: str, index: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = deepcopy(hevy_fixture(name)["workouts"][index])
    return payload


async def _counts(engine: AsyncEngine) -> tuple[int, int, int]:
    """`(workouts, workout_exercises, workout_sets)` reachable from this user's Hevy rows."""
    scoped = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER)
    async with engine.connect() as conn:
        workouts = await conn.scalar(
            sa.select(sa.func.count()).select_from(Workout).where(*scoped)
        )
        exercises = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutExercise)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*scoped)
        )
        sets = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutSet)
            .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*scoped)
        )
    return (workouts or 0, exercises or 0, sets or 0)


async def _cleanup(engine: AsyncEngine) -> None:
    """Remove everything this module's tests can have committed.

    The workout delete takes its exercises and sets with it by FK cascade, which is the same
    mechanism `delete_workout` relies on -- so a cleanup that leaked children would also be
    evidence the cascade is wrong.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.delete(Workout).where(
                Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER
            )
        )
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


@pytest.mark.integration
async def test_upsert_is_idempotent_across_three_runs(engine: AsyncEngine) -> None:
    """HEVY-03: three writes of the same payload leave one workout, two exercises, three sets.

    Three rather than two, deliberately. Two runs would pass even if the second silently
    replaced the row wholesale; the third catches a delete-then-insert that only works once.
    """
    sessionmaker = make_sessionmaker(engine)
    workout = _workout("workouts_page1")
    try:
        observed = []
        for _ in range(3):
            async with sessionmaker() as session:
                await upsert_workout(session, user_id=DEFAULT_USER_ID, workout=workout)
                await session.commit()
            observed.append(await _counts(engine))

        assert observed == [(1, 2, 3)] * 3
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_upsert_replaces_children_when_a_set_is_removed(engine: AsyncEngine) -> None:
    """An edited workout with FEWER sets must shrink, not accumulate.

    This is the whole reason children are delete-and-reinserted rather than upserted on
    `(workout_id, index)`. A per-child upsert leaves the surplus row behind, and every volume
    and tonnage figure Phase 4 computes from it is inflated forever -- silently, because the
    workout still looks correct in every other respect.
    """
    sessionmaker = make_sessionmaker(engine)
    raw = _raw_workout("workouts_page1")
    edited = deepcopy(raw)
    # Drop the `index: 1` working set from Bench Press, leaving only the warmup.
    edited["exercises"][0]["sets"] = [edited["exercises"][0]["sets"][0]]

    try:
        async with sessionmaker() as session:
            await upsert_workout(
                session, user_id=DEFAULT_USER_ID, workout=HevyWorkout.model_validate(raw)
            )
            await session.commit()
        assert await _counts(engine) == (1, 2, 3)

        async with sessionmaker() as session:
            await upsert_workout(
                session, user_id=DEFAULT_USER_ID, workout=HevyWorkout.model_validate(edited)
            )
            await session.commit()

        assert await _counts(engine) == (1, 2, 2)
        async with engine.connect() as conn:
            surviving = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutSet)
                .where(WorkoutSet.set_index == 1)
            )
        assert surviving == 0, "an orphan set survived the shrink and will inflate Phase 4 volume"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_workout_cascades_and_leaves_siblings(engine: AsyncEngine) -> None:
    """HEVY-04: deleting one workout takes its own children and nothing else."""
    sessionmaker = make_sessionmaker(engine)
    first = _workout("workouts_page1")
    second = _workout("workouts_page2")
    try:
        async with sessionmaker() as session:
            await persist_workout_page(session, user_id=DEFAULT_USER_ID, workouts=[first, second])
            await session.commit()
        assert await _counts(engine) == (2, 3, 4)

        async with sessionmaker() as session:
            removed = await delete_workout(
                session, user_id=DEFAULT_USER_ID, external_id=first.id
            )
            await session.commit()

        assert removed is True
        # Exactly page 2's workout, its one exercise and its one set are left standing.
        assert await _counts(engine) == (1, 1, 1)
        async with engine.connect() as conn:
            survivor = await conn.scalar(
                sa.select(Workout.external_id).where(Workout.user_id == DEFAULT_USER_ID)
            )
        assert survivor == second.id
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_unknown_workout_is_a_noop(engine: AsyncEngine) -> None:
    """A deletion for a workout we never stored is information, not an error.

    The events feed can report a deletion for a workout created and deleted between two of our
    syncs. Raising here would fail a drain over a workout that never existed locally.
    """
    sessionmaker = make_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            removed = await delete_workout(
                session, user_id=DEFAULT_USER_ID, external_id="never-synced"
            )
            await session.commit()
        assert removed is False
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_malformed_workout_is_skipped_and_the_page_commits(engine: AsyncEngine) -> None:
    """Pitfall 11: without a SAVEPOINT, one bad row poisons every statement after it.

    The failure is real -- a weight that genuinely overflows `Numeric(7, 3)` -- so this asserts
    against PostgreSQL's actual transaction-abort semantics rather than against a Python
    exception someone invented.
    """
    sessionmaker = make_sessionmaker(engine)
    bad_raw = _raw_workout("workouts_page1")
    bad_raw["id"] = "bad-workout-0001"
    bad_raw["exercises"][0]["sets"][0]["weight_kg"] = OVERFLOW_WEIGHT
    bad = HevyWorkout.model_validate(bad_raw)
    good = _workout("workouts_page2")

    try:
        async with sessionmaker() as session:
            result = await persist_workout_page(
                session, user_id=DEFAULT_USER_ID, workouts=[bad, good]
            )
            await session.commit()

        assert result.skipped == (bad.id,)
        assert result.upserted == 1
        # The good workout that came AFTER the failure is what proves the savepoint: without
        # one, its INSERT dies with "current transaction is aborted".
        assert await _counts(engine) == (1, 1, 1)
    finally:
        await _cleanup(engine)

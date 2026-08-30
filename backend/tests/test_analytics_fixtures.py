"""The golden fixture builder, tested as the load-bearing thing it is.

This module tests the FIXTURE, not the analytics. Nothing here computes volume
or frequency; plans 04-05 onward do that, and every one of them trusts
`golden_workout` to have written exactly the workout its test described. If the
builder is wrong, those tests certify a wrong answer with a green tick.

`test_golden_builder_never_commits` is the load-bearing one. A builder that
committed would leave rows in the session-scoped, shared container, and the
symptom would surface in an unrelated module -- `test_migrations.py` asserts
`count(*) == 1` on `users` from a separate connection and would start failing for
reasons that have nothing to do with migrations. That is the hardest class of
failure to attribute, so it is caught here, at the source, by proving from a
SECOND connection that the rows are invisible.

`test_golden_builder_mapping_resolves_through_the_resolver` is the second: it
proves the builder writes the mapping tables in the shape the resolver reads,
which is the precondition for plan 04-08's `override_changes_answer` test.

All four tests need the container and carry the integration marker.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.normalization.muscles import CanonicalMuscleGroup, MappingSource, MuscleRole
from app.normalization.resolver import effective_muscles_bulk
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# Distinct from the `RESOLVER-*` ids `test_normalization_mapping.py` writes and the
# `hevy-*` ids the sync tests write: the container is session-scoped and shared.
_TEMPLATE = "ANALYTICS-FIXTURE-BENCH"
_UNCOMMITTED_WORKOUT_ID = "ANALYTICS-FIXTURE-UNCOMMITTED"

# Aware and fixed. Ruff DTZ rejects a naive literal, and the builder rejects one
# at runtime.
_START = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)


@pytest.mark.integration
async def test_golden_builder_rows_are_visible_through_the_same_session(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """What the builder flushes is what the session under test reads back.

    The whole Phase 4 test strategy rests on this: the analytics function takes
    the SAME `AsyncSession`, so it sees the flushed rows inside the still-open
    transaction. A function that opened its own session would run in a different
    transaction and see nothing at all.
    """
    await golden_workout.template(external_id=_TEMPLATE)
    workout_id = await golden_workout.workout(
        start_time=_START,
        exercises=[
            GoldenExercise(
                template_external_id=_TEMPLATE,
                sets=[GoldenSet(weight_kg=Decimal("60.000"), reps=10)] * 3,
            ),
            GoldenExercise(
                template_external_id=_TEMPLATE,
                title="Second",
                sets=[GoldenSet(weight_kg=Decimal("40.000"), reps=12)] * 3,
            ),
        ],
    )

    # Guard against a vacuous pass: a builder that silently wrote nothing and
    # returned None would make every count below trivially zero.
    assert workout_id is not None

    set_count = await session.scalar(
        select(func.count())
        .select_from(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .where(WorkoutExercise.workout_id == workout_id)
    )
    assert set_count == 6, "2 exercises x 3 sets must land as 6 rows, not 2 and not 0"

    stored_start = await session.scalar(select(Workout.start_time).where(Workout.id == workout_id))
    assert stored_start is not None
    # FOUND-04: TIMESTAMPTZ round-trips aware. A naive value here would mean the
    # column was declared without a timezone and every week-boundary fixture in
    # this phase would bucket by the server's idea of local time.
    assert stored_start.tzinfo is not None
    assert stored_start.utcoffset() == dt.timedelta(0)
    assert stored_start == _START


@pytest.mark.integration
async def test_golden_builder_never_commits(
    engine: AsyncEngine, session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A second connection cannot see the builder's rows, because they are uncommitted.

    This is the guarantee that lets a session-scoped Postgres container be shared
    by the whole suite. Asserted from a genuinely separate connection rather than
    by inspecting `session.in_transaction()`, because the property that matters is
    what ANOTHER connection observes.
    """
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.workout(
        start_time=_START,
        external_id=_UNCOMMITTED_WORKOUT_ID,
        exercises=[GoldenExercise(template_external_id=_TEMPLATE, sets=[GoldenSet(reps=8)])],
    )

    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as other:
        found = await other.scalar(
            select(func.count())
            .select_from(Workout)
            .where(Workout.external_id == _UNCOMMITTED_WORKOUT_ID)
        )

    assert found == 0, (
        "the golden builder COMMITTED: a separate connection can see its rows, which means "
        "the shared session-scoped container is now polluted for every later test"
    )

    # And the row really does exist inside the open transaction -- otherwise the
    # assertion above would pass on a builder that wrote nothing at all.
    visible_here = await session.scalar(
        select(func.count())
        .select_from(Workout)
        .where(Workout.external_id == _UNCOMMITTED_WORKOUT_ID)
    )
    assert visible_here == 1


@pytest.mark.integration
async def test_golden_builder_supports_a_second_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Two users' data can coexist, which is what makes a missing scope detectable.

    This is the scaffolding the ASVS V4 cross-tenant tests in plans 04-05 through
    04-08 depend on (T-04-02). A single-user suite cannot detect a missing
    `user_id` predicate: with one user, every row belongs to them, so an unscoped
    query returns the right answer by accident and stays green until real
    multi-user data exists.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    # The same external_id for both: `exercise_templates` is unique per
    # (user_id, provider, external_id), so a shared id is legal and is exactly
    # the case a missing scope would confuse.
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.template(external_id=_TEMPLATE, user_id=ANALYTICS_SECOND_USER_ID)

    mine = await golden_workout.workout(
        start_time=_START,
        exercises=[GoldenExercise(template_external_id=_TEMPLATE, sets=[GoldenSet(reps=10)])],
    )
    theirs = await golden_workout.workout(
        start_time=_START,
        user_id=ANALYTICS_SECOND_USER_ID,
        exercises=[GoldenExercise(template_external_id=_TEMPLATE, sets=[GoldenSet(reps=10)])],
    )
    assert mine != theirs

    # Restricted to the two ids this test wrote rather than to `start_time >=
    # _START`: the container is shared, and a date-only predicate would be at the
    # mercy of any committed row another module happened to leave behind.
    both = (mine, theirs)

    unscoped = await session.scalar(
        select(func.count()).select_from(Workout).where(Workout.id.in_(both))
    )
    assert unscoped == 2, "both users' workouts must exist, or the scoping assertion proves nothing"

    scoped = await session.scalar(
        select(func.count())
        .select_from(Workout)
        .where(Workout.id.in_(both), Workout.user_id == DEFAULT_USER_ID)
    )
    assert scoped == 1


@pytest.mark.integration
async def test_golden_builder_mapping_resolves_through_the_resolver(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The builder writes the mapping tables in the shape the resolver reads.

    Both halves matter. The base set proves `template(muscles=...)` lands in
    `exercise_muscles` as the resolver expects; the override proves
    `override(...)` goes through `set_override` and therefore inherits the
    REPLACEMENT rule rather than merging. Without this, plan 04-08's
    `override_changes_answer` test could pass while per-muscle volume was
    silently computed from the base mapping -- a wrong answer with no error
    anywhere in the stack.
    """
    await golden_workout.template(
        external_id=_TEMPLATE,
        muscles=[
            (CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT),
            (CanonicalMuscleGroup.TRICEPS, MuscleRole.INDIRECT),
        ],
    )

    base = await effective_muscles_bulk(
        session, user_id=DEFAULT_USER_ID, template_external_ids=[_TEMPLATE]
    )
    assert {(m.muscle_group, m.role) for m in base[_TEMPLATE]} == {
        (CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT),
        (CanonicalMuscleGroup.TRICEPS, MuscleRole.INDIRECT),
    }

    written = await golden_workout.override(
        external_id=_TEMPLATE,
        muscles=[(CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT)],
    )
    assert written == 1

    resolved = await effective_muscles_bulk(
        session, user_id=DEFAULT_USER_ID, template_external_ids=[_TEMPLATE]
    )
    # One, not two: the override REPLACES the base set. A merge would leave
    # triceps behind and make "this exercise does not work triceps" unexpressible.
    assert len(resolved[_TEMPLATE]) == 1
    assert resolved[_TEMPLATE][0].muscle_group is CanonicalMuscleGroup.CHEST
    assert resolved[_TEMPLATE][0].source is MappingSource.OVERRIDE

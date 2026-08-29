"""HEVY-03 / HEVY-04 enforced by the DATABASE, not by the sync code.

Every assertion runs against the real Postgres container. The point is that idempotency
and cascade deletion are structural guarantees: a future refactor of the sync service
cannot accidentally remove them without failing here.
"""

import datetime as dt
import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import BodyMeasurement, Workout, WorkoutExercise, WorkoutSet
from tests.conftest import DEFAULT_USER_ID

# Fixed and timezone-aware. A naive literal would be rejected by Ruff DTZ and would
# also make the assertions depend on the machine's local offset.
_START = dt.datetime(2026, 8, 1, 6, 0, tzinfo=dt.UTC)

# Emoji on purpose: Hevy's own example title carries one, and a mis-declared
# encoding or a too-narrow column would surface here rather than on first sync.
_TITLE = "Push Day 💪"

# 8-char uppercase hex, the built-in-template id shape Hevy actually sends. The
# column is a plain String precisely so this and a full UUID both fit.
_TEMPLATE_ID = "05293BCA"

# A calendar date, not a timestamp: `datetime.fromisoformat("2026-08-01")` returns a
# NAIVE datetime, which is exactly the value `measured_on` being a DATE avoids storing.
_MEASURED_ON = dt.date(2026, 8, 1)

# The identity and audit columns of `body_measurements`. Everything else is a metric.
_BODY_IDENTITY_COLUMNS = frozenset(
    {"id", "user_id", "source", "external_id", "measured_on", "created_at", "updated_at"}
)

# T-03-11. Broader than the columns this phase creates, on purpose: the test has to fail
# for a credential column added by any FUTURE migration, not only by this one.
_CREDENTIAL_SHAPED = re.compile(r"credential|password|passwd|secret|api_key|apikey|token")


def _workout_values(external_id: str, **overrides: Any) -> dict[str, Any]:
    """A minimal valid `workouts` row. Core `insert()` binds every value."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": DEFAULT_USER_ID,
        "provider": "hevy",
        "external_id": external_id,
        "title": _TITLE,
        "start_time": _START,
        "end_time": _START + dt.timedelta(hours=1),
    }
    values.update(overrides)
    return values


@pytest.mark.integration
async def test_workout_timestamps_are_timestamptz(engine: AsyncEngine) -> None:
    """FOUND-04 against live DDL: a bare ``DateTime()`` in the model shows up here."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select column_name, data_type from information_schema.columns "
                "where table_schema = 'public' and table_name = 'workouts'"
            )
        )
    data_types = {row[0]: row[1] for row in rows}
    for column in (
        "start_time",
        "end_time",
        "provider_created_at",
        "provider_updated_at",
        "created_at",
        "updated_at",
    ):
        assert data_types[column] == "timestamp with time zone", column


@pytest.mark.integration
async def test_set_numeric_precision(engine: AsyncEngine) -> None:
    """`weight_kg` is NUMERIC(7,3) in the database, not DOUBLE PRECISION.

    Phase 4 sums thousands of these into tonnage. A float column would make the
    same set of workouts produce different totals depending on summation order.
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "select numeric_precision, numeric_scale "
                    "from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'workout_sets' "
                    "and column_name = 'weight_kg'"
                )
            )
        ).one()
    assert (row[0], row[1]) == (7, 3)


@pytest.mark.integration
async def test_unique_constraints_exist(engine: AsyncEngine) -> None:
    """All three keys exist as REAL unique constraints, which is what `ON CONFLICT` needs."""
    async with engine.connect() as conn:
        rows = await conn.execute(sa.text("select conname from pg_constraint where contype = 'u'"))
    names = {row[0] for row in rows}
    assert {
        "uq_workouts_user_provider_external_id",
        "uq_workout_exercises_workout_id_exercise_index",
        "uq_workout_sets_workout_exercise_id_set_index",
    } <= names


@pytest.mark.integration
async def test_duplicate_external_id_is_rejected(engine: AsyncEngine) -> None:
    """HEVY-03: re-syncing the same Hevy workout cannot create a second row.

    The two inserts carry different primary keys, so this proves the
    ``(user_id, provider, external_id)`` constraint and not merely the PK.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.insert(Workout).values(**_workout_values("dup-test")))

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(Workout).values(**_workout_values("dup-test")))
    finally:
        # The container is session-scoped and shared; a leaked row would break
        # every later test that counts workouts.
        async with engine.begin() as conn:
            await conn.execute(sa.delete(Workout).where(Workout.external_id.like("dup-test%")))


@pytest.mark.integration
async def test_delete_cascades_and_leaves_siblings(engine: AsyncEngine) -> None:
    """HEVY-04: one workout's deletion takes its own subtree and nothing else."""
    workout_a, workout_b = uuid.uuid4(), uuid.uuid4()
    exercise_a, exercise_b = uuid.uuid4(), uuid.uuid4()

    try:
        async with engine.begin() as conn:
            for workout_id, exercise_id, external_id in (
                (workout_a, exercise_a, "cascade-a"),
                (workout_b, exercise_b, "cascade-b"),
            ):
                await conn.execute(
                    sa.insert(Workout).values(**_workout_values(external_id, id=workout_id))
                )
                await conn.execute(
                    sa.insert(WorkoutExercise).values(
                        id=exercise_id,
                        workout_id=workout_id,
                        exercise_index=0,
                        title="Bench Press (Barbell)",
                        exercise_template_external_id=_TEMPLATE_ID,
                    )
                )
                await conn.execute(
                    sa.insert(WorkoutSet),
                    [
                        {
                            "id": uuid.uuid4(),
                            "workout_exercise_id": exercise_id,
                            "set_index": set_index,
                            "set_type": "normal",
                            "weight_kg": Decimal("60.500"),
                            "reps": 8,
                        }
                        for set_index in (0, 1)
                    ],
                )

        async with engine.begin() as conn:
            await conn.execute(sa.delete(Workout).where(Workout.id == workout_a))

        async with engine.connect() as conn:
            surviving_workouts = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(Workout)
                .where(Workout.external_id.like("cascade-%"))
            )
            surviving_exercises = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutExercise)
                .where(WorkoutExercise.workout_id == workout_b)
            )
            surviving_sets = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutSet)
                .where(WorkoutSet.workout_exercise_id == exercise_b)
            )
            orphaned_sets = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutSet)
                .where(WorkoutSet.workout_exercise_id == exercise_a)
            )

        assert surviving_workouts == 1
        assert surviving_exercises == 1
        assert surviving_sets == 2
        # The cascade reached the GRANDchildren too. Without this the sets of the
        # deleted workout would survive as unreachable rows and still be summed by
        # any Phase 4 query that joins from `workout_sets` upward.
        assert orphaned_sets == 0
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.delete(Workout).where(Workout.external_id.like("cascade-%")))


@pytest.mark.integration
async def test_body_measurement_date_is_a_date_not_a_timestamp(engine: AsyncEngine) -> None:
    """HEVY-07 against live DDL: `measured_on` is a DATE column.

    A TIMESTAMPTZ here would silently force every sync to invent a time of day, and
    two syncs of the same Hevy entry could then disagree about which row they mean.
    """
    async with engine.connect() as conn:
        data_type = await conn.scalar(
            sa.text(
                "select data_type from information_schema.columns "
                "where table_schema = 'public' and table_name = 'body_measurements' "
                "and column_name = 'measured_on'"
            )
        )
    assert data_type == "date"


@pytest.mark.integration
async def test_body_measurement_has_all_seventeen_metric_columns(engine: AsyncEngine) -> None:
    """One row per date carries every metric Hevy sends -- not one row per metric."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = 'body_measurements'"
            )
        )
    metrics = {row[0] for row in rows} - _BODY_IDENTITY_COLUMNS
    assert len(metrics) == 17, sorted(metrics)


@pytest.mark.integration
async def test_duplicate_body_measurement_date_is_rejected(engine: AsyncEngine) -> None:
    """Re-syncing the same Hevy date cannot create a second row.

    The two inserts carry different primary keys, so this proves the
    ``(user_id, source, measured_on)`` constraint and not merely the PK.
    """
    values: dict[str, Any] = {
        "user_id": DEFAULT_USER_ID,
        "source": "hevy",
        "measured_on": _MEASURED_ON,
        "weight_kg": Decimal("81.40"),
    }
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.insert(BodyMeasurement).values(id=uuid.uuid4(), **values))

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(BodyMeasurement).values(id=uuid.uuid4(), **values))
    finally:
        # The container is session-scoped and shared.
        async with engine.begin() as conn:
            await conn.execute(
                sa.delete(BodyMeasurement).where(BodyMeasurement.measured_on == _MEASURED_ON)
            )


@pytest.mark.integration
async def test_no_table_stores_a_credential(engine: AsyncEngine) -> None:
    """The Hevy key lives in the environment, not the database (T-03-12).

    This test is what keeps it that way.
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select table_name, column_name from information_schema.columns "
                "where table_schema = 'public'"
            )
        )
    offenders = [
        f"{table_name}.{column_name}"
        for table_name, column_name in rows
        if _CREDENTIAL_SHAPED.search(column_name.lower())
    ]
    assert offenders == []


@pytest.mark.integration
async def test_secondary_muscle_groups_is_a_text_array(engine: AsyncEngine) -> None:
    """Hevy's secondary muscles survive as an ARRAY, not a comma-joined string.

    A delimited string would have to be split on every read, and any muscle name
    containing the delimiter would corrupt silently.
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "select data_type, is_nullable from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'exercise_templates' "
                    "and column_name = 'secondary_muscle_groups'"
                )
            )
        ).one()
    assert row[0] == "ARRAY"
    # NOT NULL with a `'{}'` default: "no secondary muscles" is an empty array, never
    # NULL, so Phase 4 never has to distinguish the two.
    assert row[1] == "NO"

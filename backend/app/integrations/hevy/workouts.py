"""Workout persistence and full sync (HEVY-01, HEVY-03, HEVY-08).

Idempotency has a specific shape here, forced by the API: Hevy's exercises and sets carry only
an `index`, never an id. There is therefore no stable key to upsert a child against. The
correct pattern -- verified against PostgreSQL 18 -- is:

    upsert the workout on (user_id, provider, external_id)
    DELETE its exercises  (ON DELETE CASCADE takes the sets)
    reinsert every exercise and set

The tempting alternative -- upsert children on (workout_id, index) -- is wrong in a way that
is invisible until Phase 4: an edited workout with FEWER sets than before leaves the surplus
rows in place, and every volume, tonnage and PR figure computed from them is inflated forever.

Failure isolation uses SAVEPOINTs, not try/except alone. In PostgreSQL a failed statement
aborts the whole transaction; every later statement then fails with "current transaction is
aborted, commands ignored until end of transaction block". `session.begin_nested()` is what
makes "skip the one bad workout, commit the other nine" possible at all.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.db.repositories.sync_state import PROVIDER_HEVY
from app.integrations.hevy.schemas import HevyWorkout

log = structlog.get_logger()

PROVIDER = PROVIDER_HEVY


@dataclass(frozen=True, slots=True)
class PagePersistResult:
    """What one page of workouts did to the database."""

    upserted: int
    # Hevy workout ids, not rows: a skipped workout has no row to point at. Kept so the caller
    # can name what was dropped instead of reporting a bare count.
    skipped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkoutSyncResult:
    """The outcome of a whole `sync_workouts` run."""

    pages_fetched: int
    workouts_upserted: int
    skipped: tuple[str, ...]
    # `None` when the run never established a reconciliation baseline. Compared against
    # `local_count` to detect a silently partial sync (D-09).
    remote_count: int | None
    local_count: int


async def upsert_workout(
    session: AsyncSession, *, user_id: uuid.UUID, workout: HevyWorkout
) -> uuid.UUID:
    """Write one workout and its whole exercise/set tree idempotently. HEVY-03.

    Does not commit. The caller owns the transaction, because D-08 requires the page's rows and
    the resume checkpoint to land together or not at all.
    """
    statement = pg_insert(Workout).values(
        id=uuid.uuid4(),
        user_id=user_id,
        provider=PROVIDER,
        external_id=workout.id,
        title=workout.title,
        description=workout.description,
        routine_external_id=workout.routine_id,
        start_time=workout.start_time,
        end_time=workout.end_time,
        # Hevy's own timestamps, distinct from this row's `created_at`/`updated_at`, which
        # record when WE stored it.
        provider_created_at=workout.created_at,
        provider_updated_at=workout.updated_at,
    )
    # NO staleness guard on this conflict clause -- no predicate, deliberately. A guarded
    # ON CONFLICT suppresses the update, which makes RETURNING emit NOTHING, which makes
    # scalar_one() raise NoResultFound on exactly the workouts that were skipped as
    # unchanged (Pitfall 4). Hevy is the source of truth and an unconditional update is
    # always correct here; the guard would buy nothing and cost a branch that only fires
    # in production.
    #
    # Bound to the constraint BY NAME rather than by column list, so a rename fails loudly
    # instead of degrading into a duplicate-row insert.
    upsert = statement.on_conflict_do_update(
        constraint="uq_workouts_user_provider_external_id",
        set_={
            "title": statement.excluded.title,
            "description": statement.excluded.description,
            "routine_external_id": statement.excluded.routine_external_id,
            "start_time": statement.excluded.start_time,
            "end_time": statement.excluded.end_time,
            "provider_created_at": statement.excluded.provider_created_at,
            "provider_updated_at": statement.excluded.provider_updated_at,
        },
    ).returning(Workout.id)
    workout_id: uuid.UUID = (await session.execute(upsert)).scalar_one()

    # Delete-and-reinsert, NOT per-child upsert. See the module docstring.
    # ON DELETE CASCADE on workout_sets.workout_exercise_id removes the sets.
    await session.execute(delete(WorkoutExercise).where(WorkoutExercise.workout_id == workout_id))
    for exercise in workout.exercises:
        exercise_id = uuid.uuid4()
        await session.execute(
            insert(WorkoutExercise).values(
                id=exercise_id,
                workout_id=workout_id,
                exercise_index=exercise.index,
                title=exercise.title,
                notes=exercise.notes,
                # Stored even when no local `exercise_templates` row exists. D-03 requires
                # the workout to persist regardless of whether its template has been synced
                # or mapped -- which is exactly why this column is a plain string and not a
                # foreign key.
                exercise_template_external_id=exercise.exercise_template_id,
                # `0` is a real superset group, so this must never be tested for truthiness.
                supersets_id=exercise.supersets_id,
            )
        )
        if exercise.sets:
            # executemany: a list of dicts as the SECOND argument to session.execute().
            # Measured at 44x faster than row-by-row for 12,000 rows; `sets` is by far the
            # highest-cardinality table this sync writes.
            await session.execute(
                insert(WorkoutSet),
                [
                    {
                        "id": uuid.uuid4(),
                        "workout_exercise_id": exercise_id,
                        "set_index": s.index,
                        # Verbatim: VOL-01 excludes exactly the string 'warmup', and the
                        # dropset/failure distinction is what Phase 5's PR detection reads.
                        "set_type": s.type,
                        "weight_kg": s.weight_kg,
                        "reps": s.reps,
                        "distance_meters": s.distance_meters,
                        "duration_seconds": s.duration_seconds,
                        "rpe": s.rpe,
                        "custom_metric": s.custom_metric,
                    }
                    for s in exercise.sets
                ],
            )
    return workout_id


async def delete_workout(session: AsyncSession, *, user_id: uuid.UUID, external_id: str) -> bool:
    """Delete a workout and (by FK cascade) everything under it. HEVY-04.

    Returns False when nothing matched. That is a NO-OP, not an error: the events feed can
    report a deletion for a workout that was created and deleted between two of our syncs and
    that we therefore never stored.

    RETURNING rather than `rowcount`: the unique constraint makes at most one row match, and
    a returned id is a typed answer the ORM layer states directly.
    """
    removed = await session.scalars(
        delete(Workout)
        .where(
            Workout.user_id == user_id,
            Workout.provider == PROVIDER,
            Workout.external_id == external_id,
        )
        .returning(Workout.id)
    )
    return removed.first() is not None


async def persist_workout_page(
    session: AsyncSession, *, user_id: uuid.UUID, workouts: Sequence[HevyWorkout]
) -> PagePersistResult:
    """Write one page of workouts, quarantining any single workout the database rejects.

    Each workout gets its own SAVEPOINT. Without one, PostgreSQL aborts the entire transaction
    on the first failed statement and every later workout on the page fails too, so one
    malformed record would cost the whole page (Pitfall 11).
    """
    upserted = 0
    skipped: list[str] = []
    for workout in workouts:
        try:
            async with session.begin_nested():  # SAVEPOINT
                await upsert_workout(session, user_id=user_id, workout=workout)
        except SQLAlchemyError as exc:
            # Class name only. Rendering a DataError reproduces the offending bound parameter
            # values -- i.e. this user's workout titles and weights -- straight into a log
            # line (T-03-23).
            skipped.append(workout.id)
            log.warning("hevy_workout_skipped", workout_id=workout.id, reason=type(exc).__name__)
        else:
            upserted += 1
    return PagePersistResult(upserted=upserted, skipped=tuple(skipped))

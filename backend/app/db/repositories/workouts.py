"""The two Phase 6 queries with no analytics function behind them (MCP-02, MCP-03, MCP-05).

`fitness_get_recent_workouts` (D-09) and `fitness_get_workout` (D-11, D-12) are the only tools in
this phase that ask a question Phase 4 and Phase 5 never asked: "what did the last N sessions look
like", and "show me exactly one of them". Everything else composes an existing analytics function.
These two are purpose-built PROJECTIONS with fixed shapes and hard caps -- deliberately not raw
table access, which MCP-03 forbids.

**Read-only, and the caller owns the transaction.** Every function here takes an `AsyncSession`
and never commits, flushes, adds, or imports `insert` / `update` / `delete`. That mirrors
`sync_state.py`'s contract and `app/analytics/`'s: MCP-05 makes read-only a product guarantee for
v1, and a stray write buried in a projection is still a write no matter how read-only the tool
that called it claims to be.

**The hard-set rule is IMPORTED, never restated.** `hard_set_predicates` comes from
`app.analytics.rollup`. This is the one place the `app/db` -> `app.analytics` arrow is drawn, and
it is drawn on purpose: `rollup.py` says the hard-set decision is "ONE constant, checked in ONE
place", and a second copy here is exactly how the two would eventually disagree -- at which point
one workout reports 12 hard sets through `fitness_get_recent_workouts` and 14 through
`fitness_get_weekly_volume`, with nothing erroring anywhere.

**Tonnage follows Phase 4's operand-presence gate exactly.** The product `weight_kg * reps` is
NULL whenever either operand is, SQL `SUM` skips those rows silently, and the result is reported
as `None` rather than `0`. "We could not compute tonnage for this session" is a different fact
from "you moved zero kilograms". `tonnage_sets` travels beside the figure and counts the sets that
actually contributed, so the population the number was computed over is visible rather than
assumed.

**The hard-set rule is applied as a `case`, never as a WHERE filter.** A WHERE filter would drop
warm-up-only workouts out of the list entirely, and "I trained on Wednesday" would silently become
false. The joins are OUTER for the same reason: a workout with no exercises and no sets is still a
workout that happened.

**No surrogate id ever leaves this module** (T-06-08). `Workout.id` appears in GROUP BY and in the
joins because that is what makes the aggregate correct; the returned rows carry `external_id`
only, which is the id D-12 keys `fitness_get_workout` on and the one Hevy itself uses.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import Numeric, and_, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rollup import hard_set_predicates
from app.core.time import local_day
from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.db.repositories.sync_state import PROVIDER_HEVY

log = structlog.get_logger()

# Tonnage is summed in SQL and must round-trip as an exact `Decimal`. The scale matches
# `workout_sets.weight_kg` (Numeric(7,3)); the precision is widened so a whole session's tonnage
# cannot overflow the column type its operands came from.
_TONNAGE_TYPE = Numeric(12, 3)

_SECONDS_PER_MINUTE = 60


@dataclass(frozen=True, slots=True)
class WorkoutSummaryRow:
    """One workout, at the grain D-09 specifies: session-level totals and nothing per-exercise.

    `tonnage_kg` is `Decimal | None` and the `None` is load-bearing -- see the module docstring.
    """

    external_id: str
    local_day: dt.date
    title: str
    duration_minutes: int
    exercise_count: int
    hard_sets: int
    tonnage_sets: int
    tonnage_kg: Decimal | None


@dataclass(frozen=True, slots=True)
class WorkoutSetRow:
    """One set exactly as recorded, warm-up or not, with every modality column carried."""

    set_index: int
    set_type: str
    weight_kg: Decimal | None
    reps: int | None
    distance_meters: Decimal | None
    duration_seconds: int | None
    rpe: Decimal | None


@dataclass(frozen=True, slots=True)
class WorkoutExerciseRow:
    """One exercise within a workout, with its sets in `set_index` order."""

    exercise_index: int
    title: str
    exercise_template_external_id: str
    supersets_id: int | None
    sets: tuple[WorkoutSetRow, ...]


@dataclass(frozen=True, slots=True)
class WorkoutDetailRow:
    """One whole workout. `total_sets` is the TRUE count, before any truncation."""

    external_id: str
    local_day: dt.date
    title: str
    duration_minutes: int
    exercises: tuple[WorkoutExerciseRow, ...]
    total_sets: int


def _duration_minutes(start: dt.datetime, end: dt.datetime) -> int:
    """Whole minutes between two aware instants, rounded to nearest.

    Both columns are `DateTime(timezone=True)` and both are NOT NULL, so this never has to
    consider a missing end time. Rounded rather than truncated: a 74-minute-40-second session
    reported as 74 would be off by more than the figure's own resolution.

    Neither column carries a DB CHECK that `end >= start`, and nothing upstream validates it on
    sync or edit. Clamp rather than let a corrupted row report a negative session length to
    Claude.
    """
    seconds = (end - start).total_seconds()
    if seconds < 0:
        log.warning("workout_duration_negative", start=start.isoformat(), end=end.isoformat())
        return 0
    return round(seconds / _SECONDS_PER_MINUTE)


async def recent_workout_summaries(
    session: AsyncSession, *, user_id: uuid.UUID, tz: str, limit: int
) -> list[WorkoutSummaryRow]:
    """The most recent `limit` workouts as compact summaries, newest first (D-09, D-10).

    ONE aggregate statement. Fetching the sets into Python to count them is the anti-pattern
    CLAUDE.md's "SQL aggregates" rule exists to prevent, and at ~20 sets per session over a
    50-workout page it is a thousand rows crossing the wire to produce eight numbers.

    `limit` is a REQUIRED keyword argument with no default (D-10, MCP-03): the caller -- the tool
    layer -- owns the cap, and a default here would be a second, invisible place for it to live.

    `user_id` is keyword-only with no default (T-06-02, ASVS V4), so forgetting the tenant
    predicate is a `TypeError` rather than a cross-tenant read a single-user suite cannot see.
    """
    hard_set = and_(*hard_set_predicates())

    # Operand presence, never a modality allow-list. `weight_kg * reps` is NULL whenever either
    # side is, and SQL SUM drops NULL inputs without a word; the count beside the sum is what
    # makes that droppage visible instead of silent.
    has_tonnage = and_(
        *hard_set_predicates(),
        WorkoutSet.weight_kg.is_not(None),
        WorkoutSet.reps.is_not(None),
    )

    stmt = (
        select(
            Workout.external_id,
            Workout.title,
            Workout.start_time,
            Workout.end_time,
            # `distinct` is required on both counts: the set join fans each exercise row out once
            # per set, so a plain `count(WorkoutExercise.id)` would report 20 exercises for a
            # 5-exercise, 20-set session.
            func.count(distinct(WorkoutExercise.id)).label("exercise_count"),
            # The hard-set rule as a CASE, never a WHERE. A WHERE would delete every
            # warm-up-only workout from the list rather than reporting it with zero hard sets.
            func.count(distinct(case((hard_set, WorkoutSet.id)))).label("hard_sets"),
            func.count(case((has_tonnage, 1))).label("tonnage_sets"),
            cast(
                func.sum(case((hard_set, WorkoutSet.weight_kg * WorkoutSet.reps))),
                _TONNAGE_TYPE,
            ).label("tonnage_kg"),
        )
        .select_from(Workout)
        # OUTER on BOTH joins: a workout with no exercises, or an exercise with no sets, is still
        # something that happened and must still appear in the list.
        .join(WorkoutExercise, WorkoutExercise.workout_id == Workout.id, isouter=True)
        .join(WorkoutSet, WorkoutSet.workout_exercise_id == WorkoutExercise.id, isouter=True)
        .where(
            # The tenant predicate leads (T-06-02).
            Workout.user_id == user_id,
            Workout.provider == PROVIDER_HEVY,
        )
        .group_by(
            Workout.id,
            Workout.external_id,
            Workout.title,
            Workout.start_time,
            Workout.end_time,
        )
        # The `external_id` tie-break is NOT optional: two workouts can share a `start_time`, and
        # an unstable order is a flaky test and a list whose "most recent 10" changes between two
        # identical calls.
        .order_by(Workout.start_time.desc(), Workout.external_id.desc())
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()
    return [
        WorkoutSummaryRow(
            external_id=row.external_id,
            # FOUND-03: the day a workout belongs to is the USER's local day, and at UTC+7 every
            # instant from 17:00Z belongs to tomorrow.
            local_day=local_day(row.start_time, tz),
            title=row.title,
            duration_minutes=_duration_minutes(row.start_time, row.end_time),
            exercise_count=row.exercise_count,
            hard_sets=row.hard_sets,
            tonnage_sets=row.tonnage_sets,
            # Left exactly as the driver returns it: `Decimal | None`, never coerced to zero.
            tonnage_kg=row.tonnage_kg,
        )
        for row in rows
    ]


async def workout_detail(
    session: AsyncSession, *, user_id: uuid.UUID, external_id: str, tz: str, max_sets: int
) -> WorkoutDetailRow | None:
    """One workout in full, keyed on its Hevy external id (D-11, D-12). `None` if unknown.

    `tz` is required for the same reason `recent_workout_summaries` needs it: `local_day` is the
    USER's calendar day (FOUND-03), and `app/core/time.py` is explicit that a module-level default
    timezone is how a wrong-timezone bug passes every test. The two functions must agree about
    which day a workout belongs to, or the same session is dated 2026-08-30 in the list and
    2026-08-31 in the detail view.

    **This is the ONE place in Phase 6 that does not exclude warm-ups.** Every other tool reports
    hard sets, because that is the unit training volume is measured in. This tool is the raw
    record of what happened, so every set is returned with its `set_type` carried alongside and
    the reader can tell a warm-up from a working set.

    **A missing workout returns `None` and raises nothing.** An unknown id is an answer, not a
    failure -- and a raised exception in a tool body reaches Claude verbatim as its message text
    (Pitfall 3), which is the highest-risk disclosure surface in this phase.

    `external_id` reaches SQL as a BOUND parameter of a Core expression (T-06-04). There is no
    string formatting of SQL anywhere in this module.

    `max_sets` is required with no default (T-06-05). Truncation drops sets from the END --
    highest `exercise_index`, then highest `set_index` -- so the earliest work of the session is
    what survives, and `total_sets` always reports the true pre-truncation count so the caller can
    set `sets_truncated` from `total_sets > max_sets`. A silent truncation would be a wrong
    answer; a flagged one is a smaller answer.
    """
    workout = (
        await session.execute(
            select(
                Workout.id,
                Workout.external_id,
                Workout.title,
                Workout.start_time,
                Workout.end_time,
            ).where(
                # T-06-02: the tenant predicate leads and is unconditional, so a guessed
                # `external_id` belonging to another user resolves to no row at all.
                Workout.user_id == user_id,
                Workout.provider == PROVIDER_HEVY,
                Workout.external_id == external_id,
            )
        )
    ).one_or_none()
    if workout is None:
        return None

    set_rows = (
        await session.execute(
            select(
                WorkoutExercise.exercise_index,
                WorkoutExercise.title,
                WorkoutExercise.exercise_template_external_id,
                WorkoutExercise.supersets_id,
                WorkoutSet.set_index,
                WorkoutSet.set_type,
                WorkoutSet.weight_kg,
                WorkoutSet.reps,
                WorkoutSet.distance_meters,
                WorkoutSet.duration_seconds,
                WorkoutSet.rpe,
            )
            .select_from(WorkoutExercise)
            # OUTER: an exercise recorded with no sets is part of the record of the session.
            .join(WorkoutSet, WorkoutSet.workout_exercise_id == WorkoutExercise.id, isouter=True)
            .where(WorkoutExercise.workout_id == workout.id)
            # Deterministic and meaningful: this is the order the session was performed in, and
            # it is also the order truncation consumes.
            .order_by(WorkoutExercise.exercise_index, WorkoutSet.set_index)
        )
    ).all()

    # Fold in Python rather than with a second per-exercise query: one round trip, and the
    # nesting rule stays a plain loop that is readable without a database.
    exercises: list[WorkoutExerciseRow] = []
    total_sets = 0
    for row in set_rows:
        if not exercises or exercises[-1].exercise_index != row.exercise_index:
            exercises.append(
                WorkoutExerciseRow(
                    exercise_index=row.exercise_index,
                    title=row.title,
                    exercise_template_external_id=row.exercise_template_external_id,
                    supersets_id=row.supersets_id,
                    sets=(),
                )
            )
        if row.set_index is None:
            # The OUTER join's placeholder for an exercise with no sets. Not a set; not counted.
            continue
        total_sets += 1
        current = exercises[-1]
        exercises[-1] = WorkoutExerciseRow(
            exercise_index=current.exercise_index,
            title=current.title,
            exercise_template_external_id=current.exercise_template_external_id,
            supersets_id=current.supersets_id,
            sets=(
                *current.sets,
                WorkoutSetRow(
                    set_index=row.set_index,
                    set_type=row.set_type,
                    weight_kg=row.weight_kg,
                    reps=row.reps,
                    distance_meters=row.distance_meters,
                    duration_seconds=row.duration_seconds,
                    rpe=row.rpe,
                ),
            ),
        )

    if total_sets > max_sets:
        exercises = _truncate_from_the_end(exercises, max_sets=max_sets)

    return WorkoutDetailRow(
        external_id=workout.external_id,
        local_day=local_day(workout.start_time, tz),
        title=workout.title,
        duration_minutes=_duration_minutes(workout.start_time, workout.end_time),
        exercises=tuple(exercises),
        # The TRUE count, deliberately computed before truncation.
        total_sets=total_sets,
    )


def _truncate_from_the_end(
    exercises: list[WorkoutExerciseRow], *, max_sets: int
) -> list[WorkoutExerciseRow]:
    """Keep the `max_sets` lowest `(exercise_index, set_index)` sets, dropping emptied exercises.

    Only ever called when the true count already exceeds the cap, so an exercise left with no
    sets here is one truncation emptied -- and reporting it with an empty set list would read as
    "you performed this exercise and recorded nothing", which is a different and false statement.
    """
    kept: list[WorkoutExerciseRow] = []
    remaining = max_sets
    for exercise in exercises:
        if remaining <= 0:
            break
        trimmed = exercise.sets[:remaining]
        remaining -= len(trimmed)
        kept.append(
            WorkoutExerciseRow(
                exercise_index=exercise.exercise_index,
                title=exercise.title,
                exercise_template_external_id=exercise.exercise_template_external_id,
                supersets_id=exercise.supersets_id,
                sets=trimmed,
            )
        )
    return kept

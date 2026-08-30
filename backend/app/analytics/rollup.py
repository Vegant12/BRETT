"""The one query substrate under VOL-01, VOL-02 and VOL-03: window, aggregate, fan-out.

Five rules in this module are counter-intuitive, and each of the first three was measured
producing a silently wrong number against the live 327-workout database.

**One aggregate, at the ``(week, workout_id, template_id)`` grain.** VOL-01 (weekly volume),
VOL-02 (per-muscle volume) and VOL-03 (frequency) all read the same rows. The coarser
``(week, template_id)`` grain is the obvious simplification -- 16% fewer rows -- and it makes
per-muscle SESSION counts impossible to compute at all. Aggregating ``workout_id`` away inflated
hamstring frequency from 2 to 8 (4.0x) on one real training week.

**The tonnage gate is OPERAND PRESENCE, never a modality allow-list.** Tonnage is computed
wherever both a weight and a rep count exist, and nowhere else. The model's own modality
vocabulary had already drifted from what the provider actually sends; operand presence
reproduces the live modality table exactly and survives the provider inventing a tenth
modality tomorrow.

**Hard sets are an EXCLUSION of ``warmup``, never an allow-list of ``normal``.** Filtering to
``normal`` would discard 823 dropset sets -- 12% of all hard sets -- and would silently start
discarding ``failure`` sets the day the provider first sends one.

**Muscle resolution goes through ``effective_muscles_bulk``, never a join.** The override rule
is REPLACEMENT -- any override replaces the base set entirely -- and a join expresses merge. A
join agrees with the resolver today only because ``exercise_muscle_overrides`` holds zero rows;
it starts lying, with no error anywhere, the first time the user corrects a mapping.

**``Decimal``, never binary floating point, for every summed magnitude.** These figures multiply
into tonnage sums, and two arithmetically identical weekly totals must compare equal.

The split is deliberate: SQL does the counting, Python does the business rules. The aggregate is
one indexed statement; every fold below it is pure, synchronous and unit-testable with no
container. That is CLAUDE.md's "SQL aggregates + plain Python keeps them trivially
unit-testable" rule expressed as a file layout.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, and_, cast, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import (
    local_range_bounds,
    snap_local_week_range,
    validate_timezone,
)
from app.db.models.user import User
from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.normalization.resolver import EffectiveMuscle, effective_muscles_bulk

# VOL-01 excludes exactly this set type and no other. Written as the value being EXCLUDED, never
# as an allow-list of included types: `dropset` is 823 live sets (12% of hard sets) and `failure`
# is declared in workout.py but has never been sent, so an allow-list would start silently
# dropping it the day it first appears.
WARMUP_SET_TYPE = "warmup"

# U-02 (extends VOL-01). A duration-only set -- neither reps nor weight, e.g. a timed plank hold
# -- COUNTS as a hard set, exactly like any other non-warmup set. It contributes nothing to reps
# or tonnage because those columns are NULL for it.
#
# ONE constant, checked in ONE place (`_hard_set_predicates`), so flipping this decision later is
# a one-line change. Do NOT scatter a modality list through the query or the fold: 24 live sets
# are affected and the flip must not require finding every site.
COUNT_DURATION_ONLY_SETS = True

# ASVS V5 / MCP-03: reject an implausible range before any row is materialised, so a Phase 6 tool
# cannot ask for two centuries of week buckets. ~5 years, which comfortably covers the 17 months
# of real history and any "all time" question a coach would ask.
MAX_ANALYTICS_WINDOW_DAYS = 1830


@dataclass(frozen=True, slots=True)
class AnalyticsWindow:
    """A validated analytics window. INTERNAL -- never returned to a caller.

    ``start_day`` / ``end_day`` are POST-snap. When ``snap_to_weeks`` was False they equal what
    the caller asked for; when it was True they have been widened outward to whole Monday-start
    weeks (U-01), which is why weekly volume never reports a partial week as a whole one.

    ``days`` is the inclusive local-day span of ``[start_day, end_day]`` and is what frequency
    divides by, so an unsnapped 10-day window is 10/7 weeks and not 2.
    """

    tz: str
    start_day: dt.date
    end_day: dt.date
    utc_start: dt.datetime
    utc_end: dt.datetime
    days: int


def build_window(
    *, start_day: dt.date, end_day: dt.date, tz: str, snap_to_weeks: bool
) -> AnalyticsWindow:
    """Validate, optionally snap, and convert an inclusive local date range (D-03, U-01).

    Pure and synchronous on purpose: every guard here is a business rule, and encoding a
    business rule in SQL makes it untestable without a container.

    The clamp is applied to the RANGE THE CALLER ASKED FOR, before snapping, so the error
    message describes their request rather than a widened version of it. Every message names
    the failure and carries no date value and no user id, because it will be logged.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    if (end_day - start_day).days + 1 > MAX_ANALYTICS_WINDOW_DAYS:
        raise ValueError("requested analytics window exceeds the maximum span")

    # ASVS V5: `users.timezone` carries no DB CHECK constraint, and this string is about to
    # reach the query as a bound timezone parameter. Rejecting it here beats an
    # unknown-timezone failure raised from inside an aggregate query.
    zone = validate_timezone(tz)

    resolved_start, resolved_end = (
        snap_local_week_range(start_day, end_day) if snap_to_weeks else (start_day, end_day)
    )
    utc_start, utc_end = local_range_bounds(resolved_start, resolved_end, zone)
    return AnalyticsWindow(
        tz=zone,
        start_day=resolved_start,
        end_day=resolved_end,
        utc_start=utc_start,
        utc_end=utc_end,
        days=(resolved_end - resolved_start).days + 1,
    )


async def resolve_window(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    snap_to_weeks: bool,
) -> AnalyticsWindow:
    """Read the user's timezone (FOUND-03) and build the window.

    The timezone comes from ``users.timezone`` and is never a module constant, an environment
    variable or a caller default: a hardcoded default would let a wrong-timezone bug pass every
    test, and at UTC+7 every instant between 17:00Z and 24:00Z belongs to the NEXT local day --
    which is every morning workout.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return build_window(start_day=start_day, end_day=end_day, tz=tz, snap_to_weeks=snap_to_weeks)


@dataclass(frozen=True, slots=True)
class SetRollupRow:
    """One (local week, workout, exercise template) group of non-warmup sets.

    ``tonnage_sets`` sits beside ``tonnage_kg`` deliberately. SQL ``SUM`` skips NULL products
    without a warning, so an unguarded tonnage figure is a real number computed over a silently
    smaller population -- 543 of 7,719 live non-warmup sets produce a NULL product. With
    ``tonnage_sets`` the caller can tell "0 kg, and we know it" from "we could not compute this".

    ``workout_id`` is carried at this grain and NOT aggregated away, because it is the only thing
    that makes per-muscle session counts possible. Dropping it inflated hamstring frequency from
    2 to 8 on a real week.
    """

    week_start: dt.date
    workout_id: uuid.UUID
    template_external_id: str
    hard_sets: int
    total_reps: int | None
    tonnage_sets: int
    tonnage_kg: Decimal | None


def _hard_set_predicates() -> list[Any]:
    """Which sets count as hard sets. VOL-01 plus U-02, in one place.

    Returns predicates rather than a single expression so the caller composes them into the
    same WHERE list as the user and window filters -- keeping every predicate visible in one
    statement instead of buried in a nested boolean.
    """
    predicates: list[Any] = [WorkoutSet.set_type != WARMUP_SET_TYPE]
    if not COUNT_DURATION_ONLY_SETS:
        # A duration-only set is one with NEITHER reps NOR weight. A short-distance-weight set
        # has a weight and no reps and is therefore NOT duration-only; it always counts.
        predicates.append(not_(and_(WorkoutSet.weight_kg.is_(None), WorkoutSet.reps.is_(None))))
    return predicates


async def weekly_set_rows(
    session: AsyncSession, *, user_id: uuid.UUID, window: AnalyticsWindow
) -> list[SetRollupRow]:
    """The one aggregate every Phase 4 metric is built from.

    7,984 live sets collapse to ~2,239 rows in ~50 ms. Fetching the sets into Python to count
    them is the anti-pattern CLAUDE.md's "SQL aggregates" rule exists to prevent; folding those
    rows out to muscle groups in Python is what keeps the business rules unit-testable. That
    split is the whole design.

    There is deliberately no row cap. The guard is ``MAX_ANALYTICS_WINDOW_DAYS``, applied by
    ``build_window`` before anything is materialised: a silent truncation would be a wrong
    answer, whereas an over-wide request is a refused one.
    """
    # `cast(..., Date)` is NOT cosmetic. `date_trunc` over a timestamp-without-time-zone yields
    # a NAIVE datetime, which never compares equal to the `datetime.date` week keys the spine
    # and the folds use -- the merge would then silently produce two entries per week.
    #
    # `func.timezone(tz, col)` keeps the timezone a BOUND PARAMETER (T-04-01). Never f-string it.
    week = cast(func.date_trunc("week", func.timezone(window.tz, Workout.start_time)), Date)

    # Operand presence, never a modality allow-list: `weight_kg * reps` is NULL whenever either
    # side is, and SQL SUM drops NULL inputs without a word. The FILTER-ed count beside the sum
    # is what makes that droppage visible instead of silent.
    has_tonnage = and_(WorkoutSet.weight_kg.is_not(None), WorkoutSet.reps.is_not(None))

    stmt = (
        select(
            week.label("week_start"),
            Workout.id.label("workout_id"),
            WorkoutExercise.exercise_template_external_id.label("template_id"),
            func.count().label("hard_sets"),
            func.sum(WorkoutSet.reps).label("total_reps"),
            func.count().filter(has_tonnage).label("tonnage_sets"),
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps)
            .filter(has_tonnage)
            .label("tonnage_kg"),
        )
        .select_from(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        .where(
            # T-04-02: the tenant predicate leads, and `user_id` is keyword-only with no default,
            # so forgetting it is a TypeError rather than a cross-tenant read.
            Workout.user_id == user_id,
            # The column stays BARE on the left of both comparisons -- that is what keeps
            # `ix_workouts_user_id_start_time` usable. Converting the column's timezone here
            # instead was measured as a Seq Scan removing 299 of 327 rows.
            Workout.start_time >= window.utc_start,
            Workout.start_time < window.utc_end,
            *_hard_set_predicates(),
        )
        # The grain is (week, workout, template), not (week, template). The coarser one is 16%
        # fewer rows and makes per-muscle session counts impossible to compute at all.
        .group_by(week, Workout.id, WorkoutExercise.exercise_template_external_id)
        # Deterministic ordering is a repo-wide rule (`resolver.py`, `hevy/sync.py`);
        # dict-iteration order is a flaky test waiting to happen.
        .order_by(week, Workout.id, WorkoutExercise.exercise_template_external_id)
    )

    rows = (await session.execute(stmt)).all()
    return [
        SetRollupRow(
            week_start=row.week_start,
            workout_id=row.workout_id,
            template_external_id=row.template_id,
            hard_sets=row.hard_sets,
            total_reps=int(row.total_reps) if row.total_reps is not None else None,
            tonnage_sets=row.tonnage_sets,
            # Left exactly as the driver returns it: `Decimal | None`, never coerced. `None`
            # means "no set in this group had both operands", which is not zero kilograms.
            tonnage_kg=row.tonnage_kg,
        )
        for row in rows
    ]


async def resolve_row_muscles(
    session: AsyncSession, *, user_id: uuid.UUID, rows: Sequence[SetRollupRow]
) -> dict[str, list[EffectiveMuscle]]:
    """Resolve every template in the window in TWO queries, not two per template.

    Delegates entirely to ``effective_muscles_bulk``. Never join ``exercise_muscles`` here: the
    rule is that ANY override REPLACES the base set entirely, and a join expresses merge. The
    join produces byte-identical output today only because the override table has zero rows --
    it starts lying the first time the user corrects a mapping, with no error anywhere.
    """
    template_ids = sorted({row.template_external_id for row in rows})
    if not template_ids:
        return {}
    return await effective_muscles_bulk(
        session, user_id=user_id, template_external_ids=template_ids
    )

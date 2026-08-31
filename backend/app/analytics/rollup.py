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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, and_, cast, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import (
    local_range_bounds,
    snap_local_week_range,
    validate_timezone,
)
from app.db.models.exercise import ExerciseTemplate
from app.db.models.user import User
from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from app.normalization.resolver import EffectiveMuscle, apply_weights, effective_muscles_bulk

# VOL-01 excludes exactly this set type and no other. Written as the value being EXCLUDED, never
# as an allow-list of included types: `dropset` is 823 live sets (12% of hard sets) and `failure`
# is declared in workout.py but has never been sent, so an allow-list would start silently
# dropping it the day it first appears.
WARMUP_SET_TYPE = "warmup"

# U-02 (extends VOL-01). A duration-only set -- neither reps nor weight, e.g. a timed plank hold
# -- COUNTS as a hard set, exactly like any other non-warmup set. It contributes nothing to reps
# or tonnage because those columns are NULL for it.
#
# ONE constant, checked in ONE place (`hard_set_predicates`), so flipping this decision later is
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


def hard_set_predicates() -> list[Any]:
    """Which sets count as hard sets. VOL-01 plus U-02, in one place.

    Returns predicates rather than a single expression so the caller composes them into the
    same WHERE list as the user and window filters -- keeping every predicate visible in one
    statement instead of buried in a nested boolean.

    Public because `app/db/repositories/workouts.py` composes the same rule into the per-workout
    projection `fitness_get_recent_workouts` returns; two definitions of 'hard set' would let one
    workout report different set counts through two different tools.
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
            *hard_set_predicates(),
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


@dataclass(frozen=True, slots=True)
class QualifyingSetRow:
    """One non-warm-up set, with the local day it belongs to, its modality and its title.

    SET grain, deliberately NOT the (local week, workout, template) grain of ``SetRollupRow``.
    D-04 selects the day's best set by ESTIMATED 1RM, which is a value derived per set and
    cannot be recovered from a pre-aggregated row; PROG-04's last sentence says the same about
    PR detection. This is a different question from Phase 4's, so it is a different aggregate --
    do not try to serve both from one.

    ``exercise_type`` is carried so ``estimates.estimate_1rm`` never needs a second query, and so
    a ``None`` (a workout referencing a template that is not synced locally) is naturally treated
    as "not weight_reps" rather than crashing. ``title`` is carried for the same reason and to
    settle a duplication risk before it happens: PROG-01, PROG-02, PROG-03, PROG-04 and CMP-01
    all want an exercise title, and ``frequency._template_titles`` is private to its module.
    Selecting it in this join costs nothing and leaves exactly ONE implementation.

    ``set_index`` is carried because it is the last tie-break in the deterministic ordering, and
    because a PR is more useful when the specific set is identifiable.
    """

    workout_id: uuid.UUID
    local_day: dt.date
    template_external_id: str
    title: str | None
    exercise_type: str | None
    set_type: str
    set_index: int
    weight_kg: Decimal | None
    reps: int | None


async def qualifying_set_rows(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    window: AnalyticsWindow,
    template_external_ids: Sequence[str] | None = None,
) -> list[QualifyingSetRow]:
    """Every non-warm-up set in the window, at set grain, ordered deterministically.

    Measured against the live database with EXPLAIN (ANALYZE, BUFFERS), PostgreSQL 18: a 12-week
    window over all exercises returns 889 rows in 10.07 ms via a Bitmap Index Scan on
    ``ix_workouts_user_id_start_time`` (40 of 327 workouts), nested-looped into
    ``uq_workout_sets_workout_exercise_id_set_index``. The all-time worst case is 7,719 rows in
    17 ms.

    There is deliberately no row cap, for the same reason ``weekly_set_rows`` has none: the guard
    is ``MAX_ANALYTICS_WINDOW_DAYS`` applied by ``build_window`` before anything is materialised.
    A silent truncation is a wrong answer; an over-wide request is a refused one.

    ``template_external_ids`` narrows to specific exercises via a BOUND ``IN`` list (ASVS V5) --
    never an interpolated string, and it can only ever narrow the result, never widen the tenant
    scope, because the tenant predicate is unconditional.
    """
    # `cast(..., Date)` is NOT cosmetic, and the trap is the same one `weekly_set_rows` documents
    # for `date_trunc`: `func.timezone(...)` over a timestamp-without-time-zone yields a NAIVE
    # datetime, which never compares equal to the `datetime.date` day keys every Phase 5 fold
    # uses -- producing two entries per day, silently, with no error.
    #
    # `func.timezone(tz, col)` keeps the timezone a BOUND PARAMETER (T-04-01, ASVS V5). Never
    # f-string it: Ruff S608 and the raw-SQL ban in `test_analytics_isolation.py` both enforce
    # this. That ban is a regex over this very source, so it cannot be named literally here --
    # spelling out the construct it forbids would fail the guard from inside a comment.
    local_day = cast(func.timezone(window.tz, Workout.start_time), Date)

    predicates: list[Any] = [
        # T-04-02: the tenant predicate leads, and `user_id` is keyword-only with no default, so
        # forgetting it is a TypeError rather than a cross-tenant read a single-user suite
        # cannot see.
        Workout.user_id == user_id,
        # The column stays BARE on the left of both comparisons -- that is what keeps
        # `ix_workouts_user_id_start_time` usable. Converting the column's timezone here instead
        # was measured in Phase 4 as a Seq Scan removing 299 of 327 rows.
        Workout.start_time >= window.utc_start,
        Workout.start_time < window.utc_end,
        # EXCLUSION of warmup, never an allow-list of 'normal'. D-08 keeps 823 live dropset sets
        # and the declared-but-never-sent `failure` type fully PR-eligible; an allow-list would
        # drop both silently. One definition of the warm-up rule, reused -- never re-spelled.
        *hard_set_predicates(),
    ]
    if template_external_ids is not None:
        predicates.append(
            WorkoutExercise.exercise_template_external_id.in_(list(template_external_ids))
        )

    stmt = (
        select(
            Workout.id.label("workout_id"),
            local_day.label("local_day"),
            WorkoutExercise.exercise_template_external_id.label("template_external_id"),
            ExerciseTemplate.title,
            ExerciseTemplate.exercise_type,
            WorkoutSet.set_type,
            WorkoutSet.set_index,
            WorkoutSet.weight_kg,
            WorkoutSet.reps,
        )
        .select_from(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        # OUTER join, never inner. `workout_exercises.exercise_template_external_id` is a plain
        # string and deliberately not a foreign key, so a workout may reference a template that
        # is not synced locally -- an inner join would silently drop those sets from every
        # Phase 5 number. The tenant predicate is repeated ON THE JOIN because Hevy's built-in
        # template ids are GLOBAL: omitting it attaches another user's `exercise_type` to this
        # user's set, which changes the D-03 e1RM gate. That is a correctness bug as well as a
        # disclosure one.
        .outerjoin(
            ExerciseTemplate,
            and_(
                ExerciseTemplate.external_id == WorkoutExercise.exercise_template_external_id,
                ExerciseTemplate.user_id == user_id,
            ),
        )
        .where(*predicates)
        # Deterministic ordering is a repo-wide rule, and in this phase it is stronger than a
        # test-stability concern: a plateau streak read out of order is a WRONG ANSWER, not a
        # flaky one. Template first because every Phase 5 fold groups by exercise, then the
        # local day because every fold is chronological within it.
        .order_by(
            WorkoutExercise.exercise_template_external_id,
            local_day,
            Workout.id,
            WorkoutSet.set_index,
        )
    )

    result = await session.execute(stmt)
    return [
        QualifyingSetRow(
            workout_id=row.workout_id,
            local_day=row.local_day,
            template_external_id=row.template_external_id,
            title=row.title,
            exercise_type=row.exercise_type,
            set_type=row.set_type,
            set_index=row.set_index,
            # Left exactly as the driver returns it: `Decimal | None`, never coerced to a float
            # and never defaulted to zero. `None` means "this set has no weight", which is not
            # zero kilograms -- a bodyweight set and a 0 kg set are different facts.
            weight_kg=row.weight_kg,
            reps=row.reps,
        )
        for row in result.all()
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


@dataclass(slots=True)
class MuscleBucket:
    """Accumulator for one (week, muscle) or one (window, muscle) cell.

    Mutable on purpose -- it is an intermediate, never a return value. The public Pydantic
    models in ``schemas.py`` are the frozen ones.

    ``session_ids`` is a SET, not a counter, and that is the single most important line in this
    module. One workout containing three hamstring exercises is ONE hamstring session;
    incrementing here instead inflated hamstrings from 2 to 8 (4.0x) in a real week, and
    inflated 14 of 16 muscle groups. The numbers still look plausible, which is why this has to
    be structural rather than reviewed.
    """

    direct_sets: int = 0
    indirect_sets: int = 0
    weighted_sets: Decimal = field(default_factory=lambda: Decimal(0))
    session_ids: set[uuid.UUID] = field(default_factory=set)


# Warning sign that this went wrong: any `sum(r.sessions for r in rows)` anywhere downstream.
def _fold_by_muscle(
    rows: Sequence[SetRollupRow],
    resolved: Mapping[str, Sequence[EffectiveMuscle]],
    weights: Mapping[MuscleRole, Decimal] | None,
    keyed_by_week: bool,
) -> dict[Any, MuscleBucket]:
    """The one fan-out implementation. Both public folds delegate here.

    A second copy specialised per key shape is how the weekly and whole-window answers would
    eventually disagree -- the ``resolver.py::effective_muscles`` delegation pattern.
    """
    buckets: dict[Any, MuscleBucket] = {}
    for row in rows:
        muscles = resolved.get(row.template_external_id, ())
        if not muscles:
            # D-03 (Phase 3): an unmapped template must not block anything. It contributes to
            # no muscle bucket and raises nothing -- silently, because "we have no mapping for
            # this exercise" is a curation gap surfaced by `mapping-gaps`, not a query failure.
            continue
        # NORM-03 / D-04: the weight is applied at QUERY time by the resolver's own pure
        # function. Never a CASE WHEN in SQL, and never a weight literal spelled out here --
        # the defaults live in the taxonomy module and the caller overrides them per query.
        weight_by_muscle = apply_weights(muscles, weights)
        for muscle in muscles:
            key = (row.week_start, muscle.muscle_group) if keyed_by_week else muscle.muscle_group
            bucket = buckets.setdefault(key, MuscleBucket())
            if muscle.role is MuscleRole.DIRECT:
                bucket.direct_sets += row.hard_sets
            else:
                bucket.indirect_sets += row.hard_sets
            # Decimal * int stays exact. Binary floating point here would make two
            # arithmetically identical weekly totals compare unequal.
            bucket.weighted_sets += weight_by_muscle[muscle.muscle_group] * row.hard_sets
            bucket.session_ids.add(row.workout_id)
    return buckets


def fold_weeks_by_muscle(
    rows: Sequence[SetRollupRow],
    resolved: Mapping[str, Sequence[EffectiveMuscle]],
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> dict[tuple[dt.date, CanonicalMuscleGroup], MuscleBucket]:
    """VOL-02: per-week, per-muscle buckets.

    Pure and synchronous -- no session, no I/O -- so every rule above is unit-testable with no
    container. Weeks with no training produce no key here on purpose; the caller projects onto
    ``local_week_spine`` so a zero week is a zero and not an absence.
    """
    return _fold_by_muscle(rows, resolved, weights, keyed_by_week=True)


def fold_window_by_muscle(
    rows: Sequence[SetRollupRow],
    resolved: Mapping[str, Sequence[EffectiveMuscle]],
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> dict[CanonicalMuscleGroup, MuscleBucket]:
    """VOL-03: whole-window, per-muscle buckets. Delegates to the same fold as the weekly one.

    Not derivable by summing the weekly buckets: adding their ``session_ids`` COUNTS would
    double-count nothing but adding their sizes would, and re-folding from the same rows keeps
    one workout spanning two definitions of "the week" impossible to double-count.
    """
    return _fold_by_muscle(rows, resolved, weights, keyed_by_week=False)


def fold_window_by_template(
    rows: Sequence[SetRollupRow],
) -> dict[str, set[uuid.UUID]]:
    """VOL-03 per exercise: distinct workouts per template over the whole window.

    A set for the same reason as ``MuscleBucket``'s session accumulator: an exercise performed
    twice in one workout -- a real possibility, even though this account has never done it --
    is one session.
    """
    sessions: dict[str, set[uuid.UUID]] = {}
    for row in rows:
        sessions.setdefault(row.template_external_id, set()).add(row.workout_id)
    return sessions

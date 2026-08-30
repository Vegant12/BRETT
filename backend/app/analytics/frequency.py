"""VOL-03: training frequency -- sessions per week, overall and per muscle group and exercise.

**A per-muscle session count is ``COUNT(DISTINCT workout_id)``, never a running total.** One
workout containing three hamstring exercises is ONE hamstring session. Adding the per-template
session counts together instead inflated hamstrings from 2 to 8 (4.0x) in a real training week,
and inflated 14 of 16 muscle groups the same way. The inflated numbers still look plausible --
"you trained hamstrings 8 times" reads as history rather than as arithmetic -- so no reviewer
catches it, and the correctness has to be STRUCTURAL. Every count below is the size of a ``set``
of workout ids that ``rollup.fold_window_by_muscle`` already de-duplicated. The warning sign
that this regressed is any total taken over the ``.sessions`` fields of these rows, anywhere
downstream.

**D-03: the window is the RAW requested range, divided by its true length.** Frequency
deliberately does NOT widen the range to whole weeks the way weekly volume does (U-01), because
the division already handles a partial week correctly: a 10-day window is 10/7 weeks, not 2.
Widening would answer a range the caller never asked about and report a rate over days that do
not exist in their question.

**Every rate is quantized at the boundary, in exactly one place.** Unquantized division returned
``Decimal('3.1612903225806452')`` against the live database -- a number no coach would read and
no test could assert on stably. Two places, matching blueprint 23's own ``2.0x/week`` example.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER
owns the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,
    build_coverage,
    build_freshness,
    is_insufficient,
)
from app.analytics.rollup import (
    fold_window_by_muscle,
    fold_window_by_template,
    resolve_row_muscles,
    resolve_window,
    weekly_set_rows,
)
from app.analytics.schemas import (
    ExerciseFrequency,
    MuscleGroupFrequency,
    TrainingFrequencyResult,
)
from app.db.models.exercise import ExerciseTemplate
from app.normalization.muscles import MuscleRole

# Two places, matching blueprint 23's own `2.0x/week` example. Unquantized division returned
# Decimal('3.1612903225806452') against the live database -- a number no coach would read and no
# test could assert on stably.
_RATE_QUANTUM = Decimal("0.01")


def sessions_per_week(sessions: int, days: int) -> Decimal:
    """Exact sessions-per-week over an arbitrary INCLUSIVE local-day span.

    ``Decimal`` throughout, never binary floating point: 10 days is exactly 10/7 weeks, and
    binary floating point would make two arithmetically identical rates compare unequal.

    Public rather than private so Phase 5's CMP-01 per-week normalization reuses this one
    definition instead of re-deriving it, and so the formula stays unit-testable with no
    container.

    A window of zero days is a caller bug, not a zero rate -- raising beats returning a number
    that silently divides by nothing. The message carries no user data because it will be logged.
    """
    if days <= 0:
        raise ValueError("window length must be positive")
    weeks = Decimal(days) / Decimal(7)
    return (Decimal(sessions) / weeks).quantize(_RATE_QUANTUM)


async def _template_titles(
    session: AsyncSession, *, user_id: uuid.UUID, template_external_ids: Sequence[str]
) -> dict[str, str]:
    """Titles for the templates in the window, in ONE query.

    A workout can reference a template that does not exist locally -- ``workout_exercises``
    stores a plain string, deliberately not a foreign key, so an unsynced or upstream-deleted
    template must not block anything. Missing templates simply have no title.

    T-04-02: the tenant predicate is explicit here as well as on the workout aggregate. Template
    ids are shared across users -- Hevy's built-in ids are global -- so omitting it would let one
    user's exercise title be attached to another user's frequency row.
    """
    if not template_external_ids:
        return {}
    result = await session.execute(
        select(ExerciseTemplate.external_id, ExerciseTemplate.title).where(
            ExerciseTemplate.user_id == user_id,
            ExerciseTemplate.external_id.in_(list(template_external_ids)),
        )
    )
    return {external_id: title for external_id, title in result.all()}


async def get_training_frequency(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> TrainingFrequencyResult:
    """VOL-03: sessions per week overall, per muscle group and per exercise (D-03).

    The window is resolved WITHOUT week snapping: the raw requested range IS the window, and the
    rate divides by its true length. Weekly volume widens its range outward instead (U-01)
    because its buckets have to be comparable to one another; a rate does not.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=False
    )
    rows = await weekly_set_rows(session, user_id=user_id, window=window)
    resolved = await resolve_row_muscles(session, user_id=user_id, rows=rows)
    by_muscle = fold_window_by_muscle(rows, resolved, weights)
    by_template = fold_window_by_template(rows)
    titles = await _template_titles(
        session, user_id=user_id, template_external_ids=sorted(by_template)
    )
    coverage = await build_coverage(
        session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
    )

    # len(bucket.session_ids), never a total of anything. See the module docstring: adding
    # per-template session counts together inflated 14 of 16 muscle groups by up to 4.0x on
    # real data, and every inflated figure still read as plausible training history.
    muscle_sessions = {group: len(bucket.session_ids) for group, bucket in by_muscle.items()}
    exercise_sessions = {
        external_id: len(workout_ids) for external_id, workout_ids in by_template.items()
    }

    # Sorted by a stated key, never dict-iteration order -- Phase 6 will diff these between
    # runs, and a flaky ordering is a flaky test.
    muscle_groups = [
        MuscleGroupFrequency(
            muscle_group=group,
            sessions=muscle_sessions[group],
            sessions_per_week=sessions_per_week(muscle_sessions[group], window.days),
            insufficient_data=is_insufficient(muscle_sessions[group]),
        )
        for group in sorted(muscle_sessions, key=lambda muscle_group: muscle_group.value)
    ]
    exercises = [
        ExerciseFrequency(
            exercise_template_external_id=external_id,
            title=titles.get(external_id),
            sessions=exercise_sessions[external_id],
            sessions_per_week=sessions_per_week(exercise_sessions[external_id], window.days),
            insufficient_data=is_insufficient(exercise_sessions[external_id]),
        )
        for external_id in sorted(exercise_sessions)
    ]

    return TrainingFrequencyResult(
        sessions_per_week=sessions_per_week(coverage.sessions_in_window, window.days),
        muscle_groups=muscle_groups,
        exercises=exercises,
        coverage=coverage,
        # BOTH resources: the muscle map comes from exercise_templates, so a stale template
        # sync silently changes every per-muscle number here. Weekly volume needs only
        # `workouts` because it never resolves a muscle map.
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_MUSCLE
        ),
    )

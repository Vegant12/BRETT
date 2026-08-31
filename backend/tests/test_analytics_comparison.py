"""CMP-01: two-period comparison with counts and sums normalized per week.

THE load-bearing test is `test_unequal_length_periods_with_identical_weekly_training`. The
specific wrong number it catches is a 2x delta: a 28-day period against a 14-day period holding
the same weekly training has EQUAL per-week figures, and an implementation that compared raw
window totals reports period A as twice period B -- a "you halved your training" verdict produced
entirely by the calendar.

Its partner is `test_best_e1rm_is_a_level_and_is_never_divided`. Without it, an implementation
that normalized everything per week would still pass the test above while reporting a best e1RM of
about 29 kg for a lifter who pressed 100 kg -- a quarter of the number
`get_exercise_progression` reports for the same exercise in the same window, and still shaped like
a weight.

Never an approximate comparison: every expected value below is an exact `Decimal` literal. The
rule is stated in words rather than by naming the helper it forbids, because the acceptance grep
for that helper is a plain substring search and would otherwise fail on the sentence documenting
the rule -- the trap already recorded at `test_hevy_isolation.py:88-93`.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.comparison import _delta_percent, _per_week, compare_periods
from app.analytics.frequency import sessions_per_week
from app.analytics.schemas import ComparisonRate, PeriodComparisonResult
from app.db.repositories.sync_state import (
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
)
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `CMP-*` so these fixture ids cannot collide with `test_analytics_frequency.py`'s `FREQ-*`,
# `test_analytics_volume.py`'s `VOL-*`, `test_analytics_progression.py`'s `PROG-*`,
# `test_analytics_rollup.py`'s `ROLLUP-*` or `test_normalization_mapping.py`'s `RESOLVER-*`: the
# container is session-scoped and shared, so a reused id lets one module's rollback take another
# module's fixtures with it.
_BENCH = "CMP-bench"
_NEW = "CMP-new"
_PUSHUP = "CMP-pushup"
_SHARED = "CMP-shared"

# Period A is a 28-day baseline and period B a 14-day comparison, so an implementation comparing
# RAW window totals reports a 2x difference where the per-week truth is zero.
_A_START = dt.date(2026, 7, 6)
_A_END = dt.date(2026, 8, 2)  # 28 days
_B_START = dt.date(2026, 8, 3)
_B_END = dt.date(2026, 8, 16)  # 14 days

# Both ranges above are whole Monday-to-Sunday weeks, which means U-01 week snapping is a NO-OP
# over them -- a snapping implementation would pass every assertion written against them. This
# deliberately RAGGED Wednesday-to-Thursday 23-day range is the shape that actually catches it:
# snapped, it widens to 2026-07-06..2026-08-02 (28 days, 4 sessions) instead of staying 23 days
# with 3, so the rate would divide by five days the caller never asked about.
_RAGGED_START = dt.date(2026, 7, 8)  # Wednesday
_RAGGED_END = dt.date(2026, 7, 30)  # Thursday -- 23 days inclusive

# Jakarta is UTC+7, so 02:00Z is 09:00 local on the same day -- comfortably inside the local day
# each constant is named for, and never at risk of sliding into its neighbour or across the
# period boundary at 2026-08-02T17:00Z.
_A_WEEKS = [dt.datetime(2026, 7, day, 2, 0, tzinfo=dt.UTC) for day in (6, 13, 20, 27)]
_B_WEEKS = [dt.datetime(2026, 8, day, 2, 0, tzinfo=dt.UTC) for day in (3, 10)]

# Three identical working sets. 100 kg x 5 is Epley 116.667, which is the value the LEVEL test
# asserts on; the same tuple is reused everywhere so a test arrangement differs only in its dates
# and its template, never in its set contents.
_WORKING_SETS = (GoldenSet(weight_kg=Decimal("100.000"), reps=5),) * 3
_HEAVIER_SETS = (GoldenSet(weight_kg=Decimal("110.000"), reps=5),) * 3
_BODYWEIGHT_SETS = (GoldenSet(reps=12),) * 3


def _exercise(
    template_id: str, sets: tuple[GoldenSet, ...] = _WORKING_SETS
) -> GoldenExercise:
    """One exercise on the given template. Muscle-agnostic on purpose."""
    return GoldenExercise(template_external_id=template_id, sets=sets)


async def _compare(
    session: AsyncSession,
    *,
    user_id: uuid.UUID = DEFAULT_USER_ID,
    include_muscle_groups: bool = False,
) -> PeriodComparisonResult:
    """The 28-day-vs-14-day comparison every test below asks for, spelled once."""
    return await compare_periods(
        session,
        user_id=user_id,
        period_a_start=_A_START,
        period_a_end=_A_END,
        period_b_start=_B_START,
        period_b_end=_B_END,
        include_muscle_groups=include_muscle_groups,
    )


async def _seed_weekly_bench(golden_workout: GoldenBuilder) -> None:
    """One identical bench workout in every week of BOTH periods: 4 in A, 2 in B.

    Identical weekly training across two windows of different lengths is the whole fixture: the
    per-week answer is the same on both sides and the raw-total answer is not.
    """
    await golden_workout.template(external_id=_BENCH)
    for start_time in _A_WEEKS + _B_WEEKS:
        await golden_workout.workout(start_time=start_time, exercises=[_exercise(_BENCH)])


def test_per_week_helper_agrees_with_sessions_per_week() -> None:
    """The markerless fast-suite test: two per-week implementations must not drift.

    No integration marker on purpose, for the reason `test_analytics_frequency.py` states about
    the same formula: this arithmetic is the piece CMP-01 reuses from VOL-03, and it must stay
    verifiable when Docker is not running.

    The table deliberately includes non-multiples of 7 (10, 74, 30, 23 days). A whole-weeks-only
    table would pass against an implementation that divided by whole weeks.
    """
    for sessions, days in ((3, 10), (2, 7), (11, 74), (1, 30), (9, 28), (5, 23), (0, 14)):
        assert _per_week(Decimal(sessions), days) == sessions_per_week(sessions, days), (
            "two per-week implementations have drifted; CMP-01's sessions figure must be "
            "byte-identical to VOL-03's"
        )

    # The same fixed literal `sessions_per_week` raises, carrying no date, count or user id
    # because it is going to be logged.
    with pytest.raises(ValueError, match="window length must be positive"):
        _per_week(Decimal(1), 0)


@pytest.mark.integration
async def test_unequal_length_periods_with_identical_weekly_training(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test: 28 days against 14 days, same weekly training, zero delta.

    An implementation that compared raw window totals reports every period-A figure as twice its
    period-B counterpart and calls it a 50% drop. The numbers are real, the units are right, and
    the entire difference is the calendar.
    """
    await _seed_weekly_bench(golden_workout)

    result = await _compare(session)

    # Anti-vacuous guard: the two periods really are different lengths, and all four metrics
    # really were built. A fixture that wrote nothing would make every delta below a trivial zero.
    assert result.period_a.days == 28
    assert result.period_b.days == 14
    assert len(result.totals) == 4

    for row in result.totals:
        assert row.period_a_per_week is not None, row.metric
        assert row.delta_per_week == Decimal("0.00"), (
            f"{row.metric}: raw window totals were compared; the 2x length difference produced "
            f"a fake halving"
        )
        assert row.delta_percent == Decimal("0.00"), row.metric


@pytest.mark.integration
async def test_periods_are_not_snapped_to_whole_weeks(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03 carries forward: the raw requested range IS the window, for BOTH periods.

    The ragged 23-day period is what gives this teeth. `_A_START`/`_A_END` are already a whole
    Monday-to-Sunday span, so snapping them changes nothing and an assertion written only against
    them is satisfied by a snapping implementation. Snapping the ragged range widens it to 28 days
    and pulls in a fourth session the caller never asked about.
    """
    await _seed_weekly_bench(golden_workout)

    aligned = await _compare(session)

    assert aligned.period_a.start_day == _A_START
    assert aligned.period_a.end_day == _A_END
    assert aligned.period_b.days == 14

    ragged = await compare_periods(
        session,
        user_id=DEFAULT_USER_ID,
        period_a_start=_RAGGED_START,
        period_a_end=_RAGGED_END,
        period_b_start=_B_START,
        period_b_end=_B_END,
    )

    message = (
        "the window was widened to whole weeks; the rate then divides by a length the caller "
        "never asked for"
    )
    assert ragged.period_a.start_day == _RAGGED_START, message
    assert ragged.period_a.end_day == _RAGGED_END, message
    assert ragged.period_a.days == 23, message
    # 2026-07-06 falls OUTSIDE the ragged range and inside its snapped widening, so this count is
    # 3 against a correct implementation and 4 against a snapping one.
    assert ragged.period_a.coverage.sessions_in_window == 3, message


@pytest.mark.integration
async def test_totals_metric_set_and_ordering(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Exactly four metrics, sorted by `metric` -- never dict-insertion order.

    Phase 6 will diff these responses between runs, and a flaky ordering is a flaky test.
    """
    await _seed_weekly_bench(golden_workout)

    result = await _compare(session)

    assert [row.metric for row in result.totals] == [
        "hard_sets",
        "sessions",
        "tonnage_kg",
        "total_reps",
    ]


@pytest.mark.integration
async def test_best_e1rm_is_a_level_and_is_never_divided(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A maximum is compared as a LEVEL. Dividing it by weeks makes the delta worse, not better.

    Period A is four weeks and period B is two, so a per-week-normalized level would report about
    29 kg and about 64 kg for a lifter who pressed 100 kg and then 110 kg -- numbers still shaped
    like weights, still ordered the right way, and a quarter and a half of what
    `get_exercise_progression` reports for the same exercise in the same window.
    """
    await golden_workout.template(external_id=_BENCH, title="Bench Press (Barbell)")
    await golden_workout.workout(start_time=_A_WEEKS[0], exercises=[_exercise(_BENCH)])
    await golden_workout.workout(
        start_time=_B_WEEKS[0], exercises=[_exercise(_BENCH, _HEAVIER_SETS)]
    )

    result = await _compare(session)

    level = next(
        row for row in result.exercise_levels if row.exercise_template_external_id == _BENCH
    )
    assert level.metric == "best_estimated_1rm_kg"
    assert level.title == "Bench Press (Barbell)"
    assert level.period_a_value == Decimal("116.667")
    assert level.period_b_value == Decimal("128.333")
    assert level.delta == Decimal("11.666")

    message = (
        "the best e1RM was divided by the number of weeks; a level compared per week is a "
        "quarter of the number the progression endpoint reports for the same exercise"
    )
    # Any division by a week count of 2 or more drops the level BELOW the weight actually
    # lifted, which is the cheapest possible statement of the rule.
    assert level.period_a_value > Decimal("100.000"), message
    assert level.period_b_value > Decimal("110.000"), message
    # Structural, not arithmetic: a `ComparisonLevel` has no per-week field at all, so the wrong
    # thing is unrepresentable rather than merely absent.
    assert hasattr(level, "period_a_per_week") is False, message


@pytest.mark.integration
async def test_zero_baseline_yields_null_percent(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """An exercise trained in B and not in A is ordinary, not an error.

    Both halves are asserted: the ABSENT baseline that this fixture produces, and the genuine
    numeric zero that a period with no training produces.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.template(external_id=_NEW)
    await golden_workout.workout(start_time=_A_WEEKS[0], exercises=[_exercise(_BENCH)])
    await golden_workout.workout(
        start_time=_B_WEEKS[0], exercises=[_exercise(_BENCH), _exercise(_NEW)]
    )

    result = await _compare(session)

    message = (
        "a zero baseline must be None -- not an exception, not infinity, not a silent zero"
    )
    row = next(
        candidate
        for candidate in result.exercises
        if candidate.exercise_template_external_id == _NEW
    )
    assert row.period_a_per_week is None, (
        "an absent exercise was reported as zero per week; 'you did not do this' and 'you did "
        "it zero times per week' are different facts"
    )
    assert row.period_b_per_week == Decimal("0.50")
    assert row.delta_per_week is None, message
    assert row.delta_percent is None, message
    # The genuine numeric zero, not merely an absence -- the branch a fixture cannot reach
    # through `exercises` because an untrained template produces no row at all.
    assert _delta_percent(Decimal("0.00"), Decimal("5.00")) is None, message


@pytest.mark.integration
async def test_tonnage_and_reps_are_none_not_zero_for_a_bodyweight_period(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """`None` tonnage and `Decimal("0.00")` tonnage are different facts, per period.

    Period A holds only rep-counted sets with no weight, so no set in it has both tonnage
    operands. Reporting zero kilograms there would claim the lifter moved nothing; reporting
    `None` says the figure could not be computed, which is the truth.
    """
    await golden_workout.template(external_id=_PUSHUP, exercise_type="reps_only")
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_A_WEEKS[0], exercises=[_exercise(_PUSHUP, _BODYWEIGHT_SETS)]
    )
    await golden_workout.workout(start_time=_B_WEEKS[0], exercises=[_exercise(_BENCH)])

    result = await _compare(session)

    tonnage = next(row for row in result.totals if row.metric == "tonnage_kg")
    assert tonnage.period_a_per_week is None, (
        "a period whose sets carry no weight reported zero tonnage; 'we could not compute this' "
        "is a different fact from 'it was zero'"
    )
    assert tonnage.period_b_per_week == Decimal("750.00")
    assert tonnage.delta_per_week is None
    assert tonnage.delta_percent is None

    reps = next(row for row in result.totals if row.metric == "total_reps")
    assert reps.period_a_per_week == Decimal("9.00"), (
        "reps were suppressed along with tonnage; a bodyweight period still has a rep count"
    )
    assert reps.period_b_per_week == Decimal("7.50")


@pytest.mark.integration
async def test_muscle_groups_are_opt_in(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """16 groups x 3 figures x 2 periods plus deltas is 96+ numbers, so Phase 6 asks for them.

    The default must be an EMPTY LIST rather than an omitted key: MCP-03 wants compact JSON, and
    an always-on expansion is the largest response in the phase.
    """
    await golden_workout.template(
        external_id=_BENCH,
        muscles=[
            (CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT),
            (CanonicalMuscleGroup.TRICEPS, MuscleRole.INDIRECT),
        ],
    )
    for start_time in _A_WEEKS + _B_WEEKS:
        await golden_workout.workout(start_time=start_time, exercises=[_exercise(_BENCH)])

    default = await _compare(session)
    assert default.muscle_groups == [], (
        "the per-muscle expansion shipped without being asked for; MCP-03 wants compact JSON"
    )

    expanded = await _compare(session, include_muscle_groups=True)

    values = [row.muscle_group.value for row in expanded.muscle_groups]
    assert values == ["chest", "triceps"]
    assert values == sorted(values)
    for row in expanded.muscle_groups:
        assert isinstance(row.direct_sets, ComparisonRate)
        assert isinstance(row.indirect_sets, ComparisonRate)
        assert isinstance(row.weighted_sets, ComparisonRate)

    # Same weekly training on both sides, so the per-muscle delta is zero for the same reason
    # the totals are -- and it is normalized against each period's OWN length to get there.
    chest = next(
        row
        for row in expanded.muscle_groups
        if row.muscle_group is CanonicalMuscleGroup.CHEST
    )
    assert chest.direct_sets.period_a_per_week == Decimal("3.00")
    assert chest.direct_sets.period_b_per_week == Decimal("3.00")
    assert chest.direct_sets.delta_per_week == Decimal("0.00")
    assert chest.indirect_sets.period_a_per_week == Decimal("0.00")


@pytest.mark.integration
async def test_each_period_reports_independent_coverage(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-02 per period, not per response.

    Four sessions in A and one in B put the two periods on OPPOSITE sides of D-05's threshold at
    the same time, which is the case a single response-level block cannot express at all.
    """
    await golden_workout.template(external_id=_BENCH)
    for start_time in _A_WEEKS:
        await golden_workout.workout(start_time=start_time, exercises=[_exercise(_BENCH)])
    await golden_workout.workout(start_time=_B_WEEKS[0], exercises=[_exercise(_BENCH)])

    result = await _compare(session)

    assert result.period_a.coverage.sessions_in_window == 4
    assert result.period_a.coverage.insufficient_data is False
    assert result.period_b.coverage.sessions_in_window == 1
    assert result.period_b.coverage.insufficient_data is True, (
        "a comparison where one period has a single session is not a comparison, and one "
        "response-level coverage block cannot express that"
    )


@pytest.mark.integration
async def test_second_users_workouts_are_invisible(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """T-05-56 / ASVS V4: a single-user suite cannot see a missing tenant predicate.

    Both users get a template under the SAME external id with different titles, because Hevy's
    built-in template ids are GLOBAL: an unscoped title lookup would attach the other user's
    exercise name to this user's comparison row.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.workout(start_time=_A_WEEKS[0], exercises=[_exercise(_SHARED)])
    for start_time in _A_WEEKS + _B_WEEKS:
        await golden_workout.workout(
            start_time=start_time,
            exercises=[_exercise(_SHARED)],
            user_id=ANALYTICS_SECOND_USER_ID,
        )

    mine = await _compare(session)
    theirs = await _compare(session, user_id=ANALYTICS_SECOND_USER_ID)

    # Anti-vacuous guard: if the fixture wrote nothing, both sides would be zero and equal.
    assert theirs.period_a.coverage.sessions_in_window == 4
    assert len(mine.exercises) == 1

    sessions = next(row for row in mine.totals if row.metric == "sessions")
    assert sessions.period_a_per_week == Decimal("0.25"), (
        "another user's workouts leaked into this comparison (ASVS V4)"
    )
    assert sessions.period_b_per_week == Decimal("0.00")
    assert mine.exercises[0].title == "Mine", (
        "another user's exercise title leaked into this comparison; Hevy's built-in template "
        "ids are global, so the title lookup has to be tenant-scoped too (ASVS V4)"
    )


@pytest.mark.integration
async def test_comparison_freshness_names_both_resources(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: this answer is only as fresh as the STALER of its two sources.

    Both the muscle map and the e1RM modality gate (`exercise_type`) come from
    `exercise_templates`, so a stale template sync silently changes numbers in this response with
    no error anywhere in the stack.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(start_time=_A_WEEKS[0], exercises=[_exercise(_BENCH)])

    result = await _compare(session)

    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}

"""VOL-01 weekly volume, against golden fixtures whose answers were computed by hand.

Three rules under test are counter-intuitive, and each one shipped a silently wrong number
somewhere in the research phase before it was pinned here.

**Hard sets are `!= 'warmup'`, never `== 'normal'`.** An allow-list of `normal` discards 823 live
dropset sets -- 12% of all hard sets -- and starts discarding `failure` sets the day the provider
first sends one. `test_dropset_counts_as_a_hard_set` is what makes the difference visible.

**Tonnage is gated on operand presence and reported as `None`, not `0`.** `weight x reps` is NULL
whenever either operand is, and SQL `SUM` skips those rows without a word.

**`weight_kg = 0` is a real hard set contributing `Decimal("0.000")`.** 48 live non-warmup sets
carry one. "Cleaning" the tonnage input with `weight_kg > 0` drops every one of them.

`test_modality_without_operands_reports_tonnage_none` is the LOAD-BEARING test in this module.
An implementation that reported a confident `Decimal("0")` for a week of bodyweight-only work
would look correct in every other test here -- the warm-up, dropset and zero-load figures would
all still come out right -- and would tell Claude "you moved zero kilograms" when the truth is
"this week's modalities cannot produce a tonnage figure at all". Only this test can tell those
two apart.

`test_superset_grouping_changes_no_number` proves a NEGATIVE: a superset is a scheduling
relationship between exercises, so it changes rest and changes nothing about sets, reps or load.
It is written as an equality between two fixtures rather than against a magic expected number,
so it also guards against a future "fix" that collapses superset exercises into one set group.

Plan 04-08 appends the VOL-02 tests to this module; there is one docstring and one import block,
and they extend rather than duplicate.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rollup import SetRollupRow
from app.analytics.schemas import WeeklyVolumeWeek
from app.analytics.volume import _fold_week_totals, get_weekly_volume
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `VOL-*` so these cannot collide with `test_analytics_rollup.py`'s `ROLLUP-*` ids,
# `test_normalization_mapping.py`'s `RESOLVER-*` ids, or the sync tests' hevy ids: the container
# is session-scoped and shared.
_BENCH = "VOL-BENCH"
_PUSHUP = "VOL-PUSHUP"
_PLANK = "VOL-PLANK"
_ROW = "VOL-ROW"

# Monday 2026-08-24 at 09:00 Jakarta (= 02:00Z). Well inside the local Monday, so this fixture
# tests the arithmetic and not the boundary -- the boundary has its own test below.
_MONDAY = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)
_WEEK_START = dt.date(2026, 8, 24)
_WEEK_END = dt.date(2026, 8, 30)
_SIXTY = Decimal("60.000")


async def _one_week(
    session: AsyncSession, *, user_id: uuid.UUID = DEFAULT_USER_ID
) -> WeeklyVolumeWeek:
    """The single week of the fixed test window, with a guard against a vacuous pass."""
    result = await get_weekly_volume(
        session, user_id=user_id, start_day=_WEEK_START, end_day=_WEEK_END
    )
    assert len(result.weeks) == 1, f"expected one snapped week, got {len(result.weeks)}"
    return result.weeks[0]


@pytest.mark.integration
async def test_warmup_sets_are_excluded_from_every_figure(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Warm-ups contribute to NONE of hard_sets, total_reps, tonnage_sets or tonnage_kg.

    The two warm-ups carry the same 60 kg x 10 as the three working sets on purpose. A leak
    would then show as 5 hard sets and 3000 kg rather than as a smaller, more plausible drift.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[
                    GoldenSet(set_type="warmup", weight_kg=_SIXTY, reps=10),
                    GoldenSet(set_type="warmup", weight_kg=_SIXTY, reps=10),
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                ],
            )
        ],
    )

    week = await _one_week(session)

    assert week.hard_sets == 3, "a warm-up set was counted as a hard set"
    assert week.total_reps == 30, "a warm-up set's reps reached the weekly total"
    assert week.tonnage_sets == 3, "a warm-up set was counted in the tonnage population"
    assert week.tonnage_kg == Decimal("1800.000"), "a warm-up set contributed tonnage"
    assert week.sessions == 1


@pytest.mark.integration
async def test_dropset_counts_as_a_hard_set(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """`dropset` is real work and is 823 live sets. Only an allow-list of `normal` would drop it.

    This is the test that distinguishes "hard sets are everything that is not a warm-up" from
    "hard sets are the ones typed `normal`". Both read identically in the warm-up test above.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                    GoldenSet(weight_kg=_SIXTY, reps=10),
                    GoldenSet(set_type="dropset", weight_kg=_SIXTY, reps=10),
                    GoldenSet(set_type="dropset", weight_kg=_SIXTY, reps=10),
                ],
            )
        ],
    )

    week = await _one_week(session)

    assert week.hard_sets == 5, "a dropset was not counted as a hard set"
    assert week.total_reps == 50
    assert week.tonnage_sets == 5
    assert week.tonnage_kg == Decimal("3000.000"), "a dropset contributed no tonnage"


@pytest.mark.integration
async def test_modality_without_operands_reports_tonnage_none(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The load-bearing one: a bodyweight week reports `None` kilograms, never a confident zero.

    SQL `SUM` skips NULL products silently, so an implementation that coerced the absent sum to
    `Decimal("0")` would pass every other test in this module and would tell Claude "you moved
    zero kilograms" when the honest answer is "this week's modalities cannot produce tonnage".
    """
    await golden_workout.template(external_id=_PUSHUP, exercise_type="reps_only")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_PUSHUP,
                sets=[GoldenSet(reps=15), GoldenSet(reps=15), GoldenSet(reps=15)],
            )
        ],
    )

    week = await _one_week(session)

    assert week.hard_sets == 3, "a reps-only set is still a hard set"
    assert week.total_reps == 45
    assert week.tonnage_sets == 0, "a set with no weight entered the tonnage population"
    assert week.tonnage_kg is None, (
        "a bodyweight week reported a tonnage number. 'We could not compute tonnage' is a "
        "different fact from 'tonnage was zero', and only None can express the first"
    )


@pytest.mark.integration
async def test_duration_only_sets_count_as_hard_sets(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """U-02: a timed hold has neither reps nor weight and is still a hard set.

    `total_reps` is `None` rather than `0` for the same reason tonnage is: nothing here reported
    a rep count, so there is no rep total to report.
    """
    await golden_workout.template(external_id=_PLANK, exercise_type="duration")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_PLANK,
                sets=[
                    GoldenSet(duration_seconds=60),
                    GoldenSet(duration_seconds=60),
                    GoldenSet(duration_seconds=60),
                ],
            )
        ],
    )

    week = await _one_week(session)

    assert week.hard_sets == 3, "a duration-only set was dropped from the hard-set count"
    assert week.total_reps is None, "a week of timed holds reported a confident rep total"
    assert week.tonnage_sets == 0
    assert week.tonnage_kg is None


@pytest.mark.integration
async def test_zero_load_set_is_a_tonnage_set_contributing_zero(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A `weight_kg` of zero is a known figure that happens to be zero, not a missing value.

    48 live non-warmup sets carry one -- a bodyweight-weighted exercise done with no added load.
    A `weight_kg > 0` gate to "clean" the tonnage input drops every one of them, and the loss is
    invisible in the total.
    """
    await golden_workout.template(external_id=_PUSHUP, exercise_type="bodyweight_weighted")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_PUSHUP,
                sets=[GoldenSet(weight_kg=Decimal("0.000"), reps=10)],
            )
        ],
    )

    week = await _one_week(session)

    assert week.hard_sets == 1
    assert week.total_reps == 10
    assert week.tonnage_sets == 1, "a zero-weight set was treated as missing rather than as zero"
    assert week.tonnage_kg == Decimal("0.000"), (
        "a zero-load set must contribute a known zero. None here would say 'not computable', "
        "which is the opposite of what a bodyweight-weighted set with no added load means"
    )


@pytest.mark.integration
async def test_superset_grouping_changes_no_number(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Two exercises sharing a `supersets_id` produce exactly the same week as two without one.

    Written as an equality between two fixtures rather than against a magic expected number, so
    it stays a regression test against a future "fix" that collapses superset exercises into one
    set group -- whatever the correct numbers are, the two arrangements must agree on them.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.template(external_id=_ROW, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                supersets_id=1,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            ),
            GoldenExercise(
                template_external_id=_ROW,
                supersets_id=1,
                title="Superset partner",
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            ),
        ],
    )

    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(
        external_id=_BENCH, exercise_type="weight_reps", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.template(
        external_id=_ROW, exercise_type="weight_reps", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.workout(
        start_time=_MONDAY,
        user_id=ANALYTICS_SECOND_USER_ID,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            ),
            GoldenExercise(
                template_external_id=_ROW,
                title="Not a superset partner",
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            ),
        ],
    )

    superset_week = await _one_week(session)
    plain_week = await _one_week(session, user_id=ANALYTICS_SECOND_USER_ID)

    # Guard against a vacuous pass: two empty weeks would also be equal.
    assert superset_week.hard_sets > 0
    assert superset_week == plain_week, (
        "supersets changed a volume number. A superset is a SCHEDULING relationship between "
        "exercises -- it changes rest, not set counts, reps or load"
    )


def test_fold_week_totals_keeps_total_reps_none_when_no_row_reports_reps() -> None:
    """A week of nothing but timed holds must report None reps, not a confident 0.

    No marker and no fixtures on purpose: the None-versus-zero rule is the one most likely to be
    "simplified" away, and it should stay verifiable with Docker down.
    """
    workout_id = uuid.uuid4()
    week_start = dt.date(2026, 8, 24)
    rows = [
        SetRollupRow(week_start, workout_id, _PLANK, 3, None, 0, None),
        SetRollupRow(week_start, workout_id, _BENCH, 2, None, 0, None),
    ]

    totals = _fold_week_totals(rows)[week_start]

    assert totals.hard_sets == 5
    assert totals.total_reps is None, "a fold over rows that reported no reps invented a zero"
    assert totals.tonnage_sets == 0
    assert len(totals.session_ids) == 1, "two rows from one workout are one session"

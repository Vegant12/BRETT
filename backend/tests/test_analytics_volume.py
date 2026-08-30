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
import sqlalchemy as sa
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


# ---------------------------------------------------------------------------
# D-02 / U-01: local week bucketing, outward snapping, and the gap-free spine
# ---------------------------------------------------------------------------

# The boundary table, transcribed from `test_time.py`. Jakarta is UTC+7, so 17:00Z is exactly
# local midnight -- and every morning workout falls in the 17:00Z-24:00Z band that naive-UTC
# bucketing puts on the WRONG local day.
_BEFORE_MIDNIGHT = dt.datetime(2026, 8, 23, 16, 30, tzinfo=dt.UTC)  # -> week 2026-08-17
_AT_MIDNIGHT = dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)  # -> week 2026-08-24
_NEAR_MIDNIGHT_UTC = dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC)  # -> week 2026-08-24

# Both candidate weeks, so the one the workout did NOT land in is asserted to be a zero row
# rather than merely absent from the result.
_EARLIER_WEEK = dt.date(2026, 8, 17)
_BOUNDARY_WEEKS = (_EARLIER_WEEK, _WEEK_START)

_THREE_WEEK_START = dt.date(2026, 8, 10)
_THREE_WEEK_END = dt.date(2026, 8, 30)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("started_at", "expected_week"),
    [
        (_BEFORE_MIDNIGHT, _EARLIER_WEEK),
        (_AT_MIDNIGHT, _WEEK_START),
        (_NEAR_MIDNIGHT_UTC, _WEEK_START),
    ],
)
async def test_week_boundary_uses_the_users_local_timezone(
    session: AsyncSession,
    golden_workout: GoldenBuilder,
    started_at: dt.datetime,
    expected_week: dt.date,
) -> None:
    """The verified boundary table, transcribed from `test_time.py`.

    | UTC instant               | Jakarta local    | local week |
    |---------------------------|------------------|------------|
    | 2026-08-23T16:30:00+00:00 | Sun 2026-08-23 23:30 | 2026-08-17 |
    | 2026-08-23T17:00:00+00:00 | Mon 2026-08-24 00:00 | 2026-08-24 |
    | 2026-08-23T23:30:00+00:00 | Mon 2026-08-24 06:30 | 2026-08-24 |

    The last two are the ones naive-UTC bucketing gets wrong, and at UTC+7 that band holds
    every morning workout -- so the failure would not be an edge case, it would be most of
    the data.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=started_at,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)],
            )
        ],
    )

    result = await get_weekly_volume(
        session, user_id=DEFAULT_USER_ID, start_day=_EARLIER_WEEK, end_day=_WEEK_END
    )

    actual = {week.week_start: (week.hard_sets, week.sessions) for week in result.weeks}
    assert actual == {
        week: ((1, 1) if week == expected_week else (0, 0)) for week in _BOUNDARY_WEEKS
    }, f"the workout at {started_at.isoformat()} did not land in the {expected_week} local week"


@pytest.mark.integration
async def test_week_boundary_changes_when_the_timezone_changes(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Flipping `users.timezone` moves the same instant into a different week.

    This is the test that distinguishes "reads user configuration" from "hardcodes Asia/Jakarta
    somewhere". Hardcoding the timezone argument would make every other bucketing test in this
    module pass even if the column were ignored entirely.

    17:00Z is Monday 00:00 in Jakarta and Sunday 13:00 in New York, so the same workout belongs
    to two different local weeks depending on nothing but that one column.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_AT_MIDNIGHT,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)],
            )
        ],
    )

    def _trained_week(result_weeks: list[WeeklyVolumeWeek]) -> dt.date:
        trained = [week.week_start for week in result_weeks if week.hard_sets == 1]
        assert len(trained) == 1, f"expected exactly one trained week, got {trained}"
        return trained[0]

    jakarta = await get_weekly_volume(
        session, user_id=DEFAULT_USER_ID, start_day=_EARLIER_WEEK, end_day=_WEEK_END
    )
    assert _trained_week(jakarta.weeks) == _WEEK_START

    try:
        await session.execute(
            sa.text("update users set timezone = :tz where id = :uid"),
            {"tz": "America/New_York", "uid": DEFAULT_USER_ID},
        )
        flipped = await get_weekly_volume(
            session, user_id=DEFAULT_USER_ID, start_day=_EARLIER_WEEK, end_day=_WEEK_END
        )
        assert _trained_week(flipped.weeks) == _EARLIER_WEEK, (
            "the week bucket did not follow users.timezone -- the zone is being taken from "
            "somewhere other than the column FOUND-03 makes the source of truth"
        )
    finally:
        # Belt: undo the value. Braces: the golden_workout fixture discards the whole
        # transaction, so the shared container is untouched even if an assertion above failed.
        await session.execute(
            sa.text("update users set timezone = :tz where id = :uid"),
            {"tz": "Asia/Jakarta", "uid": DEFAULT_USER_ID},
        )


@pytest.mark.integration
async def test_window_snaps_outward_to_whole_weeks(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A Wednesday-to-Thursday request returns the whole Monday-start week it sits inside.

    Without the outward snap this window would report a partial week whose total is not
    comparable to a full one -- which reads as "volume dropped" -- and the Monday workout,
    which is inside the very training week the user asked about, would be invisible.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            )
        ],
    )

    result = await get_weekly_volume(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=dt.date(2026, 8, 26),
        end_day=dt.date(2026, 8, 27),
    )

    assert len(result.weeks) == 1, "a two-day request must snap to exactly one whole week"
    assert result.weeks[0].week_start == _WEEK_START
    assert result.weeks[0].hard_sets > 0, (
        "the Monday workout fell outside the bucket. It is inside the same training week the "
        "user asked about, which is the entire reason the window snaps outward"
    )


@pytest.mark.integration
async def test_weeks_are_gap_free_including_zero_training_weeks(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Three requested weeks, one trained: the answer is three rows, not one."""
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            )
        ],
    )

    result = await get_weekly_volume(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=_THREE_WEEK_START,
        end_day=_THREE_WEEK_END,
    )

    assert [week.week_start for week in result.weeks] == [
        dt.date(2026, 8, 10),
        _EARLIER_WEEK,
        _WEEK_START,
    ], (
        "a zero-training week vanished from the result -- that is the most "
        "diagnostically interesting week Claude could have seen"
    )
    for empty in result.weeks[:2]:
        assert empty.sessions == 0
        assert empty.hard_sets == 0
        assert empty.total_reps is None
        assert empty.tonnage_sets == 0
        assert empty.tonnage_kg is None
    assert result.weeks[2].hard_sets == 3


@pytest.mark.integration
async def test_response_carries_freshness_and_coverage(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01 and DQ-02 ride on every response, and D-05's boundary is crossed here.

    `freshness` reports `workouts` and only `workouts`: VOL-01 never resolves a muscle map, so
    `exercise_templates` staleness cannot change a number in this answer. A per-muscle result
    that reported the same single key would be claiming a freshness it does not have.
    """
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            )
        ],
    )

    first = await get_weekly_volume(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert set(first.freshness.resources) == {"workouts"}
    assert first.coverage.sessions_in_window == 1
    assert first.coverage.insufficient_data is True, "one session cannot support a weekly rate"
    assert first.coverage.earliest_data_at == _MONDAY

    await golden_workout.workout(
        start_time=_MONDAY + dt.timedelta(days=2),
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            )
        ],
    )

    second = await get_weekly_volume(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert second.coverage.sessions_in_window == 2
    assert second.coverage.insufficient_data is False, (
        "two sessions is the D-05 threshold, not one more than it -- an off-by-one in the "
        "comparison would flag a perfectly reportable window as too sparse"
    )
    assert second.weeks[0].sessions == 2


@pytest.mark.integration
async def test_weekly_volume_is_scoped_to_one_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Three workouts for a second user and one for the default user, in the same local week."""
    await golden_workout.template(external_id=_BENCH, exercise_type="weight_reps")
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
            )
        ],
    )

    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(
        external_id=_BENCH, exercise_type="weight_reps", user_id=ANALYTICS_SECOND_USER_ID
    )
    for offset in range(3):
        await golden_workout.workout(
            start_time=_MONDAY + dt.timedelta(days=offset),
            user_id=ANALYTICS_SECOND_USER_ID,
            exercises=[
                GoldenExercise(
                    template_external_id=_BENCH,
                    sets=[GoldenSet(weight_kg=_SIXTY, reps=10)] * 3,
                )
            ],
        )

    mine = await _one_week(session)
    theirs = await _one_week(session, user_id=ANALYTICS_SECOND_USER_ID)

    # Non-vacuous guard: if the second user's rows were missing entirely, the scoping assertion
    # below would pass while proving nothing.
    assert theirs.sessions == 3
    assert theirs.hard_sets == 9

    assert (mine.sessions, mine.hard_sets) == (1, 3), (
        "ASVS V4 violated: weekly volume included another user's workouts"
    )

"""BODY-01: rolling body-weight averages and the smoothed rate (D-13 through D-17).

Every test here is SYNTHETIC and runs under a FROZEN CLOCK. A test written against live data
would assert `trend_rate_percent_per_week is None` today -- correctly, because the D-16 anchor
window 2026-07-26..2026-08-01 holds zero weigh-ins after a real 52-day logging gap -- and would
then start passing for the wrong reason around 2026-09-06 when the gap fills in.

THE load-bearing test is `test_windows_gate_independently`. The specific wrong behaviour it
catches is a single response-level flag: an implementation with one shared `insufficient_data`
returns a null 30-day average whenever the 7-day window is sparse, deleting the one number that
IS trustworthy after a travel week.

Its partner is `test_smoothed_rate_is_null_when_the_anchor_window_is_empty`: without it, an
implementation that fell back to the prior-week delta would report +0.72%/week off one week of
glycogen noise -- nearly three times BODY-02's lean-bulk threshold -- and it would look entirely
plausible.

The dedupe and window-average tests carry NO integration marker on purpose. D-13's
"no interpolation" rule and D-14's tie-break are business rules, and business rules must stay
verifiable when Docker is not running -- the same argument `test_analytics_frequency.py` makes
for its `sessions_per_week` tests.

Every assertion is exact `Decimal` equality. No tolerance helper appears anywhere in this
module -- deliberately, and not even in this sentence: a tolerance would let a quantization
regression through, and the averages are quantized on purpose (`_WEIGHT_QUANTUM`).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.bodyweight import (
    MANUAL_SOURCE,
    BodyMeasurementRow,
    _dedupe_by_day,
    _window_average,
    get_body_weight_trend,
)
from app.analytics.metadata import MEASURED_DAY_FLOORS
from app.analytics.schemas import BodyWeightTrendResult, MeasurementCoverage
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
)

# The frozen instants. 02:00 UTC is 09:00 in Asia/Jakarta -- an instant where the UTC day and the
# LOCAL day AGREE, so the coverage tests isolate the coverage rule. `_DISAGREE_INSTANT` is the
# opposite case on purpose: 18:00Z on the 29th is 01:00 local on the 30th.
_AGREE_INSTANT = "2026-08-30T02:00:00+00:00"
_DISAGREE_INSTANT = "2026-08-29T18:00:00+00:00"
_ANCHOR = dt.date(2026, 8, 30)

_HEVY_SOURCE = "hevy"


def _row(day_offset: int, weight: str | None, source: str = _HEVY_SOURCE) -> BodyMeasurementRow:
    """One weigh-in `day_offset` days BEFORE the anchor. `weight` is a Decimal string or None."""
    return BodyMeasurementRow(
        measured_on=_ANCHOR - dt.timedelta(days=day_offset),
        source=source,
        weight_kg=None if weight is None else Decimal(weight),
    )


async def _seed(
    golden_workout: GoldenBuilder,
    *,
    days: Sequence[tuple[int, str]],
    source: str = _HEVY_SOURCE,
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """Seed weigh-ins as `(days-before-the-anchor, weight)` pairs.

    Offsets rather than literal dates so every fixture reads in the same frame the windows are
    defined in -- `[anchor-6, anchor]` is `range(7)` and not seven hand-copied date literals that
    have to be re-derived by a reader checking whether a fixture really lands in the window.
    """
    for offset, weight in days:
        await golden_workout.body_measurement(
            measured_on=_ANCHOR - dt.timedelta(days=offset),
            weight_kg=Decimal(weight),
            source=source,
            user_id=user_id,
        )


def _uniform(offsets: Sequence[int], weight: str) -> list[tuple[int, str]]:
    """The same weight on every listed day -- the shape most coverage tests want."""
    return [(offset, weight) for offset in offsets]


def _window_view(
    result: BodyWeightTrendResult, window_days: int
) -> tuple[Decimal | None, MeasurementCoverage]:
    """The (average, coverage) pair for one window, selected explicitly rather than by getattr.

    Spelled out so a renamed field is a type error here rather than an `AttributeError` at
    runtime inside a parametrized case.
    """
    if window_days == 7:
        return result.average_7d_kg, result.coverage_7d
    if window_days == 14:
        return result.average_14d_kg, result.coverage_14d
    if window_days == 30:
        return result.average_30d_kg, result.coverage_30d
    raise ValueError("unsupported measurement window length")


def test_manual_wins_over_hevy_for_the_same_day() -> None:
    """D-14, asserted in BOTH input orderings so the rule is order-independent, not lucky."""
    hevy = _row(0, "65.00")
    manual = _row(0, "66.00", source=MANUAL_SOURCE)

    for rows in ([hevy, manual], [manual, hevy]):
        by_day = _dedupe_by_day(rows)
        assert by_day == {_ANCHOR: Decimal("66.00")}, (
            "D-14: the natural key permits two rows per day; averaging them or counting the day "
            "twice both produce plausible numbers"
        )


def test_rows_without_a_weight_are_dropped() -> None:
    """A waist-only weigh-in is not a body-weight data point.

    Counting it toward a coverage floor would make sparse data read as sufficient -- the exact
    failure D-15's floors exist to prevent.
    """
    rows = [_row(0, "65.00"), _row(1, None), _row(2, "67.00")]

    by_day = _dedupe_by_day(rows)

    assert _ANCHOR - dt.timedelta(days=1) not in by_day
    assert len(by_day) == 2
    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("66.000"), 2)


def test_window_average_is_exact_and_quantized() -> None:
    """Exact `Decimal` equality, never a tolerance: 196.50 over three days is exactly 65.500."""
    by_day = _dedupe_by_day([_row(0, "65.00"), _row(1, "65.50"), _row(2, "66.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("65.500"), 3)


def test_no_interpolation_across_a_gap() -> None:
    """D-13: a 7-day window with weigh-ins on days 1, 2 and 7 averages exactly those three.

    The count is 3, not 7. An implementation that carried the last known value forward would
    return 7 here and a smoothed average that was never measured -- which on live data would
    fabricate a real 52-day logging gap into a straight line.
    """
    by_day = _dedupe_by_day([_row(6, "64.00"), _row(5, "65.00"), _row(0, "66.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("65.000"), 3)


def test_an_empty_window_is_none_and_not_zero() -> None:
    """A bodyweight of zero is not the same fact as "nobody weighed in"."""
    by_day = _dedupe_by_day([_row(40, "65.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (None, 0)


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_windows_gate_independently(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test: a sparse 7-day window must not delete the 30-day answer.

    Twelve consecutive weigh-ins ending ten days ago is exactly the shape a travel week leaves
    behind. An implementation carrying ONE response-level `insufficient_data` nulls the 30-day
    average here -- the single number that is still trustworthy -- and the response still looks
    entirely well-formed.
    """
    await _seed(golden_workout, days=_uniform(range(10, 22), "65.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.anchor_day == _ANCHOR
    assert result.coverage_7d.measured_days_in_window == 0
    assert result.coverage_7d.insufficient_data is True
    assert result.average_7d_kg is None
    assert result.coverage_14d.measured_days_in_window == 4
    assert result.coverage_14d.insufficient_data is True
    assert result.average_14d_kg is None
    assert result.coverage_30d.measured_days_in_window == 12
    assert result.coverage_30d.insufficient_data is False, (
        "the 30-day window was flagged because the 7-day one was sparse. D-15's floors are "
        "INDEPENDENT: a single response-level flag deletes the one number that is still good"
    )
    assert result.average_30d_kg == Decimal("65.000")

    # One more weigh-in takes the 14-day window from 4 measured days to its floor of 5, and only
    # that window may move.
    await _seed(golden_workout, days=[(9, "65.00")])

    flipped = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert flipped.coverage_14d.measured_days_in_window == 5
    assert flipped.coverage_14d.insufficient_data is False
    assert flipped.average_14d_kg == Decimal("65.000")
    assert flipped.coverage_7d.insufficient_data is True
    assert flipped.average_7d_kg is None


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
@pytest.mark.parametrize(
    ("window_days", "measured_days", "expect_insufficient"),
    [
        (7, 2, True),
        (7, 3, False),
        (14, 4, True),
        (14, 5, False),
        (30, 9, True),
        (30, 10, False),
    ],
)
async def test_every_floor_on_both_sides(
    session: AsyncSession,
    golden_workout: GoldenBuilder,
    window_days: int,
    measured_days: int,
    expect_insufficient: bool,
) -> None:
    """Both sides of all three D-15 floors: 2 vs 3, 4 vs 5, 9 vs 10.

    One side alone is satisfiable by a wrong implementation -- "always insufficient" passes every
    below-floor case and "never insufficient" passes every at-floor one. Together they pin the
    boundary itself.
    """
    # A guard on the parameter table: it must agree with the module's own floors, or these cases
    # would test a boundary nothing in `app/` believes in.
    assert (measured_days < MEASURED_DAY_FLOORS[window_days]) is expect_insufficient

    await _seed(golden_workout, days=_uniform(range(measured_days), "70.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)
    average, coverage = _window_view(result, window_days)

    assert coverage.window_days == window_days
    assert coverage.measured_days_in_window == measured_days
    assert coverage.insufficient_data is expect_insufficient
    assert (average is None) is expect_insufficient
    if not expect_insufficient:
        assert average == Decimal("70.000")


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_smoothed_rate_matches_the_hand_computed_value(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-16 against an exact hand-computed Decimal, denominator included.

    Current 7-day average is exactly 66.000 (264.00 / 4); the anchor window four weeks back is
    exactly 64.000 (256.00 / 4). The smoothed rate is (66.000 - 64.000) / 4 = 0.500 kg/week, and
    100 x 0.500 / 66.000 = 0.757575... -> 0.76%/week.
    """
    await _seed(
        golden_workout,
        days=[(0, "65.00"), (1, "66.00"), (2, "66.00"), (3, "67.00")],
    )
    await _seed(
        golden_workout,
        days=[(31, "65.00"), (32, "64.00"), (33, "64.00"), (34, "63.00")],
    )

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    # Anti-vacuous-pass guards: both endpoint windows really are populated and really did pass
    # their own floor, so a null rate here would be a bug rather than the documented gate.
    assert result.average_7d_kg == Decimal("66.000")
    assert result.trend_anchor_coverage.measured_days_in_window == 4
    assert result.trend_anchor_coverage.insufficient_data is False

    assert result.trend_rate_kg_per_week == Decimal("0.500")
    assert result.trend_rate_percent_per_week == Decimal("0.76"), (
        "the percent rate used the anchor average or the mean of the two as the denominator; "
        "D-10's basis is percent of PRESENT bodyweight"
    )


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_smoothed_rate_is_null_when_the_anchor_window_is_empty(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-16's gate, and the live-data case today: null is the correct answer, not a fallback.

    An implementation that quietly substituted the prior-week delta would report +0.72%/week off
    one week of glycogen and water noise -- nearly three times BODY-02's lean-bulk threshold --
    and the number would look entirely plausible.
    """
    await _seed(golden_workout, days=_uniform(range(3), "66.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.trend_rate_kg_per_week is None
    assert result.trend_rate_percent_per_week is None
    assert result.trend_anchor_coverage.measured_days_in_window == 0
    assert result.trend_anchor_coverage.insufficient_data is True
    # The null rate must not poison the averages: this window passed its own floor.
    assert result.average_7d_kg == Decimal("66.000")
    assert result.coverage_7d.insufficient_data is False


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_latest_week_delta_is_separate_and_survives_a_null_rate(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-17: the raw delta has its OWN gate and is surfaced when the smoothed rate is null."""
    await _seed(golden_workout, days=_uniform(range(3), "66.00"))
    await _seed(golden_workout, days=_uniform(range(7, 10), "65.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.latest_week_delta_kg == Decimal("1.000"), (
        "D-17 is surfaced for context and gated independently; it is never the figure BODY-02 "
        "classifies against"
    )
    assert result.trend_rate_kg_per_week is None
    assert result.trend_rate_percent_per_week is None


@pytest.mark.integration
@time_machine.travel(_DISAGREE_INSTANT, tick=False)
async def test_anchor_is_the_local_day_not_the_utc_date(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """FOUND-03: the anchor is the USER's calendar day, chosen at an instant where they differ.

    If the anchor were the UTC date the 7-day window would be [08-23, 08-29], the 2026-08-30
    weigh-in would fall outside it, and the count would be 2 -- below the floor -- rather than 3.
    """
    await _seed(golden_workout, days=_uniform(range(3), "66.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.anchor_day == dt.date(2026, 8, 30), (
        "18:00Z on the 29th is 01:00 local on the 30th in Asia/Jakarta; got the server's UTC date"
    )
    assert result.coverage_7d.measured_days_in_window == 3
    assert result.coverage_7d.insufficient_data is False
    assert result.average_7d_kg == Decimal("66.000")


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_second_users_weigh_ins_are_invisible(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4 / T-05-38. The second user is 30 kg heavier on the SAME dates.

    A single-user suite cannot see a missing tenant predicate: every row belongs to the only
    user, so an unscoped read returns the right answer by accident.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await _seed(golden_workout, days=_uniform(range(5), "65.00"))
    await _seed(
        golden_workout,
        days=_uniform(range(5), "95.00"),
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.average_7d_kg == Decimal("65.000"), (
        "another user's weigh-ins leaked into this user's average (ASVS V4)"
    )
    # Guard against a vacuous pass: five days really were seeded for this user, and ten rows
    # really do exist in the window across the two.
    assert result.coverage_7d.measured_days_in_window == 5


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_freshness_names_only_body_measurements(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01 / T-05-44: this answer depends on ONE sync resource, so it names exactly one.

    `workouts` and `exercise_templates` do not feed a body-weight average, and naming them would
    make an unrelated stale sync look like a caveat on this number.
    """
    await _seed(golden_workout, days=_uniform(range(3), "66.00"))

    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert set(result.freshness.resources) == {"body_measurements"}


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_no_measurements_at_all_returns_all_nulls(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """An empty history is an ANSWER, not an exception -- and never a bodyweight of zero.

    `golden_workout` is requested even though nothing is seeded: it is the fixture that rolls the
    transaction back, so this test cannot leave the shared container in a state the next module
    inherits.
    """
    result = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    assert result.anchor_day == _ANCHOR
    assert result.average_7d_kg is None
    assert result.average_14d_kg is None
    assert result.average_30d_kg is None
    assert result.trend_rate_kg_per_week is None
    assert result.trend_rate_percent_per_week is None
    assert result.latest_week_delta_kg is None
    for coverage in (
        result.coverage_7d,
        result.coverage_14d,
        result.coverage_30d,
        result.trend_anchor_coverage,
    ):
        assert coverage.measured_days_in_window == 0
        assert coverage.insufficient_data is True
        assert coverage.earliest_measurement_at is None

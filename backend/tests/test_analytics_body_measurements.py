"""BODY-05: the 16 non-weight circumference/composition metrics.

Integration tests carry ``@pytest.mark.integration`` and a frozen clock; business-rule tests
that need neither a database nor a clock carry no marker, matching the fast/slow split in
``test_analytics_bodyweight.py``. ``Decimal`` equality is exact throughout this module, with no
tolerance helpers -- the same convention ``test_analytics_bodyweight.py`` uses, since BODY-05's
entire result is a two-point delta and a rounding shortcut here would be a silent bug.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import time_machine
from sqlalchemy import Numeric, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.body_measurements import (
    MetricReading,
    fold_by_day,
    get_body_measurement_trend,
)
from app.analytics.schemas import BodyMeasurementMetric
from app.db.models.body import BodyMeasurement
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder

# BODY-01 owns weight; BODY-05 covers everything else on the table.
_WEIGHT_COLUMN = "weight_kg"
_EXPECTED_METRIC_COUNT = 16


def _numeric_columns() -> set[str]:
    """Every Numeric column on ``BodyMeasurement``, read from the mapper rather than typed out.

    Derived from the ORM on purpose: a hand-copied list would keep passing after a column was
    added to the model and forgotten in the enum, which is the exact drift this file exists to
    catch.
    """
    return {
        column.key
        for column in inspect(BodyMeasurement).columns
        if isinstance(column.type, Numeric)
    }


def test_the_enum_is_exactly_the_non_weight_numeric_columns() -> None:
    """D-09/D-10: the selector and the ORM model cannot drift apart.

    Set equality in BOTH directions. A member with no column makes ``getattr`` raise at runtime
    inside a tool call; a column with no member is a metric Claude can never ask about, and
    neither failure announces itself anywhere else.
    """
    assert {metric.value for metric in BodyMeasurementMetric} == (
        _numeric_columns() - {_WEIGHT_COLUMN}
    )


def test_the_enum_has_sixteen_members_and_excludes_weight() -> None:
    """D-10's count, written as a literal so an accidental deletion cannot pass silently."""
    assert len(BodyMeasurementMetric) == _EXPECTED_METRIC_COUNT
    assert _WEIGHT_COLUMN not in {metric.value for metric in BodyMeasurementMetric}, (
        "weight_kg belongs to BODY-01's fitness_get_body_weight_trend; a member here would give "
        "the same question two answers depending on which tool was called"
    )


def test_every_metric_resolves_to_a_real_orm_attribute() -> None:
    """The mechanism D-09 leans on: ``getattr(BodyMeasurement, metric.value)`` must not raise."""
    for metric in BodyMeasurementMetric:
        assert getattr(BodyMeasurement, metric.value) is not None


_FIXTURE_DAY = dt.date(2026, 6, 1)


@pytest.mark.integration
async def test_fixture_seeds_non_weight_columns(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Wave 0: the fixture builder can write a circumference and a composition value.

    Asserted against the DATABASE, not against the builder's arguments -- a kwarg accepted and
    silently dropped before the INSERT would pass an argument-level check and fail every BODY-05
    integration test afterwards with a confusing "no readings in the window".

    The weight-only row is here to prove the defaults did not change: a pre-BODY-05 call site
    must still write NULLs into the three new columns, not zeros.
    """
    await golden_workout.body_measurement(
        measured_on=_FIXTURE_DAY,
        weight_kg=Decimal("65.40"),
        waist_cm=Decimal("81.50"),
        neck_cm=Decimal("38.00"),
        fat_percent=Decimal("18.20"),
    )
    await golden_workout.body_measurement(
        measured_on=_FIXTURE_DAY - dt.timedelta(days=1), weight_kg=Decimal("65.60")
    )

    rows = (
        await session.execute(
            select(
                BodyMeasurement.measured_on,
                BodyMeasurement.waist_cm,
                BodyMeasurement.neck_cm,
                BodyMeasurement.fat_percent,
            )
            .where(BodyMeasurement.user_id == DEFAULT_USER_ID)
            .order_by(BodyMeasurement.measured_on)
        )
    ).all()

    assert len(rows) == 2
    weight_only, full = rows
    assert (weight_only.waist_cm, weight_only.neck_cm, weight_only.fat_percent) == (
        None,
        None,
        None,
    ), "the new kwargs default to None, so an existing call site still writes a weight-only row"
    assert full.waist_cm == Decimal("81.50")
    assert full.neck_cm == Decimal("38.00")
    assert full.fat_percent == Decimal("18.20")


# The frozen instant. 02:00 UTC is 09:00 in Asia/Jakarta -- an instant where the UTC day and the
# LOCAL day AGREE, matching `test_analytics_bodyweight.py`'s own `_AGREE_INSTANT`.
_AGREE_INSTANT = "2026-08-30T02:00:00+00:00"
_ANCHOR = dt.date(2026, 8, 30)


async def _seed(
    golden_workout: GoldenBuilder,
    *,
    column: str,
    offsets: Sequence[tuple[int, str]],
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """Seed one metric column as `(days-before-the-anchor, value)` pairs.

    Offsets rather than literal dates, for the reason `test_analytics_bodyweight.py`'s own `_seed`
    docstring gives: every fixture reads in the same frame the window is defined in, so a reader
    checking whether a fixture lands inside `[anchor-89, anchor]` does not have to re-derive seven
    date literals by hand.
    """
    for offset, value in offsets:
        await golden_workout.body_measurement(
            measured_on=_ANCHOR - dt.timedelta(days=offset),
            weight_kg=None,
            user_id=user_id,
            **{column: Decimal(value)},
        )


def test_fold_by_day_collapses_same_day_readings() -> None:
    """Two readings on the same day fold to one entry; three distinct days fold to three."""
    same_day = [
        MetricReading(measured_on=_ANCHOR, source="hevy", value=Decimal("85.00")),
        MetricReading(measured_on=_ANCHOR, source="manual", value=Decimal("86.00")),
    ]
    assert len(fold_by_day(same_day)) == 1

    distinct_days = [
        MetricReading(
            measured_on=_ANCHOR - dt.timedelta(days=offset), source="hevy", value=Decimal("85.00")
        )
        for offset in (0, 1, 2)
    ]
    assert len(fold_by_day(distinct_days)) == 3


def test_delta_is_an_exact_decimal_subtraction() -> None:
    """Fold two readings and subtract; a stray `.quantize(Decimal("0.001"))` would render -3.500."""
    readings = [
        MetricReading(
            measured_on=_ANCHOR - dt.timedelta(days=80), source="hevy", value=Decimal("85.00")
        ),
        MetricReading(measured_on=_ANCHOR, source="hevy", value=Decimal("81.50")),
    ]
    by_day = fold_by_day(readings)
    days = sorted(by_day)
    delta = by_day[days[-1]] - by_day[days[0]]

    assert delta == Decimal("-3.50")
    assert str(delta) == "-3.50"


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_latest_versus_earliest_delta_over_the_window(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The headline BODY-05 case: three waist readings collapse to one exact delta."""
    await _seed(
        golden_workout,
        column="waist_cm",
        offsets=[(80, "85.00"), (40, "83.20"), (0, "81.50")],
    )

    result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.WAIST_CM
    )

    assert result.latest_value == Decimal("81.50")
    assert result.earliest_value == Decimal("85.00")
    assert result.delta_value == Decimal("-3.50")
    assert result.latest_measured_on == _ANCHOR
    assert result.earliest_measured_on == _ANCHOR - dt.timedelta(days=80)
    assert result.window_days == 90
    assert result.stale_after_days == 30
    assert result.anchor_day == _ANCHOR
    assert result.coverage.window_days == 90
    assert result.coverage.measured_days_in_window == 3
    assert result.metric is BodyMeasurementMetric.WAIST_CM


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_the_window_boundary_is_inclusive_at_eighty_nine_days(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """`[anchor-89, anchor]` is 90 calendar days; offset 90 is one day outside it."""
    await _seed(
        golden_workout,
        column="waist_cm",
        offsets=[(90, "80.00"), (89, "82.00"), (0, "81.50")],
    )

    result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.WAIST_CM
    )

    assert result.coverage.measured_days_in_window == 2, (
        "offset 90 is one day OUTSIDE the inclusive [anchor-89, anchor] window and must be excluded"
    )
    assert result.earliest_measured_on == _ANCHOR - dt.timedelta(days=89)


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_a_null_column_is_not_a_reading(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A row that only carries `weight_kg` is not a reading of any circumference/composition
    metric."""
    for offset in (10, 20, 30):
        await golden_workout.body_measurement(
            measured_on=_ANCHOR - dt.timedelta(days=offset), weight_kg=Decimal("70.00")
        )
    await _seed(golden_workout, column="waist_cm", offsets=[(5, "81.50")])

    waist_result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.WAIST_CM
    )
    assert waist_result.coverage.measured_days_in_window == 1

    fat_result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.FAT_PERCENT
    )
    assert fat_result.coverage.measured_days_in_window == 0
    assert fat_result.latest_value is None
    assert fat_result.delta_value is None
    assert fat_result.is_stale is False
    assert fat_result.days_since_latest_reading is None


@pytest.mark.integration
@time_machine.travel(_AGREE_INSTANT, tick=False)
async def test_two_metrics_on_the_same_rows_are_independent(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The generic path must not leak coverage state between two metrics on the same table.

    ``neck_cm``'s one reading lands on the SAME row as one of ``waist_cm``'s three: the natural
    key is ``(user_id, source, measured_on)``, so two rows cannot share a ``measured_on`` under
    the same source. This is also the realistic shape -- Hevy writes every column on every sync.
    """
    await golden_workout.body_measurement(
        measured_on=_ANCHOR - dt.timedelta(days=80), weight_kg=None, waist_cm=Decimal("85.00")
    )
    await golden_workout.body_measurement(
        measured_on=_ANCHOR - dt.timedelta(days=40), weight_kg=None, waist_cm=Decimal("83.20")
    )
    await golden_workout.body_measurement(
        measured_on=_ANCHOR,
        weight_kg=None,
        waist_cm=Decimal("81.50"),
        neck_cm=Decimal("38.00"),
    )

    waist_result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.WAIST_CM
    )
    neck_result = await get_body_measurement_trend(
        session, user_id=DEFAULT_USER_ID, metric=BodyMeasurementMetric.NECK_CM
    )

    assert waist_result.coverage.insufficient_data is False
    assert neck_result.coverage.insufficient_data is True

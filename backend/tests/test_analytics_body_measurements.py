"""BODY-05: the 16 non-weight circumference/composition metrics.

Integration tests carry ``@pytest.mark.integration`` and a frozen clock; business-rule tests
that need neither a database nor a clock carry no marker, matching the fast/slow split in
``test_analytics_bodyweight.py``. ``Decimal`` equality is exact throughout this module, with no
tolerance helpers -- the same convention ``test_analytics_bodyweight.py`` uses, since BODY-05's
entire result is a two-point delta and a rounding shortcut here would be a silent bug.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import Numeric, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

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

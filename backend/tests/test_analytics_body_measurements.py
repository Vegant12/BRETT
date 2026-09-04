"""BODY-05: the 16 non-weight circumference/composition metrics.

Integration tests carry ``@pytest.mark.integration`` and a frozen clock; business-rule tests
that need neither a database nor a clock carry no marker, matching the fast/slow split in
``test_analytics_bodyweight.py``. ``Decimal`` equality is exact throughout this module, with no
tolerance helpers -- the same convention ``test_analytics_bodyweight.py`` uses, since BODY-05's
entire result is a two-point delta and a rounding shortcut here would be a silent bug.
"""

from sqlalchemy import Numeric, inspect

from app.analytics.schemas import BodyMeasurementMetric
from app.db.models.body import BodyMeasurement

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

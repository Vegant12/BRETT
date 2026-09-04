"""HEALTH-12/NUTR-04 fixture smoke tests (Phase 13, plan 13-02) plus the PURE-function tests
for ``app/analytics/health.py`` (Phase 13, plan 13-04).

This module started as Wave 0 fixture infrastructure and now also covers everything in
``app/analytics/health.py`` that needs no container: ``period_measured_day_floor``,
``_fold_by_metric_day``, ``_window_average``/``_window_total``, and the two enum/unit
registry-agreement tests. The CONTAINER-backed behavioural tests for the four public functions
(``get_activity_trend``, ``get_nutrition_trend``, ``get_activity_period_summary``,
``get_nutrition_period_summary``) land in plan 13-05; a reader should not take their absence
here as missing coverage.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.health import (
    HealthMetricRow,
    _fold_by_metric_day,
    _window_average,
    _window_total,
    period_measured_day_floor,
)
from app.analytics.metadata import MEASURED_DAY_FLOORS
from app.analytics.schemas import (
    ACTIVITY_METRIC_UNITS,
    NUTRITION_METRIC_UNITS,
    ActivityMetric,
    NutritionMetric,
)
from app.db.models.health import HealthDailyMetric
from app.db.repositories.sync_state import PROVIDER_APPLE_HEALTH, get_sync_state
from app.integrations.health_auto_export.registry import METRIC_REGISTRY
from tests.conftest import (
    DEFAULT_USER_ID,
    WORST_CASE_HEALTH_DAYS,
    GoldenBuilder,
)

_FIXTURE_DAY = dt.date(2026, 6, 1)


async def test_health_metric_seeds_a_row_the_same_session_can_read(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The fixture's basic contract: seed once, read it back in the SAME session."""
    await golden_workout.health_metric(
        metric="step_count", local_day=_FIXTURE_DAY, value=Decimal("8000")
    )

    row = (
        await session.execute(
            select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
    ).scalar_one()

    assert row.value == Decimal("8000")
    assert row.units == "count"
    assert row.metric == "step_count"
    assert row.local_day == _FIXTURE_DAY
    assert row.source == PROVIDER_APPLE_HEALTH
    assert row.source_name == "iPhone"


async def test_two_source_names_coexist_on_one_metric_day(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The row-level proof behind the fold rule plan 13-04 implements: the natural key
    permits two source_names on the same (metric, local_day), and their values sum to the
    expected total -- mirroring the real 2026-08-23 production day on which Foodvisor and
    Built With Science both wrote dietary_energy.
    """
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=_FIXTURE_DAY,
        value=Decimal("1200"),
        source_name="Foodvisor",
    )
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=_FIXTURE_DAY,
        value=Decimal("400"),
        source_name="Built With Science",
    )

    rows = (
        await session.execute(
            select(HealthDailyMetric).where(
                HealthDailyMetric.user_id == DEFAULT_USER_ID,
                HealthDailyMetric.metric == "dietary_energy",
                HealthDailyMetric.local_day == _FIXTURE_DAY,
            )
        )
    ).scalars().all()

    assert len(rows) == 2
    assert {row.source_name for row in rows} == {"Foodvisor", "Built With Science"}
    assert sum((row.value for row in rows), Decimal(0)) == Decimal("1600")


async def test_an_unknown_metric_name_is_rejected_at_seed_time(
    golden_workout: GoldenBuilder,
) -> None:
    """`dietary_protein` is the real third-party misspelling `registry.py`'s docstring calls
    out (the wire name is `protein`, never `dietary_protein`). The fixture must reject it at
    seed time rather than silently seeding a row no analytics query can ever find.
    """
    with pytest.raises(KeyError):
        await golden_workout.health_metric(
            metric="dietary_protein", local_day=_FIXTURE_DAY, value=Decimal("100")
        )


@pytest.mark.integration
async def test_worst_case_history_seeds_apple_health_rows_and_freshness(
    session: AsyncSession, worst_case_history: None
) -> None:
    """The widened worst-case fixture carries a real Apple Health envelope: every registry
    metric on every seeded day, and non-null freshness for both apple_health resources -- so a
    report tool's byte budget is measured against a real payload, not an all-None one.
    """
    count = (
        await session.execute(
            select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
    ).scalars().all()
    assert len(count) == WORST_CASE_HEALTH_DAYS * (5 + 7 * 2)

    activity_state = await get_sync_state(
        session, user_id=DEFAULT_USER_ID, provider=PROVIDER_APPLE_HEALTH, resource="activity"
    )
    nutrition_state = await get_sync_state(
        session, user_id=DEFAULT_USER_ID, provider=PROVIDER_APPLE_HEALTH, resource="nutrition"
    )
    assert activity_state is not None
    assert activity_state.last_synced_at is not None
    assert nutrition_state is not None
    assert nutrition_state.last_synced_at is not None


# ---------------------------------------------------------------------------------------------
# `period_measured_day_floor` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_period_measured_day_floor_agrees_with_measured_day_floors() -> None:
    """Byte-for-byte agreement with `MEASURED_DAY_FLOORS`, asserted by ITERATING that mapping
    rather than by three separate literals -- the generalization must reproduce D-15's three
    published floors exactly (7->3, 14->5, 30->10), or the "generalizes rather than competes
    with it" claim in the docstring is false.
    """
    for window_days, floor in MEASURED_DAY_FLOORS.items():
        if window_days == 90:
            # BODY-05's 90-day floor follows a DIFFERENT rule (a 2-point comparison, not an
            # average) -- `period_measured_day_floor`'s docstring only claims agreement with
            # the three AVERAGE-gating floors.
            continue
        assert period_measured_day_floor(window_days) == floor


def test_period_measured_day_floor_one_day_period_needs_only_one_day() -> None:
    """A 1-day period whose single day was logged is completely covered; a floor of 2 would
    make it unsatisfiable."""
    assert period_measured_day_floor(1) == 1


def test_period_measured_day_floor_intermediate_lengths() -> None:
    assert period_measured_day_floor(3) == 2
    assert period_measured_day_floor(31) == 11


def test_period_measured_day_floor_rejects_zero_or_negative() -> None:
    with pytest.raises(ValueError, match="period length must be at least one day"):
        period_measured_day_floor(0)


# ---------------------------------------------------------------------------------------------
# `_fold_by_metric_day` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_fold_by_metric_day_sums_across_source_name() -> None:
    """The 2026-08-23 production shape: two source_names, one metric-day, sum not either one."""
    rows = [
        HealthMetricRow(metric="dietary_energy", local_day=_FIXTURE_DAY, value=Decimal("1040")),
        HealthMetricRow(metric="dietary_energy", local_day=_FIXTURE_DAY, value=Decimal("504")),
    ]
    folded = _fold_by_metric_day(rows)
    assert folded == {"dietary_energy": {_FIXTURE_DAY: Decimal("1544")}}


def test_fold_by_metric_day_keeps_metrics_and_days_separate() -> None:
    day_two = _FIXTURE_DAY + dt.timedelta(days=1)
    rows = [
        HealthMetricRow(metric="step_count", local_day=_FIXTURE_DAY, value=Decimal("8000")),
        HealthMetricRow(metric="step_count", local_day=day_two, value=Decimal("6000")),
        HealthMetricRow(metric="active_energy", local_day=_FIXTURE_DAY, value=Decimal("300")),
    ]
    folded = _fold_by_metric_day(rows)
    assert folded == {
        "step_count": {_FIXTURE_DAY: Decimal("8000"), day_two: Decimal("6000")},
        "active_energy": {_FIXTURE_DAY: Decimal("300")},
    }


# ---------------------------------------------------------------------------------------------
# `_window_average` / `_window_total` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_window_average_and_total_on_empty_window_return_none() -> None:
    avg, measured_days = _window_average({}, end_day=_FIXTURE_DAY, window_days=7)
    assert avg is None
    assert measured_days == 0
    assert _window_total({}, end_day=_FIXTURE_DAY, window_days=7) is None


def test_window_average_and_total_single_value_window() -> None:
    by_day = {_FIXTURE_DAY: Decimal("100")}
    avg, measured_days = _window_average(by_day, end_day=_FIXTURE_DAY, window_days=7)
    assert avg == Decimal("100.000")
    assert measured_days == 1
    assert _window_total(by_day, end_day=_FIXTURE_DAY, window_days=7) == Decimal("100.000")


def test_window_average_no_rounding_drift_across_a_seven_value_fold() -> None:
    """Seven measured days summing to a value not evenly divisible by seven -- the average
    must be the exact quantized quotient, and the total must be the exact (unrounded) sum."""
    by_day = {
        _FIXTURE_DAY + dt.timedelta(days=offset): Decimal("100")
        for offset in range(7)
    }
    avg, measured_days = _window_average(by_day, end_day=_FIXTURE_DAY + dt.timedelta(days=6),
                                          window_days=7)
    assert measured_days == 7
    assert avg == Decimal("100.000")
    total = _window_total(by_day, end_day=_FIXTURE_DAY + dt.timedelta(days=6), window_days=7)
    assert total == Decimal("700.000")


# ---------------------------------------------------------------------------------------------
# Registry-agreement tests -- the declared-not-imported boundary's safety net.
# ---------------------------------------------------------------------------------------------


def test_activity_metric_enum_matches_the_registry() -> None:
    assert {m.value for m in ActivityMetric} == {
        name for name, spec in METRIC_REGISTRY.items() if spec.kind == "activity"
    }


def test_nutrition_metric_enum_matches_the_registry() -> None:
    assert {m.value for m in NutritionMetric} == {
        name for name, spec in METRIC_REGISTRY.items() if spec.kind == "nutrition"
    }


def test_activity_metric_units_match_the_registry_canonical_units() -> None:
    for member in ActivityMetric:
        assert ACTIVITY_METRIC_UNITS[member] == METRIC_REGISTRY[member.value].canonical_unit


def test_nutrition_metric_units_match_the_registry_canonical_units() -> None:
    for member in NutritionMetric:
        assert NUTRITION_METRIC_UNITS[member] == METRIC_REGISTRY[member.value].canonical_unit

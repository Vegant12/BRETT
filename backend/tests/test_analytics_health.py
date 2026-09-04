"""HEALTH-12/NUTR-04 fixture smoke tests (Phase 13, plan 13-02).

This module is Wave 0 infrastructure, not the behavioural test suite for
``app/analytics/health.py`` -- that module does not exist yet. Only the
``GoldenBuilder.health_metric`` seeding method and the widened
``worst_case_history`` fixture are under test here. The HEALTH-12/NUTR-04
behavioural tests (rolling averages, per-window/per-metric coverage floors)
land in plan 13-05 once ``app/analytics/health.py`` is built; a reader should
not take this file's short length as missing coverage.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.health import HealthDailyMetric
from app.db.repositories.sync_state import PROVIDER_APPLE_HEALTH, get_sync_state
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

"""HEALTH-09 and NUTR-03 against a real Postgres container.

The day-grained upsert is the whole design, and it only means anything against a database that
actually enforces `uq_health_daily_metrics_user_source_metric_source_name_day`. SQLite would
accept a duplicate key and every assertion below would pass while production silently grew two
rows per day.

Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share a
session-scoped container with every other integration test, and a health row that outlived its
test would make the NEXT test's "one row, not two" assertion depend on execution order.
"""

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import HealthDailyMetric, SyncState
from app.db.repositories.sync_state import PROVIDER_APPLE_HEALTH
from app.integrations.health_auto_export.ingest import ingest_payload
from app.integrations.health_auto_export.schemas import HAEPayload
from tests.conftest import DEFAULT_USER_ID, hae_fixture

# One stored row, as data rather than as ORM identity:
# (metric, source_name, local_day, value, units, sample_count).
Snapshot = tuple[str, str, dt.date, Decimal, str, int]


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _payload(name: str) -> HAEPayload:
    return HAEPayload.model_validate(hae_fixture(name))


async def _read_all_rows(maker: async_sessionmaker[AsyncSession]) -> list[Snapshot]:
    """Every stored health row, as comparable DATA.

    `value` is read back as the `Decimal` the `NUMERIC(14,4)` column holds and compared exactly.
    A float comparison here would hide precisely the corruption Finding C is about -- a prorated
    `flights_climbed` fragment that survives the round trip in one representation and not the
    other.
    """
    async with maker() as session:
        rows = await session.scalars(
            sa.select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        return sorted(
            (row.metric, row.source_name, row.local_day, row.value, row.units, row.sample_count)
            for row in rows
        )


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove everything this module writes, pass or fail."""
    async with maker() as session:
        await session.execute(
            sa.delete(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        await session.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID,
                SyncState.provider == PROVIDER_APPLE_HEALTH,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# HEALTH-09 / NUTR-03: re-sending an overlapping export window is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_identical_payload_twice_changes_nothing(engine: AsyncEngine) -> None:
    """HEALTH-09 / ROADMAP criterion #3: re-sending an overlapping export window is a no-op.

    An additive conflict clause passes a single-delivery test and fails this one -- which is the
    entire reason this test exists against a real constraint rather than as a unit test on the
    statement object.
    """
    maker = _maker(engine)
    payload = _payload("activity_and_nutrition")
    try:
        first = await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        snapshot_1 = await _read_all_rows(maker)
        second = await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        snapshot_2 = await _read_all_rows(maker)

        assert snapshot_1, (
            "HEALTH-09 cannot be proven against an empty table: the first ingest wrote nothing, "
            "so the equality below would hold vacuously"
        )
        assert snapshot_2 == snapshot_1, (
            "HEALTH-09 violated: a second delivery of the identical window changed the stored "
            "data. In production Health Auto Export re-sends overlapping windows routinely, so "
            "an additive conflict clause inflates every calorie and step figure on every "
            f"delivery. {len(snapshot_1)} row(s) before, {len(snapshot_2)} after"
        )
        assert second.rows_upserted == first.rows_upserted, (
            f"the second ingest wrote a different number of rows than the first: "
            f"{first.rows_upserted} then {second.rows_upserted}"
        )
    finally:
        await _cleanup(maker)

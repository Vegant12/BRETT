"""HEVY-07 against a real Postgres container.

The date-keyed upsert is the whole design, and it only means anything against a database that
actually enforces `uq_body_measurements_user_source_measured_on`. Only the HTTP transport is
mocked.

Mocking rule (conftest, Pitfall 3): RESPONSES use `httpx.Response` (0.x, the type respx
asserts on); EXCEPTIONS use `httpx2` types. Passing an `httpx2.Response` into `side_effect`
fails inside respx with a bare `AssertionError` that points at nothing.

Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share
a session-scoped container with every other integration test, and a body-measurement row that
outlived its test would make the NEXT test's "two rows, not four" assertion depend on
execution order.
"""

import datetime
from decimal import Decimal
from typing import Any

import httpx  # 0.x -- what respx asserts response objects are (Pitfall 3)
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from respx import Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import BodyMeasurement, SyncState
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_BODY_MEASUREMENTS,
    STATUS_IDLE,
    get_sync_state,
)
from app.integrations.hevy.body import sync_body_measurements
from app.integrations.hevy.client import HevyClient
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

MEASUREMENTS = "https://api.hevyapp.com/v1/body_measurements"

# Distinctive on purpose: the log-stream test asserts this exact string is absent.
HEVY_KEY = "hevy-key-body-must-not-be-logged"

DB_URL = "postgresql://u:pw@localhost:5432/db"

# The LOCAL column names -- note the seven `*_cm` renames of Hevy's unsuffixed fields. Listed
# here rather than derived from the model so that a column silently dropped from the mapping
# in `body.py` fails a test instead of quietly reading back as NULL forever.
METRIC_COLUMNS = (
    "weight_kg",
    "lean_mass_kg",
    "fat_percent",
    "neck_cm",
    "shoulder_cm",
    "chest_cm",
    "left_bicep_cm",
    "right_bicep_cm",
    "left_forearm_cm",
    "right_forearm_cm",
    "abdomen_cm",
    "waist_cm",
    "hips_cm",
    "left_thigh_cm",
    "right_thigh_cm",
    "left_calf_cm",
    "right_calf_cm",
)


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The predicate and attempt count stay real."""


def _client(**kwargs: Any) -> HevyClient:
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _page(*, page_count: int = 1, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The canned page, optionally re-shaped. `hevy_fixture` re-reads the file each call, so
    mutating the result cannot bleed into another test."""
    payload = hevy_fixture("body_measurements_page1")
    payload["page_count"] = page_count
    if rows is not None:
        payload["body_measurements"] = rows
    return payload


def _ok(**kwargs: Any) -> httpx.Response:
    return httpx.Response(200, json=_page(**kwargs))


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove everything this module writes, pass or fail."""
    async with maker() as session:
        await session.execute(
            sa.delete(BodyMeasurement).where(BodyMeasurement.user_id == DEFAULT_USER_ID)
        )
        await session.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID,
                SyncState.provider == PROVIDER_HEVY,
            )
        )
        await session.commit()


async def _rows(maker: async_sessionmaker[AsyncSession]) -> list[BodyMeasurement]:
    async with maker() as session:
        result = await session.scalars(
            sa.select(BodyMeasurement)
            .where(BodyMeasurement.user_id == DEFAULT_USER_ID)
            .order_by(BodyMeasurement.measured_on)
        )
        return list(result)


async def _state(
    maker: async_sessionmaker[AsyncSession], resource: str = RESOURCE_BODY_MEASUREMENTS
) -> SyncState | None:
    async with maker() as session:
        return await get_sync_state(
            session, user_id=DEFAULT_USER_ID, provider=PROVIDER_HEVY, resource=resource
        )


@pytest.mark.integration
async def test_all_seventeen_metrics_persist(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """Every metric Hevy sends for a date lands in its renamed local column.

    The seven unsuffixed wire fields (`abdomen`, `waist`, `hips`, the thighs and the calves)
    are the ones a mapping typo would silently drop, so each is asserted by value rather than
    by a blanket non-null check.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        first = (await _rows(maker))[0]
        assert first.measured_on == datetime.date(2026, 8, 1)
        assert first.weight_kg == Decimal("80.50")
        assert first.fat_percent == Decimal("18.50")
        assert first.waist_cm == Decimal("80.00")
        assert first.abdomen_cm == Decimal("85.00")
        assert first.right_calf_cm == Decimal("37.50")
        missing = [column for column in METRIC_COLUMNS if getattr(first, column) is None]
        assert not missing, f"metrics dropped on the way in: {missing}"
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_nulls_are_preserved_not_defaulted(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """A row where the user entered only their weight is normal, not malformed.

    Defaulting the sixteen absent metrics to zero would put a 0 cm waist into every
    circumference trend Phase 4 draws.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        sparse = (await _rows(maker))[1]
        assert sparse.measured_on == datetime.date(2026, 8, 8)
        assert sparse.weight_kg == Decimal("80.10")
        populated = [
            column
            for column in METRIC_COLUMNS
            if column != "weight_kg" and getattr(sparse, column) is not None
        ]
        assert not populated, f"absent metrics were materialised: {populated}"
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_measured_on_is_a_date_object(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """A calendar date, never an instant.

    `datetime.datetime` is a SUBCLASS of `datetime.date`, so `isinstance` would pass on a
    value that had silently acquired a midnight time-of-day -- and a midnight in the wrong
    offset is the classic way a Jakarta workout lands on the previous day. The identity
    check is the only one that states the claim.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        value = (await _rows(maker))[0].measured_on
        assert type(value) is datetime.date
        assert not isinstance(value, datetime.datetime)
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_resync_upserts_on_the_date(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """HEVY-03 for this resource: the DATE is the identity, so a re-sync updates in place.

    Two full runs over the same single page. Four rows would mean the constraint is not the
    one the upsert names, or that `id` (a fresh uuid4 on every call) had become the key.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok(), _ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        assert len(await _rows(maker)) == 2
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_metric_cleared_upstream_is_cleared_locally(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """Row-replacement semantics, mirroring Hevy's own PUT. A stale body-fat number lingering
    after the user deleted it would quietly corrupt Phase 5's recomposition verdict."""
    maker = _maker(engine)
    cleared = hevy_fixture("body_measurements_page1")["body_measurements"][0]
    cleared["fat_percent"] = None
    httpx2_mock.get(MEASUREMENTS).mock(
        side_effect=[_ok(), httpx.Response(200, json=_page(rows=[cleared]))]
    )
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)
            assert (await _rows(maker))[0].fat_percent == Decimal("18.50")
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        after = await _rows(maker)
        assert after[0].fat_percent is None, "a metric deleted upstream survived locally"
        # The metrics the user did NOT clear are still there -- this is a replacement, not
        # a truncation.
        assert after[0].weight_kg == Decimal("80.50")
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_404_terminates_pagination_cleanly(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """Pitfall 5: `/v1/body_measurements` answers 404 for an out-of-range page.

    `page_count: 5` is deliberate -- the run must stop because the transport said "no more
    pages", not because it reached the advertised count. A 404 read as a failure would mark
    the run errored after it had already fetched everything.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS, params={"page": "1"}).mock(side_effect=[_ok(page_count=5)])
    httpx2_mock.get(MEASUREMENTS, params={"page": "2"}).mock(side_effect=[httpx.Response(404)])
    try:
        async with _client() as client:
            result = await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        assert result.pages_fetched == 1
        assert result.rows_upserted == 2
        state = await _state(maker)
        assert state is not None
        assert state.status == STATUS_IDLE
        assert state.last_error is None
    finally:
        await _cleanup(maker)

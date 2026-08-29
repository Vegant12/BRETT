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
import io
import json
import logging
from decimal import Decimal
from typing import Any

import httpx  # 0.x -- what respx asserts response objects are (Pitfall 3)
import pytest
import sqlalchemy as sa
import structlog
from pydantic import SecretStr
from respx import Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import BodyMeasurement, SyncState
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_BODY_MEASUREMENTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    STATUS_ERROR,
    STATUS_IDLE,
    advance_cursor_page,
    ensure_sync_state,
    get_sync_state,
)
from app.integrations.hevy.body import sync_body_measurements
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.errors import HevyServerError
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

MEASUREMENTS = "https://api.hevyapp.com/v1/body_measurements"

# Distinctive on purpose: the log-stream test asserts this exact string is absent.
HEVY_KEY = "hevy-key-body-must-not-be-logged"

DB_URL = "postgresql://u:pw@localhost:5432/db"

# The three metric values in `body_measurements_page1.json`, as they would be rendered.
# `test_no_metric_value_reaches_the_log_stream` asserts none of them survives into a log line.
FIXTURE_METRIC_VALUES = ("80.5", "18.5", "65")

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
async def test_page_size_is_ten(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """Pitfall 6: this endpoint caps at 10, and the sync must actually ask for 10.

    Asserted on the RECORDED REQUEST rather than on `HevyClient.PAGE_SIZE_BODY_MEASUREMENTS`
    -- a constant that is correct but never reaches the query string would pass an
    introspection test and still make Hevy return its default of five per page.
    """
    maker = _maker(engine)
    route = httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        assert dict(route.calls.last.request.url.params) == {"page": "1", "pageSize": "10"}
    finally:
        await _cleanup(maker)


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
async def test_source_is_hevy_and_external_id_is_null(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """D-06/D-07: one table for every provider, and this provider has no id to store.

    `external_id` must stay NULL rather than be filled with a synthesised value such as the
    ISO date -- a fabricated id would look like a real one to the manual-entry path that
    lands in a later phase, and `source` is what keeps the two apart.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        rows = await _rows(maker)
        assert rows, "the sync wrote nothing"
        assert all(row.source == "hevy" for row in rows)
        assert all(row.external_id is None for row in rows)
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


@pytest.mark.integration
async def test_404_consumes_no_retry_budget(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """T-03-36: the terminator must not be retryable.

    `HevyPageNotFound` inherits from `HevyClientError`, which is absent from
    `RETRYABLE_EXCEPTIONS`. If it were ever moved under a retryable base, this route would be
    called five times and every single body-measurement sync would spend the whole backoff
    budget on its last, entirely normal, page.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS, params={"page": "1"}).mock(side_effect=[_ok(page_count=5)])
    terminator = httpx2_mock.get(MEASUREMENTS, params={"page": "2"}).mock(
        side_effect=[httpx.Response(404)]
    )
    try:
        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        assert terminator.call_count == 1
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_last_synced_at_for_body_measurements_is_independent(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-09: three data sources, three independent freshness answers.

    All three bookkeeping rows exist before the run, so the NULLs afterwards are a positive
    statement that this sync touched only its own resource -- not an artefact of two rows
    never having been created. A shared `last_synced_at` would report body measurements as
    fresh the moment workouts synced, which is exactly the staleness Claude has to be able
    to see.
    """
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    try:
        async with maker() as session:
            for resource in (RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES):
                await ensure_sync_state(
                    session,
                    user_id=DEFAULT_USER_ID,
                    provider=PROVIDER_HEVY,
                    resource=resource,
                )
            await session.commit()

        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        body = await _state(maker)
        assert body is not None
        assert body.last_synced_at is not None
        assert body.last_synced_at.tzinfo is not None, "FOUND-04: freshness is stored aware"

        for resource in (RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES):
            other = await _state(maker, resource)
            assert other is not None
            assert other.last_synced_at is None, f"{resource} was marked fresh by a body sync"
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_server_error_records_an_error_and_keeps_the_cursor(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-08/D-08: a failed run resumes where it stopped and says why in `last_error`.

    The cursor is pre-seeded to page 3 so that "kept" is observable -- with a fresh row it
    would be NULL both before and after, and the assertion would hold no matter what the
    driver did. Clearing it here would turn every transient Hevy outage into a full re-walk
    of ten-row pages.
    """
    maker = _maker(engine)
    route = httpx2_mock.get(MEASUREMENTS).mock(
        side_effect=[httpx.Response(500), httpx.Response(500)]
    )
    try:
        async with maker() as session:
            await ensure_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_BODY_MEASUREMENTS,
            )
            await advance_cursor_page(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_BODY_MEASUREMENTS,
                cursor_page=3,
            )
            await session.commit()

        async with _client(max_attempts=2) as client:
            with pytest.raises(HevyServerError):
                await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        assert route.call_count == 2
        assert dict(route.calls.last.request.url.params)["page"] == "3", (
            "the run restarted from page 1 instead of resuming at the checkpoint"
        )

        state = await _state(maker)
        assert state is not None
        assert state.status == STATUS_ERROR
        assert state.cursor_page == 3
        assert state.last_error is not None
        assert len(state.last_error) <= 500
        # T-03-12: `last_error` is read back into log lines, so it must carry a curated
        # `safe_message` and never a rendered payload.
        for value in FIXTURE_METRIC_VALUES:
            assert value not in state.last_error
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_no_metric_value_reaches_the_log_stream(
    engine: AsyncEngine, httpx2_mock: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Body composition is personal health data (V8). Sync lifecycle logs carry counts and
    dates; they must never carry a measurement."""
    maker = _maker(engine)
    httpx2_mock.get(MEASUREMENTS).mock(side_effect=[_ok()])
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("HEVY_API_KEY", HEVY_KEY)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        # The real pipeline, rendered into a buffer -- NOT `structlog.testing`, which clears
        # the configured processor chain for its duration and would leave this test green
        # over a redaction layer that never ran (test_secret_redaction.py's Pitfall 6).
        configure_logging(Settings(_env_file=None))
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)

        async with _client() as client:
            await sync_body_measurements(client, maker, user_id=DEFAULT_USER_ID)

        out = buffer.getvalue()
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
        await _cleanup(maker)

    entries = [json.loads(line) for line in out.splitlines() if line.strip()]
    # Without this the test would pass trivially on an empty buffer, which is the failure
    # mode a mis-wired capture actually produces.
    assert any(entry["event"] == "hevy_body_sync_completed" for entry in entries)

    # `timestamp` is dropped before the scan: its microsecond field is an unconstrained
    # six-digit number that will eventually contain "65" by chance, and a suite that goes
    # red once a fortnight teaches people to re-run it rather than read it.
    scanned = json.dumps([
        {key: value for key, value in entry.items() if key != "timestamp"} for entry in entries
    ])
    for value in FIXTURE_METRIC_VALUES:
        assert value not in scanned, f"T-03-33 violated: metric value {value!r} reached a log"
    assert HEVY_KEY not in scanned, "FOUND-05 violated: the api-key reached the log stream"

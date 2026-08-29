"""HEVY-08: a failed sync must not corrupt what already succeeded.

Following `test_mcp_tools.py`'s rule, the failures here are REAL where it matters. The
malformed-workout test does not patch a raise -- it sends a weight that genuinely overflows
`Numeric(7, 3)`, so the SAVEPOINT quarantine is proven against PostgreSQL's actual
transaction-abort semantics rather than against a Python exception someone invented.
"""

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import SyncState, Workout
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    advance_cursor_page,
    get_sync_state,
)
from app.db.session import make_sessionmaker
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.errors import HevyServerError
from app.integrations.hevy.workouts import sync_workouts
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"

PAGE_1_WORKOUT = "11111111-1111-1111-1111-111111111111"
PAGE_2_WORKOUT = "22222222-2222-2222-2222-222222222222"


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The retry predicate and attempt count stay real."""


def _client() -> HevyClient:
    """`max_attempts=2` so retry exhaustion is reached in two calls, not five."""
    return HevyClient(SecretStr("test-key"), max_attempts=2, sleep=_no_sleep)


def _mock_count(mock: Router, remote_count: int = 2) -> None:
    def _count(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"workout_count": remote_count})

    mock.get(WORKOUT_COUNT).mock(side_effect=_count)


def _mock_second_page_always_500(mock: Router) -> Route:
    def _serve(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["page"]) == 2:
            return httpx.Response(500)
        return httpx.Response(200, json=hevy_fixture("workouts_page1"))

    _mock_count(mock)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


def _mock_only_page_two(mock: Router) -> Route:
    def _serve(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page == 2, f"the sync restarted at page {page} instead of resuming at 2"
        return httpx.Response(200, json=hevy_fixture("workouts_page2"))

    _mock_count(mock, remote_count=1)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


async def _external_ids(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.scalars(
            sa.select(Workout.external_id).where(
                Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER
            )
        )
        return set(rows.all())


async def _state(engine: AsyncEngine) -> SyncState:
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        state = await get_sync_state(
            session, user_id=DEFAULT_USER_ID, provider=PROVIDER_HEVY, resource=RESOURCE_WORKOUTS
        )
    assert state is not None
    return state


async def _seed_cursor_page(engine: AsyncEngine, page: int) -> None:
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        await advance_cursor_page(
            session,
            user_id=DEFAULT_USER_ID,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_WORKOUTS,
            cursor_page=page,
        )
        await session.commit()


async def _cleanup(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.delete(Workout).where(
                Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER
            )
        )
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


@pytest.mark.integration
async def test_failure_on_page_two_preserves_page_one(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-08: per-page commit means page 1 survives a page-2 failure.

    One transaction for the whole run would discard 39 pages of work on a transient blip at
    page 40 -- against an API that caps `pageSize` at 10.
    """
    _mock_second_page_always_500(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        with pytest.raises(HevyServerError):
            async with _client() as client:
                await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert await _external_ids(engine) == {PAGE_1_WORKOUT}
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_cursor_page_survives_a_failure(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """D-08: a failure resumes, it does not restart.

    Clearing `cursor_page` on error would turn every transient 500 into a full re-walk of
    Hevy's ten-item pages.
    """
    _mock_second_page_always_500(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        with pytest.raises(HevyServerError):
            async with _client() as client:
                await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        state = await _state(engine)
        assert state.cursor_page == 2
        assert state.status == "error"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_sync_resumes_from_the_checkpoint(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """The checkpoint is read, not merely written.

    `page=1` being absent from the recorded requests is the whole assertion: a driver that
    wrote `cursor_page` and then always started at 1 would pass every other test in this file.
    """
    route = _mock_only_page_two(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_cursor_page(engine, 2)

        async with _client() as client:
            result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.pages_fetched == 1
        requested = [dict(call.request.url.params).get("page") for call in route.calls]
        assert "1" not in requested, f"page 1 was re-fetched despite the checkpoint: {requested}"
        assert await _external_ids(engine) == {PAGE_2_WORKOUT}
    finally:
        await _cleanup(engine)

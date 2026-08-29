"""HEVY-08: a failed sync must not corrupt what already succeeded.

Following `test_mcp_tools.py`'s rule, the failures here are REAL where it matters. The
malformed-workout test does not patch a raise -- it sends a weight that genuinely overflows
`Numeric(7, 3)`, so the SAVEPOINT quarantine is proven against PostgreSQL's actual
transaction-abort semantics rather than against a Python exception someone invented.

The logging helper is duplicated from `test_hevy_sync.py` rather than shared through
`conftest.py` on purpose: `conftest.py` is imported by every module in the suite, and a helper
that only two failure-path modules need does not belong in that blast radius.
"""

import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import httpx2  # 2.x -- the EXCEPTION types the client actually raises
import pytest
import sqlalchemy as sa
import structlog
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
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
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"

PAGE_1_WORKOUT = "11111111-1111-1111-1111-111111111111"
PAGE_2_WORKOUT = "22222222-2222-2222-2222-222222222222"

# The two titles the fixtures carry. `test_last_error_contains_no_payload` asserts neither
# reaches `sync_state.last_error`.
FIXTURE_TITLES = ("Push Day 💪", "Pull Day")

BAD_WORKOUT = "bad-workout-0001"
# ASCII and distinctive, so its absence from a JSON-rendered log line is unambiguous.
BAD_TITLE = "quarantine-title-9f3a"
# Overflows `Numeric(7, 3)` -- precision 7, scale 3 allows four integer digits at most. This is
# a genuine PostgreSQL DataError, not a patched raise, which is the point of the test.
OVERFLOW_WEIGHT = 99999999


# --- fixtures and mocks ----------------------------------------------------


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


def _quarantine_page() -> dict[str, Any]:
    """One page holding a workout PostgreSQL will reject, followed by a valid one.

    Order matters: the bad workout comes FIRST, so the good one that follows it is what proves
    the savepoint. Without one, PostgreSQL has already aborted the transaction and the second
    INSERT dies with "current transaction is aborted, commands ignored until end of transaction
    block" (Pitfall 11).
    """
    good: dict[str, Any] = deepcopy(hevy_fixture("workouts_page2")["workouts"][0])
    bad: dict[str, Any] = deepcopy(hevy_fixture("workouts_page1")["workouts"][0])
    bad["id"] = BAD_WORKOUT
    bad["title"] = BAD_TITLE
    bad["exercises"][0]["sets"][0]["weight_kg"] = OVERFLOW_WEIGHT
    return {"page": 1, "page_count": 1, "workouts": [bad, good]}


def _mock_quarantine_page(mock: Router) -> Route:
    page = _quarantine_page()

    def _serve(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    # One workout survives the page, so the reconciliation baseline is 1 and no spurious
    # mismatch line lands in the log stream the next test asserts on.
    _mock_count(mock, remote_count=1)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


def _mock_page_one_drops_once(mock: Router) -> Route:
    """Page 1's first attempt dies at the socket; the retry succeeds.

    The EXCEPTION is an `httpx2` type while the RESPONSES are `httpx` 0.x -- the Pitfall-3
    split, in one function.
    """
    attempts = {1: 0}

    def _serve(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if page == 1:
            attempts[1] += 1
            if attempts[1] == 1:
                raise httpx2.ConnectError("drop")
        return httpx.Response(200, json=hevy_fixture(f"workouts_page{page}"))

    _mock_count(mock)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


@contextmanager
def _rendered_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[io.StringIO]:
    """Capture what the REAL logging pipeline writes, redaction layers included.

    Not `structlog.testing.capture_logs`: that helper replaces the configured processor chain
    for its duration, so both redaction layers would be absent and a leak could not be observed
    (test_secret_redaction.py, Pitfall 6).
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging(Settings(_env_file=None))
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        yield buffer
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()


# --- database readers ------------------------------------------------------

_SCOPED = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER)


async def _external_ids(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.scalars(sa.select(Workout.external_id).where(*_SCOPED))
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
        await conn.execute(sa.delete(Workout).where(*_SCOPED))
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


# --- tests -----------------------------------------------------------------


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
async def test_last_error_contains_no_payload(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """T-03-13: `last_error` is a display field, not somewhere a payload accumulates.

    Whatever is written here is read back by anything that reports sync health, so a naive
    rendering of the exception would put workout titles one query away from the MCP server.
    """
    _mock_second_page_always_500(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        with pytest.raises(HevyServerError):
            async with _client() as client:
                await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        last_error = (await _state(engine)).last_error
        assert last_error is not None
        assert last_error.startswith("HevyServerError")
        assert len(last_error) <= 500
        for title in FIXTURE_TITLES:
            assert title not in last_error, f"a workout title reached last_error: {title!r}"
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


@pytest.mark.integration
async def test_malformed_workout_is_quarantined_and_the_page_commits(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """One bad workout is skipped by name; the rest of its page still commits.

    The run finishes `idle`, not `error`: a record PostgreSQL refuses is a data problem to
    surface, not a reason to abandon a sync that got everything else.
    """
    _mock_quarantine_page(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.skipped == (BAD_WORKOUT,)
        assert result.workouts_upserted == 1
        assert await _external_ids(engine) == {PAGE_2_WORKOUT}
        assert (await _state(engine)).status == "idle"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_quarantine_logs_only_the_exception_class(
    engine: AsyncEngine, httpx2_mock: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-03-23: the skip is reported; the data that caused it is not.

    Rendering a `DataError` reproduces its bound parameters -- this user's workout titles and
    weights -- into whatever reads the exception. Asserted against the RENDERED stream so the
    claim covers every logger in the process, not just this module's call site.
    """
    _mock_quarantine_page(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        with _rendered_logs(monkeypatch) as buffer:
            async with _client() as client:
                await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
            rendered = buffer.getvalue()

        assert "hevy_workout_skipped" in rendered
        assert BAD_WORKOUT in rendered, "the skip must name WHICH workout was dropped"
        assert str(OVERFLOW_WEIGHT) not in rendered, "the offending bound parameter was logged"
        assert BAD_TITLE not in rendered, "T-03-23 violated: a workout title reached the log"
        for title in FIXTURE_TITLES:
            assert title not in rendered, f"a workout title reached the log: {title!r}"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_transport_error_mid_run_is_retried_then_completes(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """A dropped connection is transient, and the run must not notice it.

    Hevy's ten-item pages make a full history dozens of sequential requests, so a single
    socket error part-way through has to cost one retry rather than the whole sync.
    """
    route = _mock_page_one_drops_once(httpx2_mock)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.pages_fetched == 2
        assert await _external_ids(engine) == {PAGE_1_WORKOUT, PAGE_2_WORKOUT}
        # Three workout requests for two pages: page 1 twice, page 2 once.
        assert route.call_count == 3
        assert (await _state(engine)).status == "idle"
    finally:
        await _cleanup(engine)

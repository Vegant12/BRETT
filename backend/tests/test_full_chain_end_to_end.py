"""mock-Hevy -> sync -> PostgreSQL -> analytics -> MCP tool, in one run (blueprint 43, DEPLOY-03).

This is the composition test ROADMAP Phase 7 criterion 1 names. Every other test in this
suite covers one layer; this one covers the seam between four, and the only assertion that
earns its cost is that the analytics boundary and the MCP boundary report the SAME number.
A test that asserted "the tool returned something" would have passed throughout Phase 6 and
would prove nothing new.

Mocking rule (conftest, Pitfall 3): RESPONSES use `httpx.Response` (0.x, the type respx
asserts on); EXCEPTIONS use `httpx2` types. respx also asserts every registered route was
called, so the incremental events feed is deliberately NOT registered -- this test never
goes incremental, and registering a route it is right not to touch would fail on teardown.

Cleanup is a per-test `finally` rather than a fixture teardown: `sync_all()` COMMITS, the
Postgres container is session-scoped and shared, and a rollback cannot undo a commit.

The clock is frozen for the MCP half only. Analytics takes an explicit date range; every
`weeks`-taking MCP tool derives its window from `local_today` (app/mcp/tools/_common.py:198),
and the fixture workouts are dated August 2026, so an unfrozen `weeks=2` window would contain
nothing and the test would pass vacuously on two empty results.
"""

import contextlib
import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
import time_machine
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.analytics.volume import get_weekly_volume
from app.db.models import (
    BodyMeasurement,
    ExerciseMuscle,
    ExerciseMuscleOverride,
    ExerciseTemplate,
    SyncState,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)
from app.db.repositories.sync_state import PROVIDER_HEVY
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.sync import HevySyncService
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"
TEMPLATES = f"{BASE}/v1/exercise_templates"
MEASUREMENTS = f"{BASE}/v1/body_measurements"

# Distinctive on purpose, so a leak is unambiguous rather than a coincidence.
HEVY_KEY = "hevy-key-full-chain-must-not-be-logged"

# --- The hand-computed answer, derived once and written down -----------------
#
# `workouts_page1.json` starts at 2026-08-01T01:00:00Z and carries 3 sets: one `warmup` and
# two `normal`. `workouts_page2.json` starts at 2026-08-03T01:00:00Z and carries 1 `normal`
# set. The user's timezone is Asia/Jakarta (UTC+7), so 01:00Z is 08:00 local and the local
# days are Saturday 2026-08-01 and Monday 2026-08-03. Monday-anchored local weeks put the
# first workout in the week beginning 2026-07-27 and the second in its own week.
#
# Hard sets are an EXCLUSION of `warmup`, so the answer is 2 and 1 -- never 3 and 1.
WEEK_A = dt.date(2026, 7, 27)
WEEK_B = dt.date(2026, 8, 3)
EXPECTED_HARD_SETS_BY_WEEK = {WEEK_A: 2, WEEK_B: 1}
EXPECTED_HARD_SET_SEQUENCE = [2, 1]

# The whole point of the warm-up assertion: the database holds four set rows and every
# reported figure is three.
RAW_SET_ROWS = 4
TOTAL_HARD_SETS = 3

# The two fixture workouts, and nothing else, fall inside the window both halves ask about.
EXPECTED_SESSIONS_IN_WINDOW = 2

# The analytics half takes an EXPLICIT range and never consults a clock. 2026-08-09 is the
# Sunday that closes WEEK_B, so this range is already whole-week aligned and `get_weekly_volume`'s
# own outward snap is a no-op on it.
RANGE_START = dt.date(2026, 7, 27)
RANGE_END = dt.date(2026, 8, 9)

# 03:00Z is 10:00 in Jakarta -- comfortably inside Wednesday 2026-08-05, so this instant
# exercises the timezone arithmetic without sitting on the local-midnight boundary. From that
# local Wednesday, `weeks=2` resolves to 2026-07-27..2026-08-05, which snaps outward to exactly
# WEEK_A and WEEK_B.
FROZEN_NOW = dt.datetime(2026, 8, 5, 3, 0, tzinfo=dt.UTC)
TOOL_WEEKS = 2

_SCOPED = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER_HEVY)


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The predicate and the attempt count stay real."""


def _client(**kwargs: Any) -> HevyClient:
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _service(client: HevyClient, maker: async_sessionmaker[AsyncSession]) -> HevySyncService:
    return HevySyncService(client, maker, user_id=DEFAULT_USER_ID)


def _mock_hevy(mock: Router) -> dict[str, Route]:
    """Serve every endpoint the FULL path reaches, repeatably.

    The incremental events feed is deliberately NOT registered here: respx asserts every
    registered route was called, so a run that legitimately never goes incremental would fail
    on teardown for a route it was right not to touch.

    CALLABLE side effects rather than a list of pre-built responses: an `httpx.Response` is a
    one-shot object whose stream is consumed on first use.
    """
    pages = {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")}

    def _serve_workouts(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in pages, f"the sync requested workouts page {page}, which was not mocked"
        return httpx.Response(200, json=pages[page])

    def _serve_count(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"workout_count": 2})

    def _serve_templates(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("exercise_templates_page1"))

    def _serve_body(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("body_measurements_page1"))

    # `/v1/workouts/count` is registered FIRST: respx resolves routes in registration order,
    # and a `/v1/workouts` route added ahead of it would be the one that answered.
    return {
        "count": mock.get(WORKOUT_COUNT).mock(side_effect=_serve_count),
        "workouts": mock.get(WORKOUTS).mock(side_effect=_serve_workouts),
        "templates": mock.get(TEMPLATES).mock(side_effect=_serve_templates),
        "body": mock.get(MEASUREMENTS).mock(side_effect=_serve_body),
    }


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove every row this module can have committed, pass or fail."""
    async with maker() as session:
        for statement in (
            sa.delete(Workout).where(Workout.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscle).where(ExerciseMuscle.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscleOverride).where(
                ExerciseMuscleOverride.user_id == DEFAULT_USER_ID
            ),
            sa.delete(ExerciseTemplate).where(ExerciseTemplate.user_id == DEFAULT_USER_ID),
            sa.delete(BodyMeasurement).where(BodyMeasurement.user_id == DEFAULT_USER_ID),
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER_HEVY
            ),
        ):
            await session.execute(statement)
        await session.commit()


@contextlib.asynccontextmanager
async def _mcp_over(engine: AsyncEngine) -> AsyncIterator[None]:
    """Point `app.state.sessionmaker` at the container the sync just committed to.

    Entering `Client(mcp)` runs `mcp_lifespan`, which reads `app.state.sessionmaker`
    (app/mcp/context.py:41). Without this the tool opens a session against whatever
    DATABASE_URL points at -- a different database, which would answer every question
    with zeros and look like a passing test of an empty window.
    """
    from app.main import app

    preexisting = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield
    finally:
        if preexisting is not None:
            app.state.sessionmaker = preexisting


async def _sync_from_mocked_hevy(maker: async_sessionmaker[AsyncSession]) -> None:
    """Drive the whole Hevy sync against the mocked API, exactly as the CLI would."""
    async with _client() as hevy:
        await _service(hevy, maker).sync_all()


async def _analytics_hard_sets(maker: async_sessionmaker[AsyncSession]) -> dict[dt.date, int]:
    """The ANALYTICS boundary's answer, over an explicit range and with no clock involved."""
    async with maker() as session:
        analytics = await get_weekly_volume(
            session,
            user_id=DEFAULT_USER_ID,
            start_day=RANGE_START,
            end_day=RANGE_END,
        )
    return {week.week_start: week.hard_sets for week in analytics.weeks}


async def _weekly_volume_through_mcp(engine: AsyncEngine) -> dict[str, Any]:
    """The MCP boundary's answer to the same question, as Claude would receive it.

    `from app.mcp.server import mcp` and `from mcp import Client` are IN-FUNCTION imports and
    never module scope: `conftest` seeds the MCP environment at module import, and
    `app.mcp.server` freezes the token verifier and the Host allowlist at ITS import, so a
    module-scope import would run that bootstrap during pytest's collection phase.

    Nothing in this module drives the app over HTTP. `Client(mcp)` speaks to the server
    in-memory and so never touches `mcp.session_manager._has_started`, the one-shot flag
    `conftest`'s app-level fixture has to reach into and reset (07-RESEARCH.md Pitfall 11).
    """
    from mcp import Client

    from app.mcp.server import mcp

    with time_machine.travel(FROZEN_NOW, tick=False):
        async with _mcp_over(engine), Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": TOOL_WEEKS})

    assert result.is_error is False, (
        "DEPLOY-03 violated: fitness_get_weekly_volume returned a protocol-level error against "
        f"data the sync had just committed. Got: {result.content!r}"
    )
    payload = result.structured_content
    assert payload is not None, (
        "DEPLOY-03 violated: the tool returned no structured content. `outputSchema` and "
        "`structured_content` are both derived from the returned BaseModel, so an absent "
        "payload means Claude received prose it has to parse rather than data it can read."
    )
    assert payload["data_available"] is True, (
        "DEPLOY-03 violated: the tool reported `data_available=False` immediately after a "
        "successful sync. That is the degraded shape `@safe_tool` returns when the tool body "
        f"raised -- most likely the MCP half is reading a different database. Got: {payload}"
    )
    volume: dict[str, Any] = payload["volume"]
    return volume


async def _raw_set_row_count(maker: async_sessionmaker[AsyncSession]) -> int:
    """Every `workout_sets` row the sync wrote, warm-ups included."""
    async with maker() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutSet)
            .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*_SCOPED)
        )
    return count or 0


@pytest.mark.integration
async def test_the_full_chain_produces_the_same_answer(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """Blueprint 43 / DEPLOY-03: four layers, one run, and the same number out of both ends.

    The assertion that earns this test's cost is the LAST one. Each layer already has its own
    suite, and every one of them can be green while the composition is wrong -- an MCP tool
    that resolves the wrong window, or reads the wrong database, or snaps the range a second
    time, produces a perfectly well-formed answer to a different question.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        await _sync_from_mocked_hevy(maker)

        # --- analytics boundary: an EXPLICIT range, no clock involved -----------
        by_week = await _analytics_hard_sets(maker)
        assert by_week == EXPECTED_HARD_SETS_BY_WEEK, (
            "DEPLOY-03 violated: the analytics layer disagrees with the hand-computed answer "
            "for the two fixture workouts. Asia/Jakarta is UTC+7, so 2026-08-01T01:00Z is a "
            "local Saturday in the week beginning 2026-07-27 and 2026-08-03T01:00Z is a local "
            f"Monday in its own week. Expected {EXPECTED_HARD_SETS_BY_WEEK}; got {by_week}"
        )

        # --- MCP boundary: the SAME number, through the tool -------------------
        volume = await _weekly_volume_through_mcp(engine)
        tool_hard_sets = [week["hard_sets"] for week in volume["weeks"]]

        assert tool_hard_sets == EXPECTED_HARD_SET_SEQUENCE, (
            "DEPLOY-03 violated: the MCP tool and the analytics function disagree about the "
            f"same synced data. Analytics said {[by_week[week] for week in (WEEK_A, WEEK_B)]}; "
            f"the tool said {tool_hard_sets}. Every layer passing its own tests while the "
            "composition is wrong is exactly the failure blueprint 43 exists to catch."
        )
        assert [week["week_start"] for week in volume["weeks"]] == [
            WEEK_A.isoformat(),
            WEEK_B.isoformat(),
        ], (
            "DEPLOY-03 violated: the tool returned the right hard-set figures against the wrong "
            f"weeks, which means the windows only coincidentally agree. Got: {volume['weeks']}"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_the_chain_excludes_warm_up_sets_at_both_boundaries(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The exclusion survives all four layers, and the raw row count is what proves it.

    Asserting `3` alone would stay green against a chain that had lost the fixture's warm-up
    row somewhere in the sync -- the total would be right for the wrong reason. Reading the raw
    `workout_sets` count first pins down that the database really does hold four sets, so the
    two reported threes are an exclusion rather than a shortfall.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        await _sync_from_mocked_hevy(maker)

        raw_rows = await _raw_set_row_count(maker)
        assert raw_rows == RAW_SET_ROWS, (
            "DEPLOY-03 violated: the sync did not write the four fixture set rows, so the "
            f"warm-up exclusion below would be asserting against the wrong baseline. Got: "
            f"{raw_rows}"
        )

        analytics_total = sum((await _analytics_hard_sets(maker)).values())
        volume = await _weekly_volume_through_mcp(engine)
        tool_total = sum(week["hard_sets"] for week in volume["weeks"])

        assert analytics_total == TOTAL_HARD_SETS, (
            "VOL-01 violated at the analytics boundary: hard sets are an EXCLUSION of `warmup`, "
            f"never a count of every set. Got {analytics_total} from {raw_rows} raw rows."
        )
        assert tool_total == TOTAL_HARD_SETS, (
            "VOL-01 violated at the MCP boundary: the tool reported "
            f"{tool_total} hard sets from {raw_rows} raw set rows. The warm-up set of the first "
            "fixture workout is being counted as training volume in what Claude reads, even "
            "though the analytics layer excludes it correctly."
        )
        assert tool_total == analytics_total
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_the_mcp_half_reads_the_database_the_sync_wrote(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The metadata envelope is the proof of WHICH database answered (DQ-01, DQ-02).

    The hard-set assertions above would also be satisfied by a tool talking to some other
    database that happened to hold the same two workouts. `coverage.sessions_in_window` and
    `freshness.resources` cannot be: the session count comes from the rows this sync committed,
    and a `last_synced_at` exists only because this sync wrote a `sync_state` row moments ago.
    An empty database answers both with a confident zero and a `None`, which is what a
    mis-wired `app.state.sessionmaker` looks like from the outside.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        await _sync_from_mocked_hevy(maker)

        volume = await _weekly_volume_through_mcp(engine)

        assert volume["coverage"]["sessions_in_window"] == EXPECTED_SESSIONS_IN_WINDOW, (
            "DEPLOY-03 violated: the tool's coverage envelope reports "
            f"{volume['coverage']['sessions_in_window']} sessions where the sync committed "
            f"{EXPECTED_SESSIONS_IN_WINDOW}. A zero here means the MCP layer is reading a "
            "database this test never wrote to -- `app.state.sessionmaker` was not redirected "
            "at the container."
        )
        assert volume["freshness"]["resources"]["workouts"] is not None, (
            "DQ-01 violated: the tool reports no `last_synced_at` for `workouts`, so Claude "
            "cannot tell fresh data from stale. The sync just wrote that row; a `None` here "
            "means the freshness read and the sync write are not looking at the same database."
        )
    finally:
        await _cleanup(maker)

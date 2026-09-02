"""The WIRE contract of the Health Auto Export webhook (HEALTH-06, HEALTH-07).

What this file owns: that the route is REACHABLE, that it answers the documented status codes
over real HTTP, and that the FastAPI route inventory has not silently grown an unauthenticated
member.

What lives elsewhere, deliberately:

* the verifier's decision function -- `test_health_ingest_auth.py`, which also carries the
  over-HTTP 401 cases so both halves of "rejected, writing nothing, explaining nothing" sit
  beside each other;
* idempotency and the upsert -- `test_health_ingest_idempotency.py`;
* ROADMAP criterion #4 (Apple Health changes no Hevy number) -- `test_health_ingest_isolation.py`.

Marked `integration` throughout: a request that reaches the handler reaches `ingest_payload`,
which reads `users.timezone` and writes rows. The whole point is what a REAL request meets.
"""

import asyncio
import uuid
from collections.abc import Coroutine, Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import HealthDailyMetric, SyncState
from tests.conftest import DEFAULT_USER_ID, hae_fixture

# Distinct from `test_health_ingest_auth.SECRET` and from every other credential literal in the
# suite: an assertion that a value never reached a response body is only meaningful when nothing
# else in the process could have emitted that string.
SECRET = "route-ingest-secret-9d41-not-a-real-credential"

INGEST_PATH = "/api/v1/ingest/health-auto-export"

# The exact key set of the 202. Pinned here rather than spelled inline so a handler that starts
# returning a stored VALUE beside the counts fails one assertion with a readable diff (ASVS V8).
ACCEPTED_KEYS = frozenset(
    {"status", "rows_upserted", "rows_skipped", "datapoints_seen", "metrics_unrecognized"}
)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run one coroutine from a SYNC test body.

    `TestClient` is synchronous and drives the app through a portal in its own thread, so a
    test that needs both HTTP and direct database access cannot be `async def`. A fresh loop in
    the main thread is independent of the portal's.
    """
    return asyncio.run(coro)


async def _purge(postgres_url: str) -> None:
    """Remove everything a request through this route writes, pass or fail.

    A per-test purge rather than a fixture teardown, matching `test_health_ingest_idempotency`:
    these rows share a session-scoped container with every other integration test, and a health
    row that outlived its test would make the next test's count assertion depend on execution
    order.
    """
    engine = create_async_engine(postgres_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with maker() as session:
            await session.execute(
                sa.delete(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
            )
            await session.execute(sa.delete(SyncState).where(SyncState.user_id == DEFAULT_USER_ID))
            await session.commit()
    finally:
        await engine.dispose()


async def _health_row_count(postgres_url: str, user_id: uuid.UUID = DEFAULT_USER_ID) -> int:
    engine = create_async_engine(postgres_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with maker() as session:
            count = await session.scalar(
                sa.select(sa.func.count())
                .select_from(HealthDailyMetric)
                .where(HealthDailyMetric.user_id == user_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


@pytest.fixture
def ingest_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Configure the webhook credential for the duration of one test.

    `get_settings` is `lru_cache`d and the route calls it per request, so clearing the cache is
    what makes the new value visible. `app/main.py`'s module-level `settings` is deliberately
    NOT re-read -- it only feeds the log scrubber, and rebuilding it would mean reconfiguring
    logging mid-session.
    """
    monkeypatch.setenv("HEALTH_INGEST_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        yield SECRET
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_ingest_route_resolves_to_fastapi_not_the_mcp_mount(
    client: TestClient, ingest_secret: str, postgres_url: str
) -> None:
    """RESEARCH Pitfall 1. `app.mount("/", mcp_app)` is a CATCH-ALL registered last on purpose.

    A route registered BELOW it is dead in production while every unit test that builds its own
    app still passes -- `test_secret_redaction.py` already had to re-append the mount after
    adding a route at test time, which is how we know this is real rather than theoretical. This
    test goes over HTTP against the real `app` object for exactly that reason.

    Two failures are separated here because the registration looks correct in both. A `404` or
    an MCP-shaped error body means the mount swallowed the path. A `401` means the route
    resolved but the credential never reached the verifier.
    """
    try:
        response = client.post(
            INGEST_PATH,
            json=hae_fixture("activity_and_nutrition"),
            headers={"Authorization": f"Bearer {ingest_secret}"},
        )

        assert response.status_code == 202, (
            f"HEALTH-07: expected 202 from BRETT's own handler, got {response.status_code}. "
            f"A 404 or an MCP-shaped body means `include_router` sits BELOW "
            f"`app.mount('/', mcp_app)` and the route is dead in production. "
            f"Body: {response.text[:400]}"
        )
        body = response.json()
        assert set(body) == ACCEPTED_KEYS, (
            f"ASVS V8: the 202 body must carry exactly {sorted(ACCEPTED_KEYS)} -- counts only, "
            f"never a stored value. Got: {sorted(body)}"
        )
        assert "jsonrpc" not in body and "error" not in body, (
            f"RESEARCH Pitfall 1: the response is MCP-shaped, so the catch-all mount answered "
            f"this path instead of the FastAPI route. Got: {body}"
        )
        assert body["rows_upserted"] > 0, (
            "the request was accepted but wrote nothing, so the assertions above pass "
            "vacuously -- `ingest_payload` was not reached or the payload was empty"
        )
        assert _run(_health_row_count(postgres_url)) == body["rows_upserted"]
    finally:
        _run(_purge(postgres_url))

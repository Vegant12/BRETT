"""The WIRE contract of the Health Auto Export webhook (HEALTH-06, HEALTH-07).

What this file owns: that the route is REACHABLE, that it answers the documented status codes
over real HTTP, that an oversized body is refused BEFORE the parse, and that the FastAPI route
inventory has not silently grown an unauthenticated member.

What lives elsewhere, deliberately:

* the verifier's decision function AND the over-HTTP 401 cases -- `test_health_ingest_auth.py`,
  so both halves of "rejected, writing nothing, explaining nothing" sit beside each other;
* idempotency and the upsert -- `test_health_ingest_idempotency.py`;
* ROADMAP criterion #4 (Apple Health changes no Hevy number) -- `test_health_ingest_isolation.py`.

Marked `integration` throughout: a request that reaches the handler reaches `ingest_payload`,
which reads `users.timezone` and writes rows. The whole point is what a REAL request meets.
"""

import asyncio
import io
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import sqlalchemy as sa
import structlog
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.routing import Mount

from app.api.routes import health_ingest
from app.config import Settings, get_settings
from app.db.models import HealthDailyMetric, SyncState
from app.integrations.health_auto_export import ingest
from app.logging import configure_logging
from app.middleware import INGEST_PATH_PREFIX, TokenBucket
from tests.conftest import DEFAULT_USER_ID, hae_fixture

# Distinct from `test_health_ingest_auth.SECRET` and from every other credential literal in the
# suite: an assertion that a value never reached a response body is only meaningful when nothing
# else in the process could have emitted that string.
SECRET = "route-ingest-secret-9d41-not-a-real-credential"

INGEST_PATH = "/api/v1/ingest/health-auto-export"

# The whole FastAPI-owned route inventory. `/health` is the ONLY intentionally open route
# (D-04: platform health checks must reach it without a token).
EXPECTED_FASTAPI_ROUTES = frozenset({"/health", INGEST_PATH})

# The exact key set of the 202. Pinned here rather than spelled inline so a handler that starts
# returning a stored VALUE beside the counts fails one assertion with a readable diff (ASVS V8).
ACCEPTED_KEYS = frozenset(
    {"status", "rows_upserted", "rows_skipped", "datapoints_seen", "metrics_unrecognized"}
)

# Small enough that an oversized body is a few hundred bytes rather than eleven megabytes. The
# production value (10 MiB) is asserted in `test_config.py`; what matters HERE is the ordering
# of the checks, and generating a real 10 MB body to prove it would only make the test slow.
TINY_CAP = 128

# The two log events that can only be emitted AFTER the body has been parsed. Their ABSENCE is
# how "413 before the parse" is asserted -- a status code alone cannot distinguish a cap that
# fired early from one that fired after `model_validate_json` had already built the object.
POST_PARSE_EVENTS = ("health_ingest_payload_rejected", "health_ingest_completed")


def _run[T](coro: Any) -> T:
    """Run one coroutine from a SYNC test body.

    `TestClient` is synchronous and drives the app through a portal in its own thread, so a
    test that needs both HTTP and direct database access cannot be `async def`. A fresh loop in
    the main thread is independent of the portal's.
    """
    result: T = asyncio.run(coro)
    return result


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


@contextmanager
def _capture_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Render the REAL logging pipeline into a buffer for the duration of the block.

    Not `structlog.testing.capture_logs`: that replaces the configured processor chain for its
    duration, which would leave an absence assertion green over a pipeline that never ran
    (`test_secret_redaction.py`'s Pitfall 6).

    BOTH module proxies are replaced, mirroring `test_health_ingest_idempotency`'s async
    equivalent. The route logs from `health_ingest.py` and the ingest logs from `ingest.py`, and
    patching only one would scan half the stream and report the other half as clean -- fatal for
    a test whose entire claim is that a post-parse event is ABSENT.

    Synchronous, because `TestClient` is. The request runs in the portal thread; the stdlib
    handler and its stream are process-global, so the capture spans both threads.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")  # JSONRenderer; development is console
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_route, saved_ingest = health_ingest.log, ingest.log
    entries: list[dict[str, Any]] = []
    buffer = io.StringIO()
    try:
        configure_logging(Settings(_env_file=None))  # type: ignore[call-arg]
        structlog.configure(cache_logger_on_first_use=False)
        fresh = structlog.get_logger()
        monkeypatch.setattr(health_ingest, "log", fresh)
        monkeypatch.setattr(ingest, "log", fresh)
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        yield entries
    finally:
        health_ingest.log, ingest.log = saved_route, saved_ingest
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
        entries.extend(json.loads(line) for line in buffer.getvalue().splitlines() if line.strip())


def _event_names(entries: list[dict[str, Any]]) -> list[str]:
    return [entry.get("event", "") for entry in entries]


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


@pytest.fixture
def tiny_body_cap(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """Shrink the pre-parse body budget so an "oversized" body is a few hundred bytes."""
    monkeypatch.setenv("INGEST_MAX_BODY_BYTES", str(TINY_CAP))
    get_settings.cache_clear()
    try:
        yield TINY_CAP
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_buckets() -> Iterator[None]:
    """Give every test in this module full, independent rate-limit buckets.

    `app.state.*_bucket` is built once at import and lives for the whole session, so without
    this the tests here would spend each other's tokens and the 429 case would depend on
    execution order. Restored afterwards so no other module inherits a drained -- or an
    artificially tiny -- bucket.
    """
    from app.main import app

    saved_shared = app.state.rate_limit_bucket
    saved_ingest = app.state.ingest_rate_limit_bucket
    app.state.rate_limit_bucket = TokenBucket(capacity=100, refill_per_second=100.0)
    app.state.ingest_rate_limit_bucket = TokenBucket(capacity=100, refill_per_second=100.0)
    try:
        yield
    finally:
        app.state.rate_limit_bucket = saved_shared
        app.state.ingest_rate_limit_bucket = saved_ingest


def _fastapi_route_paths() -> set[str]:
    """Every path FastAPI itself owns, walked from the live router.

    FastAPI 0.141.1 does NOT flatten `include_router` into `app.routes`: it appends an
    `_IncludedRouter` wrapper whose own `path` is `None`, with the real `APIRoute` objects
    hanging off `original_router`. A guard written as
    `{r.path for r in app.routes if isinstance(r, APIRoute)}` -- the obvious form -- therefore
    returns the EMPTY SET on this version and passes no matter what is registered. Hence the
    recursion, and hence `test_the_route_walk_actually_finds_routes` beside it.

    Starlette `Route` objects (`/docs`, `/openapi.json`, `/redoc`, `/docs/oauth2-redirect`) are
    excluded by the `APIRoute` check: they are FastAPI's own documentation endpoints, they
    expose no data, and pinning them here would make this guard fail on a FastAPI upgrade for a
    reason that has nothing to do with authentication. The `Mount` is excluded because the MCP
    sub-app owns its own routes AND its own `RequireAuthMiddleware`.
    """
    from app.main import app

    found: set[str] = set()

    def walk(routes: list[Any]) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                found.add(route.path)
            elif isinstance(route, Mount):
                continue
            else:
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    walk(list(inner.routes))

    walk(list(app.router.routes))
    return found


# ---------------------------------------------------------------------------
# Mount order (RESEARCH Pitfall 1)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ingest_route_resolves_to_fastapi_not_the_mcp_mount(
    client: TestClient, ingest_secret: str, postgres_url: str
) -> None:
    """RESEARCH Pitfall 1. The mount at `/` is a CATCH-ALL registered last on purpose.

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
            f"A 404 or an MCP-shaped body means `include_router` sits BELOW the catch-all "
            f"mount and the route is dead in production. Body: {response.text[:400]}"
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
        assert body["status"] == "accepted"
        assert body["rows_upserted"] > 0, (
            "the request was accepted but wrote nothing, so the assertions above pass "
            "vacuously -- `ingest_payload` was not reached or the payload was empty"
        )
        assert _run(_health_row_count(postgres_url)) == body["rows_upserted"]
    finally:
        _run(_purge(postgres_url))


def test_the_router_is_registered_before_the_catch_all_mount() -> None:
    """The same claim as above, asserted STRUCTURALLY rather than over HTTP.

    Deliberately not a text search on `app/main.py`. Two comments in that file legitimately
    spell the mount call while explaining why order matters, so comparing string positions
    reports the WRONG answer on a correct file -- and would keep reporting it after somebody
    "fixed" the guard by deleting the explanation. Route-list order is what Starlette actually
    resolves against, so that is what is asserted.

    Registered as a FAST test (no container): it is pure structure, and a broken registration
    should fail on the commit that introduces it rather than after a container spins up.
    """
    from app.main import app

    def owns_the_ingest_path(route: Any) -> bool:
        inner = getattr(route, "original_router", None)
        return inner is not None and any(
            getattr(r, "path", None) == INGEST_PATH for r in inner.routes
        )

    routes = list(app.router.routes)
    mount_indexes = [i for i, route in enumerate(routes) if isinstance(route, Mount)]
    ingest_indexes = [i for i, route in enumerate(routes) if owns_the_ingest_path(route)]

    assert mount_indexes, "no Mount found: the walk is wrong, so the comparison below is vacuous"
    assert ingest_indexes, (
        f"no router owning {INGEST_PATH} is registered on `app` at all -- the route does not "
        f"exist, or `include_router` was never called"
    )
    assert max(ingest_indexes) < min(mount_indexes), (
        f"RESEARCH Pitfall 1 violated: the ingest router is registered at index "
        f"{max(ingest_indexes)}, AFTER the catch-all mount at index {min(mount_indexes)}. "
        f"Starlette resolves in list order, so the mount answers every request to "
        f"{INGEST_PATH} and the route is dead in production while this suite still passes"
    )


# ---------------------------------------------------------------------------
# Pre-parse size cap (RESEARCH Pitfall 5, T-08-45)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_an_oversized_declared_body_is_rejected_before_the_parse(
    client: TestClient,
    ingest_secret: str,
    tiny_body_cap: int,
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
) -> None:
    """A declared `Content-Length` above the cap costs one header lookup and nothing else.

    The status code alone would not distinguish this from a cap applied AFTER
    `model_validate_json` had already built the object -- which is the failure RESEARCH Pitfall
    5 is about, because that version OOMs on a real 10 MB body and Cloud Run reports it as a
    bare 503. The absence of every post-parse log event is what pins the ordering.
    """
    oversized = json.dumps({"data": {"metrics": [{"name": "step_count", "units": "count"}]}})
    oversized += " " * (tiny_body_cap * 4)

    try:
        with _capture_logs(monkeypatch) as entries:
            response = client.post(
                INGEST_PATH,
                content=oversized.encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {ingest_secret}",
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 413, (
            f"expected 413 for a body of {len(oversized)} bytes against a {tiny_body_cap}-byte "
            f"cap, got {response.status_code}. Body: {response.text[:200]}"
        )
        assert response.json() == {"error": "payload_too_large"}, (
            f"the 413 body must carry exactly one key: anyone on the internet can make this "
            f"endpoint emit it. Got: {response.json()}"
        )

        names = _event_names(entries)
        assert "health_ingest_payload_too_large" in names, (
            f"the cap fired but logged nothing, so an operator sees a 413 with no explanation. "
            f"Events: {names}"
        )
        too_large = next(e for e in entries if e["event"] == "health_ingest_payload_too_large")
        assert too_large["declared_bytes"] == len(oversized), (
            "the DECLARED length branch must be the one that fired -- checking the cheap header "
            "before reading the stream is the whole point of having both"
        )
        for forbidden in POST_PARSE_EVENTS:
            assert forbidden not in names, (
                f"RESEARCH Pitfall 5 violated: {forbidden!r} was emitted, so the body reached "
                f"the parser before the cap was applied. On a real 10 MB body that is an OOM "
                f"reported as a bare 503. Events: {names}"
            )
        assert _run(_health_row_count(postgres_url)) == 0
    finally:
        _run(_purge(postgres_url))


@pytest.mark.integration
def test_an_oversized_undeclared_body_is_rejected_before_the_parse(
    client: TestClient,
    ingest_secret: str,
    tiny_body_cap: int,
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
) -> None:
    """`Content-Length` is OPTIONAL and attacker-controlled, so the stream is capped too.

    Sent as an iterator, which makes httpx use chunked transfer encoding and omit
    `Content-Length` entirely. A handler that trusted the header would sail past the cap here
    and buffer the whole body -- the declared-length check alone is not the control.
    """

    def chunks() -> Iterator[bytes]:
        yield b'{"data": {"metrics": ['
        for _ in range(8):
            yield b'{"name": "step_count", "units": "count", "data": []},'
        yield b"]}}"

    try:
        with _capture_logs(monkeypatch) as entries:
            response = client.post(
                INGEST_PATH,
                content=chunks(),
                headers={
                    "Authorization": f"Bearer {ingest_secret}",
                    "Content-Type": "application/json",
                },
            )

        assert response.status_code == 413, (
            f"expected 413 for a chunked body over the {tiny_body_cap}-byte cap, got "
            f"{response.status_code}. A 400 means the body was PARSED first, which is the "
            f"ordering bug. Body: {response.text[:200]}"
        )
        assert response.json() == {"error": "payload_too_large"}

        names = _event_names(entries)
        too_large = [e for e in entries if e["event"] == "health_ingest_payload_too_large"]
        assert too_large, f"the streaming cap fired but logged nothing. Events: {names}"
        assert "read_bytes" in too_large[0], (
            f"the STREAMING branch must be the one that fired: with no Content-Length header "
            f"there is nothing for the declared-length check to read. Got: {too_large[0]}"
        )
        for forbidden in POST_PARSE_EVENTS:
            assert forbidden not in names, (
                f"RESEARCH Pitfall 5 violated: {forbidden!r} was emitted, so an undeclared body "
                f"reached the parser. Events: {names}"
            )
        assert _run(_health_row_count(postgres_url)) == 0
    finally:
        _run(_purge(postgres_url))


@pytest.mark.integration
def test_a_body_within_the_cap_is_not_rejected_as_oversized(
    client: TestClient, ingest_secret: str, tiny_body_cap: int, postgres_url: str
) -> None:
    """The guard on the two guards above: the cap must not reject EVERYTHING.

    Without this, a handler that answered 413 unconditionally would pass both oversized cases
    and the whole endpoint would be dead while the suite stayed green.
    """
    small = json.dumps({"data": {"metrics": []}}).encode("utf-8")
    assert len(small) <= tiny_body_cap, "the fixture body is itself over the cap"

    try:
        response = client.post(
            INGEST_PATH,
            content=small,
            headers={
                "Authorization": f"Bearer {ingest_secret}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 202, (
            f"an empty-but-valid envelope under the cap must be accepted, got "
            f"{response.status_code}: {response.text[:200]}"
        )
        assert response.json()["rows_upserted"] == 0
    finally:
        _run(_purge(postgres_url))


# ---------------------------------------------------------------------------
# Envelope rejection
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_valid_json_that_is_not_an_hae_envelope_is_a_400(
    client: TestClient, ingest_secret: str, monkeypatch: pytest.MonkeyPatch, postgres_url: str
) -> None:
    """A broken envelope is the one HAE failure that rejects the whole request.

    `schemas.py` makes every datapoint field optional precisely so that an odd datapoint costs
    one datapoint rather than the window; `data` is the single required field, and its absence
    means a misconfigured exporter or something that is not HAE at all.

    The log line is asserted to carry a class NAME and no input: `ValidationError.__str__`
    renders `input_value=...`, i.e. this person's calorie counts (T-08-47).
    """
    try:
        with _capture_logs(monkeypatch) as entries:
            response = client.post(
                INGEST_PATH,
                json={"not_data": {"metrics": []}},
                headers={"Authorization": f"Bearer {ingest_secret}"},
            )

        assert response.status_code == 400, (
            f"expected 400 for a non-HAE envelope, got {response.status_code}: "
            f"{response.text[:200]}"
        )
        assert response.json() == {"error": "invalid_payload"}, (
            f"the 400 body must carry exactly one key and no validation detail. "
            f"Got: {response.json()}"
        )

        rejected = [e for e in entries if e["event"] == "health_ingest_payload_rejected"]
        assert len(rejected) == 1, (
            f"expected one rejection log line. Events: {_event_names(entries)}"
        )
        assert rejected[0]["reason"] == "HAEPayloadError", (
            f"T-08-47: the reason must be a class NAME. A rendered ValidationError carries "
            f"`input_value=...`. Got: {rejected[0]}"
        )
        assert "input_value" not in json.dumps(rejected[0]), (
            f"T-08-47 violated: the rejection log line carries the input. Got: {rejected[0]}"
        )
        assert _run(_health_row_count(postgres_url)) == 0
    finally:
        _run(_purge(postgres_url))


# ---------------------------------------------------------------------------
# Route inventory drift guard (RESEARCH Pitfall 3, T-08-42)
# ---------------------------------------------------------------------------


def test_the_route_walk_actually_finds_routes() -> None:
    """A guard on the guard below: an empty walk would make it vacuously true.

    FastAPI's internal route representation has already changed once in this project's
    lifetime (0.141.1 wraps `include_router` in `_IncludedRouter` rather than flattening), and
    the failure mode of a walk that stops working is silence, not an error.
    """
    paths = _fastapi_route_paths()

    assert "/health" in paths, (
        f"the route walk found {sorted(paths)}, which does not include the one route that has "
        f"existed since Phase 1. `_fastapi_route_paths` no longer understands FastAPI's route "
        f"structure, so the inventory guard below is checking nothing"
    )


def test_no_unauthenticated_fastapi_route_was_added() -> None:
    """RESEARCH Pitfall 3: a FastAPI route inherits ZERO auth from the MCP sub-app.

    The MCP SDK's RequireAuthMiddleware wraps only `mcp_app`. Any route added to `app` itself is
    open to the internet on an --allow-unauthenticated Cloud Run service unless it checks a
    credential in its own handler. This is a drift guard, not a proof of correctness: it fails
    when a route is ADDED, so the addition gets reviewed.

    `/health` is on the list because D-04 made it deliberately open -- the platform health check
    must reach it without a token, and its body is `{status, database}` and nothing else.
    `/api/v1/ingest/health-auto-export` is on it because this plan's handler authenticates as
    its first statement.
    """
    paths = _fastapi_route_paths()

    assert paths == set(EXPECTED_FASTAPI_ROUTES), (
        f"T-08-42: the FastAPI route inventory changed. Expected "
        f"{sorted(EXPECTED_FASTAPI_ROUTES)}, got {sorted(paths)}. Added "
        f"{sorted(paths - EXPECTED_FASTAPI_ROUTES)}, removed "
        f"{sorted(EXPECTED_FASTAPI_ROUTES - paths)}. A new route here is reachable by anyone on "
        f"the internet unless its own handler checks a credential -- update this list only "
        f"after confirming the new route does"
    )


# ---------------------------------------------------------------------------
# Rate limiting (RESEARCH Pitfall 2, T-08-46)
# ---------------------------------------------------------------------------


def test_the_ingest_path_falls_under_the_limiter_prefix() -> None:
    """The route path must start with the prefix `_bucket` selects on.

    A route mounted one character off -- `/api/v1/ingestion/...`, say -- would be throttled by
    the bucket `/mcp` shares, and every assertion in `test_rate_limit.py` would still pass
    because that file tests the middleware against a path it spells itself.
    """
    assert INGEST_PATH.startswith(INGEST_PATH_PREFIX), (
        f"RESEARCH Pitfall 2: {INGEST_PATH!r} does not start with {INGEST_PATH_PREFIX!r}, so "
        f"the dedicated ingest bucket is never selected and a burst of phone exports drains "
        f"the bucket Claude's connector uses"
    )


@pytest.mark.integration
def test_an_over_limit_request_429s_from_the_ingest_bucket(client: TestClient) -> None:
    """T-08-46 over real HTTP: the write path is bounded, and bounded SEPARATELY.

    The requests here are deliberately UNAUTHENTICATED. The limiter runs outside the router, so
    it spends a token before the handler ever sees the request -- which is the property that
    bounds an anonymous flood -- and it means this test drains a bucket without writing a row.

    A frozen clock, because the bucket refills on `time.monotonic` and a real one would let the
    second request through on a slow machine.
    """
    from app.main import app

    app.state.ingest_rate_limit_bucket = TokenBucket(
        capacity=1, refill_per_second=1.0, clock=lambda: 0.0
    )
    shared = TokenBucket(capacity=5, refill_per_second=1.0, clock=lambda: 0.0)
    app.state.rate_limit_bucket = shared

    first = client.post(INGEST_PATH, json={"data": {"metrics": []}})
    second = client.post(INGEST_PATH, json={"data": {"metrics": []}})

    assert first.status_code == 401, (
        f"the drain is broken: the first request should have reached the handler and been "
        f"refused for want of a credential, got {first.status_code}"
    )
    assert second.status_code == 429, (
        f"T-08-46 violated: a second request against a capacity-1 ingest bucket was not "
        f"throttled. Got {second.status_code}: {second.text[:200]}"
    )
    assert second.json() == {"error": "rate_limited"}

    # The other half of RESEARCH Pitfall 2, and the reason the second bucket exists at all.
    assert client.get("/openapi.json").status_code == 200, (
        "draining the ingest bucket also drained the bucket every other path shares, so a "
        "burst of phone exports 429s Claude's next tool call mid-coaching-turn"
    )

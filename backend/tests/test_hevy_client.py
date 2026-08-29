"""HevyClient transport behaviour (HEVY-01, HEVY-05, HEVY-08).

**Only the HTTP transport is replaced.** The status->exception mapping, the tenacity retry
predicate, the per-endpoint page-size constants, the query parameters and the Pydantic
validation are all the real code under test. Mocking `HevyClient.get_workouts` instead would
leave a permanently green suite over a client that has never issued a request.

Mocking rule (see conftest): RESPONSES use `httpx.Response` (0.x, what respx asserts on);
EXCEPTIONS use `httpx2` types.

One further substitution, and it is narrow: every client built here is given a no-op `sleep`.
The real wait strategy is `wait_exponential_jitter(initial=1, max=60, jitter=2)`, so the five
retry tests below would otherwise spend 1-3 REAL seconds each -- a ~10s tax on a suite whose
entire point is to run without a container. The *predicate* (which errors retry) and the
*stop* (how many attempts) are untouched and are what every assertion here is about; only the
duration of the pause between attempts is removed.
"""

import datetime as dt
import io
import logging
from decimal import Decimal
from typing import Any

import httpx  # 0.x -- required by respx for response objects
import httpx2  # 2.x -- the client under test, and the exception types
import pytest
import structlog
from pydantic import SecretStr
from respx import Router

from app.config import Settings
from app.integrations.hevy.client import HevyClient, build_hevy_client
from app.integrations.hevy.errors import (
    HevyAuthError,
    HevyClientError,
    HevyResponseError,
    HevyServerError,
)
from app.logging import configure_logging
from tests.conftest import hevy_fixture

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"
EVENTS = f"{BASE}/v1/workouts/events"
TEMPLATES = f"{BASE}/v1/exercise_templates"
MEASUREMENTS = f"{BASE}/v1/body_measurements"

# Distinctive on purpose: `test_key_never_appears_in_an_exception` asserts this exact string
# is absent from every rendered error, so a future refactor that starts interpolating the
# credential fails loudly instead of shipping.
HEVY_KEY = "hevy-key-9f3a-must-not-be-logged"

DB_URL = "postgresql://u:pw@localhost:5432/db"


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff to nothing. See this module's docstring."""


def _client(**kwargs: Any) -> HevyClient:
    """The real client, real retry policy, no real waiting."""
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)


def _ok(name: str = "workouts_page1") -> httpx.Response:
    return httpx.Response(200, json=hevy_fixture(name))


def test_page_size_constants_match_the_live_caps() -> None:
    """Pitfall 6: three endpoints cap at 10 and one caps at 100.

    A single module-level `PAGE_SIZE = 10` would make template sync issue ~40 requests
    instead of ~5, against a rate limit nobody has ever seen documented. The values are
    asserted individually rather than as a set so that a swap between two of them fails.
    """
    assert HevyClient.PAGE_SIZE_WORKOUTS == 10
    assert HevyClient.PAGE_SIZE_EVENTS == 10
    assert HevyClient.PAGE_SIZE_BODY_MEASUREMENTS == 10
    assert HevyClient.PAGE_SIZE_EXERCISE_TEMPLATES == 100


async def test_workouts_request_sends_key_header_and_page_size(httpx2_mock: Router) -> None:
    """The credential travels as Hevy's literal `api-key` header, not `Authorization`.

    Asserted on the RECORDED REQUEST rather than on the client's internals: a header dict
    that is built correctly but never attached would pass an introspection test and fail
    every real call.
    """
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[_ok()])

    async with _client() as client:
        page = await client.get_workouts(page=1)

    assert page.page == 1
    request = route.calls.last.request
    assert request.headers["api-key"] == HEVY_KEY
    assert dict(request.url.params) == {"page": "1", "pageSize": "10"}


async def test_templates_request_uses_page_size_100(httpx2_mock: Router) -> None:
    """Pitfall 6 again, from the request side: the one endpoint that is not 10."""
    route = httpx2_mock.get(TEMPLATES).mock(
        side_effect=[httpx.Response(200, json=hevy_fixture("exercise_templates_page1"))]
    )

    async with _client() as client:
        page = await client.get_exercise_templates(page=1)

    assert len(page.exercise_templates) == 4
    assert dict(route.calls.last.request.url.params) == {"page": "1", "pageSize": "100"}


async def test_events_request_serialises_since_as_utc_z(httpx2_mock: Router) -> None:
    """The cursor is sent in the format Hevy's `since` parameter documents.

    A `datetime.isoformat()` would emit `+00:00`, and a non-UTC input would be sent in its
    own offset -- either of which makes the incremental window mean something other than
    what the checkpoint recorded.
    """
    route = httpx2_mock.get(EVENTS).mock(
        side_effect=[httpx.Response(200, json=hevy_fixture("workout_events_page1"))]
    )
    # Deliberately NOT UTC: a client that skipped `astimezone` would send `07:00+07:00` and
    # silently re-window seven hours of events.
    jakarta = dt.timezone(dt.timedelta(hours=7))
    since = dt.datetime(2026, 8, 1, 7, 0, tzinfo=jakarta)

    async with _client() as client:
        await client.get_workout_events(since=since, page=1)

    params = dict(route.calls.last.request.url.params)
    assert params == {"page": "1", "pageSize": "10", "since": "2026-08-01T00:00:00Z"}


async def test_events_request_rejects_naive_since(httpx2_mock: Router) -> None:
    """FOUND-04: a naive datetime has no defined instant, so it cannot be a cursor.

    Rejected BEFORE any request is issued, and that half of the claim is asserted twice
    over. No route is registered at all, so respx's `assert_all_mocked` would raise on any
    request the client managed to send; `httpx2_mock.calls` then states the same property
    positively. Sending a naive value would silently reinterpret the checkpoint in whatever
    offset the process happens to run in.
    """
    async with _client() as client:
        with pytest.raises(ValueError, match="naive datetime"):
            await client.get_workout_events(since=dt.datetime(2026, 8, 1, 0, 0), page=1)  # noqa: DTZ001

    assert not httpx2_mock.calls, "the guard must fire before the transport, not after it"


async def test_rate_limit_is_retried_then_succeeds(httpx2_mock: Router) -> None:
    """429 is transient by definition: the next attempt is the whole point of a rate limit."""
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx.Response(429), _ok()])

    async with _client() as client:
        page = await client.get_workouts(page=1)

    assert page.workouts[0].title == "Push Day 💪"
    assert route.call_count == 2


async def test_server_error_is_retried_then_succeeds(httpx2_mock: Router) -> None:
    """5xx is Hevy's problem, not the request's -- the identical request may well work."""
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx.Response(500), _ok()])

    async with _client() as client:
        page = await client.get_workouts(page=1)

    assert page.page == 1
    assert route.call_count == 2


async def test_transport_error_is_retried_then_succeeds(httpx2_mock: Router) -> None:
    """A dropped connection never produced a status, so the status map cannot classify it.

    `httpx2.TransportError` is in `RETRYABLE_EXCEPTIONS` for exactly this case. Note the
    Pitfall-3 split in one line: the EXCEPTION is an httpx2 type, the RESPONSE is httpx 0.x.
    """
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx2.ConnectError("drop"), _ok()])

    async with _client() as client:
        page = await client.get_workouts(page=1)

    assert page.page == 1
    assert route.call_count == 2


async def test_auth_error_is_not_retried(httpx2_mock: Router) -> None:
    """Pitfall 7, the headline case: a 401 consumes exactly one call.

    The second queued response is a 200 that must never be reached. If the predicate ever
    widened to "retry any non-2xx", this test would return a page instead of raising -- and
    a revoked API key would surface as a minute-long timeout instead of an auth error.
    """
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx.Response(401), _ok()])

    async with _client() as client:
        with pytest.raises(HevyAuthError):
            await client.get_workouts(page=1)

    assert route.call_count == 1


async def test_bad_request_is_not_retried(httpx2_mock: Router) -> None:
    """A 400 means the request itself is wrong; repeating it verbatim cannot fix that."""
    route = httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx.Response(400), _ok()])

    async with _client() as client:
        with pytest.raises(HevyClientError):
            await client.get_workouts(page=1)

    assert route.call_count == 1


async def test_retry_exhaustion_reraises_the_real_error(httpx2_mock: Router) -> None:
    """`reraise=True`: the caller sees WHAT failed, not that something failed.

    `tenacity.RetryError` would tell the sync service only "gave up", when the decision it
    has to make -- checkpoint or roll back -- depends on whether Hevy was down (retry the run
    later) or the key was rejected (a human has to act).
    """
    route = httpx2_mock.get(WORKOUTS).mock(
        side_effect=[httpx.Response(500), httpx.Response(500), _ok()]
    )

    async with _client(max_attempts=2) as client:
        with pytest.raises(HevyServerError):
            await client.get_workouts(page=1)

    assert route.call_count == 2


async def test_body_measurements_404_returns_none(httpx2_mock: Router) -> None:
    """Pitfall 5: on THIS endpoint a 404 means "past the last page", not "broken".

    `call_count == 1` is the second half of the claim. Treating the terminator as retryable
    would spend the entire backoff budget at the end of every single body-measurement sync.
    """
    route = httpx2_mock.get(MEASUREMENTS).mock(side_effect=[httpx.Response(404)])

    async with _client() as client:
        assert await client.get_body_measurements(page=9) is None

    assert route.call_count == 1


async def test_body_measurements_page_parses(httpx2_mock: Router) -> None:
    """A row where only `weight_kg` was entered is normal, not malformed.

    Hevy emits one row per DATE with every unentered metric null, so the model has to
    tolerate a row that is 16/17 empty -- and the parse has to keep the value exact.
    """
    httpx2_mock.get(MEASUREMENTS).mock(
        side_effect=[httpx.Response(200, json=hevy_fixture("body_measurements_page1"))]
    )

    async with _client() as client:
        page = await client.get_body_measurements(page=1)

    assert page is not None
    assert len(page.body_measurements) == 2
    sparse = page.body_measurements[1]
    assert sparse.weight_kg == Decimal("80.1")
    assert all(
        getattr(sparse, field) is None
        for field in type(sparse).model_fields
        if field not in ("date", "weight_kg")
    )


async def test_workout_count_returns_an_int(httpx2_mock: Router) -> None:
    """The envelope is unwrapped at the boundary: callers get a number, not a model."""
    count = httpx.Response(200, json={"workout_count": 42})
    httpx2_mock.get(WORKOUT_COUNT).mock(side_effect=[count])

    async with _client() as client:
        assert await client.get_workout_count() == 42


async def test_single_workout_is_fetched_by_a_percent_encoded_id(httpx2_mock: Router) -> None:
    """The sixth endpoint, and the one place an upstream value reaches the request PATH.

    `/v1/workouts/{workoutId}` returns a bare `Workout` with no envelope. The id comes from
    a Hevy payload, not from this codebase, so it is percent-encoded: an id containing `/`
    or `..` would otherwise rewrite the path this client asks for. Both properties are
    asserted in one test because the encoding only matters on this method.
    """
    workout = hevy_fixture("workouts_page1")["workouts"][0]
    route = httpx2_mock.get(url__regex=rf"{WORKOUTS}/.+").mock(
        side_effect=[httpx.Response(200, json=workout), httpx.Response(200, json=workout)]
    )

    async with _client() as client:
        fetched = await client.get_workout("11111111-1111-1111-1111-111111111111")
        await client.get_workout("../../evil id")

    assert fetched.id == "11111111-1111-1111-1111-111111111111"
    assert fetched.exercises[0].sets[1].rpe == Decimal("9.5")
    assert str(route.calls[0].request.url) == f"{WORKOUTS}/11111111-1111-1111-1111-111111111111"
    assert str(route.calls[1].request.url) == f"{WORKOUTS}/..%2F..%2Fevil%20id", (
        "an id from an upstream payload escaped into the request path unencoded"
    )


async def test_malformed_response_raises_hevy_response_error_without_the_payload(
    httpx2_mock: Router,
) -> None:
    """T-03-18: the schema failure is reported; the data that failed is not.

    `ValidationError.__str__` renders `input_value=...`. On this endpoint that is workout
    titles; on `/v1/body_measurements` it is body-composition numbers. Raising
    `HevyResponseError(...) from None` is what stops either from riding along in a traceback
    that reaches a log line.
    """
    httpx2_mock.get(WORKOUTS).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "page": 1,
                    "page_count": 1,
                    "workouts": [{"id": 1, "title": "secret-title-9f3a"}],
                },
            )
        ]
    )

    async with _client() as client:
        with pytest.raises(HevyResponseError) as excinfo:
            await client.get_workouts(page=1)

    rendered = str(excinfo.value) + repr(excinfo.value) + excinfo.value.safe_message
    assert "secret-title-9f3a" not in rendered, (
        "T-03-18 violated: the rejected payload was reproduced into the raised error"
    )
    assert "/v1/workouts" in excinfo.value.safe_message


async def test_key_never_appears_in_an_exception(httpx2_mock: Router) -> None:
    """T-03-16: the one place the credential is unwrapped is the header dict.

    Every rendering an operator or a log processor could reach is checked -- `str`, `repr`
    and the opt-in `safe_message` -- because an exception that carried the key would put it
    somewhere the structlog deny-list cannot help.
    """
    httpx2_mock.get(WORKOUTS).mock(side_effect=[httpx.Response(401)])

    async with _client() as client:
        with pytest.raises(HevyAuthError) as excinfo:
            await client.get_workouts(page=1)

    for rendered in (str(excinfo.value), repr(excinfo.value), excinfo.value.safe_message):
        assert HEVY_KEY not in rendered, (
            "T-03-16 violated: the rejected API key leaked into a Hevy exception"
        )


async def test_rate_limit_headers_are_logged(
    httpx2_mock: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-10: Hevy documents no rate limit, so the live headers are the only evidence.

    Asserted against the RENDERED log stream, not `structlog.testing`: that helper clears the
    configured processor chain for its duration, so the redaction layers would not run and a
    leak could not be observed (test_secret_redaction.py's Pitfall 6).
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("HEVY_API_KEY", HEVY_KEY)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging(Settings(_env_file=None))
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)

        httpx2_mock.get(WORKOUTS).mock(
            side_effect=[
                httpx.Response(429, headers={"retry-after": "3", "ratelimit-remaining": "0"}),
                _ok(),
            ]
        )
        async with _client() as client:
            await client.get_workouts(page=1)

        out = buffer.getvalue()
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()

    assert "hevy_rate_limit_headers" in out
    assert "retry-after" in out
    assert "ratelimit-remaining" in out
    assert HEVY_KEY not in out, "FOUND-05 violated: the api-key reached the log stream"


def test_build_hevy_client_requires_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail at construction, and name the ENV VAR the operator has to fix.

    Both the unset and the empty-string case must fail: an empty key would otherwise build a
    client that sends `api-key: ` and 401s twenty pages into a full sync. Mirrors
    `build_token_verifier`, which raises on `MCP_AUTH_SECRET` for the same reason.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.delenv("HEVY_API_KEY", raising=False)

    unset = Settings(_env_file=None)
    assert unset.hevy_api_key is None
    with pytest.raises(RuntimeError, match="HEVY_API_KEY"):
        build_hevy_client(unset)

    monkeypatch.setenv("HEVY_API_KEY", "")
    with pytest.raises(RuntimeError, match="HEVY_API_KEY"):
        build_hevy_client(Settings(_env_file=None))

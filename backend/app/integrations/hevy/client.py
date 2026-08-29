"""Hevy HTTP transport (HEVY-01, HEVY-05, HEVY-08).

Transport concerns ONLY. This class never touches the database, never decides what to keep,
and never advances a checkpoint -- all of that is `sync.py`'s job. Keeping the split sharp is
what lets the sync logic be tested without a network and the transport be tested without a
database.

Two facts drive the design and neither is in the blueprint:

* Page sizes differ PER ENDPOINT. `/v1/workouts`, `/v1/workouts/events` and
  `/v1/body_measurements` cap at 10; `/v1/exercise_templates` caps at **100**. A single
  module-level PAGE_SIZE = 10 would make template sync issue ~40 requests instead of ~5,
  against a rate limit nobody has ever seen documented (Pitfall 6).
* Hevy documents NO rate limit, no 429, and no 401 on any GET endpoint -- verified by an
  exhaustive keyword scan of the live spec. All three happen anyway. Every response header
  matching `ratelimit` or `retry-after` is logged, because the first real sync is the only
  chance this project will get to learn what the actual limits are (D-10).
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

import anyio
import httpx2
import structlog
from pydantic import SecretStr, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import Settings
from app.integrations.hevy.errors import (
    RETRYABLE_EXCEPTIONS,
    HevyAuthError,
    HevyClientError,
    HevyPageNotFound,
    HevyRateLimited,
    HevyResponseError,
    HevyServerError,
)
from app.integrations.hevy.schemas import (
    PaginatedBodyMeasurements,
    PaginatedExerciseTemplates,
    PaginatedWorkoutEvents,
    PaginatedWorkouts,
    WorkoutCount,
)

log = structlog.get_logger()

# Hevy's `since` parameter is a Z-suffixed UTC instant. `datetime.isoformat()` would emit
# `+00:00`, which is the same moment but not the same string, and this value is a cursor.
_SINCE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class HevyClient:
    BASE_URL = "https://api.hevyapp.com"

    # Verified against the live OpenAPI, 2026-08-29. NOT interchangeable.
    PAGE_SIZE_WORKOUTS = 10
    PAGE_SIZE_EVENTS = 10
    PAGE_SIZE_BODY_MEASUREMENTS = 10
    PAGE_SIZE_EXERCISE_TEMPLATES = 100

    def __init__(
        self,
        api_key: SecretStr,
        *,
        max_attempts: int = 5,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        # The credential is unwrapped ONCE here and stored only inside the client's own
        # header dict -- never on self, never in a log field, never in an exception. Mirrors
        # StaticTokenVerifier / AuthKitJWTVerifier.
        self._max_attempts = max_attempts
        # Two injection seams, both for tests and both narrow. `transport` swaps the socket;
        # `sleep` swaps the pause BETWEEN attempts, leaving the retry predicate and the
        # attempt count -- the parts worth testing -- entirely real. `anyio.sleep` rather
        # than `asyncio.sleep` so this works unchanged under whichever event loop the MCP
        # SDK's anyio stack happens to be running.
        self._sleep = sleep
        self._client = httpx2.AsyncClient(
            base_url=self.BASE_URL,
            headers={"api-key": api_key.get_secret_value()},
            # Explicit and non-negotiable: an unbounded read turns one hung Hevy request
            # into a sync run that never ends and a checkpoint that never advances.
            timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        """Release the connection pool. The owner of the client owns its lifetime."""
        await self._client.aclose()

    async def __aenter__(self) -> "HevyClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --- request path --------------------------------------------------------

    async def _request(self, path: str, **params: str | int) -> dict[str, Any]:
        """One HTTP GET with the status->exception mapping applied. No retry here.

        Order matters: 404 is checked before the generic 4xx branch because
        `/v1/body_measurements` uses it as an end-of-pages terminator (Pitfall 5), and 429
        before 4xx because it is the one 4xx that IS transient.
        """
        response = await self._client.get(path, params=params)
        self._log_rate_limit_headers(path, response)
        status = response.status_code
        if status == 429:
            raise HevyRateLimited(retry_after=response.headers.get("retry-after"))
        if status in (401, 403):
            raise HevyAuthError(status)
        if status == 404:
            raise HevyPageNotFound(status)
        if status >= 500:
            raise HevyServerError(status)
        if status >= 400:
            raise HevyClientError(status)
        payload: dict[str, Any] = response.json()
        return payload

    @staticmethod
    def _log_rate_limit_headers(path: str, response: httpx2.Response) -> None:
        """D-10 / STATE.md open item: Hevy's real limits are undocumented, and the ONLY way
        to learn them is to record what the live API actually returns. Header NAMES and
        values only -- the request headers (which carry the key) are never touched."""
        observed = {
            key.lower(): value
            for key, value in response.headers.items()
            if "ratelimit" in key.lower() or key.lower() == "retry-after"
        }
        if observed:
            log.info("hevy_rate_limit_headers", path=path, **observed)

    async def _get(self, path: str, **params: str | int) -> dict[str, Any]:
        """`_request` wrapped in tenacity.

        `str | int` rather than `object`: httpx2's `params=` is typed, and an untyped
        passthrough would let a `datetime` or a `Decimal` reach the query string as its
        `repr` -- which is precisely the bug `get_workout_events` formats `since` to avoid.
        """
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            stop=stop_after_attempt(self._max_attempts),
            # Jitter matters: without it, a Hevy outage plus a fixed backoff produces a
            # synchronised retry storm from every client at once.
            wait=wait_exponential_jitter(initial=1, max=60, jitter=2),
            # reraise=True surfaces HevyServerError, not tenacity.RetryError -- the caller
            # needs to know WHAT failed to decide whether to checkpoint.
            reraise=True,
            sleep=self._sleep,
        ):
            with attempt:
                return await self._request(path, **params)
        raise AssertionError("unreachable: AsyncRetrying always returns or raises")

    # --- endpoints -----------------------------------------------------------

    async def get_workouts(self, *, page: int) -> PaginatedWorkouts:
        """`GET /v1/workouts` -- the full-sync page reader."""
        payload = await self._get("/v1/workouts", page=page, pageSize=self.PAGE_SIZE_WORKOUTS)
        try:
            return PaginatedWorkouts.model_validate(payload)
        except ValidationError:
            # `from None` so the ValidationError -- whose `__str__` renders `input_value=`,
            # i.e. the user's workout titles -- cannot ride along in a traceback that
            # reaches a log line (T-03-18).
            raise HevyResponseError("/v1/workouts") from None

    async def get_workout_count(self) -> int:
        """`GET /v1/workouts/count` -- unwrapped at the boundary, so callers get a number."""
        payload = await self._get("/v1/workouts/count")
        try:
            return WorkoutCount.model_validate(payload).workout_count
        except ValidationError:
            raise HevyResponseError("/v1/workouts/count") from None

    async def get_workout_events(self, *, since: dt.datetime, page: int) -> PaginatedWorkoutEvents:
        """`GET /v1/workouts/events` -- the incremental cursor read.

        `since` must be timezone-aware (FOUND-04, and Ruff DTZ forbids naive arithmetic
        anyway): a naive value has no defined instant, so sending it would silently
        reinterpret the checkpoint in whatever offset the process happens to run in.
        """
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("naive datetime rejected: `since` must be timezone-aware UTC")
        payload = await self._get(
            "/v1/workouts/events",
            page=page,
            pageSize=self.PAGE_SIZE_EVENTS,
            since=since.astimezone(dt.UTC).strftime(_SINCE_FORMAT),
        )
        try:
            return PaginatedWorkoutEvents.model_validate(payload)
        except ValidationError:
            raise HevyResponseError("/v1/workouts/events") from None

    async def get_exercise_templates(self, *, page: int) -> PaginatedExerciseTemplates:
        """`GET /v1/exercise_templates` -- the ONE endpoint whose page size is 100."""
        payload = await self._get(
            "/v1/exercise_templates", page=page, pageSize=self.PAGE_SIZE_EXERCISE_TEMPLATES
        )
        try:
            return PaginatedExerciseTemplates.model_validate(payload)
        except ValidationError:
            raise HevyResponseError("/v1/exercise_templates") from None

    async def get_body_measurements(self, *, page: int) -> PaginatedBodyMeasurements | None:
        """`GET /v1/body_measurements` -- returns ``None`` once the pages run out."""
        try:
            payload = await self._get(
                "/v1/body_measurements",
                page=page,
                pageSize=self.PAGE_SIZE_BODY_MEASUREMENTS,
            )
        except HevyPageNotFound:
            # Pitfall 5: unlike /v1/workouts (which 400s on a bad page), this endpoint
            # documents 404 "Page not found". It means "you paged past the end", so it is a
            # terminator, not a failure -- treating it as fatal would mark a run failed
            # after it had already fetched everything.
            return None
        try:
            return PaginatedBodyMeasurements.model_validate(payload)
        except ValidationError:
            raise HevyResponseError("/v1/body_measurements") from None


def build_hevy_client(settings: Settings) -> HevyClient:
    """Fail fast at construction, not at the first request.

    A sync process that starts without a usable key is a process that logs a confusing
    401 twenty pages in. Names the ENV VAR, not the settings field, because the env var is
    what the operator has to fix.

    Deliberately a factory and NOT a module-level singleton: `app/db/session.py` documents
    why -- an object built at import time binds itself to whichever event loop imported it.
    """
    key = settings.hevy_api_key
    if key is None or not key.get_secret_value():
        raise RuntimeError("HEVY_API_KEY is required to run a Hevy sync")
    return HevyClient(key)

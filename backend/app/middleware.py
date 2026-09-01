"""Request rate limiting for the whole ASGI app (ROADMAP Phase 7 criterion #2).

Registered with ``app.add_middleware`` in ``app/main.py``, which Starlette applies
OUTSIDE the router -- so this runs before ``app.mount("/", mcp_app)`` resolves and
therefore before the MCP SDK's own ``RequireAuthMiddleware``. That is the strong
reading of "rate limiting applied ahead of handler work": an UNAUTHENTICATED flood
is bounded too, which a limiter living inside the MCP tool layer could not do.

Pure ASGI: this class implements ``__call__(scope, receive, send)`` itself and
never subclasses Starlette's response-materialising middleware base (the
``BaseHTTP...`` one, whose full name this module deliberately does not spell --
see the last paragraph). ``/mcp`` answers ``text/event-stream``
(``app/mcp/server.py`` builds the app with ``json_response`` at its ``False``
default) and that base class buffers the whole response body, which breaks
streaming intermittently and only under real HTTP.

The bucket is per PROCESS. ``scripts/deploy-cloud-run.sh`` deploys with
``--max="${BRETT_MAX_INSTANCES:-2}"``, so the service-wide ceiling is up to 2x the
configured numbers. That multiplier is accepted deliberately: adding Redis to make
one single-user connector's limit exact would double the failure surface and the
bill of the thing meant to protect against cost.

NO client-supplied header is read, parsed or logged. The service is
``--allow-unauthenticated``, so the forwarded-client-address header is entirely
attacker-controlled and a per-IP key would be both forgeable and near-global
anyway -- all legitimate traffic originates from Anthropic's ``160.79.104.0/21``
egress. One global bucket is the enforceable control, and reading no headers means
there is no untrusted input path in this module at all (T-07-01, ASVS V5).

``test_the_limiter_reads_no_client_supplied_header`` enforces that last paragraph
by asserting that neither the forwarded-address header's name nor the
response-materialising base class's name appears anywhere in this file --
docstring and comments included. The check is deliberately crude, because a check
that skipped prose could be satisfied by a comment asserting compliance while the
code did the opposite. That is the only reason the two names are described above
rather than written out.
"""

import time
from collections.abc import Callable

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings

log = structlog.get_logger()

# Never limited.
#   /health          -- Cloud Run's startup and liveness probe target. A 429 here
#                       marks the revision unhealthy for a reason nothing in
#                       health.py explains.
#   /.well-known/    -- the RFC 9728 metadata document Claude fetches ANONYMOUSLY
#                       during connector discovery, inside a documented 10-second
#                       budget. Throttling it surfaces as "Couldn't reach the MCP
#                       server" with no further detail.
EXEMPT_PREFIXES: tuple[str, ...] = ("/health", "/.well-known/")

# The exact key set of the 429 body. One key, asserted by test: this endpoint can
# be made to emit this body by anyone on the internet, so it must never grow a
# field that echoes the presented credential or an exception detail (T-07-02).
_RATE_LIMITED_BODY = b'{"error":"rate_limited"}'


class TokenBucket:
    """Fixed-capacity bucket refilled at a constant rate.

    ``clock`` is injected because ``time_machine.travel()`` does NOT patch
    ``time.monotonic()`` (verified 2026-09-01), and ``time.monotonic`` is the only
    correct source here -- an NTP step or a wall-clock jump must not top the bucket
    up. Injection mirrors ``HevyClient(sleep=...)``, the project's established seam
    for a time-dependent component.
    """

    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        self._capacity = capacity
        self._refill = refill_per_second
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def take(self) -> float | None:
        """Return ``None`` when the request is allowed, else seconds to wait."""
        now = self._clock()
        self._tokens = min(float(self._capacity), self._tokens + (now - self._last) * self._refill)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return None
        return (1.0 - self._tokens) / self._refill


class RateLimitMiddleware:
    """Reject over-limit HTTP requests with a minimal 429 before routing."""

    def __init__(self, app: ASGIApp, *, bucket: TokenBucket) -> None:
        self.app = app
        self._default_bucket = bucket

    def _bucket(self, scope: Scope) -> TokenBucket:
        # `app/main.py` also publishes the bucket at `app.state.rate_limit_bucket`
        # so there is exactly one live bucket object and a test can replace it
        # without rebuilding the middleware stack. Falls back to the constructor
        # argument if `scope["app"]` is absent, so the middleware still works
        # mounted under a bare Starlette router.
        state = getattr(scope.get("app"), "state", None)
        bucket = getattr(state, "rate_limit_bucket", None)
        return bucket if isinstance(bucket, TokenBucket) else self._default_bucket

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path.startswith(EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        wait = self._bucket(scope).take()
        if wait is None:
            await self.app(scope, receive, send)
            return

        retry_after = max(1, int(wait) + 1)
        # The path and the wait, and nothing else. Never a header value, never the
        # credential, never a client address (blueprint 44, FOUND-05).
        log.info("rate_limit_rejected", path=path, retry_after=retry_after)
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode("ascii")),
                    (b"content-length", str(len(_RATE_LIMITED_BODY)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _RATE_LIMITED_BODY})


def build_limiter(settings: Settings) -> TokenBucket:
    """Build the process-wide bucket from configuration.

    There is no development bypass. A limiter that is off in development is a
    limiter nobody has ever seen fire.
    """
    return TokenBucket(
        capacity=settings.rate_limit_burst,
        refill_per_second=settings.rate_limit_per_minute / 60.0,
    )

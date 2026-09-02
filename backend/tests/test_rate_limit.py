"""Rate limiter tests (ROADMAP Phase 7 criterion #2, DEPLOY-03).

Split deliberately, the same way `test_mcp_auth.py` splits the token verifier:

* **here (fast, no marker)** -- the bucket's arithmetic under an injected clock,
  and a static read of the module that proves it touches no client-supplied
  header.
* **over HTTP (marked `integration`, appended by plan 07-05)** -- the wire
  contract: the 429 status, its exact key set, its `Retry-After`, the two path
  exemptions, and that the limiter fires BEFORE auth.

The clock is injected rather than frozen with `time-machine`: `time_machine.travel()`
does not patch `time.monotonic()`, and `time.monotonic` is what a correct bucket
uses. A test that waited for a real refill would have to sleep; nothing here
sleeps, by any means, and nothing here ever should -- the fast suite is run on
every commit and a limiter test that waits out its own refill window is the kind
of thing that gets a whole suite skipped.

The no-sleeping rule is grep-enforced by both plans in this pair, which is why
the sleeping call is never spelled out literally anywhere in this module --
describe it, do not write it. (Plan 07-01 kept the marker name itself unspelled
too, while this file held only the fast half; the half plan 07-05 appended below
carries that marker on every test, so that second constraint is spent.)
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from app.config import Settings
from app.middleware import (
    EXEMPT_PREFIXES,
    INGEST_PATH_PREFIX,
    RateLimitMiddleware,
    TokenBucket,
    build_ingest_limiter,
    build_limiter,
)

DB_URL = "postgresql://u:pw@localhost:5432/brett"

MIDDLEWARE_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "middleware.py").read_text()


class _FakeClock:
    """A hand-advanced monotonic clock. `time-machine` cannot drive `time.monotonic`."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build ``Settings`` from the environment, exactly as the app does at boot.

    Env vars rather than constructor kwargs, and ``_env_file=None``, both mirror
    ``test_mcp_auth.py``: the deployed service is configured by
    ``deploy/cloud-run.env.yaml``, so the env path is the one worth testing, and a
    developer's real ``.env`` must never decide the outcome.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_a_fresh_bucket_allows_exactly_capacity_takes() -> None:
    """DEPLOY-03: a frozen clock never refills, so capacity is the whole budget.

    If this fails the bucket is either handing out more than its capacity (no
    limit exists) or fewer (the connector 429s on its first coaching turn).
    """
    bucket = TokenBucket(capacity=2, refill_per_second=0.5, clock=_FakeClock())

    allowed = [bucket.take(), bucket.take()]
    denied = bucket.take()

    assert allowed == [None, None], (
        f"DEPLOY-03 violated: a bucket with capacity=2 refused one of its first two takes on a "
        f"frozen clock. Every rejection here is a 429 in the middle of a coaching turn, which "
        f"is worse than an unthrottled minute for a single-user connector. Got: {allowed}"
    )
    assert isinstance(denied, float), (
        f"DEPLOY-03 violated: the third take against a capacity=2 bucket was allowed, so the "
        f"bucket enforces no ceiling at all and the rate limit is decorative. Expected a float "
        f"wait in seconds. Got: {denied!r}"
    )


def test_refill_restores_one_token_after_the_configured_interval() -> None:
    """DEPLOY-03: refill is a rate, not a reset -- one token per 1/refill seconds.

    A bucket that refilled to full on any elapsed time would let a caller take
    `capacity` requests every tick forever, which is a limiter in name only.
    """
    clock = _FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=0.5, clock=clock)
    bucket.take()
    bucket.take()

    clock.advance(1.0 / 0.5)
    first_after_wait = bucket.take()
    second_after_wait = bucket.take()

    assert first_after_wait is None, (
        f"DEPLOY-03 violated: after waiting exactly 1/refill_per_second seconds the drained "
        f"bucket still refused a take, so a caller who honours Retry-After is rejected again "
        f"and backs off forever. Got: {first_after_wait!r}"
    )
    assert isinstance(second_after_wait, float), (
        f"DEPLOY-03 violated: one refill interval yielded MORE than one token, so the bucket "
        f"tops itself up faster than configured and the effective rate exceeds "
        f"RATE_LIMIT_PER_MINUTE. Got: {second_after_wait!r}"
    )


def test_refill_never_exceeds_capacity() -> None:
    """DEPLOY-03: an idle hour must not bank an hour's worth of requests.

    Without the `min(capacity, ...)` clamp the bucket accumulates tokens while
    nothing is happening, and the burst available after a quiet night is
    unbounded -- exactly the cost spike the limiter exists to prevent.
    """
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, refill_per_second=1.0, clock=clock)

    clock.advance(3_600.0)
    allowed = [bucket.take() for _ in range(3)]
    denied = bucket.take()

    assert allowed == [None, None, None], (
        f"DEPLOY-03 violated: a bucket idle for an hour could not serve its own capacity of 3. "
        f"Got: {allowed}"
    )
    assert isinstance(denied, float), (
        f"DEPLOY-03 violated: after an idle hour the bucket allowed more than capacity=3 takes, "
        f"so accumulated tokens are not clamped and an idle service banks an unbounded burst. "
        f"Got: {denied!r}"
    )


def test_wait_seconds_are_reported_for_retry_after() -> None:
    """DEPLOY-03: the returned wait is what becomes the `Retry-After` header.

    A wrong number here is not a failed request, it is a client that retries too
    early (and is rejected again) or too late (and stalls the coaching turn).
    """
    bucket = TokenBucket(capacity=1, refill_per_second=0.5, clock=_FakeClock())
    bucket.take()

    wait = bucket.take()

    assert wait == pytest.approx(2.0), (
        f"DEPLOY-03 violated: a drained bucket refilling at 0.5 tokens/second needs 2.0 seconds "
        f"to earn one token, but the bucket reported a different wait. `Retry-After` is derived "
        f"from this value, so a client honouring it would retry at the wrong time. Got: {wait!r}"
    )


def test_build_limiter_maps_settings_to_bucket_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEPLOY-03: the factory must map per-MINUTE config onto a per-SECOND bucket.

    The two settings are given deliberately different values (60 and 30) so a
    swapped mapping -- capacity from the rate, refill from the burst -- fails here
    instead of shipping a limiter whose numbers mean nothing like what the env
    file says.
    """
    settings = _settings(monkeypatch, RATE_LIMIT_PER_MINUTE="60", RATE_LIMIT_BURST="30")

    bucket = build_limiter(settings)

    # The private reads are the point of the test: these two numbers ARE the
    # factory's entire responsibility, and a purely behavioural check would pass
    # for a bucket built from the wrong field pair whenever the values coincided.
    assert bucket._refill == pytest.approx(1.0), (
        f"DEPLOY-03 violated: RATE_LIMIT_PER_MINUTE=60 must become 1.0 tokens/second, but "
        f"build_limiter produced a different refill rate -- the deployed limit would differ "
        f"from deploy/cloud-run.env.yaml by a factor of 60. Got: {bucket._refill!r}"
    )
    assert bucket._capacity == 30, (
        f"DEPLOY-03 violated: RATE_LIMIT_BURST=30 must become the bucket capacity, but "
        f"build_limiter produced a different one, so the burst allowance is not the configured "
        f"one. Got: {bucket._capacity!r}"
    )

    allowed = [bucket.take() for _ in range(30)]
    assert allowed == [None] * 30, (
        f"DEPLOY-03 violated: the bucket built from RATE_LIMIT_BURST=30 refused one of its "
        f"first 30 takes, so the configured burst is not actually available. Got "
        f"{allowed.count(None)} allowed of 30"
    )


def test_the_limiter_reads_no_client_supplied_header() -> None:
    """T-07-01/ASVS V5: there is no untrusted input path in the limiter at all.

    The service is deployed --allow-unauthenticated, so any internet client can
    set its own X-Forwarded-For and Cloud Run appends to it rather than replacing
    it. A per-IP key would therefore be forgeable, and near-global anyway since
    all legitimate traffic comes from one /21. The chosen mitigation is not
    "parse it carefully" but "never read it", which is only a mitigation while
    this assertion holds.
    """
    lowered = MIDDLEWARE_SOURCE.lower()
    for forbidden in ("x-forwarded-for", 'scope["headers"]', "basehttpmiddleware"):
        assert forbidden not in lowered, (
            f"T-07-01 violated: backend/app/middleware.py mentions {forbidden!r}. "
            f"The limiter is global by design precisely so it has no attacker-controlled "
            f"input; reading a client header reintroduces one (07-RESEARCH.md Pitfall 3)."
        )


def test_exempt_prefixes_cover_health_and_well_known() -> None:
    """T-07-04: the two paths a 429 must never reach, pinned as an exact tuple.

    `/health` is Cloud Run's probe target -- throttling it marks the revision
    unhealthy for a reason nothing in health.py explains. `/.well-known/` is the
    RFC 9728 metadata document Claude fetches anonymously inside a 10-second
    discovery budget, where a 429 surfaces only as "Couldn't reach the MCP
    server". Asserted as equality, not membership: a THIRD exemption added later
    would be an unthrottled hole nobody reviewed.
    """
    assert EXEMPT_PREFIXES == ("/health", "/.well-known/"), (
        f"T-07-04 violated: the exemption list changed. Removing an entry makes the limiter "
        f"able to fail the Cloud Run health probe or Claude's connector discovery; adding one "
        f"opens an unthrottled path. Got: {EXEMPT_PREFIXES!r}"
    )


# --- The ingest bucket (Phase 8, RESEARCH Pitfall 2) -------------------------
#
# Unit-level, against `RateLimitMiddleware._bucket` directly, and in the fast half.
# The route these paths name does not exist yet -- plan 08-07 builds it -- so an HTTP
# test could not be written here at all; and even once it can, bucket SELECTION is a
# pure function of the path and `app.state`, so driving it through the transport
# would only add ways for the test to fail for reasons that are not the one under test.

INGEST_PATH = f"{INGEST_PATH_PREFIX}health-auto-export"


async def _unreached_app(scope: Scope, receive: Receive, send: Send) -> None:
    """The downstream app. `_bucket` must never call it -- it only resolves an object."""
    raise AssertionError("_bucket must not dispatch downstream")


def _app_state(**buckets: TokenBucket) -> SimpleNamespace:
    """Stand in for the FastAPI app the middleware reaches through ``scope["app"]``.

    ``SimpleNamespace`` rather than a real ``FastAPI``: the middleware reads exactly
    two attributes off ``app.state`` and nothing else, and constructing the real app
    here would drag in its settings, its lifespan and its mounted MCP sub-app for a
    test about two ``getattr`` calls. Omitting a keyword leaves the attribute genuinely
    absent, which is the bare-router case below.
    """
    return SimpleNamespace(state=SimpleNamespace(**buckets))


def _http_scope(path: str, app: SimpleNamespace | None = None) -> Scope:
    scope: Scope = {"type": "http", "path": path}
    if app is not None:
        scope["app"] = app
    return scope


def _frozen(capacity: int) -> TokenBucket:
    """A bucket whose clock never moves, so nothing here can refill mid-assertion."""
    return TokenBucket(capacity=capacity, refill_per_second=0.5, clock=_FakeClock())


def test_ingest_path_uses_its_own_bucket() -> None:
    """RESEARCH Pitfall 2: the ingest prefix selects the ingest bucket, not the shared one.

    If this fails the second bucket exists but nothing routes to it, so every Health
    Auto Export delivery still spends tokens Claude's connector needs -- the exact
    coupling the second bucket was added to remove.
    """
    shared, ingest = _frozen(3), _frozen(3)
    middleware = RateLimitMiddleware(_unreached_app, bucket=_frozen(1))

    resolved = middleware._bucket(
        _http_scope(INGEST_PATH, _app_state(rate_limit_bucket=shared, ingest_rate_limit_bucket=ingest))
    )

    assert resolved is ingest, (
        f"HEALTH-07 violated: a request to {INGEST_PATH} resolved to a bucket that is not "
        f"app.state.ingest_rate_limit_bucket, so ingest traffic is still drawing from the "
        f"bucket /mcp shares. Resolved the shared bucket: {resolved is shared}"
    )


def test_draining_the_ingest_bucket_leaves_the_shared_bucket_full() -> None:
    """RESEARCH Pitfall 2, the defining assertion: a burst of exports cannot 429 Claude.

    Health Auto Export has no documented retry, so the pressure to exempt the ingest
    path is real -- and the answer is this separation instead. Drained THROUGH the
    middleware's own resolution rather than by taking from the object directly: taking
    from a bucket a test hand-picked would pass even if `_bucket` returned the shared
    one for every path in existence.
    """
    shared, ingest = _frozen(3), _frozen(3)
    app = _app_state(rate_limit_bucket=shared, ingest_rate_limit_bucket=ingest)
    middleware = RateLimitMiddleware(_unreached_app, bucket=_frozen(1))
    ingest_scope = _http_scope(INGEST_PATH, app)

    drained = [middleware._bucket(ingest_scope).take() for _ in range(3)]
    over_limit = middleware._bucket(ingest_scope).take()

    assert drained == [None, None, None], (
        f"the drain is broken: the ingest bucket refused one of its own capacity-3 takes, so "
        f"the assertion below would pass for the wrong reason. Got: {drained}"
    )
    assert isinstance(over_limit, float), (
        f"HEALTH-07 violated: the ingest path is not throttled at all -- a fourth take against "
        f"a capacity-3 bucket was allowed, which means `_bucket` handed out a fresh object each "
        f"time or the path is exempt. Got: {over_limit!r}"
    )
    mcp_take = middleware._bucket(_http_scope("/mcp", app)).take()
    assert mcp_take is None, (
        f"RESEARCH Pitfall 2 violated: draining the ingest bucket also drained the bucket /mcp "
        f"uses, so a burst of phone exports 429s Claude's next tool call in the middle of a "
        f"coaching turn. The two buckets are the same object or the prefix check is inverted. "
        f"Got: {mcp_take!r}"
    )


def test_mcp_path_never_uses_the_ingest_bucket() -> None:
    """The other direction: the ingest carve-out must not widen to everything else.

    A prefix check written against the wrong string -- or against `in` instead of
    `startswith` -- would quietly move ALL traffic onto the ingest bucket, and every
    assertion about the ingest side would still pass.
    """
    shared, ingest = _frozen(3), _frozen(3)
    app = _app_state(rate_limit_bucket=shared, ingest_rate_limit_bucket=ingest)
    middleware = RateLimitMiddleware(_unreached_app, bucket=_frozen(1))

    for path in ("/mcp", "/api/v1/sync", "/", "/api/v1/ingestion-report"):
        assert middleware._bucket(_http_scope(path, app)) is shared, (
            f"HEALTH-07 violated: {path!r} resolved to the INGEST bucket. Only paths under "
            f"{INGEST_PATH_PREFIX!r} may, or the ingest allowance silently becomes the "
            f"allowance for the whole service"
        )


def test_ingest_prefix_is_not_exempt() -> None:
    """T-08-12: the ingest path is rate-limited, never exempted.

    The temptation is documented and real -- a 429 to Health Auto Export is permanent
    data loss because it does not retry. But `/api/v1/ingest/` is an internet-reachable
    WRITE path on a service deployed --allow-unauthenticated, and adding it here would
    make it the one unbounded surface in the process: anyone on the internet could then
    drive unlimited request bodies into the JSON parser. The separate bucket is the
    answer; the exemption never is.
    """
    assert INGEST_PATH_PREFIX not in EXEMPT_PREFIXES, (
        f"T-08-12 violated: {INGEST_PATH_PREFIX!r} was added to EXEMPT_PREFIXES, making an "
        f"internet-reachable write path the only unthrottled surface on an "
        f"--allow-unauthenticated service. Got: {EXEMPT_PREFIXES!r}"
    )
    assert not INGEST_PATH_PREFIX.startswith(EXEMPT_PREFIXES), (
        f"T-08-12 violated: {INGEST_PATH_PREFIX!r} falls under an existing exemption in "
        f"{EXEMPT_PREFIXES!r}, so the ingest route would be unthrottled without anyone having "
        f"edited the exemption tuple at all"
    )
    assert not INGEST_PATH.startswith(EXEMPT_PREFIXES), (
        f"T-08-12 violated: the real ingest path {INGEST_PATH!r} is exempt from rate limiting"
    )


def test_ingest_bucket_falls_back_when_none_is_published() -> None:
    """The middleware must keep working mounted under a bare router, as it does today.

    `_bucket` resolves through `scope["app"]`, and neither that key nor either bucket
    attribute is guaranteed to exist -- Starlette sets `scope["app"]` only when the
    request travels through an application object. A `_bucket` that assumed the ingest
    attribute was there would raise AttributeError INSIDE the limiter, which is a 500
    on every ingest request from a middleware whose entire job is to answer 429.
    """
    shared, fallback = _frozen(3), _frozen(1)
    middleware = RateLimitMiddleware(_unreached_app, bucket=fallback)

    only_shared = middleware._bucket(_http_scope(INGEST_PATH, _app_state(rate_limit_bucket=shared)))
    no_app_at_all = middleware._bucket(_http_scope(INGEST_PATH))

    assert only_shared is shared, (
        "HEALTH-07 violated: with no ingest bucket published, the ingest path must fall back to "
        "the shared bucket -- an unresolvable bucket must never mean an unlimited one"
    )
    assert no_app_at_all is fallback, (
        "HEALTH-07 violated: with no `app` in the scope at all, `_bucket` must fall back to the "
        "constructor argument. Anything else is an AttributeError inside the limiter, i.e. a 500 "
        "from the component whose job is to answer 429"
    )


def test_build_ingest_limiter_maps_ingest_settings_to_bucket_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ingest factory must read the INGEST_* pair, not the shared one.

    All four numbers are given different values on purpose. A factory that read
    `rate_limit_burst` instead of `ingest_rate_limit_burst` is invisible against the
    shipped configuration, where both pairs are deliberately 30/30 -- it would only
    surface the day someone retuned one of them and the other silently moved too.
    """
    settings = _settings(
        monkeypatch,
        RATE_LIMIT_PER_MINUTE="600",
        RATE_LIMIT_BURST="99",
        INGEST_RATE_LIMIT_PER_MINUTE="60",
        INGEST_RATE_LIMIT_BURST="12",
    )

    bucket = build_ingest_limiter(settings)

    assert bucket._refill == pytest.approx(1.0), (
        f"HEALTH-07 violated: INGEST_RATE_LIMIT_PER_MINUTE=60 must become 1.0 tokens/second. A "
        f"refill of 10.0 means the factory read RATE_LIMIT_PER_MINUTE instead. Got: "
        f"{bucket._refill!r}"
    )
    assert bucket._capacity == 12, (
        f"HEALTH-07 violated: INGEST_RATE_LIMIT_BURST=12 must become the bucket capacity. A "
        f"capacity of 99 means the factory read RATE_LIMIT_BURST instead. Got: "
        f"{bucket._capacity!r}"
    )
    assert build_limiter(settings)._capacity == 99, (
        "the two factories must stay independent: the shared limiter still reads the shared "
        "burst, so neither factory can be a rename of the other"
    )


# --- Wire-contract constants (see `test_mcp_auth.py` for the same block) -----
#
# Defined here rather than imported from that module: test modules in this repo do
# not import each other, and a shared fixture file would hide which envelope a given
# assertion actually sent. `params._meta` is mandatory in the 2026-07-28 transport --
# omit it and the server answers `-32602`, which is a 200 and would silently make
# every rate-limit assertion below meaningless.
MCP_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}
MCP_HDRS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2026-07-28",
    "Mcp-Method": "tools/list",
    "Mcp-Name": "tools/list",
}
LIST_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": MCP_META}}

# Mirrors `conftest._TEST_MCP_ENV["MCP_AUTH_SECRET"]`, deliberately duplicated
# rather than imported. `backend/tests/*` ignores S105/S106.
AUTH = {"Authorization": "Bearer test-mcp-secret-not-a-real-credential"}

# Distinctive on purpose, and the same device `test_mcp_auth.BAD_TOKEN` uses: the
# leak assertions below can only detect "the rejection echoes the credential it
# was given" if the credential it was given is a string nothing else would emit.
BAD_TOKEN = "wrong-token-9f3a-must-not-be-echoed"

# The RFC 9728 document Claude fetches ANONYMOUSLY during connector discovery.
DISCOVERY_PATH = "/.well-known/oauth-protected-resource/mcp"


def _install_frozen_bucket(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, capacity: int
) -> TokenBucket:
    """Swap the live bucket for a tiny one whose clock never moves.

    ``app.state.rate_limit_bucket`` is the single live bucket object and the
    middleware resolves it per request, so replacing it here takes effect without
    rebuilding the middleware stack.

    The clock is frozen rather than advanced: a bucket that could refill mid-test
    would make the assertions racy, and nothing in this module waits for anything.

    Done through ``monkeypatch`` rather than a bare assignment because the app is
    process-global. ``conftest.client`` does ``from app.main import app``, and
    Python's module cache hands every test in the session the SAME object -- so an
    unrestored drained bucket would 429 every later client-using test in the run,
    for a reason nothing in those tests explains. ``monkeypatch`` puts the true
    previous value back in its own teardown, which is the ``finally``
    ``test_mcp_mount.py::mcp_server`` writes by hand for ``app.state.sessionmaker``.
    It also raises when the attribute is absent, so a ``main.py`` that stopped
    publishing the bucket fails loudly here instead of silently exercising the
    middleware's constructor fallback and passing.
    """
    bucket = TokenBucket(capacity=capacity, refill_per_second=0.5, clock=lambda: 1_000.0)
    monkeypatch.setattr(client.app.state, "rate_limit_bucket", bucket)
    return bucket


def _drain(client: TestClient, monkeypatch: pytest.MonkeyPatch, *, capacity: int = 2) -> None:
    """Install a frozen-clock bucket and empty it, so the very next request is over the limit.

    Emptied by taking from the bucket directly rather than by firing ``capacity``
    HTTP requests: the setup then cannot be confused with the behaviour under
    test, and a test asserting on "the first rejected request" really is asserting
    on the first one.
    """
    bucket = _install_frozen_bucket(client, monkeypatch, capacity=capacity)
    for _ in range(capacity):
        assert bucket.take() is None, (
            "the drain helper is broken: a fresh bucket refused one of its own capacity takes"
        )


@pytest.mark.integration
def test_over_limit_request_is_rejected_with_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ROADMAP-2/DEPLOY-03: the ceiling is enforced on the real endpoint, not just in the bucket.

    Three identical requests against a capacity-2 frozen-clock bucket. The first
    two are the whole budget; the third is the first request the limiter has ever
    had to refuse over HTTP.

    The first two are asserted to be 200 as well, and that half is not padding: a
    middleware that rejected everything -- a mis-scoped exemption check, an
    inverted ``take()`` test -- satisfies a third-request-only assertion perfectly
    while taking the connector down completely.
    """
    _install_frozen_bucket(client, monkeypatch, capacity=2)

    statuses = [
        client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH}).status_code
        for _ in range(3)
    ]

    assert statuses[:2] == [200, 200], (
        f"DEPLOY-03 violated: the limiter refused a request inside a capacity-2 budget, so it "
        f"rejects traffic it was configured to allow. Got: {statuses}"
    )
    assert statuses[2] == 429, (
        f"ROADMAP-2 violated: the third request against a capacity-2 bucket was answered "
        f"{statuses[2]}, not 429. The middleware is registered but is not actually gating the "
        f"mounted endpoint -- check that `add_middleware(RateLimitMiddleware, ...)` is on the "
        f"FastAPI app and that `app.state.rate_limit_bucket` is the object it reads. "
        f"Got: {statuses}"
    )


@pytest.mark.integration
def test_the_429_leaks_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-07-02: the rejection body is one field and nothing else.

    The exact key set is asserted, not merely the absence of known-bad strings.
    Unlike the 401, whose envelope the MCP SDK owns and holds still, this body is
    entirely ours and nothing external stops it growing a field -- so the failure
    worth guarding is a future edit that helpfully starts echoing the presented
    credential, the configured issuer, or an exception detail on an endpoint anyone
    on the internet can make emit it. A substring check would not notice a new
    field; a key-set check cannot miss it.

    Fired twice, with a good credential and then with a deliberately distinctive
    bad one. The limiter runs ahead of auth, so both are the SAME body -- which is
    exactly why the second call is worth making: "does the rejection echo what the
    caller presented?" is only answerable when the caller presents something no
    other code path would ever produce.
    """
    _drain(client, monkeypatch)
    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 429, (
        f"the leak assertions below are only meaningful against the limiter's own body, but the "
        f"drained bucket produced {response.status_code}. Body: {response.text[:200]}"
    )
    assert set(response.json()) == {"error"}, (
        f"T-07-02 violated: the 429 body grew a field. Got: {response.json()}"
    )
    for leak in (
        "test-mcp-secret-not-a-real-credential",
        "postgresql",
        "asyncpg",
        "127.0.0.1",
        "Traceback",
    ):
        assert leak not in response.text, (
            f"FOUND-05/T-07-02 violated: {leak!r} leaked into the 429 body"
        )

    unauthorized = client.post(
        "/mcp",
        json=LIST_BODY,
        headers={**MCP_HDRS, "Authorization": f"Bearer {BAD_TOKEN}"},
    )

    assert unauthorized.status_code == 429, (
        f"the bucket refilled mid-test, so the second rejection never happened. The clock is "
        f"frozen precisely to stop this. Got: {unauthorized.status_code}"
    )
    assert BAD_TOKEN not in unauthorized.text, (
        f"FOUND-05/T-07-02 violated: the 429 echoed the credential the caller presented "
        f"({BAD_TOKEN!r}). Body: {unauthorized.text[:200]}"
    )


@pytest.mark.integration
def test_the_429_carries_a_retry_after_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEPLOY-03: a throttled caller is told when to come back rather than left to guess.

    Without `Retry-After` a well-behaved client has nothing to back off against,
    and one throttled coaching turn becomes a tight retry loop against the exact
    endpoint the limiter exists to protect -- the limiter would then be generating
    the load it was added to bound.

    Parsed as an integer rather than merely asserted present: RFC 9110 also permits
    an HTTP-date form here, and a header in that form is a header this client
    cannot act on.
    """
    _drain(client, monkeypatch)

    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 429
    retry_after = response.headers.get("Retry-After")
    assert retry_after is not None, (
        f"DEPLOY-03 violated: the 429 carried no `Retry-After`, so a client honouring backoff "
        f"has nothing to honour. Headers: {dict(response.headers)}"
    )
    assert retry_after.isdigit(), (
        f"DEPLOY-03 violated: `Retry-After` must be delta-seconds, not RFC 9110's HTTP-date "
        f"form. Got: {retry_after!r}"
    )
    assert int(retry_after) >= 1, (
        f"DEPLOY-03 violated: `Retry-After: {retry_after}` tells the client to retry immediately, "
        f"which is a retry storm rather than a backoff."
    )


@pytest.mark.integration
def test_the_limiter_runs_before_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-07-24: an UNAUTHENTICATED flood is bounded too -- 429, not 401.

    This is the entire reason the limiter is registered with `add_middleware` on
    the FastAPI app instead of inside the MCP tool layer. Starlette applies
    app-level middleware OUTSIDE the router, so it runs before
    `app.mount("/", mcp_app)` resolves and therefore ahead of the SDK's own
    RequireAuthMiddleware.

    A 401 here would mean every anonymous request still reaches the token verifier
    -- a JWKS-backed signature check, on a service deployed
    --allow-unauthenticated -- before anything refuses it. The limiter would then
    bound only the traffic that already had a valid credential, which is not the
    traffic anyone is worried about.
    """
    _drain(client, monkeypatch)

    response = client.post("/mcp", json=LIST_BODY, headers=MCP_HDRS)

    assert response.status_code == 429, (
        f"T-07-24 violated: an unauthenticated over-limit request was answered "
        f"{response.status_code}, not 429. A 401 means the limiter sits INSIDE the MCP sub-app's "
        f"auth chain, so an anonymous flood reaches the verifier and the limiter bounds nothing "
        f"that matters. Body: {response.text[:200]}"
    )


@pytest.mark.integration
def test_health_is_never_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-07-04: Cloud Run's probe target answers normally with the bucket fully drained.

    Run against a DRAINED bucket on purpose -- that is the only condition under
    which this exemption can fail, and a test against a healthy bucket would pass
    whether the carve-out existed or not.

    A 429 here marks the revision unhealthy for a reason nothing in `health.py`
    explains: the limiter would take the service down by protecting it. The body is
    asserted too, so an exemption that returned some other 200 (a mount swallowing
    the route, say) still fails.
    """
    _drain(client, monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200, (
        f"T-07-04 violated: /health returned {response.status_code} with the bucket drained. "
        f"Cloud Run's startup and liveness probes hit this path; throttling it fails the "
        f"deployment. Body: {response.text[:200]}"
    )
    assert response.json() == {"status": "ok", "database": "connected"}, (
        f"T-07-04: /health was not throttled but no longer answers its own contract. "
        f"Got: {response.json()}"
    )


@pytest.mark.integration
def test_discovery_document_is_never_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-07-04: connector discovery answers normally with the bucket fully drained.

    Claude fetches this document ANONYMOUSLY inside a documented 10-second budget,
    and no auth header is sent here for that reason. Throttling it surfaces to the
    user only as "Couldn't reach the MCP server", with the authorization server
    logging no traffic at all -- a failure mode that looks nothing like a rate
    limit and would be debugged everywhere except here.

    Drained bucket for the same reason as the /health case: a healthy bucket cannot
    distinguish an exemption that works from one that was never written.
    """
    _drain(client, monkeypatch)

    response = client.get(DISCOVERY_PATH)

    assert response.status_code == 200, (
        f"T-07-04 violated: {DISCOVERY_PATH} returned {response.status_code} with the bucket "
        f"drained, so connector setup can be throttled into failing. "
        f"Body: {response.text[:200]}"
    )
    assert "authorization_servers" in response.json(), (
        f"T-07-04: the discovery document was not throttled but is no longer the RFC 9728 "
        f"document Claude needs. Got: {response.json()}"
    )


@pytest.mark.integration
def test_an_authenticated_request_under_the_limit_still_succeeds(client: TestClient) -> None:
    """T-07-25: the DEFAULT bucket does not throttle one ordinary call.

    The only test in this module that does NOT replace the live bucket. Every other
    test proves the limiter fires; this one proves it does not fire when it should
    not, against the geometry `deploy/cloud-run.env.yaml` actually ships.

    The failure this catches is a mistuned default -- the limiter is the one
    control here that damages the product when it is too strict, and a 429 in the
    middle of a coaching turn is worse for a single-user connector than an
    unthrottled minute. Asserting on the tool list rather than merely on 200 keeps
    the claim honest: the request travelled the whole way through the limiter,
    auth, transport and dispatch.
    """
    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 200, (
        f"T-07-25 violated: a single authenticated request was answered "
        f"{response.status_code} against the default bucket "
        f"(RATE_LIMIT_BURST/RATE_LIMIT_PER_MINUTE). Body: {response.text[:200]}"
    )
    assert "fitness_ping" in [tool["name"] for tool in response.json()["result"]["tools"]], (
        "T-07-25: the request was not throttled but did not reach the tool surface either, so "
        "the limiter is answering on behalf of the MCP sub-app."
    )

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

Both that rule and the split above are enforced by greps in 07-01-PLAN.md, which
is why neither the sleeping call nor the integration marker is spelled out
literally anywhere in this module.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.middleware import EXEMPT_PREFIXES, TokenBucket, build_limiter

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

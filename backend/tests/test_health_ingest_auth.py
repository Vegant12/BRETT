"""Unit tests for the Health Auto Export webhook credential check (HEALTH-07).

These test the verifier **directly**, not over HTTP, and that is deliberate. Splitting the
concern:

* **the first half** -- the verifier's decision function: what it accepts, what it denies, that
  it denies in constant time, and that no input shape can make it raise instead of returning
  ``False``.
* **the second half** (appended by plan 08-07, marked ``integration``) -- the wire contract:
  that a missing or wrong credential yields a bare ``401`` that writes nothing and explains
  nothing.

Proving the decision function first means the HTTP tests only have to prove the plumbing, not
re-derive every rejection case through a transport. They stay in ONE file because they are one
claim -- "rejected, writing nothing, explaining nothing" -- and splitting them across files is
how the over-HTTP half would eventually be deleted as a duplicate of the unit half it is not.
"""

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import HealthDailyMetric, SyncState
from app.integrations.health_auto_export.auth import verify_bearer
from tests.conftest import DEFAULT_USER_ID

SECRET = "s3cret-ingest-value-not-a-real-credential"

# Distinctive on purpose: plan 08-07's `test_401_leaks_nothing` asserts this exact string is
# absent from the rejection body, so a handler that starts echoing the presented credential back
# to the caller fails loudly instead of shipping.
BAD_TOKEN = "wrong-ingest-token-7b2e-must-not-be-echoed"

AUTH_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "integrations" / "health_auto_export" / "auth.py"
)

INGEST_PATH = "/api/v1/ingest/health-auto-export"

# The exact 401 body. One key: this endpoint can be made to emit it by anyone on the internet,
# so it must never grow a field that echoes the presented credential or says which of the three
# rejection reasons applied (T-08-44).
UNAUTHORIZED_BODY = {"error": "unauthorized"}


def test_a_correct_bearer_credential_is_accepted() -> None:
    assert verify_bearer(f"Bearer {SECRET}", SECRET) is True


def test_a_wrong_credential_is_rejected() -> None:
    """The whole point. A rejected credential is still a credential -- nothing echoes it."""
    assert verify_bearer(f"Bearer {BAD_TOKEN}", SECRET) is False


def test_an_absent_header_is_rejected() -> None:
    """HAE not configured with a credential at all, or an unauthenticated prober."""
    assert verify_bearer(None, SECRET) is False


def test_a_bare_token_without_the_scheme_is_rejected() -> None:
    """The ``Bearer `` scheme is REQUIRED, not optional decoration."""
    assert verify_bearer(SECRET, SECRET) is False


def test_the_scheme_comparison_is_case_exact() -> None:
    """Matching what Claude-adjacent clients and HAE actually send.

    A case-insensitive scheme check would be a silent widening of the accepted surface for no
    client that exists.
    """
    assert verify_bearer(f"bearer {SECRET}", SECRET) is False


def test_a_non_ascii_header_returns_false_and_does_not_raise() -> None:
    """T-08-19. Written WITHOUT `pytest.raises` on purpose.

    `secrets.compare_digest` raises `TypeError` on a `str` holding non-ASCII characters, and the
    ASGI server latin-1 decodes header bytes. A regression to the `str` overload therefore
    escapes as an unhandled `TypeError` and fails this test loudly, rather than being caught and
    reported as an expected rejection -- which is what a `pytest.raises` wrapper would do.

    In production that same regression is a 500 with a traceback where a silent 401 belongs.
    """
    assert verify_bearer("Bearer \xff\xfe", SECRET) is False
    assert verify_bearer("Bearer \u202f\u2019\U0001f600", SECRET) is False


def test_an_unconfigured_secret_fails_closed() -> None:
    """T-08-20: an unconfigured deployment has a DISABLED ingest path, never an open one.

    The dangerous implementation is the one where `"" == ""` accepts an empty presented token,
    which is exactly what an unset environment variable produces on both sides.
    """
    assert verify_bearer("Bearer anything", "") is False
    assert verify_bearer("Bearer ", "") is False
    assert verify_bearer("Bearer", "") is False
    assert verify_bearer(None, "") is False


def test_no_input_shape_makes_the_verifier_raise() -> None:
    """Fail-closed means RETURN False, never propagate. A raise here is a 500 in production."""
    for header in (
        "",
        " ",
        "Bearer",
        "Bearer ",
        "Bearer  ",
        "Basic " + SECRET,
        "Bearer " + SECRET + " trailing",
        "Bearer " + "x" * 100_000,
        "Bearer \x00",
        "\xff",
        f"Bearer {SECRET}\n",
    ):
        assert verify_bearer(header, SECRET) in (True, False)


def test_the_comparison_is_constant_time_and_never_a_plain_equality() -> None:
    """T-08-18: a short-circuiting comparison leaks the secret one byte at a time.

    Timing cannot be asserted reliably in a unit test, so the STRUCTURE is asserted instead --
    the same approach `test_rate_limit.py` takes to the middleware's forbidden inputs.
    """
    source = AUTH_SOURCE.read_text(encoding="utf-8")

    assert "secrets.compare_digest" in source, (
        "T-08-18 violated: the ingest verifier no longer uses secrets.compare_digest. A "
        "short-circuiting `==` leaks the shared secret one byte at a time"
    )
    assert source.count('encode("utf-8")') == 2, (
        "T-08-19 violated: both sides of the comparison must be encoded to BYTES. The `str` "
        "overload of compare_digest raises TypeError on non-ASCII, which surfaces as a 500 "
        "with a traceback instead of a silent 401"
    )


def test_the_verifier_does_not_log_or_import_mcp() -> None:
    """Nothing here may log a credential, and nothing here may reach into the MCP layer.

    Importing `mcp.server.auth.provider` would put an MCP dependency inside an integrations
    package and break the boundary this package exists to draw.
    """
    source = AUTH_SOURCE.read_text(encoding="utf-8")

    for forbidden in ("app.mcp", "from mcp", "import mcp", "logging", "structlog", "print("):
        assert forbidden not in source, (
            f"backend/app/integrations/health_auto_export/auth.py mentions {forbidden!r}. The "
            f"decision function returns a plain bool; logging and the HTTP contract belong to "
            f"the route, and an MCP import breaks the package boundary"
        )


@pytest.mark.parametrize("wrong_secret", ["", "s", SECRET + "x", SECRET[:-1], SECRET.upper()])
def test_a_near_miss_secret_is_rejected(wrong_secret: str) -> None:
    """Length-adjacent and case-adjacent secrets must not be accepted."""
    assert verify_bearer(f"Bearer {SECRET}", wrong_secret) is False


# ---------------------------------------------------------------------------
# The over-HTTP half (plan 08-07). Everything above proves the DECISION; everything below
# proves the CONTRACT -- the status code, the body, and that nothing was written.
# ---------------------------------------------------------------------------


def _run[T](coro: Any) -> T:
    """Run one coroutine from a SYNC test body.

    `TestClient` is synchronous and drives the app through a portal in its own thread, so a test
    that needs both HTTP and direct database access cannot be `async def`.
    """
    result: T = asyncio.run(coro)
    return result


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


async def _purge(postgres_url: str) -> None:
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


@pytest.fixture
def configured_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Configure the webhook credential for one test.

    `get_settings` is `lru_cache`d and the route calls it per request, so clearing the cache is
    what makes the value visible to the handler.
    """
    monkeypatch.setenv("HEALTH_INGEST_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        yield SECRET
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_401_leaks_nothing(client: TestClient, configured_secret: str, postgres_url: str) -> None:
    """HEALTH-07 / success criterion #2: rejected, writing nothing, explaining nothing.

    The two rejections must be INDISTINGUISHABLE to the caller. A body, header or status that
    differed between "no credential" and "wrong credential" would tell an unauthenticated
    prober that the endpoint exists, takes a bearer token, and that theirs was the right shape
    but the wrong value -- which is the whole of what an attacker needs to know before starting.

    `BAD_TOKEN` is distinctive precisely so this assertion means something: nothing else in the
    process could emit that string, so finding it in a response can only mean the handler
    echoed the credential back.
    """
    try:
        before = _run(_health_row_count(postgres_url))

        absent = client.post(INGEST_PATH, json={"data": {"metrics": []}})
        wrong = client.post(
            INGEST_PATH,
            json={"data": {"metrics": []}},
            headers={"Authorization": f"Bearer {BAD_TOKEN}"},
        )

        assert absent.status_code == 401, f"got {absent.status_code}: {absent.text[:200]}"
        assert wrong.status_code == 401, f"got {wrong.status_code}: {wrong.text[:200]}"
        assert absent.content == wrong.content, (
            f"T-08-44 violated: the no-credential and wrong-credential bodies differ, so the "
            f"response tells a prober which check failed. "
            f"Absent: {absent.content!r}  Wrong: {wrong.content!r}"
        )
        assert absent.json() == UNAUTHORIZED_BODY, (
            f"the 401 body must carry exactly one key. Got: {absent.json()}"
        )

        for response in (absent, wrong):
            assert BAD_TOKEN not in response.text, (
                f"the presented credential was echoed into the response body: {response.text[:200]}"
            )
            for name, value in response.headers.items():
                assert BAD_TOKEN not in value, (
                    f"the presented credential was echoed into the {name!r} response header"
                )

        assert _run(_health_row_count(postgres_url)) == before, (
            "a rejected request wrote to health_daily_metrics -- the credential check must run "
            "BEFORE anything reaches ingest_payload"
        )
    finally:
        _run(_purge(postgres_url))


@pytest.mark.integration
def test_unset_secret_rejects_every_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, postgres_url: str
) -> None:
    """T-08-20 over HTTP: an unconfigured deployment has a DISABLED ingest path, never an open one.

    Three outcomes are possible for an unset `HEALTH_INGEST_SECRET` and only one is acceptable.
    A `200`/`202` means `""` matched `""` and the endpoint is open to anyone who found the URL.
    A `500` means the handler dereferenced `None` -- still closed, but it reports a broken
    service and buries the real cause. `401` is the contract: the path is off.

    Asserted with a CORRECT-looking credential presented, because the dangerous implementation
    is the one that accepts whatever it is given when it has nothing to compare against.
    """
    monkeypatch.delenv("HEALTH_INGEST_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().health_ingest_secret is None, (
            "the environment still supplies a credential, so this test cannot observe the "
            "unconfigured case at all"
        )

        for headers in (
            {},
            {"Authorization": f"Bearer {SECRET}"},
            {"Authorization": "Bearer "},
            {"Authorization": f"Bearer {BAD_TOKEN}"},
        ):
            response = client.post(INGEST_PATH, json={"data": {"metrics": []}}, headers=headers)

            assert response.status_code == 401, (
                f"T-08-20 violated: with no configured secret, a request carrying "
                f"{headers or 'no credential'} got {response.status_code} rather than 401. "
                f"Body: {response.text[:200]}"
            )
            assert response.json() == UNAUTHORIZED_BODY

        assert _run(_health_row_count(postgres_url)) == 0
    finally:
        get_settings.cache_clear()
        _run(_purge(postgres_url))

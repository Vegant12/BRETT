"""Unit tests for the Health Auto Export webhook credential check (HEALTH-07).

These test the verifier **directly**, not over HTTP, and that is deliberate. Splitting the
concern:

* **here** -- the verifier's decision function: what it accepts, what it denies, that it denies
  in constant time, and that no input shape can make it raise instead of returning ``False``.
* **over HTTP** (appended by plan 08-07, marked ``integration``) -- the wire contract: that a
  missing or wrong credential yields a bare ``401`` that writes nothing and explains nothing.

Proving the decision function here means the HTTP tests only have to prove the plumbing, not
re-derive every rejection case through a transport.
"""

from pathlib import Path

import pytest

from app.integrations.health_auto_export.auth import verify_bearer

SECRET = "s3cret-ingest-value-not-a-real-credential"

# Distinctive on purpose: plan 08-07's `test_401_leaks_nothing` asserts this exact string is
# absent from the rejection body, so a handler that starts echoing the presented credential back
# to the caller fails loudly instead of shipping.
BAD_TOKEN = "wrong-ingest-token-7b2e-must-not-be-echoed"

AUTH_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "integrations" / "health_auto_export" / "auth.py"
)


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

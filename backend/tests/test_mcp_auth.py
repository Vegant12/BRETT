"""Unit tests for the MCP bearer-token verifier (MCP-04).

These test the verifier **directly**, not over HTTP, and that is deliberate. The
in-memory ``mcp.Client`` used elsewhere in this phase connects straight to the
``MCPServer`` object and bypasses ``RequireAuthMiddleware`` entirely, so it can
never observe a 401. Splitting the concern:

* **here** -- the verifier's decision function: what it accepts, what it denies,
  and that it denies in constant time.
* **over HTTP** (plan 02-04's mount tests) -- the wire contract: that a missing
  or wrong credential yields ``401`` with a ``resource_metadata=`` challenge and
  a valid one yields ``200``.

Proving the decision function here means the HTTP tests only have to prove the
plumbing, not re-derive every rejection case through a transport.
"""

import inspect

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.mcp.auth import StaticTokenVerifier, build_token_verifier

SECRET = "a-long-enough-test-secret-not-a-real-credential"
DB_URL = "postgresql://u:sup3rpw@h:5432/db"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build ``Settings`` from the environment, exactly as the app does at boot.

    ``_env_file=None`` mirrors ``test_config.py``: a developer's real ``.env``
    must never decide the outcome of a test.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


async def test_static_verifier_accepts_exact_secret() -> None:
    """The one accepting case: byte-for-byte equality with MCP_AUTH_SECRET."""
    token = await StaticTokenVerifier(SECRET).verify_token(SECRET)

    assert token is not None
    assert token.token == SECRET
    assert token.client_id == "brett-cli"
    assert token.scopes == []


async def test_static_verifier_rejects_wrong_token() -> None:
    """Anything that is not the secret is denied -- including non-ASCII input.

    ``secrets.compare_digest`` raises ``TypeError`` on a ``str`` containing
    non-ASCII characters, and Starlette's ``AuthenticationMiddleware`` catches
    only ``AuthenticationError``. A verifier that compares ``str`` directly
    therefore turns an attacker-supplied header byte into a 500 with a
    traceback instead of a silent 401 (T-02-04). Header bytes are latin-1
    decoded by the ASGI server, so reaching this case takes one arbitrary byte.
    """
    verifier = StaticTokenVerifier(SECRET)

    assert await verifier.verify_token("wrong") is None
    assert await verifier.verify_token("é") is None, (
        "T-02-04 violated: a non-ASCII token must be denied, not raise"
    )


async def test_static_verifier_rejects_empty_token() -> None:
    """An absent credential is a denied credential, never an accepted default."""
    assert await StaticTokenVerifier(SECRET).verify_token("") is None


async def test_static_verifier_rejects_prefix() -> None:
    """No prefix or substring match: only the whole secret authenticates."""
    verifier = StaticTokenVerifier(SECRET)

    assert await verifier.verify_token(SECRET + "x") is None
    assert await verifier.verify_token(SECRET[:-1]) is None


def test_build_token_verifier_returns_static(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default mode wires the static verifier with the configured secret."""
    settings = _settings(monkeypatch, MCP_AUTH_MODE="static", MCP_AUTH_SECRET=SECRET)

    verifier = build_token_verifier(settings)

    assert isinstance(verifier, StaticTokenVerifier)


def test_build_token_verifier_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """No secret -> refuse to start, and say so without echoing a credential.

    Failing at import is the point: a server that starts without a working
    verifier is a server that is unauthenticated in production until somebody
    notices. Both the unset and the empty-string case must fail -- an empty
    secret would otherwise authenticate an empty token.
    """
    monkeypatch.delenv("MCP_AUTH_SECRET", raising=False)
    unset = _settings(monkeypatch, MCP_AUTH_MODE="static")
    assert unset.mcp_auth_secret is None

    with pytest.raises(RuntimeError) as excinfo:
        build_token_verifier(unset)
    assert "MCP_AUTH_SECRET" in str(excinfo.value)

    empty = _settings(monkeypatch, MCP_AUTH_MODE="static", MCP_AUTH_SECRET="")
    assert empty.mcp_auth_secret == SecretStr("")

    with pytest.raises(RuntimeError) as empty_excinfo:
        build_token_verifier(empty)

    rendered = str(empty_excinfo.value) + repr(empty_excinfo.value)
    assert "MCP_AUTH_SECRET" in rendered
    for leak in ("SecretStr", "get_secret_value", "''"):
        assert leak not in rendered, (
            f"FOUND-05/T-02-04 violated: {leak!r} leaked into the startup error"
        )


def test_build_token_verifier_rejects_unimplemented_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``authkit`` must raise, never silently degrade to static bearer.

    A selector that fell back to ``static`` on an unimplemented mode would let a
    production deploy configured for JWKS validation come up quietly accepting a
    shared bearer token instead.
    """
    settings = _settings(monkeypatch, MCP_AUTH_MODE="authkit", MCP_AUTH_SECRET=SECRET)

    with pytest.raises(RuntimeError) as excinfo:
        build_token_verifier(settings)

    assert "02-06" in str(excinfo.value)


def test_static_verifier_uses_constant_time_comparison() -> None:
    """A `==` comparison leaks the secret one byte at a time (T-02-05)."""
    source = inspect.getsource(StaticTokenVerifier.verify_token)
    assert "compare_digest" in source
    assert "token ==" not in source
    assert "== self._secret" not in source

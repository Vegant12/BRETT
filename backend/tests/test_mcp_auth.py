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

Plan 02-04 added the second half: the **wire contract** the SDK builds around
that decision function, driven through the mounted endpoint. The split matters
because the two halves fail independently and only one of them is ours. Claude
requires a `401` -- not a `403`, not a tool-level error -- carrying a
`resource_metadata=` parameter, and it "does not honor a `WWW-Authenticate`
header on a `200` response". None of that shape is produced by
`StaticTokenVerifier`; it is produced by `RequireAuthMiddleware` from
`AuthSettings`, several layers away from any code in this repo. A verifier that
still returns the right answer while the SDK emits the wrong envelope is a
connector that cannot authenticate, and the tests below are what would catch it.
"""

import inspect

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.mcp.auth import StaticTokenVerifier, build_token_verifier

SECRET = "a-long-enough-test-secret-not-a-real-credential"
DB_URL = "postgresql://u:sup3rpw@h:5432/db"

# --- Wire-contract constants (see `test_mcp_mount.py` for the same block) -----
#
# Defined here rather than imported from that module: test modules in this repo
# do not import each other, and a shared fixture file would hide which envelope
# a given assertion actually sent. `params._meta` is mandatory in the 2026-07-28
# transport -- omit it and the server answers `-32602` (RESEARCH Pitfall 5).
#
# The 401 fires in middleware *before* envelope parsing, so the auth assertions
# below would hold even without `_meta`. It is included anyway so that the one
# test expecting `200` exercises the same request shape as the ones expecting
# `401`, and a failure can only be about the credential.
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

# Distinctive on purpose: `test_401_leaks_nothing` asserts this exact string is
# absent from the rejection body, so an SDK that starts echoing the presented
# credential back to the caller fails loudly instead of shipping.
BAD_TOKEN = "wrong-token-9f3a-must-not-be-echoed"


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


@pytest.mark.integration
def test_rejects_unauthenticated(client: TestClient) -> None:
    """T-02-06: no credential -> 401 carrying Claude's discovery pointer.

    The `resource_metadata=` parameter is the whole point. Claude reads it from
    the `WWW-Authenticate` challenge to find the RFC 9728 document, and from
    there the authorization server. A bare `401` with no pointer is a dead end
    that produces "Couldn't reach the MCP server" with nothing else to go on.
    """
    response = client.post("/mcp", json=LIST_BODY, headers=MCP_HDRS)

    assert response.status_code == 401
    assert (
        'resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp"'
        in response.headers["www-authenticate"]
    ), (
        "MCP-04: the 401 must point at the RFC 9728 document. Got: "
        f"{response.headers.get('www-authenticate')!r}"
    )


@pytest.mark.integration
def test_rejects_bad_token(client: TestClient) -> None:
    """T-02-06: a wrong credential is rejected exactly like a missing one.

    Byte-identical bodies are the assertion, not a coincidence. If a wrong token
    produced a different response than no token, the difference would itself be
    an oracle: an attacker could use it to confirm a guessed credential format,
    or to distinguish "this token is unknown" from "this endpoint needs a
    token". The verifier verifies; it does not presence-check.
    """
    unauthenticated = client.post("/mcp", json=LIST_BODY, headers=MCP_HDRS)
    response = client.post(
        "/mcp",
        json=LIST_BODY,
        headers={**MCP_HDRS, "Authorization": f"Bearer {BAD_TOKEN}"},
    )

    assert response.status_code == 401
    assert response.text == unauthenticated.text
    assert response.headers["www-authenticate"] == unauthenticated.headers["www-authenticate"]


@pytest.mark.integration
def test_accepts_valid_bearer(client: TestClient) -> None:
    """MCP-04: the configured secret authenticates and reaches the tool surface.

    Asserting on the tool list rather than merely on `200` is deliberate -- it
    proves the request travelled the whole way through auth, transport, and
    dispatch, instead of being answered by something upstream that happens to
    return 200.
    """
    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 200
    assert [tool["name"] for tool in response.json()["result"]["tools"]] == ["fitness_ping"]


@pytest.mark.integration
def test_401_leaks_nothing(client: TestClient) -> None:
    """T-02-04: the rejection body is two fields and nothing else.

    The exact key set is asserted, not merely the absence of known-bad strings.
    This endpoint is unauthenticated by definition -- anyone on the internet can
    make it emit this body -- so the failure mode worth guarding is an SDK
    upgrade that helpfully starts including the presented token, the configured
    issuer, or an exception detail in the error payload. A substring check would
    not notice a new field; a key-set check cannot miss it.
    """
    response = client.post(
        "/mcp",
        json=LIST_BODY,
        headers={**MCP_HDRS, "Authorization": f"Bearer {BAD_TOKEN}"},
    )

    assert response.status_code == 401
    assert set(response.json()) == {"error", "error_description"}, (
        f"FOUND-05/T-02-04: the 401 body grew a field. Got: {response.json()}"
    )
    for leak in (
        "test-mcp-secret-not-a-real-credential",
        BAD_TOKEN,
        "postgresql",
        "asyncpg",
        "127.0.0.1",
        "Traceback",
    ):
        assert leak not in response.text, (
            f"FOUND-05/T-02-04 violated: {leak!r} leaked into the 401 body"
        )


@pytest.mark.integration
def test_protected_resource_metadata_path(client: TestClient) -> None:
    """T-02-03/T-02-02: the RFC 9728 document is where Claude probes for it.

    This is the Pitfall 3 tripwire. Mounted under a prefix instead of at `/`,
    this exact path 404s -- and nothing else changes, because static-bearer auth
    never triggers a 401 and therefore never exercises discovery. The failure
    would surface weeks later as a connector that cannot authenticate while the
    authorization server logs no traffic at all.

    No auth header: the metadata document is deliberately anonymous, which is
    also why `resource` is asserted equal to configuration rather than merely
    present -- whatever is published here is public.
    """
    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    body = response.json()
    settings = get_settings()

    assert body["resource"].rstrip("/") == settings.mcp_resource_url.rstrip("/")
    # A single entry, not merely "contains": Claude uses `authorization_servers[0]`
    # and never falls back to a later one, so a second entry would be dead
    # config that silently masks a wrong first entry (T-02-02, Pitfall 9).
    assert [server.rstrip("/") for server in body["authorization_servers"]] == [
        settings.mcp_issuer_url.rstrip("/")
    ]

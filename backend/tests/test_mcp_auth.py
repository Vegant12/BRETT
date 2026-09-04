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

Plan 02-06 added the third block: the Stage-B `AuthKitJWTVerifier`. **Where the
stubbing boundary sits matters more here than anywhere else in the suite, so it
is stated explicitly.** The signing key is a real RSA-2048 key pair generated
per module by `cryptography`, the tokens are really signed by `jwt.encode`, and
the acceptance/rejection decision is really made by `jwt.decode`. A token signed
by an unrelated key is genuinely rejected by the signature check; a token whose
`iss`, `aud` or `exp` is wrong is genuinely rejected by the claim checks. The
*only* thing replaced is `PyJWKClient.get_signing_key_from_jwt` -- i.e. the
blocking HTTPS round trip that fetches the public key -- because the network is
not what is under test and WorkOS is not reachable from CI.

The inverse approach, mocking `jwt.decode`, would prove nothing at all: every
threat this class exists to stop (T-02-02 audience confusion, algorithm
confusion, expiry) lives *inside* that call. Stubbing it would leave a green
suite over a verifier that accepts anything.
"""

import base64
import inspect
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.mcp.auth import AuthKitJWTVerifier, StaticTokenVerifier, build_token_verifier

SECRET = "a-long-enough-test-secret-not-a-real-credential"
DB_URL = "postgresql://u:sup3rpw@h:5432/db"

# --- Stage B (authkit) constants ---------------------------------------------
#
# `AUDIENCE` is deliberately NOT equal to `ISSUER` and NOT equal to the
# conftest-seeded `MCP_RESOURCE_URL`: the Resource Indicator is a distinct
# identity from the authorization server's, and a verifier that conflated them
# would still pass a test where the two strings matched.
ISSUER = "https://example.authkit.app"
AUDIENCE = "https://brett.example.com/mcp"
# Never assumed by the verifier -- it is configuration, read from the
# authorization server's discovery document (RESEARCH assumption A1). The value
# here is inert: the key fetch is stubbed in every test below.
JWKS_URI = "https://example.authkit.app/oauth2/jwks"

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


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    """The tenant's signing key. Module-scoped: 2048-bit generation is not free."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def foreign_rsa_key() -> rsa.RSAPrivateKey:
    """An unrelated key, standing in for an attacker signing their own tokens."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _mint(
    key: rsa.RSAPrivateKey,
    *,
    issuer: str = ISSUER,
    audience: str | None = AUDIENCE,
    expires_in: int = 3600,
    scope: str = "read",
    subject: str = "user_123",
) -> str:
    """Sign a real RS256 token, varying exactly one claim per caller."""
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": issuer,
        "sub": subject,
        "exp": now + expires_in,
        "iat": now,
        "scope": scope,
        "client_id": "cimd-client",
    }
    if audience is not None:
        claims["aud"] = audience
    return jwt.encode(claims, key, algorithm="RS256")


def _mint_unsigned(issuer: str = ISSUER, audience: str = AUDIENCE) -> str:
    """Hand-build an ``alg: none`` token.

    Built byte by byte rather than through ``jwt.encode`` because PyJWT refuses
    to mint one: ``alg: none`` is the classic algorithm-confusion attack, and the
    library will not help you produce it. The signature segment is empty, which
    is what ``none`` means.
    """

    def _segment(payload: dict[str, object]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = int(time.time())
    header = _segment({"alg": "none", "typ": "JWT"})
    body = _segment({"iss": issuer, "aud": audience, "exp": now + 3600, "sub": "attacker"})
    return f"{header}.{body}."


def _verifier(
    key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    *,
    audience: str = AUDIENCE,
) -> AuthKitJWTVerifier:
    """A verifier whose key FETCH is stubbed and whose key CHECK is real.

    Replacing ``get_signing_key_from_jwt`` swaps a blocking HTTPS round trip for
    the very public key the JWKS endpoint would have returned. Everything after
    it -- signature, ``iss``, ``aud``, ``exp``, algorithm allowlist -- runs
    unmodified. See this module's docstring for why the boundary is here.
    """
    verifier = AuthKitJWTVerifier(issuer=ISSUER, audience=audience, jwks_uri=JWKS_URI)
    monkeypatch.setattr(
        verifier._jwks,
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=key.public_key()),
    )
    return verifier


def _exp_of(token: str) -> int:
    """Read a token's ``exp`` without validating it, to assert the pass-through."""
    claims: dict[str, int] = jwt.decode(token, options={"verify_signature": False})
    return claims["exp"]


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


def test_build_token_verifier_authkit_never_degrades_to_static(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``authkit`` must never silently degrade to static bearer.

    Until plan 02-06 this property was enforced by the mode raising "not
    implemented". Now that the mode *is* implemented the property still has to
    hold, and it is the stronger of the two claims: a selector that fell back to
    ``static`` on a half-configured ``authkit`` deploy would bring a server up
    quietly accepting a shared bearer token where the operator asked for JWKS
    validation -- and every request would keep succeeding, so nothing would ever
    surface the mistake.

    Both branches are asserted. Fully configured, the mode must NOT hand back a
    ``StaticTokenVerifier``; half configured, it must refuse to start rather than
    hand back anything at all.
    """
    configured = _settings(
        monkeypatch,
        MCP_AUTH_MODE="authkit",
        MCP_AUTH_SECRET=SECRET,
        MCP_ISSUER_URL=ISSUER,
        MCP_RESOURCE_URL=AUDIENCE,
        MCP_JWKS_URI=JWKS_URI,
    )

    assert not isinstance(build_token_verifier(configured), StaticTokenVerifier)

    half_configured = _settings(
        monkeypatch,
        MCP_AUTH_MODE="authkit",
        MCP_AUTH_SECRET=SECRET,
        MCP_JWKS_URI="",
    )

    with pytest.raises(RuntimeError):
        build_token_verifier(half_configured)


def test_static_verifier_uses_constant_time_comparison() -> None:
    """A `==` comparison leaks the secret one byte at a time (T-02-05)."""
    source = inspect.getsource(StaticTokenVerifier.verify_token)
    assert "compare_digest" in source
    assert "token ==" not in source
    assert "== self._secret" not in source


# --- Stage B: AuthKitJWTVerifier (D-03/D-04) ---------------------------------


async def test_authkit_accepts_valid_token(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one accepting case, and the shape of what it hands the SDK.

    ``scopes`` is asserted as a split list rather than the raw claim because
    ``AccessToken.scopes`` is ``list[str]`` and OAuth's ``scope`` claim is a
    space-delimited string -- a verifier that passed the string straight through
    would produce a single scope named ``"read write"`` that no scope check
    could ever match.
    """
    token = _mint(rsa_key)

    verified = await _verifier(rsa_key, monkeypatch).verify_token(token)

    assert verified is not None
    assert verified.token == token
    assert verified.subject == "user_123"
    assert verified.expires_at == _exp_of(token)
    assert verified.scopes == ["read"]
    assert verified.client_id == "cimd-client"


async def test_authkit_rejects_wrong_issuer(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correctly-signed token from the wrong authorization server is denied.

    The signature is valid here -- only ``iss`` differs. Without the explicit
    ``issuer=`` check, any AS whose key happened to be served by the configured
    JWKS URI would be trusted.
    """
    token = _mint(rsa_key, issuer="https://attacker.authkit.app")

    assert await _verifier(rsa_key, monkeypatch).verify_token(token) is None


async def test_authkit_rejects_wrong_audience(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-02-02, the confused deputy: a token minted for another MCP server.

    This is the single most important rejection in the file. WorkOS will happily
    issue tokens for every resource registered in the tenant; the ``aud`` binding
    is the only thing stopping a token obtained for some other server -- by a
    client the user legitimately authorised -- from being replayed against
    BRETT's health data.
    """
    token = _mint(rsa_key, audience="https://someone-elses-server.example.com/mcp")

    assert await _verifier(rsa_key, monkeypatch).verify_token(token) is None


async def test_authkit_rejects_expired_token(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token whose ``exp`` has passed is denied, signature notwithstanding."""
    token = _mint(rsa_key, expires_in=-60)

    assert await _verifier(rsa_key, monkeypatch).verify_token(token) is None


async def test_authkit_rejects_unknown_signing_key(
    rsa_key: rsa.RSAPrivateKey,
    foreign_rsa_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token signed by a key that is not in the JWKS is denied.

    Every claim is correct; only the signing key is foreign. This is what proves
    the cryptographic check is genuinely running -- if ``jwt.decode`` were being
    mocked anywhere, this test would pass for the wrong reason and so would the
    whole file.
    """
    token = _mint(foreign_rsa_key)

    assert await _verifier(rsa_key, monkeypatch).verify_token(token) is None


async def test_authkit_rejects_token_without_audience(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-02-02: an absent ``aud`` is a rejection, not an unconstrained token.

    ``options={"require": [...]}`` is what makes this fail. PyJWT only enforces a
    claim it finds; without ``require``, a token that simply omits ``aud`` skips
    the audience check entirely and the confused-deputy guard becomes optional
    for anyone who can influence what the AS stamps.
    """
    token = _mint(rsa_key, audience=None)

    assert await _verifier(rsa_key, monkeypatch).verify_token(token) is None


async def test_authkit_rejects_when_jwks_fetch_fails(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-02-07: a JWKS outage denies the request -- it never fails open, and it
    never fails loudly either.

    Two properties in one assertion. ``is None`` is fail-CLOSED: an unreachable
    identity provider must not become "authentication is disabled today" on a
    health-data endpoint. That the call *returns* rather than raising is
    fail-QUIET: an escaping exception would surface as a 500 with a traceback
    instead of the 401 the connector needs, and the traceback of a decode failure
    can carry the presented token (T-02-04).
    """
    verifier = _verifier(rsa_key, monkeypatch)

    def _explode(token: str) -> None:
        raise ConnectionError("jwks down")

    monkeypatch.setattr(verifier._jwks, "get_signing_key_from_jwt", _explode)

    # No `pytest.raises` and no try/except: reaching the assertion at all is the
    # fail-quiet half of the proof.
    assert await verifier.verify_token(_mint(rsa_key)) is None


async def test_authkit_rejects_alg_none_token(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Algorithm confusion: an unsigned token is not a valid token.

    ``algorithms=["RS256"]`` is the whole defence. Omit it, or widen it to
    include ``none``, and anyone can mint a token with any claims they like --
    the key fetch is stubbed to succeed here precisely so that the algorithm
    allowlist is the only thing left standing between this token and acceptance.
    """
    assert await _verifier(rsa_key, monkeypatch).verify_token(_mint_unsigned()) is None


def test_build_token_verifier_authkit_requires_jwks_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No JWKS URI -> refuse to start, and name the variable that is missing.

    ``MCP_JWKS_URI`` defaults to empty because RESEARCH assumption A1 is
    unverified: ``/oauth2/jwks`` is a documentation claim, not a contract, so the
    value must be read from the authorization server's discovery document. An
    empty URI would otherwise construct a ``PyJWKClient`` pointed at nothing and
    fail closed on every single request -- correct behaviour, silently, forever.
    """
    settings = _settings(
        monkeypatch,
        MCP_AUTH_MODE="authkit",
        MCP_AUTH_SECRET=SECRET,
        MCP_ISSUER_URL=ISSUER,
        MCP_RESOURCE_URL=AUDIENCE,
        MCP_JWKS_URI="",
    )

    with pytest.raises(RuntimeError) as excinfo:
        build_token_verifier(settings)

    assert "MCP_JWKS_URI" in str(excinfo.value)


def test_build_token_verifier_returns_authkit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fully configured, the selector wires the JWKS verifier from settings.

    The three values are asserted to have reached the instance, not merely that
    the type is right: ``issuer`` and ``audience`` swapped would still construct
    an ``AuthKitJWTVerifier`` and would still reject everything WorkOS issued.
    """
    settings = _settings(
        monkeypatch,
        MCP_AUTH_MODE="authkit",
        MCP_AUTH_SECRET=SECRET,
        MCP_ISSUER_URL=ISSUER,
        MCP_RESOURCE_URL=AUDIENCE,
        MCP_JWKS_URI=JWKS_URI,
    )

    verifier = build_token_verifier(settings)

    assert isinstance(verifier, AuthKitJWTVerifier)
    assert verifier._issuer == ISSUER
    assert verifier._audience == AUDIENCE
    assert verifier._jwks.uri == JWKS_URI


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

    A MEMBERSHIP check, not the exact list. This asserted `== ["fitness_ping"]`
    while one tool existed; plan 06-09 registered twelve more, and pinning the
    whole registry here would mean every new tool has to be added to an auth
    test that is not about the registry. The exact-registry claim lives in
    `test_mcp_tool_schemas.test_tool_registry_is_exactly_the_sixteen`.
    """
    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 200
    assert "fitness_ping" in [tool["name"] for tool in response.json()["result"]["tools"]]


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

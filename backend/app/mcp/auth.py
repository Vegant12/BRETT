"""MCP bearer-token verification (MCP-04).

Two staged mechanisms behind one selector, so ``server.py`` never changes when
the mechanism does:

* ``static``  -- constant-time compare against ``MCP_AUTH_SECRET``. Proves the
  deploy + mount + auth pipeline through Claude Code's ``--header`` flag (D-01).
* ``authkit`` -- validate a WorkOS-issued RS256 JWT against the tenant's JWKS,
  enforcing ``iss``, ``exp`` and an ``aud`` equal to this server's registered
  Resource Indicator (D-03/D-04). Landed in plan 02-06.

Only the mechanism differs between the two. The 401 shape, the RFC 9728 metadata
document, the ASGI mount and the tool surface are produced by the SDK from
``AuthSettings`` and do not change, which is the entire point of the selector:
``server.py`` never learns which mode is active.

Nothing here may log a token, a decoded claim, or an exception body. A rejected
credential is still a credential: ``verify_token`` fails CLOSED and silent
(T-02-04). Comparison is ``secrets.compare_digest`` and never ``==``, because a
short-circuiting comparison leaks the secret one byte at a time (T-02-05).
"""

import secrets
from typing import Any

import anyio.to_thread
import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.config import Settings


class StaticTokenVerifier:
    """Constant-time comparison against ``MCP_AUTH_SECRET`` (D-01)."""

    def __init__(self, secret: str) -> None:
        # Compared as BYTES, never as `str`. `secrets.compare_digest` raises
        # `TypeError` on a `str` holding non-ASCII characters, and the ASGI
        # server latin-1 decodes header bytes -- so a single arbitrary byte in
        # the Authorization header would escape as an unhandled exception.
        # Starlette's AuthenticationMiddleware catches only AuthenticationError,
        # so that surfaces as a 500 with a traceback rather than a silent 401,
        # breaking this module's fail-closed contract (T-02-04). The bytes
        # overload has no such restriction and is still constant-time.
        self._secret = secret.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token.encode("utf-8"), self._secret):
            return AccessToken(token=token, client_id="brett-cli", scopes=[])
        return None


class AuthKitJWTVerifier:
    """Validate a WorkOS AuthKit JWT against the tenant's JWKS (D-03, D-04).

    ``PyJWKClient.fetch_data`` uses a BLOCKING ``urllib.request.urlopen``, so
    calling it from this async method would stall the whole event loop for the
    duration of an HTTPS round trip -- one slow JWKS fetch would freeze every
    concurrent request (T-02-08). It is therefore pushed to a worker thread.
    ``cache_jwk_set=True`` (default, 300s) makes this a cold-start cost and a
    five-minute refresh, not a per-request cost.

    The JWKS URI is passed in rather than derived from the issuer: the path
    ``/oauth2/jwks`` is a documentation claim, not a contract, and the
    authorization server's own discovery document publishes the authoritative
    value.

    Any failure returns ``None``. Failing CLOSED on a JWKS outage means a
    transient IdP problem locks us out for up to the cache lifetime; failing
    OPEN would mean an IdP outage silently disables authentication on a health
    data endpoint (T-02-07). Nothing is logged -- an exception raised while
    decoding can carry the token itself (T-02-04).
    """

    def __init__(self, issuer: str, audience: str, jwks_uri: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks = PyJWKClient(jwks_uri, cache_jwk_set=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims: dict[str, Any] = await anyio.to_thread.run_sync(
                lambda: jwt.decode(
                    token,
                    key.key,
                    # Explicit allowlist, never `None` and never `none`/HS256: a
                    # verifier that accepts the token's own `alg` header lets an
                    # attacker choose the algorithm and sign their own tokens.
                    algorithms=["RS256"],
                    issuer=self._issuer,
                    # RFC 8707 Resource Indicator. Binding `aud` to THIS server
                    # is what stops a token minted for another MCP server from
                    # being replayed here (confused deputy, T-02-02).
                    audience=self._audience,
                    # PyJWT only validates a claim it finds. Without `require`,
                    # a token that simply omits `aud` skips the audience check
                    # entirely and the guard above becomes optional.
                    options={"require": ["exp", "iss", "aud"]},
                )
            )
        except Exception:  # noqa: BLE001 - any validation failure is just "unauthenticated"
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("client_id", "authkit"),
            # OAuth's `scope` is a space-delimited string; `AccessToken.scopes`
            # is a list. Passing the raw claim through would yield one scope
            # named "read write" that no scope check could ever match.
            scopes=(claims.get("scope") or "").split(),
            expires_at=claims.get("exp"),
            subject=claims.get("sub"),
        )


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Select the verifier for the configured auth mode.

    Fails fast at import time rather than at first request: a server that starts
    without a working verifier is a server that is unauthenticated in production
    until someone notices. Neither branch may fall through to the other -- an
    ``authkit`` deploy that quietly degraded to ``static`` would accept a shared
    bearer token where the operator asked for JWKS validation, and every request
    would keep succeeding, so nothing would ever surface the mistake.
    """
    if settings.mcp_auth_mode == "authkit":
        if not settings.mcp_jwks_uri:
            raise RuntimeError(
                "MCP_JWKS_URI is required when MCP_AUTH_MODE=authkit; read it "
                "from the authorization server's discovery document"
            )
        return AuthKitJWTVerifier(
            issuer=settings.mcp_issuer_url,
            audience=settings.mcp_resource_url,
            jwks_uri=settings.mcp_jwks_uri,
        )
    secret = settings.mcp_auth_secret
    if secret is None or not secret.get_secret_value():
        raise RuntimeError("MCP_AUTH_SECRET is required to start the MCP server")
    return StaticTokenVerifier(secret.get_secret_value())

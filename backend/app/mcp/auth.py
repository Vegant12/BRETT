"""MCP bearer-token verification (MCP-04).

Two staged mechanisms behind one selector, so ``server.py`` never changes when
the mechanism does:

* ``static``  -- constant-time compare against ``MCP_AUTH_SECRET``. Proves the
  deploy + mount + auth pipeline through Claude Code's ``--header`` flag (D-01).
* ``authkit`` -- WorkOS AuthKit JWKS validation (D-03/D-04). Landed in plan
  02-06; this module raises rather than silently degrading to ``static``.

Nothing here may log a token, a decoded claim, or an exception body. A rejected
credential is still a credential: ``verify_token`` fails CLOSED and silent
(T-02-04). Comparison is ``secrets.compare_digest`` and never ``==``, because a
short-circuiting comparison leaks the secret one byte at a time (T-02-05).
"""

import secrets

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


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Select the verifier for the configured auth mode.

    Fails fast at import time rather than at first request: a server that starts
    without a working verifier is a server that is unauthenticated in production
    until someone notices.
    """
    if settings.mcp_auth_mode == "authkit":
        raise RuntimeError("MCP_AUTH_MODE=authkit is not implemented until plan 02-06")
    secret = settings.mcp_auth_secret
    if secret is None or not secret.get_secret_value():
        raise RuntimeError("MCP_AUTH_SECRET is required to start the MCP server")
    return StaticTokenVerifier(secret.get_secret_value())

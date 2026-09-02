"""Shared-secret verification for the Health Auto Export webhook (HEALTH-07).

Deliberately NOT an MCP ``TokenVerifier``: importing ``mcp.server.auth.provider`` here would
put an MCP dependency inside an integrations package and break the boundary this package exists
to draw. The two auth surfaces answer to different clients -- Claude on one side, a phone app on
the other -- and must be able to change independently.

The decision function returns a plain ``bool``; the HTTP contract (a bare 401 that writes
nothing and explains nothing) is the route's job, in ``app/api/routes/health_ingest.py``.
Nothing here logs, and nothing here raises.
"""

import secrets

_BEARER_PREFIX = "Bearer "


def verify_bearer(header_value: str | None, secret: str) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header.

    Compared as BYTES, never as ``str``. ``secrets.compare_digest`` raises ``TypeError`` on a
    ``str`` holding non-ASCII characters, and the ASGI server latin-1 decodes header bytes -- so
    a single arbitrary byte in the Authorization header would escape as an unhandled exception
    and surface as a 500 with a traceback rather than a silent 401, breaking this module's
    fail-closed contract (T-08-19). The bytes overload has no such restriction and is still
    constant-time.

    Fails closed on an empty secret: an unconfigured deployment has a DISABLED ingest path,
    never an open one (T-08-20). Without this guard an unset environment variable on both sides
    would make ``""`` match ``""`` and open the endpoint to anyone who found it.

    The scheme prefix is checked before the compare. That is not a leak: the presence of the
    word "Bearer" is not secret, and the secret itself is never involved in a short-circuit
    (T-08-18).
    """
    if not secret or header_value is None:
        return False
    if not header_value.startswith(_BEARER_PREFIX):
        return False
    presented = header_value[len(_BEARER_PREFIX) :]
    return secrets.compare_digest(presented.encode("utf-8"), secret.encode("utf-8"))

"""MCP server assembly (MCP-01, MCP-04, D-05).

Import order here is load-bearing in the same way ``main.py``'s is.
``streamable_http_app()`` MUST run at import: ``mcp.session_manager`` raises
``RuntimeError`` until it has, and ``main.py``'s lifespan reads that attribute.

Three non-obvious constraints, each verified against mcp 2.0.0:

* ``AuthSettings`` is mandatory alongside ``token_verifier``. Passing a verifier
  without it raises ``ValueError`` at import, and ``AuthSettings`` itself requires
  BOTH ``issuer_url`` and ``resource_server_url`` (RESEARCH Pitfall 4). During
  the static-bearer stage ``issuer_url`` is never exercised -- a valid header
  means no 401, so no discovery -- but it must still be a valid URL.
* ``TransportSecuritySettings`` is not optional in practice. Left at ``None`` the
  SDK auto-enables DNS-rebinding protection allowing only localhost, and every
  request through Render's real Host header returns ``421 Invalid Host header``
  with no MCP-level error body (T-02-01, RESEARCH Pitfall 2).
* ``allowed_origins=[]`` on purpose. Claude's connectors call server-to-server
  from Anthropic's egress range and send no ``Origin``; a non-empty list here
  creates a 403 trap for no benefit.

The sub-app returned below owns ``/mcp`` AND
``/.well-known/oauth-protected-resource/mcp`` at its OWN root, so ``main.py``
mounts it at ``/``. Mounting at ``/mcp`` relocates the metadata document to a
path Claude never probes and breaks OAuth discovery silently -- the MCP server
receives the first request while the authorization server sees no traffic at all
(RESEARCH Pitfall 3).
"""

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from app.config import get_settings
from app.mcp.auth import build_token_verifier
from app.mcp.context import mcp_lifespan
from app.mcp.tools.ping import fitness_ping

settings = get_settings()  # lru_cached -- not a second read

mcp = MCPServer(
    name="BRETT",
    version="0.1.0",
    lifespan=mcp_lifespan,
    token_verifier=build_token_verifier(settings),
    auth=AuthSettings(
        # `str` is passed deliberately, and the `type: ignore` is the price of
        # doing it correctly. These fields are typed `AnyHttpUrl`, but
        # `AuthSettings` sets `url_preserve_empty_path=True` specifically so a
        # path-less URL passed AS A STRING keeps its canonical form. Coercing
        # with `AnyHttpUrl(...)` here to satisfy mypy would bypass that config
        # and rewrite "https://tenant.authkit.app" to ".../" -- and RFC 8414
        # issuer comparison is exact string comparison, so that trailing slash
        # silently breaks discovery against the real IdP.
        issuer_url=settings.mcp_issuer_url,  # type: ignore[arg-type]
        # Must equal the URL the user types into Claude, character for
        # character, and the Resource Indicator registered at the IdP
        # (RESEARCH Pitfall 8).
        resource_server_url=settings.mcp_resource_url,  # type: ignore[arg-type]
        # Scope design belongs with the real tool set in Phase 6. An empty
        # scope list is the least likely thing to break a first handshake.
        required_scopes=None,
    ),
)

# D-08: one tool, and it does a real DB round-trip.
mcp.add_tool(
    fitness_ping,
    name="fitness_ping",
    description="Database connectivity check.",
)

# MUST run at import time. See the module docstring.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    # No session state to lose across a Render restart or spin-down; the
    # 2026-07-28 transport removed protocol-level sessions anyway.
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=[],
    ),
)

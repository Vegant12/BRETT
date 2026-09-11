"""What this file guards: **mounting position** (MCP-01, RESEARCH Pitfall 3).

The MCP sub-app owns ``/mcp`` *and*
``/.well-known/oauth-protected-resource/mcp`` at its own root, which is the
whole reason plan 02-04 mounts it at ``/`` rather than at ``/mcp``. Mounting at
``/mcp`` relocates the RFC 9728 metadata document to a path Claude never probes,
and the failure is silent: static-bearer auth keeps working (a valid header
never triggers a 401, so discovery is never exercised) while the real connector
reports only "Couldn't reach the MCP server" and the authorization server sees
no traffic at all. Nothing about that symptom points at the mount path, so the
route inventory is asserted here as an exact list instead.

``app.mcp.server`` is imported lazily inside the fixture, never at module scope.
It calls ``get_settings()`` and ``streamable_http_app()`` at import time, and
``conftest``'s session-scoped ``_default_mcp_env`` seeds those variables only
once the session starts -- which is *after* pytest has imported every test
module during collection. A module-scope import would therefore run the
bootstrap against an unseeded environment.

The file is in two halves. The **unit** half (the ``mcp_server`` fixture) needs
no container: every assertion is about static structure -- route paths, tool
registration, JSON schema shape -- so the session factory it builds is never
connected to. The **integration** half added by plan 02-04 drives the real
mounted app through ``TestClient`` and is marked accordingly; it exists because
the sub-app being correctly shaped and the sub-app being correctly *mounted* are
two different claims, and only the second one is what a deployed request meets.
"""

from collections.abc import Iterator
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --- The 2026-07-28 per-request envelope -----------------------------------
#
# `params._meta` is mandatory in this transport revision. Omit it and the server
# answers `-32602` ("params._meta must be an object carrying the required
# 'io.modelcontextprotocol/protocolVersion' and
# 'io.modelcontextprotocol/clientCapabilities' envelope keys") -- a *parse*
# error, not a routing or auth result. A test written without the envelope would
# therefore report the same 400 whether the mount was correct or absent, and
# would prove nothing (RESEARCH Pitfall 5).
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
# rather than imported: a test asserting against the very value it imports would
# pass even if the seeding fixture stopped running. `backend/tests/*` ignores
# S105/S106, so the literal needs no noqa.
AUTH = {"Authorization": "Bearer test-mcp-secret-not-a-real-credential"}


@pytest.fixture
def mcp_server() -> Iterator[ModuleType]:
    """The imported ``app.mcp.server`` module, with ``app.state`` wired.

    Entering ``Client(mcp)`` runs ``mcp_lifespan``, which reads
    ``app.state.sessionmaker``. Outside a ``TestClient`` the FastAPI lifespan has
    never run, so that attribute does not exist and the client would fail on
    ``AttributeError`` before any assertion. It is populated here with a real
    session factory over an engine that is never connected to: SQLAlchemy defers
    connection until first use, and ``tools/list`` issues no query.
    """
    from app.config import get_settings
    from app.main import app
    from app.mcp import server as mcp_server_module

    engine = create_async_engine(get_settings().async_database_url)
    preexisting = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield mcp_server_module
    finally:
        if preexisting is not None:
            app.state.sessionmaker = preexisting
        engine.sync_engine.dispose()


def test_mcp_subapp_owns_both_routes(mcp_server: ModuleType) -> None:
    """Both routes live at the sub-app's OWN root, so 02-04 must mount at ``/``."""
    paths = [route.path for route in mcp_server.mcp_app.routes]

    assert paths == ["/mcp", "/.well-known/oauth-protected-resource/mcp"], (
        "RESEARCH Pitfall 3: the sub-app must own both paths at its own root so "
        "`app.mount('/', mcp_app)` places them where Claude probes. Mounting at "
        f"'/mcp' instead would hide the metadata document. Got: {paths}"
    )


def test_session_manager_is_available(mcp_server: ModuleType) -> None:
    """``streamable_http_app()`` ran at import.

    The session manager is created lazily and ``mcp.session_manager`` raises
    ``RuntimeError`` until ``streamable_http_app()`` has been called. Plan
    02-04's FastAPI lifespan reads exactly this attribute to enter
    ``session_manager.run()``; without that, every MCP request 500s with
    "Task group is not initialized" (RESEARCH Pitfall 1).
    """
    assert mcp_server.mcp.session_manager is not None


async def test_ping_is_registered(mcp_server: ModuleType) -> None:
    """D-08: the Phase 2 canary is still on the registry.

    This asserted ``== ["fitness_ping"]`` until plan 06-09 registered the twelve
    Phase 6 tools beside it. The exact-registry claim did not disappear -- it
    MOVED, to ``test_mcp_tool_schemas.test_tool_registry_is_exactly_the_twenty_two``,
    which owns the whole tool surface. What belongs in this file is only the part
    that is about mounting: the ping tool the mount was proven against is still
    there.
    """
    from mcp import Client

    async with Client(mcp_server.mcp) as client:
        tools = (await client.list_tools()).tools

    assert "fitness_ping" in [tool.name for tool in tools]


async def test_ping_tool_hides_ctx_from_the_model(mcp_server: ModuleType) -> None:
    """``ctx`` must not appear as a tool argument.

    ``Context[AppContext]`` is stripped from ``inputSchema``; an unannotated
    ``ctx`` is not. A mis-annotated one surfaces here as
    ``{"ctx": {"type": "string"}}`` with ``ctx`` in ``required``, meaning the
    model is asked to invent a value for the server's own lifespan handle and
    every call fails schema validation. Asserted against the serialized
    (``by_alias``) form because that is the payload the model actually receives.

    Looked up BY NAME rather than by ``tools[0]``: positional indexing was
    correct only while one tool existed, and with sixteen registered it would
    silently start asserting against whichever tool the registry happens to
    order first.
    """
    from mcp import Client

    async with Client(mcp_server.mcp) as client:
        tools = (await client.list_tools()).tools

    ping = next(tool for tool in tools if tool.name == "fitness_ping")
    input_schema = ping.model_dump(by_alias=True)["inputSchema"]

    assert input_schema["properties"] == {}, (
        "`ctx` leaked into the model-facing tool schema -- check that it is "
        f"annotated `Context[AppContext]`. Got: {input_schema}"
    )


@pytest.mark.integration
def test_mcp_endpoint_is_routed(client: TestClient) -> None:
    """MCP-01: a request reaches the MCP server, and the task group is running.

    Two failures are separated here on purpose, because the mount looks correct
    in both. A `404` means `app.mount` never registered the sub-app. A `500`
    carrying "Task group is not initialized" means it did, but the parent
    lifespan never entered `mcp.session_manager.run()` -- Starlette does not run
    a mounted sub-application's lifespan, and that is exactly where
    `streamable_http_app()` puts the call (RESEARCH Pitfall 1).
    """
    response = client.post("/mcp", json=LIST_BODY, headers={**MCP_HDRS, **AUTH})

    assert response.status_code == 200, (
        f"MCP-01: expected 200 from the mounted endpoint, got "
        f"{response.status_code}. A 404 means the mount is missing; a 500 means "
        f"the lifespan is. Body: {response.text[:400]}"
    )
    assert "Task group is not initialized" not in response.text, (
        "RESEARCH Pitfall 1: `mcp.session_manager.run()` was never entered in "
        "the FastAPI lifespan, so the sub-app's task group does not exist."
    )


@pytest.mark.integration
def test_health_still_wins_after_mount(client: TestClient) -> None:
    """FOUND-01 survives a catch-all mount.

    `app.mount("/", mcp_app)` is a catch-all, and route-resolution order is the
    only thing keeping it from swallowing the platform health check Render
    polls. If it ever did, the symptom would be a service that deploys, passes
    nothing, and is marked unhealthy for a reason nothing in `health.py`
    explains.
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


@pytest.mark.integration
def test_openapi_and_docs_still_win_after_mount(client: TestClient) -> None:
    """FastAPI's own auto-generated routes are matched before the mount."""
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


@pytest.mark.integration
def test_unknown_path_still_404s(client: TestClient) -> None:
    """The catch-all must not turn every unknown path into a 200.

    A mount at `/` makes the MCP sub-app the handler of last resort for the
    entire URL space. This asserts it still declines what it does not own,
    rather than answering on behalf of routes that do not exist.
    """
    assert client.get("/definitely-not-a-route").status_code == 404


@pytest.mark.integration
def test_rejects_disallowed_host(client: TestClient) -> None:
    """T-02-01: `TransportSecuritySettings` is live, not disabled.

    This is the DNS-rebinding guard. The dangerous configuration is not a wrong
    `allowed_hosts` list -- that fails loudly and immediately -- but
    `enable_dns_rebinding_protection=False`, which makes every Host acceptable
    and produces a perfectly healthy-looking server. Asserting a foreign Host
    gets `421 Invalid Host header` is the only way to tell the two apart from
    the outside, and it fails the moment somebody "fixes" a 421 by turning the
    protection off (RESEARCH Pitfall 2).
    """
    response = client.post(
        "/mcp",
        json=LIST_BODY,
        headers={**MCP_HDRS, **AUTH, "Host": "wrong.example.com"},
    )

    assert response.status_code == 421
    assert "Invalid Host header" in response.text

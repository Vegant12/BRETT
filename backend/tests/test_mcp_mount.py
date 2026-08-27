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

No container is required. Every assertion here is about static
structure -- route paths, tool registration, JSON schema shape -- so the session
factory below is never connected to.
"""

from collections.abc import Iterator
from types import ModuleType

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
    app.state.sessionmaker = async_sessionmaker(
        engine, expire_on_commit=False, autoflush=False
    )
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


async def test_exactly_one_tool_registered(mcp_server: ModuleType) -> None:
    """D-08: one throwaway tool, and nothing else leaked into the tool surface."""
    from mcp import Client

    async with Client(mcp_server.mcp) as client:
        tools = (await client.list_tools()).tools

    assert [tool.name for tool in tools] == ["fitness_ping"]


async def test_ping_tool_hides_ctx_from_the_model(mcp_server: ModuleType) -> None:
    """``ctx`` must not appear as a tool argument.

    ``Context[AppContext]`` is stripped from ``inputSchema``; an unannotated
    ``ctx`` is not. A mis-annotated one surfaces here as
    ``{"ctx": {"type": "string"}}`` with ``ctx`` in ``required``, meaning the
    model is asked to invent a value for the server's own lifespan handle and
    every call fails schema validation. Asserted against the serialized
    (``by_alias``) form because that is the payload the model actually receives.
    """
    from mcp import Client

    async with Client(mcp_server.mcp) as client:
        tools = (await client.list_tools()).tools

    input_schema = tools[0].model_dump(by_alias=True)["inputSchema"]

    assert input_schema["properties"] == {}, (
        "`ctx` leaked into the model-facing tool schema -- check that it is "
        f"annotated `Context[AppContext]`. Got: {input_schema}"
    )

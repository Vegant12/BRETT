"""D-08: ``fitness_ping`` really reaches the database, and really degrades.

Two non-obvious choices, both deliberate.

**The in-memory ``mcp.Client`` bypasses ``RequireAuthMiddleware`` entirely, and
that is exactly what is wanted here.** Auth is proven over HTTP in
``test_mcp_auth.py``, where a 401 is unambiguous. Driving the tool through the
authenticated transport instead would fuse the two concerns: a tool that raised
and a credential that was rejected would both surface as "the call did not
return what I expected", and the first thing anyone would suspect is the token.
Splitting them means a failure here can only be the tool.

**The unreachable database is a REAL connection to closed port 1, never a
mock**, for the same reason ``test_health.py`` gives: a patched exception proves
the ``except`` branch runs, not that an actual driver error is what lands in it.
Connection failures are precisely where the DSN, the credentials, and the driver
internals live, so the leak assertion is only worth anything if the failure that
produced the payload was genuine (T-02-09).

The degrade path here is *not* the one ``/health`` takes. There is no status
code in an MCP tool result to carry the bad news, so the tool must still report
``is_error: false`` and express the failure in the payload as
``database="error"``. A tool that raised instead would reach the model as a
protocol-level error with an SDK-generated message -- which is exactly the
uncontrolled string this project refuses to let near a driver exception.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Mirrors `test_health.py:19`. Port 1 is reserved and never listening, so the
# connection fails immediately rather than hanging on a routable-but-silent host.
DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"


@pytest.mark.integration
async def test_ping_hits_database(client: TestClient) -> None:
    """Live container -> a real ``SELECT 1`` and a structured result.

    ``structured_content`` rather than the text block: returning a
    ``BaseModel`` is what populates it, and asserting on it proves the
    output-schema path Phase 6's analytics tools all depend on.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_ping", {})

    assert result.is_error is False
    assert result.structured_content == {"status": "ok", "database": "connected"}


@pytest.mark.integration
async def test_ping_degrades_cleanly(client: TestClient) -> None:
    """Unreachable database -> ``database="error"``, and still not an error result.

    The swap happens BEFORE ``async with Client(mcp)`` because ``mcp_lifespan``
    reads ``app.state.sessionmaker`` once, when the client context is entered,
    and hands the result to every tool call as ``AppContext``. Swapping after
    entry would leave the tool holding the healthy factory and the test would
    pass while proving nothing.

    ``app.state.sessionmaker`` is the attribute swapped, not
    ``app.state.engine`` -- the tool reads the factory, and ``/health`` reads the
    engine. The session-scoped engine is restored, never disposed: disposing a
    shared engine poisons every later test in the session.
    """
    from mcp import Client

    from app.mcp.server import mcp

    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    try:
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("fitness_ping", {})

        assert result.is_error is False, (
            "D-08: a database failure must degrade in the payload, not surface as "
            "a protocol-level tool error carrying an SDK-generated message."
        )
        assert result.structured_content == {"status": "ok", "database": "error"}
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()


@pytest.mark.integration
async def test_ping_degradation_leaks_nothing(client: TestClient) -> None:
    """T-02-09: not one byte of connection detail reaches the tool result.

    MCP tool output is model-facing and, through the transcript, user-facing.
    An asyncpg connection error carries the full DSN -- user, password, host,
    port, database -- so the degraded payload is where a credential would escape
    if the ``except`` branch ever started interpolating the exception.
    """
    from mcp import Client

    from app.mcp.server import mcp

    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    try:
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("fitness_ping", {})

        rendered = f"{result.structured_content}{result.content}"
        for leak in ("nobody", "nopass", "127.0.0.1", "nodb", "asyncpg", "Traceback"):
            assert leak not in rendered, (
                f"FOUND-05/T-02-09 violated: {leak!r} leaked into the tool result"
            )
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()


@pytest.mark.integration
async def test_ping_output_schema_requires_both_fields(client: TestClient) -> None:
    """Both fields are advertised as required, so neither can go missing silently.

    ``status`` alone would let a future refactor drop ``database`` and still
    satisfy the schema -- and the dropped field is the entire point of the tool.
    Asserted against the serialized (``by_alias``) form because that is the
    payload the model actually receives.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    output_schema = tools[0].model_dump(by_alias=True)["outputSchema"]

    assert set(output_schema["required"]) == {"status", "database"}
    assert set(output_schema["properties"]) == {"status", "database"}

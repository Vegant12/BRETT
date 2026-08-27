"""Lifespan context handed to every MCP tool (MCP-01).

The context BORROWS ``app.state.sessionmaker`` and must never call
``make_engine()``. A second engine here would bind its own pool to this
lifespan's event loop, double the connection count against a free-tier Postgres
that allows very few, and silently diverge from the engine ``/health`` probes --
so the health check could report ``connected`` while every tool call failed.

``from app.main import app`` is deliberately inside the function body: ``main``
imports ``app.mcp.server``, which imports this module, so a module-scope import
would be circular. Deferring it to startup breaks the cycle, and it is safe
because ``mcp_lifespan`` runs once at startup -- after the FastAPI lifespan has
already assigned ``app.state.sessionmaker`` -- not per request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from mcp.server import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()


@dataclass(slots=True)
class AppContext:
    """What every MCP tool is handed. Borrowed, never owned."""

    sessionmaker: async_sessionmaker[AsyncSession]


@asynccontextmanager
async def mcp_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Yield the tool context, sourced from the FastAPI app's state."""
    from app.main import app

    log.info("mcp_lifespan_starting")
    try:
        yield AppContext(sessionmaker=app.state.sessionmaker)
    finally:
        log.info("mcp_lifespan_stopped")

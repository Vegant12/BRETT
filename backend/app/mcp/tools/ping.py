"""Database connectivity tool (D-08, MCP-01).

Throwaway in scope, permanent in shape: Phase 6 replaces this tool but not the
path it proves. A bare echo tool would show only that the transport responds; a
real ``SELECT 1`` through ``ctx.request_context.lifespan_context.sessionmaker``
proves the lifespan-wired session factory that every real analytics tool depends
on.

``ctx`` MUST be annotated ``Context[AppContext]``. With no annotation the SDK
exposes it to the model as a required string argument (``"properties": {"ctx":
{"type": "string"}}``) and every call fails schema validation.
"""

import structlog
from mcp.server.mcpserver import Context
from pydantic import BaseModel
from sqlalchemy import text

from app.mcp.context import AppContext

log = structlog.get_logger()


class PingResult(BaseModel):
    """Returning a BaseModel auto-populates outputSchema and structuredContent."""

    status: str
    database: str


async def fitness_ping(ctx: Context[AppContext]) -> PingResult:
    """Round-trip the database through the lifespan-wired session factory."""
    database = "connected"
    try:
        sessionmaker = ctx.request_context.lifespan_context.sessionmaker
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not error
        # Mirrors health.py: the detail goes to the log (which runs through the
        # redaction pipeline); the caller gets only the coarse state. Connection
        # errors carry the DSN, host, and driver internals (T-02-09, FOUND-05).
        log.exception("mcp_ping_db_check_failed")
        database = "error"
    return PingResult(status="ok", database=database)

"""Service health endpoint (FOUND-01).

The database field is a LIVE probe, never a cached or assumed value: a health
check that reports what it believes rather than what it just measured is worse
than no health check at all, because Render will keep routing traffic to a
service whose database has gone away.
"""

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Report service status plus a live database connectivity check.

    D-03: the body is minimal -- ``{status, database}`` and nothing else. No
    Alembic revision, environment name, uptime, version, or hostname. This
    endpoint is unauthenticated (D-04) so Render's platform health check and
    uptime monitors can reach it without a token, which means everything in the
    body is public by construction.
    """
    database = "connected"
    status_code = 200
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not 500
        # The detail goes to the log (which runs through the redaction pipeline);
        # the client gets only the coarse state. Connection errors carry the DSN,
        # host, and driver internals (D-05, FOUND-05).
        log.exception("health_db_check_failed")
        database, status_code = "error", 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if status_code == 200 else "degraded", "database": database},
    )

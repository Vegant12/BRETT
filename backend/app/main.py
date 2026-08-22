"""FastAPI application bootstrap.

Bootstrap order is load-bearing: configuration is read first so a misconfigured
process dies immediately, then logging is configured -- the value scrubber needs
``settings.secret_values()`` -- and only then is the app object built. Any log
line emitted before ``configure_logging`` would bypass redaction entirely.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import health
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging import configure_logging

settings = get_settings()  # fail-fast BEFORE anything else
configure_logging(settings)  # then logging, so the scrubber has the secret values
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan.

    The engine is created here and NEVER at module import: a module-level engine
    binds its pool to whichever event loop imported it, which breaks under
    pytest-asyncio and leaks connections between tests.

    Migrations are deliberately absent -- ``alembic upgrade head`` runs
    out-of-band (a Render pre-deploy command), because startup migrations race
    across restarts.
    """
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("service_stopped")


app = FastAPI(title="BRETT", lifespan=lifespan)

# Pure-ASGI middleware, not BaseHTTPMiddleware -- the ContextVar it sets must stay
# readable inside the exception handler below.
app.add_middleware(CorrelationIdMiddleware)

# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)


# D-05: identical behavior in EVERY environment. No traceback ever reaches the
# client; the full traceback goes to the log, findable by correlation id.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error", "correlation_id": correlation_id.get()},
    )

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

from app.config import get_settings
from app.logging import configure_logging

settings = get_settings()  # fail-fast BEFORE anything else
configure_logging(settings)  # then logging, so the scrubber has the secret values
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan.

    Deliberately has no database engine: Plan 01-05 adds ``app.state.engine`` and
    ``app.state.sessionmaker`` here alongside the health router.
    """
    log.info("service_starting", environment=settings.environment)
    try:
        yield
    finally:
        log.info("service_stopped")


app = FastAPI(title="BRETT", lifespan=lifespan)

# Pure-ASGI middleware, not BaseHTTPMiddleware -- the ContextVar it sets must stay
# readable inside the exception handler below.
app.add_middleware(CorrelationIdMiddleware)


# D-05: identical behavior in EVERY environment. No traceback ever reaches the
# client; the full traceback goes to the log, findable by correlation id.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error", "correlation_id": correlation_id.get()},
    )

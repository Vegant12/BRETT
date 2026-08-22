"""FOUND-01: ``GET /health`` reports service status plus a LIVE database check.

Both directions are proven here. The failure direction matters most: a health
endpoint that is deliberately unauthenticated (D-04) and reachable from the
public internet must degrade without disclosing the DSN, the driver, or a
traceback (D-03 / D-05 / FOUND-05).

The unreachable database is simulated with a REAL connection to a closed port
rather than a mock -- the point of the test is that an actual failed connection
degrades cleanly. Port 1 is reserved and never listening, and ``timeout: 1``
keeps the failure immediate. The shared session-scoped engine is never disposed
(that would poison every later test); it is swapped out and restored instead.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"


@pytest.mark.integration
def test_health_reports_connected(client: TestClient) -> None:
    """Live database -> 200 and a minimal body (D-03)."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


@pytest.mark.integration
def test_health_reports_db_error(client: TestClient) -> None:
    """Unreachable database -> 503, and not one byte of connection detail."""
    app = client.app
    original = app.state.engine
    dead = create_async_engine(
        DEAD_DB_URL,
        connect_args={"timeout": 1},
        pool_pre_ping=False,
    )
    app.state.engine = dead
    try:
        response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {"status": "degraded", "database": "error"}
        for leak in ("nobody", "nopass", "127.0.0.1", "asyncpg", "Traceback"):
            assert leak not in response.text, (
                f"FOUND-05/D-03 violated: {leak!r} leaked into the /health body"
            )
    finally:
        app.state.engine = original


@pytest.mark.integration
def test_health_is_open(client: TestClient) -> None:
    """D-04: no credential of any kind is required.

    Render's platform health check and uptime monitors call this endpoint
    without a token, so an auth dependency here would break deployment.
    """
    client.cookies.clear()

    response = client.get("/health", headers={})

    assert response.status_code not in (401, 403)

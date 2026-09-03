"""The Health Auto Export webhook receiver (HEALTH-06, HEALTH-07).

The user's iPhone runs a Health Auto Export REST automation that POSTs a window of Apple Health
metrics here on a schedule. Nothing else calls this path. There is no browser, no session, no
cookie and no second tenant: one phone, one shared secret, one write path.

Registration order is load-bearing (RESEARCH Pitfall 1)
------------------------------------------------------
This router MUST be registered ABOVE ``app.mount("/", mcp_app)`` in ``app/main.py``. That mount
is a catch-all and is registered last on purpose, so a route added BELOW it is dead in
production while every unit test that builds its own app still passes.
``test_secret_redaction.py`` already had to re-append the mount after adding a route at test
time -- that is the existing evidence this is real rather than theoretical, and it is why
``test_health_ingest_route.py`` drives the real ``app`` object over HTTP instead of a hand-built
one.

This route inherits ZERO auth (RESEARCH Pitfall 3)
--------------------------------------------------
The MCP SDK's ``RequireAuthMiddleware`` wraps only ``mcp_app``. A FastAPI route on ``app``
itself is reachable by anyone on the internet, because the Cloud Run service is deployed
``--allow-unauthenticated`` so that Claude's anonymous RFC 9728 discovery fetch can succeed.
The credential check in this handler is therefore the ENTIRE access control for a write path
into health data, and ``test_no_unauthenticated_fastapi_route_was_added`` pins the FastAPI route
inventory so a future addition fails the suite rather than shipping.

Fail closed, and say so out loud
--------------------------------
An unset ``health_ingest_secret`` means every request gets a bare 401: an unconfigured
deployment has a DISABLED ingest path, never an open one. There is deliberately no boot-time
raise -- that would break every developer and test environment for no security gain, since the
production guarantee comes from ``test_cloud_run_deploy.py``'s assertion that the
``--set-secrets`` binding for ``HEALTH_INGEST_SECRET`` exists in the deploy script.

The order of the checks is the design
-------------------------------------
**Credential, then size, then parse.**

* Authenticating FIRST means an unauthenticated flood never gets as far as buffering a body: an
  anonymous request costs one header lookup and one constant-time compare (T-08-46).
* Capping BEFORE the parse means an oversized body is a diagnosable 413 rather than an OOM that
  Cloud Run reports as a bare 503 with no application log line to explain it (RESEARCH Pitfall
  5, T-08-45). ``Content-Length`` is checked first because it costs nothing, and the stream is
  then capped as it is read, because that header is optional and attacker-controlled.

Nothing leaves here that a caller could not already compute
-----------------------------------------------------------
The 401 and 413 bodies can be produced by anyone on the internet, so they carry one key each and
never say which of the several rejection reasons applied. The 202 body is four integer counts
and a status string: a calorie figure is personal health data and must not appear in a response
the caller is free to log (ASVS V8, T-08-48).
"""

from typing import Final

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import DEFAULT_USER_ID, get_settings
from app.integrations.health_auto_export.auth import verify_bearer
from app.integrations.health_auto_export.errors import HAEPayloadError
from app.integrations.health_auto_export.ingest import ingest_payload, parse_payload

# The prefix MUST stay under `middleware.INGEST_PATH_PREFIX` ("/api/v1/ingest/") or the request
# silently draws from the bucket Claude's connector shares, and a burst of phone exports 429s
# the next tool call mid-coaching-turn (RESEARCH Pitfall 2).
router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])
log = structlog.get_logger()

# The exact key set of each rejection body. ONE key each, asserted by test: this endpoint can be
# made to emit these bodies by anyone on the internet, so they must never grow a field that
# echoes the presented credential, an exception detail, or anything about why the check failed.
_UNAUTHORIZED_BODY: Final = {"error": "unauthorized"}
_TOO_LARGE_BODY: Final = {"error": "payload_too_large"}
_INVALID_PAYLOAD_BODY: Final = {"error": "invalid_payload"}


@router.post("/health-auto-export")
async def ingest_health_auto_export(request: Request) -> JSONResponse:
    """Authenticate, bound, parse, ingest, and answer with counts.

    There is deliberately NO ``try``/``except`` around ``ingest_payload``. ``app/main.py``'s
    global handler already returns ``{"error": "internal server error", "correlation_id": ...}``
    with no traceback, identically in every environment (D-05, T-08-51). A route-level handler
    would either duplicate that or, worse, diverge from it -- so the omission is a decision, and
    this paragraph is where it is recorded.
    """
    settings = get_settings()

    # 1. CREDENTIAL FIRST -- before a single byte of body is read. Fails closed on an unset
    #    secret. The log line says only that a rejection happened: never the presented value,
    #    never which of the three reasons applied (T-08-44).
    secret = settings.health_ingest_secret
    if secret is None or not verify_bearer(
        request.headers.get("authorization"), secret.get_secret_value()
    ):
        log.warning("health_ingest_unauthorized")
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 2. SIZE CAP -- before the parse. The declared length is checked first because it costs
    #    nothing, then the stream is capped as it is read, because Content-Length is optional
    #    and attacker-controlled. RESEARCH Pitfall 5: without this the instance OOMs and Cloud
    #    Run answers 503 with no application log line.
    cap = settings.ingest_max_body_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        log.warning("health_ingest_payload_too_large", declared_bytes=int(declared), cap=cap)
        return JSONResponse(status_code=413, content=_TOO_LARGE_BODY)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > cap:
            log.warning("health_ingest_payload_too_large", read_bytes=len(body), cap=cap)
            return JSONResponse(status_code=413, content=_TOO_LARGE_BODY)

    # 3. PARSE -- inside the quarantine boundary, and therefore inside the HAE package rather
    #    than here. `test_health_auto_export_isolation.py` forbids a route importing HAE's wire
    #    schemas by name, so `parse_payload` owns the model and this handler only holds its
    #    result. Never the exception's rendered text: a pydantic ValidationError renders
    #    `input_value=...`, i.e. this person's calorie counts, into a log line -- which is why
    #    `parse_payload` raises the value-free `HAEPayloadError` rather than letting that
    #    exception escape, and why only the class NAME is logged here (T-08-47).
    try:
        payload = parse_payload(bytes(body))
    except HAEPayloadError as exc:
        log.warning("health_ingest_payload_rejected", reason=type(exc).__name__)
        return JSONResponse(status_code=400, content=_INVALID_PAYLOAD_BODY)

    # 4. INGEST. `user_id` is resolved SERVER-SIDE from a module constant (ASVS V4, T-08-49).
    #    Health Auto Export cannot supply a tenant and must not be able to.
    result = await ingest_payload(
        request.app.state.sessionmaker, user_id=DEFAULT_USER_ID, payload=payload
    )

    # 5. COUNTS ONLY (ASVS V8). Never a value, never a metric's stored quantity.
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "rows_upserted": result.rows_upserted,
            "rows_skipped": result.rows_skipped,
            "datapoints_seen": result.datapoints_seen,
            "metrics_unrecognized": result.metrics_unrecognized,
        },
    )

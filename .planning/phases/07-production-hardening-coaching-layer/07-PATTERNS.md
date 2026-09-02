# Phase 7: Production Hardening & Coaching Layer - Pattern Map

**Mapped:** 2026-09-01
**Files analyzed:** 15 (9 new, 6 modified)
**Analogs found:** 14 / 15

> **Read this before planning.** Every excerpt below was read out of the live repo at the line
> numbers given. Where a pattern is *inverted* (a thing the analog does that the new file must
> NOT do), that is called out explicitly — Phase 7's highest-risk files are the ones whose
> closest analog is 80% right.

---

## File Classification

| New/Modified File | New? | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `backend/app/middleware.py` | NEW | middleware | request-response | `backend/app/mcp/auth.py` (single-module cross-cutting policy object) + `backend/app/api/routes/health.py` (degrade-don't-leak response shaping) | partial — **no ASGI middleware exists in this repo** |
| `backend/app/main.py` | MODIFY | config/bootstrap | request-response | itself, lines 62–77 | exact |
| `backend/app/config.py` | MODIFY | config | — | itself, lines 76–93 (`mcp_auth_mode`, `mcp_allowed_hosts_raw`) | exact |
| `deploy/cloud-run.env.yaml` | MODIFY | config | — | itself, lines 14–52 | exact |
| `backend/tests/test_rate_limit.py` | NEW | test | request-response | `backend/tests/test_mcp_auth.py` (unit/over-HTTP split + exact-key-set leak test) | exact |
| `backend/tests/test_full_chain_end_to_end.py` | NEW | test (integration) | batch composition | `backend/tests/test_hevy_end_to_end.py` (mock+cleanup) fused with `backend/tests/test_mcp_mount.py::mcp_server` (state wiring) | role-match (two half-analogs) |
| `backend/tests/test_coaching_doc.py` | NEW | test | file-I/O + static assertion | `backend/tests/test_cloud_run_deploy.py` (static assertions over committed files) | exact |
| `backend/tests/test_mcp_tool_schemas.py` | MODIFY | test | — | itself, lines 278–307 | exact |
| `docs/coaching-instructions.md` | NEW | doc | — | `docs/hevy-api-observations.md` | role-match |
| `docs/runbook-secret-rotation.md` | NEW | runbook doc | — | `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md` §"Auth Verification Matrix (deployed)" (L236–310) | exact |
| `docs/runbook-backup-restore.md` | NEW | runbook doc | — | same as above | exact |
| `scripts/verify-restore.sql` | NEW | script (SQL) | batch | `backend/tests/conftest.py::_mcp_purge_statements` (table inventory + FK order) | partial |
| `scripts/deploy-sync-job.sh` (D-10) | NEW | deploy script | batch/scheduled | `scripts/deploy-cloud-run.sh` | exact |
| `backend/tests/test_sync_job_deploy.py` **or** extension to `test_cloud_run_deploy.py` (D-10) | NEW/MODIFY | test | file-I/O + static assertion | `backend/tests/test_cloud_run_deploy.py` | exact |
| `.planning/phases/07-.../07-COACH-VERIFICATION.md` (D-09) | NEW | verification record | — | `.planning/phases/02-.../02-VERIFICATION.md` | exact |
| `README.md` (line 75) | MODIFY | doc | — | itself | exact |

---

## Pattern Assignments

### `backend/app/middleware.py` (middleware, request-response) — NEW

**Analogs:** `backend/app/mcp/auth.py` (module shape), `backend/app/api/routes/health.py` (degrade
discipline), `backend/app/main.py:62–77` (registration site).
**Match quality: partial — this is the one genuinely new *kind* of module in the phase.** There is
exactly one `add_middleware` call in the whole codebase (`main.py:66`) and it registers a
third-party class. Nothing in `backend/app/` implements `__call__(scope, receive, send)`. The
planner must not expect a drop-in analog; it must copy *conventions* from the modules below.

**Module docstring convention** — every cross-cutting module in `backend/app/` opens with a
why-not-what docstring naming the requirement ID, the load-bearing invariant, and the pitfall it
guards. Copy the shape from `backend/app/logging.py:1–28` and `backend/app/mcp/auth.py`:

```python
# backend/app/main.py:1-7 -- the canonical shape
"""FastAPI application bootstrap.

Bootstrap order is load-bearing: configuration is read first so a misconfigured
process dies immediately, then logging is configured -- the value scrubber needs
``settings.secret_values()`` -- and only then is the app object built. Any log
line emitted before ``configure_logging`` would bypass redaction entirely.
"""
```

The new module's docstring MUST carry (per RESEARCH Pitfalls 3, 5, 10): the pure-ASGI requirement,
the per-instance-bucket multiplier (`--max=2` in `scripts/deploy-cloud-run.sh:24`), and the
`X-Forwarded-For` advisory-only caveat.

**Logger pattern** (copy verbatim; `backend/app/main.py:26`, `backend/app/api/routes/health.py:15`,
`backend/app/cli.py`):

```python
import structlog

log = structlog.get_logger()
```

Module-level, named `log`, never `logger`. The redaction chain is already installed by
`configure_logging` at `main.py:25` — the new middleware needs no logging setup of its own, and the
rejection log line **must not** include the `Authorization` header or the raw `X-Forwarded-For`
value (`app/logging.py:41–69` `DENY_KEYS` covers `authorization`, but a raw XFF string is not on
that list, so it must not be logged at all).

**Degrade-without-leaking pattern** (`backend/app/api/routes/health.py:29–41`) — the closest
existing example of "build a minimal literal response body, put the detail in the log":

```python
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
```

Note the D-03 comment above it (`health.py:22–26`): *"the body is minimal — `{status, database}`
and nothing else."* The 429 body inherits that rule exactly (RESEARCH Pitfall 8).

**Injected-clock pattern** — the project's established seam for making a time-dependent component
testable is a constructor parameter, proven by `HevyClient(sleep=...)`:

```python
# backend/tests/test_hevy_end_to_end.py:92-97
async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The predicate and the attempt count stay real."""


def _client(**kwargs: Any) -> HevyClient:
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)
```

Copy this shape for `clock: Callable[[], float] = time.monotonic` (RESEARCH Pitfall 4 —
`time-machine` does not patch `time.monotonic()`).

**Fail-fast-at-import pattern** for config-derived construction (`backend/app/mcp/auth.py:117–141`):

```python
def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Select the verifier for the configured auth mode.

    Fails fast at import time rather than at first request: a server that starts
    without a working verifier is a server that is unauthenticated in production
    until someone notices. ...
    """
    if settings.mcp_auth_mode == "authkit":
        ...
```

A `build_limiter(settings) -> RateLimitMiddleware`-style factory belongs here, mirroring
`build_token_verifier`'s name and signature (`(settings: Settings) -> X`).

**Type-annotation requirement:** `pyproject.toml:82` sets `disallow_untyped_defs = true` and
`pyproject.toml:66` selects `S` (bandit) and `DTZ`. Every function including `__call__` needs full
annotations; import types from `starlette.types` (`ASGIApp, Message, Receive, Scope, Send`).

**INVERTED — do NOT copy:** `main.py` uses FastAPI's `JSONResponse`. The limiter must send raw ASGI
`http.response.start` / `http.response.body` messages instead (RESEARCH Pitfall 5 — the `/mcp`
endpoint is `text/event-stream`; `BaseHTTPMiddleware` and response-object materialisation break it).

---

### `backend/app/main.py` (config/bootstrap, MODIFY)

**Analog:** itself.

**Registration site + the comment that already mandates pure-ASGI** (lines 62–77):

```python
app = FastAPI(title="BRETT", lifespan=lifespan)

# Pure-ASGI middleware, not BaseHTTPMiddleware -- the ContextVar it sets must stay
# readable inside the exception handler below.
app.add_middleware(CorrelationIdMiddleware)

# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)

# MCP-01: mounted at "/" and NOT at "/mcp". ...
app.mount("/", mcp_app)
```

**Ordering rule (load-bearing):** `add_middleware` **prepends**, so the last one added runs first.
Per RESEARCH § *Pattern 1*, insert the limiter **before** the `CorrelationIdMiddleware` line so the
correlation id is set first and the `rate_limit_rejected` log line carries it:

```python
app.add_middleware(RateLimitMiddleware, limiter=build_limiter(settings))
app.add_middleware(CorrelationIdMiddleware)
```

The existing comment block at 64–65 is the precedent for annotating *why* the ordering is what it
is — extend it, don't replace it.

---

### `backend/app/config.py` (config, MODIFY)

**Analog:** itself, lines 68–93.

**Non-secret field pattern with a justifying comment** (lines 68–93). The new
`rate_limit_per_minute` / `rate_limit_burst` fields sit in the same block and follow the same
discipline — plain typed fields with defaults, an explicit note on why they are *not* secrets:

```python
    # MCP transport/auth configuration. NOT secrets: these are public hostnames
    # and URLs that appear in the RFC 9728 metadata document Claude fetches
    # anonymously. They must stay OUT of `_SECRET_FIELDS` -- adding a public
    # hostname to the value scrubber would redact it from every log line and
    # make the logs unreadable.
    mcp_auth_mode: Literal["static", "authkit"] = "static"
    mcp_issuer_url: str = "https://example.authkit.app"
```

**Do NOT add the new fields to `_SECRET_FIELDS`** (`config.py:25`) — a rate limit is not a
credential, and `secret_values()` (lines 138–157) feeds the log scrubber.

**Test-side companion** (`backend/tests/test_config.py:17–35`): `_clean_env` deletes every env var
by name. New `RATE_LIMIT_*` vars must be added to that tuple, or a developer's `.env` decides a
test outcome.

---

### `deploy/cloud-run.env.yaml` (config, MODIFY)

**Analog:** itself.

Flat `KEY: "value"` string mapping with a comment block per key explaining what breaks if it is
wrong (lines 17–31):

```yaml
# Host allowlist for the MCP transport's DNS-rebinding guard. Cloud Run forwards
# the ORIGINAL public Host header to the container, so this must name the real
# hostname or every request answers `421 Invalid Host header` with no MCP-level
# error body (T-02-01). Comma-separated: ...
MCP_ALLOWED_HOSTS: "brett-792870654598.us-central1.run.app,brett-cglno6k2xq-uc.a.run.app"
```

**Two hard constraints enforced by test, read `backend/tests/test_cloud_run_deploy.py` first:**

1. Values must be **strings** (quoted) — `test_env_file_parses_to_a_flat_string_mapping`, L109–126.
   `RATE_LIMIT_PER_MINUTE: 30` (unquoted int) fails the fast suite.
2. Key names must not contain `SECRET|KEY|TOKEN|PASSWORD|DATABASE_URL` —
   `_SECRET_NAME_MARKERS`, L46, enforced by `test_no_credential_shaped_key_is_present` (L172–187).
   `RATE_LIMIT_*` is safe; a name like `RATE_LIMIT_API_KEY` would not be.

**The bidirectional drift guard** (`test_every_env_var_maps_to_a_settings_field`, L128–139, and
`test_env_file_and_secret_bindings_partition_the_environment`, L257–284):

```python
def _settings_env_names() -> set[str]:
    """Every environment-variable name ``Settings`` will actually read. ..."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
    return names
```

Adding the fields to `Settings` alone requires no env-file change (defaults apply). Adding a key to
the env file with no matching `Settings` field fails immediately. This is why RESEARCH says "read
`test_cloud_run_deploy.py` before touching either file".

---

### `backend/tests/test_rate_limit.py` (test, request-response) — NEW

**Analog:** `backend/tests/test_mcp_auth.py` — exact structural match. That module is the repo's
model for "unit half + over-HTTP half in one file", and it owns the exact-key-set leak discipline
Pitfall 8 tells the 429 to copy.

**File structure (copy the split and the docstring that explains it)** — `test_mcp_auth.py:1–15`:

```python
"""Unit tests for the MCP bearer-token verifier (MCP-04).

These test the verifier **directly**, not over HTTP, and that is deliberate. ...
Splitting the concern:

* **here** -- the verifier's decision function: what it accepts, what it denies,
  and that it denies in constant time.
* **over HTTP** (plan 02-04's mount tests) -- the wire contract: ...

Proving the decision function here means the HTTP tests only have to prove the
plumbing, not re-derive every rejection case through a transport.
"""
```

Map: **unit half** = `TokenBucket.take()` with a fake clock (fast, no marker, no container);
**over-HTTP half** = `@pytest.mark.integration` + the `client` fixture.

**The exact-key-set leak assertion — copy this test almost verbatim for the 429**
(`test_mcp_auth.py:581–612`):

```python
@pytest.mark.integration
def test_401_leaks_nothing(client: TestClient) -> None:
    """T-02-04: the rejection body is two fields and nothing else.

    The exact key set is asserted, not merely the absence of known-bad strings.
    This endpoint is unauthenticated by definition -- anyone on the internet can
    make it emit this body -- so the failure mode worth guarding is an SDK
    upgrade that helpfully starts including the presented token, the configured
    issuer, or an exception detail in the error payload. A substring check would
    not notice a new field; a key-set check cannot miss it.
    """
    response = client.post(
        "/mcp",
        json=LIST_BODY,
        headers={**MCP_HDRS, "Authorization": f"Bearer {BAD_TOKEN}"},
    )

    assert response.status_code == 401
    assert set(response.json()) == {"error", "error_description"}, (
        f"FOUND-05/T-02-04: the 401 body grew a field. Got: {response.json()}"
    )
    for leak in (
        "test-mcp-secret-not-a-real-credential",
        BAD_TOKEN,
        "postgresql",
        "asyncpg",
        "127.0.0.1",
        "Traceback",
    ):
        assert leak not in response.text, (
            f"FOUND-05/T-02-04 violated: {leak!r} leaked into the 401 body"
        )
```

For the 429: `assert set(response.json()) == {"error"}` plus the same leak-marker loop.

**Wire-envelope constants — duplicate, never import** (`test_mcp_auth.py:76–102`; the identical
block also lives at `test_mcp_mount.py:36–62`). This is a stated project rule:

```python
# --- Wire-contract constants (see `test_mcp_mount.py` for the same block) -----
#
# Defined here rather than imported from that module: test modules in this repo
# do not import each other, and a shared fixture file would hide which envelope
# a given assertion actually sent. `params._meta` is mandatory in the 2026-07-28
# transport -- omit it and the server answers `-32602` (RESEARCH Pitfall 5).
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
# rather than imported. `backend/tests/*` ignores S105/S106.
AUTH = {"Authorization": "Bearer test-mcp-secret-not-a-real-credential"}
```

**Exemption tests — copy the framing from** `test_mcp_mount.py:185–198`, which already guards the
identical failure class (a catch-all swallowing `/health`):

```python
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
```

→ `test_health_is_never_rate_limited` and `test_discovery_document_is_never_rate_limited`
(RESEARCH Pitfall 7). The discovery-document analog is `test_mcp_auth.py:615–641`
(`test_protected_resource_metadata_path`, no auth header — it is deliberately anonymous).

**Log-capture pattern for `rate_limit_rejected`** (`test_secret_redaction.py:100–107`; the same
block appears at `test_hevy_end_to_end.py:488–505` with save/restore of the root handlers):

```python
def _configure(monkeypatch: pytest.MonkeyPatch, environment: str = "development") -> io.StringIO:
    """Install the real pipeline, then point its single handler at a buffer."""
    configure_logging(_settings(monkeypatch, environment))
    buf = io.StringIO()
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(buf)
    return buf
```

**INVERTED — do NOT use `structlog.testing`.** `test_hevy_end_to_end.py:490–493` states why: it
"clears the configured processor chain for its duration and would leave this test green over a
redaction layer that never ran".

---

### `backend/tests/test_full_chain_end_to_end.py` (test, batch composition) — NEW

**Analogs:** two half-analogs, fused. `test_hevy_end_to_end.py` owns the Hevy→Postgres half;
`test_mcp_mount.py::mcp_server` owns the Postgres→MCP half. RESEARCH § *Pattern 2* is explicit that
this must be a **new module**, not an extension of `test_hevy_end_to_end.py`.

**Module docstring pattern** (`test_hevy_end_to_end.py:1–12`) — states scope, the mocking rule, and
the cleanup rule up front:

```python
"""mock-Hevy -> PostgreSQL -> normalized state, in one run (ROADMAP Phase 3 criteria 1-5).

Every other Hevy test in this suite covers one driver. This one covers the composition: a
single `sync_all` against a fully mocked Hevy, then a second `sync_all` that must take the
incremental path, against a real Postgres container.

Mocking rule (conftest, Pitfall 3): RESPONSES use `httpx.Response` (0.x, the type respx
asserts on); EXCEPTIONS use `httpx2` types.

Cleanup is a per-test `finally` rather than a fixture teardown: the container is session-scoped
and shared, so a row that outlives its test changes the result of the next one.
"""
```

**Hevy mock helpers — COPY these into the new module** (`test_hevy_end_to_end.py:112–151`; RESEARCH
Pitfall 6 warns that respx asserts every registered route was called, so do not register `/events`):

```python
def _mock_hevy(
    mock: Router,
    *,
    workout_pages: dict[int, dict[str, Any]] | None = None,
    remote_count: int = 2,
) -> dict[str, Route]:
    """Serve every endpoint the FULL path reaches, repeatably.

    The events feed is deliberately NOT registered here: respx asserts every registered route
    was called, so a run that legitimately never goes incremental would fail on teardown for
    a route it was right not to touch. ...

    CALLABLE side effects rather than a list of pre-built responses: an `httpx.Response` is a
    one-shot object whose stream is consumed on first use, ...
    """
    pages = workout_pages if workout_pages is not None else _both_workout_pages()

    def _serve_workouts(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in pages, f"the sync requested workouts page {page}, which was not mocked"
        return httpx.Response(200, json=pages[page])
    ...
    # `/v1/workouts/count` is registered FIRST: respx resolves routes in registration order,
    # and a `/v1/workouts` route added ahead of it would be the one that answered.
    return {
        "count": mock.get(WORKOUT_COUNT).mock(side_effect=_serve_count),
        "workouts": mock.get(WORKOUTS).mock(side_effect=_serve_workouts),
        "templates": mock.get(TEMPLATES).mock(side_effect=_serve_templates),
        "body": mock.get(MEASUREMENTS).mock(side_effect=_serve_body),
    }
```

Also copy the import comment at `test_hevy_end_to_end.py:19`:
`import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)`

**Service construction helpers** (`test_hevy_end_to_end.py:92–106`):

```python
async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The predicate and the attempt count stay real."""


def _client(**kwargs: Any) -> HevyClient:
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _service(client: HevyClient, maker: async_sessionmaker[AsyncSession]) -> HevySyncService:
    return HevySyncService(client, maker, user_id=DEFAULT_USER_ID)
```

**Compensating-DELETE cleanup — mandatory, `sync_all()` commits**
(`test_hevy_end_to_end.py:163–179`):

```python
async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove every row this module can have committed, pass or fail."""
    async with maker() as session:
        for statement in (
            sa.delete(Workout).where(Workout.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscle).where(ExerciseMuscle.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscleOverride).where(
                ExerciseMuscleOverride.user_id == DEFAULT_USER_ID
            ),
            sa.delete(ExerciseTemplate).where(ExerciseTemplate.user_id == DEFAULT_USER_ID),
            sa.delete(BodyMeasurement).where(BodyMeasurement.user_id == DEFAULT_USER_ID),
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER_HEVY
            ),
        ):
            await session.execute(statement)
        await session.commit()
```

Used as a per-test `try/finally` (`test_hevy_end_to_end.py:238–256`):

```python
@pytest.mark.integration
async def test_sync_all_on_a_virgin_database_takes_the_full_path(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            report = await _service(client, maker).sync_all()
        ...
        counts = await _counts(maker)
        assert counts["workouts"] == 2
        assert counts["workout_sets"] == 4
        assert counts["exercise_templates"] == 4
        assert counts["body_measurements"] == 2
    finally:
        await _cleanup(maker)
```

Those four numbers (L250–254) are the verified fixture arithmetic RESEARCH § *Pattern 2* refers to.

**MCP-half state wiring — copy `test_mcp_mount.py:65–88` (save / assign / restore in `finally`):**

```python
@pytest.fixture
def mcp_server() -> Iterator[ModuleType]:
    """The imported ``app.mcp.server`` module, with ``app.state`` wired.

    Entering ``Client(mcp)`` runs ``mcp_lifespan``, which reads
    ``app.state.sessionmaker``. Outside a ``TestClient`` the FastAPI lifespan has
    never run, so that attribute does not exist and the client would fail on
    ``AttributeError`` before any assertion. ...
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
```

**MODIFICATION for this file:** the sessionmaker must be built over the **testcontainer `engine`
fixture** the sync wrote through, not `create_async_engine(get_settings().async_database_url)` —
otherwise the tool queries a different database (RESEARCH § *Pattern 2*, mechanic 2).

**Lazy import rule — repeated inside every test, never at module scope**
(`test_mcp_tool_schemas.py:16–19`):

```python
"""**`from app.mcp.server import mcp` is repeated inside every test and never written at module
scope.** `conftest` seeds the MCP environment at module import, and `app.mcp.server` freezes the
token verifier and the Host allowlist at ITS import. A module-scope import here would run that
bootstrap during pytest's collection phase, before the seeding has necessarily happened.
"""
```

**Calling a tool in-memory and reading `structured_content`**
(`test_mcp_tool_schemas.py:294–307`):

```python
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": 999})

    assert result.is_error is True, (...)
    assert result.structured_content is None, (...)
```

**The window problem** — every `weeks`-taking tool computes its window from
`app/mcp/tools/_common.py::local_today` (L198). Analytics functions instead take explicit dates:

```python
# backend/app/analytics/volume.py:137-142
async def get_weekly_volume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
) -> WeeklyVolumeResult:
```

So: call analytics with an explicit range; freeze the clock with `time-machine` for the MCP call
(RESEARCH § *Pattern 2*, "Fixture arithmetic"). `conftest._worst_case_anchor` (L684–698) is the
in-repo precedent for anchoring on `utc_now()` rather than a hard-coded date.

**Committed-vs-flushed rule** (`test_mcp_tools.py:36–43`):

```python
"""**``committed_history`` is the fixture to use here, NEVER ``golden_workout``.**
``golden_workout`` flushes and rolls back, ... A tool driven through
``Client(mcp)`` does not get that session. It opens its own from
``ctx.request_context.lifespan_context.sessionmaker`` -- a different transaction
on a different connection, which cannot see uncommitted rows at all.
"""
```

`sync_all()` commits, so this file is safe — but the same reasoning is why `_cleanup` is mandatory.

**Pitfall 11 note:** if the new module builds its own `TestClient`, it must clear
`mcp.session_manager._has_started = False` (`conftest.py:881`). Preferring `Client(mcp)` avoids it.

---

### `backend/tests/test_coaching_doc.py` (test, file-I/O + static assertion) — NEW

**Analog:** `backend/tests/test_cloud_run_deploy.py` — the repo's only "parse a committed file and
cross-check it against live Python objects" module. Exact structural match.

**Why-this-is-a-test docstring** (`test_cloud_run_deploy.py:1–24`, condensed):

```python
"""Cloud Run deploy artifacts <-> Settings drift guard (DEPLOY-01).

These are tests rather than comments because every failure they catch is silent
and remote. ...

Static assertions over committed files: no container, no network, and
deliberately no integration marker -- drift must fail the fast suite on the
commit that introduces it, not after a deploy.
"""
```

The coaching-doc analog: *a tool rename silently rots the document, and the only symptom is Claude
calling a name that no longer exists inside a user's Project.*

**Repo-root path constants** (`test_cloud_run_deploy.py:36–40`):

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / "deploy" / "cloud-run.env.yaml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-cloud-run.sh"
```

→ `COACHING_DOC = REPO_ROOT / "docs" / "coaching-instructions.md"`.

**Module-scoped parse fixture** (`test_cloud_run_deploy.py:67–69`):

```python
@pytest.fixture(scope="module")
def env_file() -> dict[str, str]:
    return yaml.safe_load(ENV_FILE.read_text())
```

**Live-registry cross-check** — the other half comes from `test_mcp_tool_schemas.py:103–122`; use
the `_mcp_state` fixture (L73–94) so the test stays container-free and out of the integration mark:

```python
async def test_tool_registry_is_exactly_the_thirteen(_mcp_state: None) -> None:
    """MCP-02: the whole tool surface, named.

    An exact set rather than a count. A count of 13 stays green through a rename, and a renamed
    tool is a tool every saved Claude conversation now calls by a name that no longer exists.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        names = {tool.name for tool in (await mcp_client.list_tools()).tools}

    assert names == EXPECTED_TOOLS, (...)
```

Assertion shape for the new file: every `fitness_*` token found in the markdown ∈ live registry,
**and** all 12 non-`fitness_ping` tools appear in the doc. Failure messages follow the house style —
`"<REQ-ID> violated: <what> ... <why it matters> ... Got: <value>"`.

---

### `backend/tests/test_mcp_tool_schemas.py` (test, MODIFY)

**Analog:** itself, lines 278–307 — the existing malformed-parameter test is the template for the
two new ones (`wrong-type`, `missing-required`):

```python
@pytest.mark.integration
async def test_a_request_above_the_cap_is_rejected_before_the_body_runs(
    client: TestClient,
) -> None:
    """T-06-05: the published `maximum` is enforced by the SDK, not by the tool.

    Argument validation happens in `FuncMetadata.call_fn_with_arg_validation`, which runs BEFORE
    `fn` is invoked. That means this rejection cannot be intercepted in the tool body and cannot
    be turned into the `data_available=False` shape every other failure in this phase takes -- it
    surfaces as `is_error=True` with no structured content.
    ...
    What matters is that no database work happens.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": 999})

    assert result.is_error is True, (...)
    assert result.structured_content is None, (...)
```

New tests: `{"weeks": "four"}` (wrong type) and `{}` against `fitness_get_exercise_progression`
(missing required `exercise_name`). Same two assertions, same `@pytest.mark.integration` + `client`
signature, same lazy import. Name them so RESEARCH's `-k malformed` / `-k missing_required`
selectors match.

---

### `docs/coaching-instructions.md` (doc) — NEW

**Analog:** `docs/hevy-api-observations.md` — the only sibling in `docs/`, and the tone/format
precedent named by D-07.

**Header pattern** (`docs/hevy-api-observations.md:1–7`):

```markdown
# Hevy API — Observed Behaviour

First recorded: 2026-08-30
Method: full + incremental sync against the live API from `python -m app.cli sync-hevy`.
Source of truth for anything NOT observed here: the live OpenAPI document at
https://api.hevyapp.com/docs/ — Hevy's own preamble warns the structure may change without
notice.
```

Shape to copy: a title, a dated provenance line, an explicit *"source of truth for anything not
here"* pointer, then `##` sections with a bolded **Verdict:** line where a claim is being made. For
the coaching doc the provenance line points at `BRETT blueprint.md` §34–36 and the source-of-truth
pointer at the live tool registry.

**Content skeleton is fully specified in `07-RESEARCH.md` § *Pattern 5*** (8 sections) — the
planner should not re-derive it. The verified 13-tool mapping table (RESEARCH L562–575) and the
metadata-envelope field table (RESEARCH L590–596) are copy-ready.

**Envelope field names to reference, verified against source** (`backend/app/analytics/schemas.py`):

```python
class FreshnessMetadata(_AnalyticsModel):
    """DQ-01. Per-resource ``last_synced_at``, keyed by the ``RESOURCE_*`` constants. ..."""
    resources: dict[str, dt.datetime | None]


class CoverageMetadata(_AnalyticsModel):
    """DQ-02. Exactly D-06's three fields -- do not add a fourth. ..."""
    sessions_in_window: int
    insufficient_data: bool
    earliest_data_at: dt.datetime | None
```

**Note (D-08 / character budget):** RESEARCH flags an unverified ~8,000-character Project
custom-instruction limit. Keep the doc tight; the tool table is the part that must survive
trimming.

---

### `docs/runbook-secret-rotation.md` + `docs/runbook-backup-restore.md` (runbook docs) — NEW

**Analog:** `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`, specifically
§"Auth Verification Matrix (deployed)" at **L236–310**. This is the established shape for "a
procedure plus a recorded proof it ran", and CONTEXT.md D-02/D-09 both explicitly say to mirror it.

**Redaction header — non-negotiable, copy verbatim in spirit** (`02-DEPLOY-LOG.md:3–8`):

```markdown
Evidence record for plan 02-05 (DEPLOY-01, MCP-01, MCP-04, D-01).

**Redaction rule for this file:** no credential value is ever recorded. `MCP_AUTH_SECRET` is
referred to by name only, and the Neon DSN is redacted to
`postgresql://***@ep-small-wave-ayqfaloh.c-5.us-east-2.aws.neon.tech/neondb`.
```

**The verification matrix table** (`02-DEPLOY-LOG.md:236–250`) — this is exactly the shape D-04's
old-token/new-token check and D-02's row-count/digest comparison must be recorded in:

```markdown
### Auth Verification Matrix (deployed)

All seven rows against `https://brett-792870654598.us-central1.run.app`, revision `brett-00005-gcx`.
Every recorded command substitutes the literal `$MCP_AUTH_SECRET` for the header value.

| Row | Command summary | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `POST /mcp`, no `Authorization` | 401 + `WWW-Authenticate` with `resource_metadata` | `401`; header exactly as below | **PASS** |
| 2 | `POST /mcp`, `Authorization: Bearer wrong-token` | 401, body byte-identical to row 1 | `401`; `cmp` reports byte-identical | **PASS** |
| 3 | `POST /mcp`, `Authorization: Bearer $MCP_AUTH_SECRET`, `tools/list` | 200, `tools[0].name == "fitness_ping"` | `200`; exactly one tool, `fitness_ping` | **PASS** |
```

Note row 3's expected value is now **13 tools**, not one — that change is itself ROADMAP criterion
#2 (RESEARCH Pitfall 1: the live revision `brett-00005-gcx` predates Phase 6).

**Honest-limitation subsections** (`02-DEPLOY-LOG.md:274–309`, "#### Row 7 required a different
method than the plan prescribes") — the precedent for the runbooks recording *why* the naive
procedure does not work:

- Secret rotation: `MCP_AUTH_MODE: "authkit"` (`deploy/cloud-run.env.yaml:50`) means
  `build_token_verifier` (`backend/app/mcp/auth.py:117–141`) returns `AuthKitJWTVerifier` and
  `StaticTokenVerifier` is never constructed — so D-04's "new token → success" is 401 without a
  mode flip (RESEARCH Pitfall 2).
- Backup/restore: Neon Free plan's 6-hour history window bounds the honest coverage claim.

**The rotation mechanism the runbook documents** (`scripts/deploy-cloud-run.sh:40`) — this line is
*why* rotation is a deploy procedure and not a `gcloud secrets` procedure:

```bash
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
```

Asserted by `test_cloud_run_deploy.py::test_every_secret_binding_is_a_secret_manager_reference`
(L235–254) and `..._partition_the_environment` (L257–272). The runbook must not propose editing
either file's secret wiring.

**The mode-flip lever the runbook temporarily moves** (`deploy/cloud-run.env.yaml:36–41`) — note the
file already documents the flip as the sanctioned rollback path:

```yaml
# Rollback is one value plus a redeploy, never a code change: set this back to
# `static` and re-run ./scripts/deploy-cloud-run.sh. The constant-time compare
# and the brett-mcp-auth-secret binding both remain in place precisely so a
# WorkOS outage stays a configuration problem (T-02-07).
MCP_AUTH_MODE: "authkit"
```

`test_auth_mode_is_a_valid_literal` (L153–169) fails the fast suite on a typo during the flip —
the runbook should tell the operator to run the fast suite between edit and deploy.

---

### `scripts/verify-restore.sql` (script, batch) — NEW

**Analog:** `backend/tests/conftest.py::_mcp_purge_statements` (L595–635) — for the *table
inventory* and its ordering, not for the SQL dialect. Also `test_hevy_end_to_end.py::TABLES`
(L80–87), the canonical "every table this composition writes" list:

```python
TABLES = (
    "workouts",
    "workout_exercises",
    "workout_sets",
    "exercise_templates",
    "exercise_muscles",
    "body_measurements",
)
```

The digest query itself is given in `07-RESEARCH.md` § *Pattern 3* (L436–441) — it names four
tables; reconcile against the eight in `conftest._MCP_PURGE_TABLES` before shipping, or state in the
runbook why the subset is sufficient.

---

### `scripts/deploy-sync-job.sh` (D-10, deploy script, batch/scheduled) — NEW

**Analog:** `scripts/deploy-cloud-run.sh` — exact. Copy the header, the `set -euo pipefail`, the
`:?`-guarded project variable, and the `--set-secrets` binding style:

```bash
#!/usr/bin/env bash
# The single reproducible description of how BRETT deploys (D-06e). This replaces
# render.yaml: it is what a future reader opens to learn how this service reaches
# production, and backend/tests/test_cloud_run_deploy.py asserts every flag below
# is still here.
#
# Requires: gcloud >= 578, an authenticated account, and the project bootstrap
# performed by plan 02-05 (APIs enabled, runtime service account, secrets created).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Never inherit `gcloud config get-value project`: the active project on a
# developer machine is routinely something unrelated, and a silent deploy into the
# wrong project is expensive to notice.
PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"
REGION="${BRETT_GCP_REGION:-us-central1}"
SERVICE="${BRETT_SERVICE:-brett}"
...
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

exec gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  ...
  --env-vars-file="$REPO_ROOT/deploy/cloud-run.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
  --set-build-env-vars="UV_FROZEN=1,UV_NO_DEV=1" \
  --quiet
```

**Deltas the sync job needs:**

- `gcloud run jobs deploy` (not `services deploy`); the job's secret binding is
  `HEVY_API_KEY=<secret>:latest` — **a third Secret Manager secret that does not exist yet**
  (`02-DEPLOY-LOG.md` §Secrets records exactly two: `brett-database-url`, `brett-mcp-auth-secret`).
  Creating it is a task, not an assumption.
- The command it runs is already built: `backend/app/cli.py` docstring, L3 —
  `PYTHONPATH=backend uv run python -m app.cli sync-hevy`. The CLI's own docstring (L18–20) names
  this phase as the owner of that decision:
  *"This is a VERIFICATION and operations trigger, not the production schedule. Phase 7 decides how
  sync actually runs in production (Cloud Run job, scheduler, or otherwise)."*
- `deploy/cloud-run.env.yaml:11–13` warns that gcloud **replaces the service's entire environment**
  from the env file. If the job shares that file, `MCP_*` keys travel with it harmlessly; if it gets
  its own file, `test_cloud_run_deploy.py`'s drift guards must be extended to cover it (they
  currently hard-code `ENV_FILE`, L37).
- `README.md:75` states "Production scheduling is Phase 7 — nothing here runs the sync on a timer."
  That line becomes false when this ships; update it in the same plan.

**Test companion:** mirror `test_cloud_run_deploy.py`'s `_REQUIRED_FLAGS` list (L53–64) and
`_secret_bindings()` text-parse (L89–106) — *"Read as text rather than executed: running the script
would deploy."*

---

### `.planning/phases/07-.../07-COACH-VERIFICATION.md` (D-09 record) — NEW

**Analog:** `.planning/phases/02-deploy-connector-auth-spike/02-VERIFICATION.md`.

**YAML front-matter + observable-truths table** (`02-VERIFICATION.md:1–20`):

```markdown
---
phase: 02-deploy-connector-auth-spike
verified: 2026-08-29T12:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 2: Deploy & Connector Auth Spike Verification Report

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ... | VERIFIED | ... |
```

Note how Truth 2's evidence records the human checkpoint explicitly: *"this is a human-verified
checkpoint (`checkpoint:human-verify`), not a claim inferred from code"* — and how Truth 3 records
an unresolved gap honestly rather than rounding it up. Both are the standard D-09's UAT record must
meet. The 6-step UAT script is in `07-RESEARCH.md` § *Pattern 5* (L598–608).

---

## Shared Patterns

### 1. Module / test-module docstrings carry the *why*, not the *what*
**Sources:** `backend/app/main.py:1–7`, `backend/app/logging.py:1–28`,
`backend/tests/test_cloud_run_deploy.py:1–24`, `backend/tests/test_mcp_tool_schemas.py:1–26`
**Apply to:** every new `.py` file in this phase.
Format: what the file guards → the requirement ID (`DEPLOY-03`, `MCP-04`, `T-02-10`, `FOUND-05`,
`ROADMAP-2`) → the specific silent failure it prevents → any load-bearing ordering constraint.
`test_mcp_tool_schemas.py:21–25` names its own highest-risk assertion in the docstring; a new test
module with a subtle assertion should do the same.

### 2. Failure messages are essays, not `assert x == y`
**Source:** `backend/tests/test_cloud_run_deploy.py:135–139` (representative of the whole suite)
```python
        assert key in known, (
            f"DEPLOY-01 violated: deploy/cloud-run.env.yaml sets {key} but Settings has no "
            f"such field (extra='ignore' means the deployed service silently ignores it, so "
            f"the deploy succeeds and the misconfiguration surfaces much later)"
        )
```
**Apply to:** every new assertion. Shape: `"<REQ-ID> violated: <observed> ... <consequence> ...
Got: <value>"`. The message must never interpolate a credential (`test_cloud_run_deploy.py:238–241`
states this rule explicitly for `--set-secrets`).

### 3. Structured logging via a module-level `log`, redaction already installed
**Source:** `backend/app/main.py:26`, `backend/app/logging.py:41–71` (`DENY_KEYS`, `REDACTED`)
**Apply to:** `backend/app/middleware.py`.
```python
log = structlog.get_logger()
```
`configure_logging(settings)` runs at `main.py:25`, before the app object exists — the middleware
inherits the three-layer FOUND-05 chain for free and must add nothing. Log **counts and the path
only** (RESEARCH § *Code Examples*): never the `Authorization` header, never the raw
`X-Forwarded-For` value.

### 4. Exact-key-set assertion on any body an anonymous caller can trigger
**Source:** `backend/tests/test_mcp_auth.py:581–612` (`test_401_leaks_nothing`)
**Apply to:** the 429 body test.
`assert set(response.json()) == {...}` **plus** a leak-marker loop. A substring check cannot notice
a new field (Pitfall 8).

### 5. Test modules do not import each other; shared constants are duplicated
**Sources:** `backend/tests/test_mcp_auth.py:76–82`, `backend/tests/test_mcp_mount.py:36–44`,
`backend/tests/test_mcp_auth.py:100–102`
**Apply to:** `test_rate_limit.py`, `test_full_chain_end_to_end.py`, `test_coaching_doc.py`.
The MCP envelope constants and the test bearer token are written out in each module that uses them,
with a comment saying so. `tests.conftest` is the only sanctioned import
(`test_hevy_end_to_end.py:53`: `from tests.conftest import DEFAULT_USER_ID, hevy_fixture`).

### 6. `from app.mcp.server import mcp` is always a lazy, in-function import
**Sources:** `backend/tests/test_mcp_tool_schemas.py:16–19` (the rule), `test_mcp_mount.py:13–18`,
`backend/tests/conftest.py:851–861` (the `client` fixture's version)
**Apply to:** every new test that touches the MCP layer.
The module freezes the token verifier and Host allowlist at import; a module-scope import runs that
bootstrap during pytest collection, before `conftest._default_mcp_env` has seeded the environment.

### 7. `app.state.sessionmaker` is saved, replaced, and restored in `finally`
**Sources:** `backend/tests/test_mcp_mount.py:80–88`, `backend/tests/test_mcp_tool_schemas.py:86–94`
**Apply to:** `test_full_chain_end_to_end.py`.
```python
    preexisting = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        ...
    finally:
        if preexisting is not None:
            app.state.sessionmaker = preexisting
        engine.sync_engine.dispose()
```

### 8. Committed rows get a compensating DELETE, never a rollback
**Sources:** `backend/tests/test_hevy_end_to_end.py:163–179` + the `try/finally` at L240–256,
`backend/tests/conftest.py::committed_history` (L637–682)
**Apply to:** `test_full_chain_end_to_end.py`.
The Postgres container is session-scoped; a row that outlives its test changes the next one's result.

### 9. Static assertions over committed files run in the FAST suite
**Source:** `backend/tests/test_cloud_run_deploy.py:22–23`
> *"Static assertions over committed files: no container, no network, and deliberately no
> integration marker -- drift must fail the fast suite on the commit that introduces it, not after
> a deploy."*

**Apply to:** `test_coaching_doc.py`, the D-10 deploy-script test, the bucket-refill unit tests.
`@pytest.mark.integration` is reserved for tests needing the Postgres container or the `client`
fixture (`pyproject.toml:57–59`).

### 10. Secrets never leave Secret Manager; env files hold only non-secrets
**Sources:** `deploy/cloud-run.env.yaml:7–9`, `scripts/deploy-cloud-run.sh:40`,
`backend/tests/test_cloud_run_deploy.py:172–187` and `235–272`
**Apply to:** both runbooks, `deploy/cloud-run.env.yaml`, `scripts/deploy-sync-job.sh`.
No secret value in any committed document or command output; new secrets bind via `--set-secrets`
with a `name:latest` reference (regex `^[a-z0-9-]+:(latest|[0-9]+)$`, L49).

### 11. Full type annotations + Ruff `E,F,I,UP,B,ASYNC,S,DTZ`
**Source:** `pyproject.toml:61–87`
**Apply to:** `backend/app/middleware.py` and every new test module.
`disallow_untyped_defs = true` (L82); `backend/tests/*` ignores only `S101,S105,S106` (L74) — app
code does not. Line length 100. `known-first-party = ["app"]` for isort ordering.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/app/middleware.py` (the ASGI `__call__` body specifically) | middleware | request-response | **No file in `backend/app/` implements the raw ASGI protocol.** `grep -rn "add_middleware\|ASGIApp\|Scope, Receive, Send" backend/app/` returns exactly one hit: `main.py:66`, which registers the third-party `CorrelationIdMiddleware`. The *module conventions* (docstring, `log`, injected clock, `build_*(settings)` factory, minimal literal body) all have analogs above; the `async def __call__(self, scope, receive, send)` skeleton and the raw `send({"type": "http.response.start", ...})` calls do not — use `07-RESEARCH.md` § *Code Examples* (L774–837), which is written against this repo's constraints. |

**Partial-analog warnings (the planner should read the analog's caveat, not just its code):**

- `docs/runbook-*.md` — the Phase 2 analog is a *log of what happened*; the runbooks are
  *procedures that will be re-run*. Copy the matrix table and the redaction header; add a
  "preconditions" section the analog has no equivalent of.
- `scripts/verify-restore.sql` — `conftest._mcp_purge_statements` is SQLAlchemy Core specifically
  so no table name reaches the driver as a string (S608). The runbook SQL is hand-written psql and
  cannot inherit that property; it is operator-run against a read-only comparison, which is why
  that is acceptable here and nowhere else.

---

## Metadata

**Analog search scope:** `backend/app/` (62 modules), `backend/tests/` (47 test modules + conftest),
`scripts/`, `deploy/`, `docs/`, `.planning/phases/02-deploy-connector-auth-spike/`, repo root
(`pyproject.toml`, `Procfile`, `README.md`, `CLAUDE.md`)
**Files read in full or in relevant part:** 22
**Pattern extraction date:** 2026-09-01
**Line numbers verified against:** working tree at commit `5c09cc5`

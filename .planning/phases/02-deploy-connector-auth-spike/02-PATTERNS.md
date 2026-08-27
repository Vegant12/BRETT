# Phase 2: Deploy & Connector Auth Spike - Pattern Map

**Mapped:** 2026-08-24
**Files analyzed:** 17 (11 new, 6 modified)
**Analogs found:** 15 / 17

> **Ground-truth precedence.** `02-RESEARCH.md` verified every MCP SDK v2 API shape against a live
> `mcp==2.0.0` install. Where this document and RESEARCH.md disagree on an *SDK* call signature,
> RESEARCH.md wins. This document is authoritative for **project conventions** — docstring style,
> secret handling, degrade-not-500, factory-not-singleton, test structure — which RESEARCH.md does
> not cover.

---

## File Classification

| New/Modified File | New/Mod | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|---------|------|-----------|----------------|---------------|
| `backend/app/mcp/__init__.py` | new | package marker | — | `backend/app/api/__init__.py` | exact |
| `backend/app/mcp/context.py` | new | provider (lifespan/DI) | event-driven (startup/shutdown) | `backend/app/db/session.py` + `main.py:27-47` | role-match |
| `backend/app/mcp/auth.py` | new | middleware (token verification) | request-response | *(partial)* `config.py:59-69` + `core/time.py` | partial |
| `backend/app/mcp/server.py` | new | config/bootstrap wiring | request-response | `backend/app/main.py:22-57` | role-match |
| `backend/app/mcp/tools/__init__.py` | new | package marker | — | `backend/app/api/routes/__init__.py` | exact |
| `backend/app/mcp/tools/ping.py` | new | controller/handler | request-response + read-only DB | `backend/app/api/routes/health.py` | **exact** |
| `render.yaml` (repo root) | new | config/IaC | declarative | `docker-compose.yml` | partial |
| `backend/tests/test_mcp_mount.py` | new | test (integration) | request-response | `backend/tests/test_health.py` | role-match |
| `backend/tests/test_mcp_auth.py` | new | test (integration) | request-response | `test_health.py` + `test_secret_redaction.py` | role-match |
| `backend/tests/test_mcp_tools.py` | new | test (integration) | read-only DB | `test_health.py:31-52` | **exact** |
| `backend/tests/test_render_blueprint.py` | new | test (unit/static) | transform (parse+assert) | `backend/tests/test_config.py` | role-match |
| `backend/app/main.py` | **mod** | bootstrap | event-driven | itself (extend in place) | self |
| `backend/app/config.py` | **mod** | config | transform | itself — `async_database_url:71-87` | self |
| `backend/tests/conftest.py` | **mod** | test fixture | — | itself — `_default_database_url:45-58` | self |
| `pyproject.toml` | **mod** | config | — | itself — `dependencies:6-17` | self |
| `.env.example` | **mod** | config | — | itself | self |
| `backend/tests/test_config.py` | **mod** | test (unit) | — | itself — `_clean_env:17-30` | self |

---

## Pattern Assignments

### `backend/app/mcp/tools/ping.py` (controller/handler, request-response + read-only DB)

**Analog:** `backend/app/api/routes/health.py` — **exact match.** Same job: touch the DB, report a
coarse status, never leak. Copy its structure line for line and swap the transport.

**Module docstring pattern** (`health.py:1-7`) — every module in this repo opens by stating the
*failure mode it prevents*, not what the code does:
```python
"""Service health endpoint (FOUND-01).

The database field is a LIVE probe, never a cached or assumed value: a health
check that reports what it believes rather than what it just measured is worse
than no health check at all, because Render will keep routing traffic to a
service whose database has gone away.
"""
```
For `ping.py` the equivalent "why" is: *this tool exists to prove the lifespan-wired `AppContext` →
sessionmaker path that every Phase 6 tool depends on; a bare echo would prove nothing.* (D-08)

**Imports + module logger** (`health.py:9-15`):
```python
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])
log = structlog.get_logger()
```
Copy: `import structlog`, `from sqlalchemy import text`, and the module-level
`log = structlog.get_logger()`. This is the repo-wide logger convention (also `main.py:24`).
Ruff isort has `known-first-party = ["app"]` (`pyproject.toml:47-50`), so `from app.mcp.context
import AppContext` sorts into the last block.

**Core pattern — degrade-to-error, never 500** (`health.py:28-42`). This is the single most
important excerpt for this file:
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
Three things to carry over verbatim:
1. `except Exception:  # noqa: BLE001 - <reason>` — Ruff's `B` ruleset is on (`pyproject.toml:45`);
   the inline reason after the noqa code is the established form.
2. `log.exception("<snake_case_event_name>")` — no interpolated detail in the event name; the
   traceback goes through the structlog scrubber (`app/logging.py:142-144`).
3. The comment explaining *what would leak* if the exception body reached the caller.

**Divergence from the analog (SDK-imposed, per RESEARCH Pattern 4):**
- Session access is `ctx.request_context.lifespan_context.sessionmaker`, **not**
  `request.app.state.engine` — the tool has no `Request`.
- The return is a `pydantic.BaseModel` (`PingResult`), not a `JSONResponse`; returning a model
  auto-populates `outputSchema` + `structuredContent`.
- There is no status-code channel in MCP, so the degrade is expressed purely in the payload
  (`database="error"`), and the tool must still return `isError: false`.
- `ctx` **must** be annotated `Context[AppContext]` or the SDK exposes it to the model as a required
  string argument (RESEARCH verified counter-example).

**Corresponding test analog:** `backend/tests/test_health.py:31-52` — see
`backend/tests/test_mcp_tools.py` below.

---

### `backend/app/mcp/context.py` (provider, event-driven)

**Analogs:** `backend/app/db/session.py` (the "factories, never module singletons" doctrine) and
`backend/app/main.py:27-47` (the `asynccontextmanager` lifespan shape).

**The invariant this file must not break** (`db/session.py:1-7`):
```python
"""Engine and session factories.

Factories, not module-level singletons, on purpose: a module-level
``create_async_engine(...)`` binds its pool to whichever event loop imported it,
which breaks under pytest-asyncio and leaks connections between tests. The
caller (``lifespan``, a fixture, the CLI) owns the engine's lifetime.
"""
```
Restated in `main.py:29-38`:
```python
    """Application lifespan.

    The engine is created here and NEVER at module import: a module-level engine
    binds its pool to whichever event loop imported it, which breaks under
    pytest-asyncio and leaks connections between tests.

    Migrations are deliberately absent -- ``alembic upgrade head`` runs
    out-of-band (a Render pre-deploy command), because startup migrations race
    across restarts.
    """
```
**Consequence for `mcp_lifespan`:** it must *borrow* `app.state.sessionmaker` and must never call
`make_engine()`. Doing so would create a second pool against free-tier Postgres. State this in the
docstring the same way the analogs do — as the failure it prevents.

**Lifespan structure to mirror** (`main.py:27-47`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("service_stopped")
```
Copy: `from collections.abc import AsyncIterator` + `from contextlib import asynccontextmanager`
(`main.py:9-10`), the `-> AsyncIterator[...]` return annotation (mypy `disallow_untyped_defs = true`,
`pyproject.toml:61`), and the `try:/yield/finally:` teardown shape.

**Type-annotation style for the sessionmaker** (`db/session.py:35`):
```python
def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
```
Use `async_sessionmaker[AsyncSession]` as the `AppContext` field type — same import block as
`db/session.py:9-14`.

**No dataclass exists in the repo yet.** `AppContext` is the first. RESEARCH Pattern 3 specifies
`@dataclass(slots=True)`; nothing in the codebase contradicts it.

---

### `backend/app/mcp/server.py` (config/bootstrap wiring, request-response)

**Analog:** `backend/app/main.py:22-57` — the only other module that does import-time bootstrap
wiring in this repo.

**Import-time bootstrap with an explicit ordering comment** (`main.py:1-7, 22-24`):
```python
"""FastAPI application bootstrap.

Bootstrap order is load-bearing: configuration is read first so a misconfigured
process dies immediately, then logging is configured -- the value scrubber needs
``settings.secret_values()`` -- and only then is the app object built. Any log
line emitted before ``configure_logging`` would bypass redaction entirely.
"""
...
settings = get_settings()  # fail-fast BEFORE anything else
configure_logging(settings)  # then logging, so the scrubber has the secret values
log = structlog.get_logger()
```
`server.py` has the *same* class of ordering constraint and must document it the same way:
`streamable_http_app()` must run at import because `main.py`'s lifespan reads
`mcp.session_manager`, which raises `RuntimeError` until then (RESEARCH Pitfall 1 / Pitfall 4).
Use `settings = get_settings()` at module scope exactly as `main.py:22` does — it is `@lru_cache`d
(`config.py:111`), so this is not a second read.

**Wiring-with-decision-tag comments** (`main.py:52-57`):
```python
# Pure-ASGI middleware, not BaseHTTPMiddleware -- the ContextVar it sets must stay
# readable inside the exception handler below.
app.add_middleware(CorrelationIdMiddleware)

# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)
```
Note the convention: a bare decision id (`D-04:`, `D-05:`, `FOUND-05`) prefixes the comment that
implements it. Phase 2 equivalents to tag: `D-05` (real structure, not a spike), `D-08` (real DB
round-trip), and the `TransportSecuritySettings` line (RESEARCH Pitfall 2 — the 421).

**SDK call shapes:** take verbatim from RESEARCH.md "Pattern 5 — Wiring" (`02-RESEARCH.md:461-497`).
Do not re-derive them.

---

### `backend/app/mcp/auth.py` (middleware, request-response)

**No role analog exists** — this repo has no authentication code. Two *partial* analogs supply the
mandatory conventions.

**Partial analog A — fail closed, never echo the rejected input** (`config.py:59-69`):
```python
    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: SecretStr) -> SecretStr:
        try:
            url = make_url(v.get_secret_value())
        except Exception:
            # `from None` and NO interpolation of the input value.
            raise ValueError("DATABASE_URL is not a valid database URL") from None
```
Direct translation: `verify_token` catches broad, returns `None` (deny), and **never** logs the
token, the claims, or the exception. The `# noqa: BLE001` + inline reason form is required
(`health.py:33`).

**Partial analog B — validate-at-the-boundary helper module** (`core/time.py:43-54`) — a
framework-agnostic module of small typed functions, each documenting the deep failure it prevents:
```python
def validate_timezone(tz: str) -> str:
    """Reject a non-IANA timezone at the boundary rather than deep in analytics.
    ...
    """
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown IANA timezone") from None
    return tz
```

**MANDATORY — the secret-handling contract this file joins.** Three layers, documented in
`config.py:1-13`:
```python
"""Typed, fail-fast application settings.

Layer 1 of the three-layer FOUND-05 secret defense:

1. **this module** — every secret is a ``SecretStr`` ...
2. ``app/logging.py`` — key-name censor + value scrubber built from
   :meth:`Settings.secret_values`.
3. the FastAPI error handler — sanitized responses.

Nothing here may ``print`` or log a settings value.
"""
```
- `authorization`, `token`, `access_token`, `secret`, `mcp_auth_secret` are **already** on the
  deny-list (`app/logging.py:41-65`) — no change needed there for the static-bearer stage.
- If a WorkOS **client secret** is introduced, it must be appended to
  `_SECRET_FIELDS` (`config.py:24`) or the value scrubber will not see it.
- `MCP_ISSUER_URL`, `MCP_RESOURCE_URL`, `MCP_ALLOWED_HOSTS` are **not** secrets — plain `str`
  fields, no `SecretStr`, and they must stay out of `_SECRET_FIELDS` (adding a non-secret there
  would make the scrubber redact a public hostname out of every log line).

**Ruff `S` (bandit) is enabled** (`pyproject.toml:45`) — `secrets.compare_digest`, never `==`.
Precedent for a deliberate bandit noqa is `config.py:106` (`# noqa: S110 - a non-URL secret is fine here`).

**Implementation bodies:** RESEARCH.md Pattern 5 Stage A/Stage B (`02-RESEARCH.md:390-457`) — these
were verified against the installed `mcp` and `pyjwt` sources; use them as-is, including the
`anyio.to_thread.run_sync` wrapper around `PyJWKClient`.

---

### `backend/app/mcp/__init__.py` and `backend/app/mcp/tools/__init__.py` (package markers)

**Analog:** `backend/app/api/__init__.py` — exact. The entire file:
```python
"""HTTP API layer."""
```
Others for tone: `backend/app/api/routes/__init__.py` → `"""Route modules."""`;
`backend/app/db/__init__.py` → `"""Database layer: declarative base, models, and engine/session factories."""`.
One line, no imports, no re-exports. Note `backend/app/__init__.py` is the sole exception (empty).

---

### `render.yaml` (config/IaC, declarative) — repo root

**Analog:** `docker-compose.yml` — partial (only other infra YAML in the repo). What transfers is
the **comment discipline**, not the schema:
```yaml
# Local development database only.
#
# NOTE ON THE PASSWORD BELOW: `brett_local_dev` is a LOCAL DEV ONLY throwaway
# credential for a container bound to localhost. It is NOT a secret ...
# Gitleaks triage: not a leak.
...
    volumes:
      # postgres:18+ REFUSES to start with the mount at `/var/lib/postgresql/data`
      # ("Error: in 18+, these Docker images are configured to store database data
      # in a format which is compatible with pg_ctlcluster"). 18 stores data in a
      # major-version subdirectory, so the mount belongs one level up.
      - brett_pgdata:/var/lib/postgresql
```
Two conventions to carry into `render.yaml`:
1. **Quote the error message a setting prevents.** The `plan: free`, `--app-dir backend`, and the
   commented-out `preDeployCommand` lines each need this (RESEARCH Pitfalls 6 and 7).
2. **Pre-empt gitleaks triage in a comment** where a value looks credential-shaped.
   `MCP_AUTH_SECRET` must use `generateValue: true` (never a literal) and `MCP_ISSUER_URL` uses
   `sync: false` — the existing pre-commit gitleaks hook is why.

**Schema:** RESEARCH.md "Render Deployment" (`02-RESEARCH.md:733-772`) has the field-verified
blueprint. Note `.python-version` already contains `3.13` and `uv.lock` already sits at repo root,
so `rootDir` stays unset.

---

### `backend/app/main.py` (MODIFIED — bootstrap, event-driven)

Two surgical edits. Preserve everything else.

**Edit 1 — extend the existing lifespan** (currently `main.py:39-47`):
```python
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("service_stopped")
```
`mcp.session_manager.run()` is entered **after** `app.state.sessionmaker` is assigned and **inside**
the existing `try:`, so the existing `finally: await engine.dispose()` still runs. Shape from
RESEARCH Pattern 2. The existing docstring (`main.py:29-38`) should gain a third paragraph
explaining the ordering, in the same "why, and what breaks otherwise" voice as the first two.

**Edit 2 — the mount, placed after the existing router** (`main.py:56-57`):
```python
# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)
```
`app.mount("/", mcp_app)` goes immediately after this line and **before** the
`@app.exception_handler(Exception)` block at `main.py:62-68` (decorator registration order is
irrelevant, but keeping route wiring contiguous matches the file's current layout). Mount at `/`,
not `/mcp` — RESEARCH Pitfall 3.

**Do not touch:** `settings = get_settings()` / `configure_logging(settings)` at `main.py:22-23`
(the docstring at `main.py:3-6` explains why nothing may precede them), and the sanitized
exception handler at `main.py:62-68`.

---

### `backend/app/config.py` (MODIFIED — config, transform)

**Self-analog for the derived-value property** (`config.py:71-87`):
```python
    @property
    def async_database_url(self) -> str:
        """Return a URL that ``asyncpg`` actually accepts.

        Managed Postgres providers hand out libpq-flavoured URLs.
        ``asyncpg.connect()`` has no ``sslmode`` parameter and no ``**kwargs``,
        so passing one through raises ``TypeError`` at connect time. Translate
        ``sslmode`` to ``ssl`` and drop the other libpq-only parameters.
        """
```
`mcp_allowed_hosts` (splitting `MCP_ALLOWED_HOSTS` on commas) is the same shape: a plain `@property`
that derives a typed value from a raw env string, with a docstring saying *why* it is a string in
the environment (so a Render custom domain can be added without a code change — RESEARCH Pitfall 2).

**Field declaration style** (`config.py:49-57`):
```python
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # SecretStr, never a pydantic DSN type: a DSN-typed field's validation
    # failure echoes the raw input -- password included -- into the
    # ValidationError message.
    database_url: SecretStr
    hevy_api_key: SecretStr | None = None
    mcp_auth_secret: SecretStr | None = None
```
`mcp_auth_secret` **already exists** and is **already** in `_SECRET_FIELDS` (`config.py:24`) — no
change needed. New fields (`mcp_issuer_url`, `mcp_resource_url`, `mcp_allowed_hosts_raw`) are plain
`str` with defaults, so local dev and the existing test suite keep working unchanged.

**Safe-by-construction:** `model_config` sets `extra="ignore"` and `frozen=True` (`config.py:35-47`)
— new env vars are additive and cannot break existing tests.

---

### `backend/tests/test_mcp_tools.py` (test, read-only DB)

**Analog:** `backend/tests/test_health.py` — **exact.** Both directions of the DB probe are already
tested there; mirror both.

**Happy path** (`test_health.py:22-28`):
```python
@pytest.mark.integration
def test_health_reports_connected(client: TestClient) -> None:
    """Live database -> 200 and a minimal body (D-03)."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
```

**Degrade path + leak assertion — copy this structure exactly** (`test_health.py:19, 31-52`):
```python
DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"


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
```
Four conventions to carry over:
1. Simulate failure with a **real** connection to closed port 1 — never a mock. The docstring at
   `test_health.py:1-13` argues this explicitly.
2. **Swap and restore**, never dispose — the session-scoped engine is shared, and disposing it
   poisons every later test.
3. The `for leak in (...)` loop with an f-string assertion message naming the violated requirement.
4. `@pytest.mark.integration` on anything touching the container (`pyproject.toml:36-38`;
   `conftest.py:9-12`).

**Divergence:** the ping tool degrades via `app.state.sessionmaker`, not `app.state.engine` — swap
that attribute instead. Use the in-memory `mcp.Client` for the tool-call itself (RESEARCH
`02-RESEARCH.md:825-843`); it bypasses auth, which is fine because auth is covered separately.

---

### `backend/tests/test_mcp_auth.py` (test, request-response)

**Analogs:** `backend/tests/test_health.py:55-66` (the "endpoint is open" assertion, inverted here
to "endpoint is closed") and `backend/tests/test_secret_redaction.py` (the leak-assertion vocabulary
for `test_401_leaks_nothing`).

**Auth-shape assertion pattern** (`test_health.py:55-66`):
```python
@pytest.mark.integration
def test_health_is_open(client: TestClient) -> None:
    """D-04: no credential of any kind is required.

    Render's platform health check and uptime monitors call this endpoint
    without a token, so an auth dependency here would break deployment.
    """
    client.cookies.clear()

    response = client.get("/health", headers={})

    assert response.status_code not in (401, 403)
```
Note the docstring names the decision id and the deployment consequence. `test_mcp_auth.py` is the
mirror image: `assert response.status_code == 401` plus the `resource_metadata=` header assertion.

**Leak-assertion pattern for `test_401_leaks_nothing`** (`test_secret_redaction.py:186-191`):
```python
    assert set(response.json()) == {"error", "correlation_id"}
    assert response.json()["error"] == "internal server error"
    assert "Traceback" not in response.text
    assert "ValueError" not in response.text, "exception class name leaked to the client"
    assert "leaky" not in response.text, "exception message leaked to the client"
```
Assert on the **exact key set**, not just absence — that is how this repo catches new fields
appearing in an error body.

**Request bodies/headers:** RESEARCH.md "HTTP auth test (TestClient)" (`02-RESEARCH.md:845-873`) —
the `_meta` envelope is mandatory or you get `-32602` instead of an auth result (Pitfall 5).

---

### `backend/tests/test_mcp_mount.py` (test, request-response)

**Analog:** `backend/tests/test_health.py` — role-match. Same `client` fixture, same
`@pytest.mark.integration` marker, same one-assertion-cluster-per-test shape.

The mount-shadowing test (`/health`, `/docs`, `/openapi.json` still win after `app.mount("/", ...)`)
has no analog — it is a new class of assertion. Model it on `test_health.py`'s style: a docstring
naming the requirement (`MCP-01`) and the failure it prevents (a catch-all mount silently
shadowing the platform health check that Render polls).

---

### `backend/tests/test_render_blueprint.py` (test, unit/static)

**Analog:** `backend/tests/test_config.py` — role-match. Unit tests, no container, no
`@pytest.mark.integration`.

**Static repo-file assertion pattern** (`test_config.py:12, 52-58`):
```python
REPO_ROOT = Path(__file__).resolve().parents[2]

...

def test_env_is_gitignored() -> None:
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", ".env"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0
```
`REPO_ROOT = Path(__file__).resolve().parents[2]` is the exact idiom for reaching `render.yaml` at
repo root from `backend/tests/`. Note the `# noqa: S603` / `# noqa: S607` on `subprocess.run` —
required by the `S` ruleset, and already precedented here and at `conftest.py:72, 93`.

**Env-var cross-check target:** every `envVars[].key` in `render.yaml` must correspond to a field on
`Settings` (`config.py:49-57` plus the new ones). `ENVIRONMENT` is a `Literal[...]` — assert
`render.yaml`'s `value: production` is a member.

---

### `backend/tests/conftest.py` (MODIFIED — test fixture)

**Self-analog 1 — the env-seeding autouse fixture** (`conftest.py:45-58`):
```python
@pytest.fixture(scope="session", autouse=True)
def _default_database_url() -> Iterator[None]:
    """Give non-integration tests a parseable ``DATABASE_URL``.

    ``Settings`` fails fast on a missing ``DATABASE_URL``, so unit tests that
    merely construct settings would otherwise need a container. Tests that care
    about the value override it themselves via ``monkeypatch``.
    """
    preexisting = os.environ.get("DATABASE_URL")
    if not preexisting:
        os.environ["DATABASE_URL"] = _PLACEHOLDER_DB_URL
    yield
    if not preexisting:
        os.environ.pop("DATABASE_URL", None)
```
Extend this fixture (or add a sibling in the identical shape) to seed `MCP_AUTH_SECRET` and
`MCP_ALLOWED_HOSTS`. Copy the save/restore-if-not-preexisting guard exactly — it is what keeps the
fixture from clobbering a developer's real environment. Constants go at module scope with a
one-line comment on why the value is safe, mirroring `conftest.py:41-42`:
```python
# Syntactically valid, never connected to. Unit tests construct `Settings`
# without a container.
_PLACEHOLDER_DB_URL = "postgresql://test:test@localhost:5432/test"
```

**Self-analog 2 — the lazy-import rationale in the `client` fixture** (`conftest.py:143-176`):
```python
@pytest.fixture
def client(postgres_url: str) -> Iterator[object]:
    """``TestClient`` for the real app, wired to the test container.

    ``app.main`` is imported lazily -- it reads settings and configures logging
    at import time, so importing it at module scope would run that bootstrap
    before any test had a chance to seed the environment.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    engine = create_async_engine(postgres_url)
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            lifespan_engine = app.state.engine
            app.state.engine = engine
            app.state.sessionmaker = async_sessionmaker(
                engine, expire_on_commit=False, autoflush=False
            )
            try:
                yield test_client
            finally:
                app.state.engine = lifespan_engine
    finally:
        engine.sync_engine.dispose()
```
**Critical for this phase:** the lazy import is now *doubly* load-bearing. `app.main` will import
`app.mcp.server`, which calls `get_settings()` and `streamable_http_app(...)` at import time —
so `MCP_ALLOWED_HOSTS` (which must include `testserver`, the `TestClient` `base_url` host) and
`MCP_AUTH_SECRET` must be in the environment *before* this import. The session-scoped autouse
fixture above runs first, which is why that is the right place for it. The existing docstring
should be extended to say so rather than replaced.

Note the fixture already assigns `app.state.sessionmaker` (line 166) — the MCP `AppContext` reads
exactly that attribute, so the container override propagates to the ping tool for free.

---

### `pyproject.toml`, `.env.example`, `backend/tests/test_config.py` (MODIFIED — config/test)

**`pyproject.toml:6-17`** — pinned-exact dependencies, no version ranges:
```toml
dependencies = [
    "fastapi==0.141.1",
    "uvicorn==0.52.4",
    ...
]
```
Add `"mcp==2.0.0"` to `[project].dependencies` (not the dev group). `httpx2==2.12.0` is currently
dev-only (line 29) and becomes a production transitive — leave the dev pin alone (RESEARCH).

**`.env.example`** — commented, grouped by phase, values always blank:
```
# Phase 3 (Hevy integration) — leave blank until then
HEVY_API_KEY=
# Phase 2 (MCP auth spike) — leave blank until then
MCP_AUTH_SECRET=
```
Update the `MCP_AUTH_SECRET` comment (it is no longer "leave blank until then") and add the three
new `MCP_*` vars in the same commented style. Never a real value — `test_env_is_gitignored`
(`test_config.py:52-58`) and the gitleaks pre-commit hook guard the real `.env`.

**`test_config.py:17-30`** — the `_clean_env` autouse fixture enumerates every env var it clears:
```python
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test starts from a known-empty environment."""
    for var in (
        "ENVIRONMENT",
        "LOG_LEVEL",
        "DATABASE_URL",
        "HEVY_API_KEY",
        "MCP_AUTH_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```
Add the new `MCP_*` vars to this tuple, or a session-level seed will leak into the unit tests that
assert on defaults. Also note the `get_settings.cache_clear()` on both sides — mandatory whenever a
test changes the environment (`config.py:111-121`).

---

## Shared Patterns

### 1. Module docstrings state the failure they prevent
**Source:** `backend/app/config.py:1-13`, `backend/app/logging.py:1-28`, `backend/app/db/session.py:1-7`,
`backend/app/api/routes/health.py:1-7`, `backend/app/core/time.py:1-15`, `backend/tests/conftest.py:1-12`
**Apply to:** every new `.py` file in this phase.

This is the strongest convention in the repo — **100% of existing modules follow it**, including
test modules. The pattern is: one-line summary naming the requirement id, blank line, then prose
explaining *what breaks if you do it the obvious way instead*. Example (`db/session.py:1-7`):
```python
"""Engine and session factories.

Factories, not module-level singletons, on purpose: a module-level
``create_async_engine(...)`` binds its pool to whichever event loop imported it,
which breaks under pytest-asyncio and leaks connections between tests. The
caller (``lifespan``, a fixture, the CLI) owns the engine's lifetime.
"""
```
Phase 2's non-obvious facts that must be captured this way: mount at `/` not `/mcp` (Pitfall 3),
`session_manager.run()` in the parent lifespan (Pitfall 1), `TransportSecuritySettings` or 421
(Pitfall 2), `AuthSettings` mandatory alongside `token_verifier` (Pitfall 4).

### 2. Degrade, never 500 — coarse status out, full detail to the log
**Source:** `backend/app/api/routes/health.py:30-38`
**Apply to:** `backend/app/mcp/tools/ping.py`, `backend/app/mcp/auth.py`
```python
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not 500
        # The detail goes to the log (which runs through the redaction pipeline);
        # the client gets only the coarse state. Connection errors carry the DSN,
        # host, and driver internals (D-05, FOUND-05).
        log.exception("health_db_check_failed")
        database, status_code = "error", 503
```
The `# noqa: BLE001 - <reason>` form with an inline justification is required (Ruff `B` is enabled).
`auth.py` is a variant: it also swallows broadly and fails closed, but logs **nothing at all**,
because the exception could carry the token.

### 3. Three-layer secret defense — the contract new code joins
**Source:** `backend/app/config.py:1-13` (layer 1), `backend/app/logging.py:41-65, 99-123` (layers 2-3),
`backend/app/main.py:62-68` (layer 3 response side)
**Apply to:** `backend/app/config.py`, `backend/app/mcp/auth.py`, `render.yaml`, all new tests
```python
DENY_KEYS = frozenset(
    {
        "api_key",
        ...
        "authorization",
        "auth",
        "secret",
        "mcp_auth_secret",
        "token",
        "access_token",
        ...
    }
)
```
Already covers everything this phase introduces on the key-name side. The action items are:
(a) any *new* secret-valued setting goes into `_SECRET_FIELDS` (`config.py:24`);
(b) non-secret MCP config (`MCP_ISSUER_URL`, `MCP_RESOURCE_URL`, `MCP_ALLOWED_HOSTS`) stays out of it;
(c) the verifier never logs a token or decoded claims.

### 4. Module-level structlog logger
**Source:** `backend/app/main.py:24`, `backend/app/api/routes/health.py:15`
**Apply to:** `backend/app/mcp/tools/ping.py`, `backend/app/mcp/context.py`, `backend/app/mcp/server.py`
```python
import structlog

log = structlog.get_logger()
```
Event names are snake_case with no interpolation: `log.info("service_starting", environment=...)`
(`main.py:42`), `log.exception("health_db_check_failed")` (`health.py:37`). Structured kwargs carry
the variable data so the scrubber and the JSON renderer can see it.

### 5. Decision-id comment tags
**Source:** `backend/app/main.py:56, 60-61`, `backend/app/api/routes/health.py:22-27`
**Apply to:** all new source files
```python
# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)

# D-05: identical behavior in EVERY environment. No traceback ever reaches the
# client; the full traceback goes to the log, findable by correlation id.
```
Phase 2 ids to use: `D-05` (real MCP structure), `D-07` (free→starter tier), `D-08` (real DB
round-trip), `MCP-01`, `MCP-04`, `DEPLOY-01`, `DEPLOY-02`, and `FOUND-05` for anything secret-adjacent.

### 6. Full type annotations, `-> None` included
**Source:** `pyproject.toml:56-62` (`disallow_untyped_defs = true`, `python_version = "3.13"`),
`backend/app/db/session.py:19, 35`, `backend/tests/test_health.py:23`
**Apply to:** every new function, including test functions (`def test_x(client: TestClient) -> None:`).
Modern union syntax throughout (`SecretStr | None`, `config.py:56`), `from collections.abc import
AsyncIterator` not `typing` (`main.py:9`). If `mcp` ships incomplete stubs, add a
`[[tool.mypy.overrides]]` block matching the existing one at `pyproject.toml:64-66`.

### 7. Test conventions
**Source:** `backend/tests/conftest.py:1-12`, `backend/tests/test_health.py`, `pyproject.toml:36-38`
**Apply to:** all four new test files
- `@pytest.mark.integration` on anything touching the Postgres container; keep
  `-m "not integration"` fast.
- Test module docstrings follow the same "why this way" rule — `test_health.py:1-13` and
  `test_secret_redaction.py:1-8` both justify a non-obvious testing choice up front.
- Leak assertions use a `for leak in (...)` loop with an f-string message naming the violated
  requirement id (`test_health.py:47-50`).
- Import `app.main` lazily inside the fixture/after env seeding, never at module scope
  (`conftest.py:150-153`; `test_secret_redaction.py:29-36` shows the module-scope variant with an
  explicit `# noqa: E402`).
- `backend/tests/*` already has `["S101", "S105", "S106"]` ignored (`pyproject.toml:53`), so
  hardcoded test tokens are fine there and nowhere else.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/app/mcp/auth.py` | middleware | request-response | No authentication code exists anywhere in the repo. Conventions come from `config.py:59-69` (fail closed, never echo input) and `core/time.py:43-54` (boundary validator module); the *implementation* must come from RESEARCH.md Pattern 5, which was verified against the installed `mcp` 2.0.0 and `pyjwt` 2.13.0 sources. |
| `render.yaml` | config/IaC | declarative | No Render blueprint has ever existed here. `docker-compose.yml` supplies only the comment discipline. Schema comes from RESEARCH.md "Render Deployment", field-verified against `render.com/docs/blueprint-spec`. |

**Adjacent gap worth flagging to the planner:** the mount-shadowing assertion in
`test_mcp_mount.py` (that `app.mount("/", ...)` does not swallow `/health`, `/docs`,
`/openapi.json`) is a new *class* of test for this repo — there is no precedent for asserting on
route-resolution order. Style it on `test_health.py`, but expect to invent the mechanics.

---

## Metadata

**Analog search scope:** `backend/app/**`, `backend/tests/**`, `backend/migrations/**`, repo root
config files (`pyproject.toml`, `docker-compose.yml`, `.env.example`, `.python-version`)
**Files scanned:** 25 Python files + 5 config files (the complete backend source tree)
**Git history checked:** `git log --diff-filter=A -- backend/app` — all Phase 1 commits, confirming
these analogs are current and not legacy
**Project skills:** none found (`.claude/skills/`, `.agents/skills/`, `.cursor/skills/`,
`.github/skills/` all absent)
**Pattern extraction date:** 2026-08-24

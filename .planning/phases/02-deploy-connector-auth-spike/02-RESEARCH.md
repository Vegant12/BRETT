# Phase 2: Deploy & Connector Auth Spike - Research

**Researched:** 2026-08-24
**Domain:** MCP Python SDK v2 remote server + OAuth 2.1 resource-server auth + Render deployment
**Confidence:** HIGH for SDK integration and deployment mechanics (empirically verified against a live install); MEDIUM for WorkOS dashboard specifics (docs are JS-only, no tenant available to probe)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Auth Strategy & Fallback**
- **D-01:** Prove the deploy + MCP mount + auth-check pipeline first via Claude Code CLI header auth (`claude mcp add --header "Authorization: Bearer $TOKEN"`) — zero extra infra, de-risks the plumbing before touching connector-specific auth.
- **D-02:** Do NOT email Anthropic to request `static_headers` beta access. Skip the beta-access wait entirely and go straight to the fallback mechanism below.
- **D-03:** Connector auth mechanism is a **managed IdP with Dynamic Client Registration (DCR)** — not a hand-rolled OAuth 2.1 resource-server shim. The MCP SDK's `TokenVerifier` validates tokens via JWKS/introspection against the IdP; the SDK itself never issues tokens.
- **D-04:** The managed IdP is **WorkOS**. Set `AuthSettings.issuer_url` to the WorkOS issuer. Note: CLAUDE.md's IdP comparison source (workos.com/blog) is vendor-authored — treat their self-comparison as a shortlist, not a verdict, if setup surfaces unexpected gaps.
- This is the phase's central uncertainty and the primary reason it exists — get D-03/D-04 working and verified end-to-end from an actual Desktop/Web/Mobile client before considering the phase done, per ROADMAP.md success criterion #2.

**Spike vs. Foundation (MCP Scaffolding)**
- **D-05:** Build the **real** `mcp/server.py` structure now, not a disposable script: `MCPServer` with lifespan-based `AppContext` wired to `app.state.engine`/`app.state.sessionmaker`, `TransportSecuritySettings(allowed_hosts=[...])` configured correctly from the start (CLAUDE.md flags the `421 Misdirected Request` default-reject as "the single most likely Phase-5 blocker"), mounted at `/mcp` inside the existing FastAPI app per the CLAUDE.md "FastAPI + MCP Integration Pattern".
- Only the **one tool** registered on this server is throwaway — Phase 6 replaces it with the real tool set, but does not rebuild the mount/lifespan/security plumbing.

**Render Commitment & Cost**
- **D-06:** Deployment platform is **Render**, not Google Cloud Run. Considered and rejected: Cloud Run reintroduces the same cold-start problem unless `min-instances=1` (costing about the same as Render Starter anyway), and needs separate Cloud SQL provisioning + a connector/proxy — more surface area while this phase is already resolving one hard unknown (auth). Render account is already provisioned per PROJECT.md.
- **D-07:** Start on Render's **free** web-service tier + free Postgres. Upgrade to Starter tier + paid Postgres **before** testing against the actual Desktop/Web/Mobile connector (free tier's 30-60s cold start exceeds Claude's 10s OAuth discovery timeout and will masquerade as a broken server). The CLI-proof step (D-01) does not require the paid tier, so cost is deferred until it's actually load-bearing.
  - **Trigger point for the upgrade:** once CLI-proof auth (D-01) is working and before attempting a real connector round-trip. Claude has discretion on exact timing within the plan, but the upgrade must happen before connector testing, not after a confusing failure.

**Throwaway Tool Design**
- **D-08:** The one registered tool performs a **real DB round-trip** (e.g. `fitness_ping` running `SELECT 1` through `app.state.engine`), not a bare echo/no-op. This proves the lifespan-wired `AppContext` → DB-session pattern that every real Phase 6 tool will depend on, not just that the endpoint responds to a call.

### Claude's Discretion
- Exact tool name/response shape for the throwaway DB-ping tool, beyond "real SELECT 1 through the lifespan engine"
- Exact `mcp/server.py` internal file layout (single file vs. small package) as long as it mirrors the CLAUDE.md pattern (lifespan → AppContext → tool reads `ctx.request_context.lifespan_context`)
- Precise WorkOS configuration details (application setup, redirect URIs, JWKS endpoint wiring) — implementation detail of D-04
- Exact Render upgrade trigger mechanics (manual dashboard change vs. `render.yaml` tier bump) as long as it happens before connector testing per D-07

### Deferred Ideas (OUT OF SCOPE)
- Emailing Anthropic for `static_headers` beta access — explicitly declined for this phase (D-02). Not lost, just not pursued now; if WorkOS/DCR setup hits a wall, revisit requesting beta access as an alternate path rather than assuming it's permanently off the table.
- Cloud Run as a deployment platform — considered and explicitly rejected for this phase (D-06). The stack is already host-agnostic per CLAUDE.md, so this remains revisitable later without architectural rework, just not during this auth-focused phase.
- Rate limiting on the MCP endpoint — blueprint §32 lists it as part of minimum private-dev auth, but it's not in this phase's ROADMAP.md success criteria or REQUIREMENTS.md; belongs with Phase 7 (Production Hardening).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **MCP-01** | A remote MCP server is deployed and reachable over HTTPS, independent of any specific device's local configuration | Pattern 1 (mount at `/`), Pattern 2 (session-manager lifespan), Pitfall 1 (`Task group is not initialized`), Pitfall 2 (`421 Invalid Host header`), Deployment section (`render.yaml`) |
| **MCP-04** | MCP server authenticates requests and rejects unauthenticated ones; the mechanism is verified working end-to-end from an actual Claude client (not just a local test client) before being considered done | Pattern 3 (`AuthSettings` + hand-written `TokenVerifier`), Pattern 4 (JWKS verifier for WorkOS), Auth Verification Matrix (exact curl commands + status codes), Claude connector discovery sequence |
| **DEPLOY-01** | Backend and MCP server are deployed to Render over HTTPS with environment-based secrets | `render.yaml` shape, `fromDatabase` env wiring, Pitfall 6 (free tier has no pre-deploy/shell/one-off job → migrations run locally), Python/uv pinning |
| **DEPLOY-02** | A Claude custom connector can be added pointing at the deployed MCP endpoint and successfully discovers and calls tools | Claude connector discovery sequence, RFC 9728 metadata path alignment, WorkOS AuthKit setup, plan-tier confirmation (Free/Pro/Max *can* add custom connectors) |
</phase_requirements>

---

## Summary

The technical shape of this phase is now settled with high confidence. I installed `mcp==2.0.0` alongside the project's exact pinned stack into a clean Python 3.13 venv and drove a real FastAPI app end-to-end — tool discovery, tool call, auth reject, auth accept, transport-security rejection — so the integration pattern in this document is verified behaviour, not inferred from docs. **The full production stack resolves with `mcp==2.0.0` added and requires zero version bumps to any existing pin**; `starlette` is already locked at 1.6.0 and `pydantic` at 2.13.4, both of which satisfy `mcp`'s constraints.

Three findings materially change the plan versus CLAUDE.md's snapshot. First, **the MCP app must be mounted at `/`, not at `/mcp`** — `streamable_http_app()` returns a Starlette app that already owns *two* routes at its own root (`/mcp` and `/.well-known/oauth-protected-resource/mcp`), and mounting it under a `/mcp` prefix relocates both, breaking Claude's OAuth discovery probe. Second, **a mounted sub-app's lifespan never runs**, so the parent FastAPI lifespan must explicitly enter `mcp.session_manager.run()` or the first request dies with `RuntimeError: Task group is not initialized`. Third, **`StaticTokenVerifier` does not exist in SDK v2** — CLAUDE.md's "keep `StaticTokenVerifier` + `AuthSettings`" guidance is stale; `TokenVerifier` is a bare one-method `Protocol` you implement yourself (about ten lines), and it *cannot* be supplied without an `AuthSettings` object carrying both `issuer_url` and `resource_server_url`.

On deployment, CLAUDE.md's free-tier caution understates the problem: Render's free tier has no pre-deploy command, no shell access, and no one-off jobs, meaning **there is no server-side way to run `alembic upgrade head` on free**. The plan must run migrations from the developer machine against Render Postgres's external connection string, or defer the whole deploy until the Starter upgrade. On auth, WorkOS's own MCP documentation now leads with **CIMD, not DCR** — DCR is described as a backwards-compatibility toggle that is *not enabled by default* — and Claude supports `oauth_cimd` out of the box and explicitly prefers it over DCR. D-03's substance (managed IdP, SDK validates tokens via JWKS, never issue tokens ourselves) is unchanged; only the registration mechanism shifts, and it is a dashboard toggle either way.

**Primary recommendation:** Build `backend/app/mcp/server.py` with a module-level `MCPServer`, hand-written `TokenVerifier`, and `AuthSettings` driven entirely by config; mount it with `app.mount("/", mcp_app)` *after* `include_router(health.router)`; enter `mcp.session_manager.run()` inside the existing `lifespan()` *after* `app.state.engine` is assigned. Ship to Render free, migrate from the laptop, prove auth with `claude mcp add --transport http --header`, then upgrade to Starter + paid Postgres, enable CIMD (and DCR as fallback) in WorkOS, register the `/mcp` URL as a Resource Indicator, and swap the verifier implementation from static-secret to JWKS. The tool code, mount, and lifespan wiring do not change across that swap.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MCP protocol transport (Streamable HTTP, envelope parsing, JSON-RPC) | MCP SDK sub-app (ASGI) | — | Owned entirely by `mcp.server`; never hand-implement. Mounted inside the FastAPI process, not a separate service |
| Token issuance, login UI, consent, client registration | External IdP (WorkOS AuthKit) | — | The official SDK is a **resource server only** and "never issues tokens". Hand-rolling an AS is explicitly forbidden by CLAUDE.md §"What NOT to Use" |
| Token *validation* (signature, `iss`, `aud`, `exp`) | API / Backend (`TokenVerifier` impl) | MCP SDK (`RequireAuthMiddleware` invokes it) | The SDK provides the middleware and the 401 shape; the verification logic is ours because the SDK ships no JWKS verifier |
| RFC 9728 protected-resource metadata (`/.well-known/...`) | MCP SDK sub-app | — | Auto-generated from `AuthSettings.resource_server_url`. Do not hand-write this route — path alignment with Claude's probe is the whole point |
| Tool execution + DB access | API / Backend (tool fn → `AppContext` → sessionmaker) | Database | Blueprint §37: MCP calls internal service functions, never HTTP back into itself |
| Engine / connection-pool lifetime | API / Backend (FastAPI `lifespan`) | — | Established Phase 1 pattern (`main.py` docstring). The MCP `AppContext` **borrows** the engine; it must not create a second one |
| Unauthenticated health probe | API / Backend (FastAPI route) | — | Must stay on the FastAPI side. `@mcp.custom_route` exists but "custom routes are never authenticated, even when the rest of the server is" — and Render's health check needs an open endpoint anyway (existing D-04) |
| TLS termination, HTTPS, public hostname | Render platform | — | Render terminates TLS and forwards the original `Host`. Nothing to build; but `Host` is exactly what `TransportSecuritySettings.allowed_hosts` inspects |
| Schema migration application | Developer machine (free tier) → Render pre-deploy (paid tier) | — | `preDeployCommand` is paid-only; free tier has no shell and no one-off jobs. See Pitfall 6 |

---

## Standard Stack

### Core — additions for this phase

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` | **2.0.0** | Remote MCP server | Official Anthropic SDK, targets the current `2026-07-28` spec. `[VERIFIED: PyPI JSON API, queried 2026-08-24 — 2.0.0 uploaded 2026-07-28T13:45:28; latest non-prerelease]` |
| `mcp-types` | **2.0.0** (transitive, exact pin) | Wire types | `mcp==2.0.0` declares `mcp-types==2.0.0` exactly — expect lockstep upgrades. `[VERIFIED: PyPI requires_dist]` |

### Already present — no change required

| Library | Locked Version | Note |
|---------|---------------|------|
| `fastapi` | 0.141.1 | `[VERIFIED: uv.lock]` |
| `starlette` | 1.6.0 | Already at 1.6.0 in `uv.lock`; satisfies `mcp`'s `starlette>=0.27` (py<3.14). No bump. `[VERIFIED: uv.lock + uv pip compile]` |
| `pydantic` | 2.13.4 | Satisfies `mcp`'s `pydantic>=2.12.0`. `[VERIFIED]` |
| `httpx2` | 2.12.0 | Currently in the **dev** group only; `mcp` requires `httpx2>=2.5.0`, so it becomes a production transitive dep. `[VERIFIED]` |

### Pulled in transitively by `mcp` (no explicit pin needed)

| Library | Resolved | Relevance to this phase |
|---------|----------|------------------------|
| `pyjwt[crypto]` | **2.13.0** | **Load-bearing for D-03/D-04** — the JWKS verifier is built on `jwt.PyJWKClient` + `jwt.decode`. No new dependency needed. `[VERIFIED: live install]` |
| `cryptography` | 50.0.0 | RS256 verification backend for pyjwt. `[VERIFIED: live install]` |
| `sse-starlette` | 3.4.8 | SSE response framing. `[VERIFIED]` |
| `jsonschema` | 4.26.0 | Tool input-schema validation. `[VERIFIED]` |
| `opentelemetry-api` | 1.44.0 | Built-in tracing spans. `[VERIFIED]` |
| `python-multipart` | 0.0.32 | `[VERIFIED]` — note: **not listed in CLAUDE.md's dependency table**; harmless but present |

**Full-stack resolution proof** `[VERIFIED: uv pip compile --python 3.13, 2026-08-24]` — adding `mcp==2.0.0` to the existing production pin set resolves to:

```
alembic==1.19.1   asyncpg==0.31.0   fastapi==0.141.1   httpx2==2.12.0
mcp==2.0.0        pydantic==2.13.4  pyjwt==2.13.0      sqlalchemy==2.0.52
sse-starlette==3.4.8                starlette==1.6.0
```

Zero conflicts. Zero forced upgrades of existing pins.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-written `TokenVerifier` | FastMCP 3.x `JWTVerifier` / `RemoteAuthProvider` | FastMCP ships batteries-included JWKS verification, saving ~40 lines. Cost: a fast-moving third-party framework in the critical path of health data, a different API from the official SDK, and PROJECT.md's constraint says "MCP Python SDK". **Not recommended** — the JWKS verifier is small and `pyjwt` is already in the tree |
| WorkOS AuthKit (D-04, locked) | Auth0, Keycloak, Stytch, `oauth_anthropic_creds` | Out of scope — D-04 is locked. If WorkOS surfaces a hard blocker, the deferred fallback per CONTEXT.md is requesting `static_headers` beta access, not swapping IdP mid-phase |
| DCR registration | **CIMD** (`oauth_cimd`) | See Auth Mechanism Decision below. Both are dashboard toggles in WorkOS; Claude supports both out of the box and prefers CIMD |
| DCR registration | Pre-registered client ID + secret entered in the connector's Advanced settings | `[CITED: claude.com/docs/connectors/building/authentication]` — "avoids dynamic client registration entirely, and the credentials are scoped to the organization that entered them." A clean escape hatch if neither CIMD nor DCR can be enabled |
| `stateless_http=True` | `stateless_http=False` | Both verified working; neither emits an `Mcp-Session-Id` under the 2026-07-28 protocol. Choose `True` — no session state to lose across Render restarts or a free-tier spin-down |

**Installation:**

```bash
uv add "mcp==2.0.0"
# httpx2 moves from the dev group to a production transitive; leave the dev pin alone
```

---

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────────────────────┐
   Claude Desktop / │  1. POST https://brett.onrender.com/mcp  │
   Web / Mobile ────┤     (no token)                           │
   (egress          └──────────────────┬───────────────────────┘
    160.79.104.0/21)                   │
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │  RENDER WEB SERVICE  (TLS terminated, original Host forwarded)          │
  │                                                                        │
  │   FastAPI app  (app.main:app)                                          │
  │   ├── lifespan:  engine → app.state.engine                             │
  │   │              THEN  mcp.session_manager.run()   ← order matters     │
  │   │                                                                    │
  │   ├── GET /health ──────────────► live SELECT 1 ──┐   (open, no auth)  │
  │   │   [registered FIRST]                          │                    │
  │   │                                               │                    │
  │   └── Mount("/", mcp_app)  [registered LAST]      │                    │
  │        │                                          │                    │
  │        ├─ Route /mcp                              │                    │
  │        │   │                                      │                    │
  │        │   ├─ TransportSecurity: Host allowed? ──── no ──► 421         │
  │        │   │                       Origin ok?  ──── no ──► 403         │
  │        │   ├─ RequireAuthMiddleware                                    │
  │        │   │     └─ TokenVerifier.verify_token(bearer)                 │
  │        │   │            ├─ None  ──► 401 + WWW-Authenticate:           │
  │        │   │            │             Bearer resource_metadata="…"  ─┐ │
  │        │   │            └─ AccessToken ──┐                           │ │
  │        │   │                             ▼                           │ │
  │        │   └─ StreamableHTTP ──► envelope check (_meta keys)          │ │
  │        │                          └─► tool dispatch                   │ │
  │        │                                │                             │ │
  │        │                        fitness_ping(ctx)                     │ │
  │        │                                │                             │ │
  │        │                    ctx.request_context.lifespan_context      │ │
  │        │                                │  (AppContext)               │ │
  │        │                                ▼                             │ │
  │        │                        app.state.sessionmaker ───────────────┼─┼──► Render
  │        │                                                              │ │    Postgres
  │        └─ Route /.well-known/oauth-protected-resource/mcp ◄───────────┘ │    (SELECT 1)
  │             returns { resource, authorization_servers:[AuthKit] }       │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │  2. Claude reads authorization_servers[0]
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │  WorkOS AuthKit   https://<project>.authkit.app                        │
  │   3. GET /.well-known/oauth-authorization-server   (RFC 8414)          │
  │   4. CIMD or DCR client identification                                 │
  │   5. Authorization Code + PKCE(S256) + resource=<mcp url>              │
  │      redirect → https://claude.ai/api/mcp/auth_callback                │
  │   6. token endpoint → JWT (aud = resource indicator)                   │
  │   7. GET /oauth2/jwks  ◄──── our TokenVerifier fetches signing keys    │
  └────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                    8. Retry POST /mcp with Authorization: Bearer <jwt>
                       → 200, tools/list, tools/call
```

**Discovery order Claude actually uses** `[CITED: claude.com/docs/connectors/building/authentication]`:
1. Preferred — the `resource_metadata=` parameter on the `401`'s `WWW-Authenticate` header (the SDK emits this automatically).
2. Fallback probe — `GET /.well-known/oauth-protected-resource/<mcp-path>`, i.e. `/.well-known/oauth-protected-resource/mcp`.
3. Fallback probe — `GET /.well-known/oauth-protected-resource`.

The SDK serves exactly path (2) and points the header at it. This alignment is **only true if the sub-app is mounted at `/`** — see Pitfall 3.

### Recommended Project Structure

```
backend/app/
├── main.py                 # MODIFIED: import mcp_app, extend lifespan, mount LAST
├── config.py               # MODIFIED: add MCP auth settings + _SECRET_FIELDS entries
├── api/routes/health.py    # unchanged
└── mcp/                    # NEW package (D-05: real structure, not a spike script)
    ├── __init__.py
    ├── context.py          # AppContext dataclass + mcp_lifespan
    ├── auth.py             # StaticTokenVerifier + AuthKitJWKSVerifier
    ├── server.py           # MCPServer instance, AuthSettings, streamable_http_app()
    └── tools/
        └── ping.py         # fitness_ping (throwaway; Phase 6 replaces this dir's contents)
```

```
render.yaml                 # NEW, repo root
.python-version             # exists ("3.13") — Render reads it
uv.lock                     # exists at repo root — Render requires it at the service root dir
```

### Pattern 1: Mount at `/`, never at `/mcp`

**What:** `streamable_http_app()` returns a Starlette app that already owns its own paths. Mounting it under a prefix relocates *all* of them.

**Verified route inventory of the returned sub-app** `[VERIFIED: live introspection]`:

```python
>>> mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", ...)
>>> [r.path for r in mcp_app.routes]
['/mcp', '/.well-known/oauth-protected-resource/mcp']
```

**When to use:** Always, for this project.

```python
# backend/app/main.py  -- Source: https://py.sdk.modelcontextprotocol.io/v2/run/asgi
app = FastAPI(title="BRETT", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(health.router)   # OWN ROUTES FIRST — they win the match

app.mount("/", mcp_app)             # CATCH-ALL LAST
```

Official docs are explicit: *"Ensure your own routes are defined before the Mount."* `[CITED: py.sdk.modelcontextprotocol.io/v2/run/asgi]`

**Verified coexistence** `[VERIFIED: live FastAPI TestClient run]` — with `app.mount("/", mcp_app)` in place: `GET /health` → 200, `GET /openapi.json` → 200, `GET /docs` → 200, `GET /nope` → 404, `POST /mcp` → 200. FastAPI's own routes are unaffected.

### Pattern 2: Drive the session manager from the parent lifespan

**What:** Starlette does not run a mounted sub-application's lifespan. `streamable_http_app()` sets `lifespan=lambda app: session_manager.run()` on the app it returns — and that lifespan is silently dropped when you mount it.

**When to use:** Always, whenever the MCP app is mounted rather than run standalone.

```python
# backend/app/main.py
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.mcp.server import mcp, mcp_app   # module-level; streamable_http_app() ran at import


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    log.info("service_starting", environment=settings.environment)
    try:
        # ORDER IS LOAD-BEARING: app.state must be populated before the MCP
        # lifespan runs, because mcp_lifespan reads app.state.sessionmaker.
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            yield
    finally:
        await engine.dispose()
        log.info("service_stopped")
```

**Verified ordering** `[VERIFIED: instrumented live run]` — printed sequence is `FastAPI lifespan ENTER` → `MCP lifespan ENTER` → *(requests)* → `MCP lifespan EXIT` → `FastAPI lifespan EXIT`. The MCP lifespan runs **once at startup**, not per request, so reading `app.state.sessionmaker` from it is safe.

### Pattern 3: `AppContext` borrows the engine — never creates one

**What:** The MCP lifespan receives the `MCPServer`, not the FastAPI app, so the bridge is a module-level reference to the app object (or to a small holder).

```python
# backend/app/mcp/context.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from mcp.server import MCPServer


@dataclass(slots=True)
class AppContext:
    """What every MCP tool is handed. Borrowed, never owned."""
    sessionmaker: async_sessionmaker[AsyncSession]


@asynccontextmanager
async def mcp_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    # Imported here, not at module scope, to avoid a circular import with main.
    from app.main import app
    # Phase 1 invariant: the engine's lifetime belongs to the FastAPI lifespan.
    # This context borrows the sessionmaker; it must NOT call make_engine().
    yield AppContext(sessionmaker=app.state.sessionmaker)
```

**Verified** `[VERIFIED: live run]` — a tool reading `ctx.request_context.lifespan_context.sessionmaker` received the exact object assigned to `app.state.sessionmaker` by the FastAPI lifespan.

### Pattern 4: The tool signature that keeps `ctx` out of the model's schema

**What:** A `Context`-annotated parameter is stripped from `inputSchema`; a *mis*-annotated one is not.

```python
# backend/app/mcp/tools/ping.py
import structlog
from mcp.server.mcpserver import Context
from pydantic import BaseModel
from sqlalchemy import text

from app.mcp.context import AppContext

log = structlog.get_logger()


class PingResult(BaseModel):
    status: str
    database: str


async def fitness_ping(ctx: Context[AppContext]) -> PingResult:
    """Round-trip the database through the lifespan-wired session factory."""
    database = "connected"
    try:
        sessionmaker = ctx.request_context.lifespan_context.sessionmaker
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - mirrors health.py: degrade, never leak
        log.exception("mcp_ping_db_check_failed")
        database = "error"
    return PingResult(status="ok", database=database)
```

**Verified schema output** `[VERIFIED: live tools/list]`:

```json
{"name": "fitness_ping",
 "inputSchema": {"type": "object", "properties": {}, "title": "fitness_pingArguments"},
 "outputSchema": {"type": "object", "title": "PingResult",
                  "properties": {"status": {"type": "string"}, "database": {"type": "string"}},
                  "required": ["status", "database"]}}
```

And `tools/call` returns `structuredContent: {"status": "ok", "database": "connected"}` with `isError: false`. Returning a `BaseModel` auto-populates both `outputSchema` and `structuredContent` — this satisfies MCP-03's "structured JSON" rule for free in Phase 6.

**Counter-example** `[VERIFIED: live run]` — writing `def fitness_ping(ctx)` with **no annotation** produced `"properties": {"ctx": {"type": "string"}}, "required": ["ctx"]`, i.e. the model was asked to supply a `ctx` string, and every call failed validation. The annotation is not cosmetic.

### Pattern 5: `AuthSettings` + a hand-written `TokenVerifier`

**What:** `TokenVerifier` is a `Protocol` with exactly one method. There is no base class to subclass and no shipped implementation.

```python
# mcp/server/auth/provider.py  -- VERIFIED source
class TokenVerifier(Protocol):
    """Protocol for verifying bearer tokens."""
    async def verify_token(self, token: str) -> AccessToken | None: ...
```

`AccessToken` fields `[VERIFIED]`: `token: str`, `client_id: str`, `scopes: list[str]` (all required), plus optional `expires_at: int | None`, `resource: str | None`, `subject: str | None`, `claims: dict | None`.

**Stage A — static bearer (satisfies D-01):**

```python
# backend/app/mcp/auth.py
import secrets
from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    """Constant-time comparison against MCP_AUTH_SECRET (D-01 CLI proof)."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, self._secret):
            return AccessToken(token=token, client_id="brett-cli", scopes=[])
        return None
```

**Stage B — WorkOS AuthKit JWKS (satisfies D-03/D-04):**

```python
# backend/app/mcp/auth.py  (continued)
import anyio.to_thread
import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken


class AuthKitJWTVerifier:
    """Validate a WorkOS AuthKit JWT against the tenant's JWKS.

    PyJWKClient.fetch_data uses a BLOCKING urllib.request.urlopen (verified in
    pyjwt 2.13.0 source). Calling it directly from this async method stalls the
    event loop for the duration of the HTTPS round trip, so it is pushed to a
    worker thread. cache_jwk_set=True (default, 300s lifespan) means this is a
    cold-start cost and a 5-minute refresh, not a per-request cost.
    """

    def __init__(self, issuer: str, audience: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks = PyJWKClient(f"{self._issuer}/oauth2/jwks", cache_jwk_set=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims = await anyio.to_thread.run_sync(
                lambda: jwt.decode(
                    token,
                    key.key,
                    algorithms=["RS256"],
                    issuer=self._issuer,
                    audience=self._audience,          # the registered Resource Indicator
                    options={"require": ["exp", "iss", "aud"]},
                )
            )
        except Exception:  # noqa: BLE001 - any validation failure is just "unauthenticated"
            return None    # NEVER log the token or the claims (FOUND-05)
        return AccessToken(
            token=token,
            client_id=claims.get("client_id", "authkit"),
            scopes=(claims.get("scope") or "").split(),
            expires_at=claims.get("exp"),
            subject=claims.get("sub"),
        )
```

**Wiring — identical for both stages:**

```python
# backend/app/mcp/server.py
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from app.config import get_settings
from app.mcp.auth import build_token_verifier   # returns Static or AuthKit per config
from app.mcp.context import mcp_lifespan
from app.mcp.tools.ping import fitness_ping

settings = get_settings()

mcp = MCPServer(
    name="BRETT",
    version="0.1.0",
    lifespan=mcp_lifespan,
    token_verifier=build_token_verifier(settings),
    auth=AuthSettings(
        issuer_url=settings.mcp_issuer_url,               # WorkOS AuthKit domain
        resource_server_url=settings.mcp_resource_url,    # https://<host>/mcp EXACTLY
        required_scopes=None,
    ),
)

mcp.add_tool(fitness_ping, name="fitness_ping", description="Database connectivity check.")

# MUST run at import time: mcp.session_manager raises RuntimeError until this
# has been called, and main.py's lifespan reads mcp.session_manager.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=settings.mcp_allowed_hosts,   # ["brett.onrender.com"]
        allowed_origins=[],                          # Claude is server-to-server; no Origin
    ),
)
```

### Anti-Patterns to Avoid

- **`app.mount("/mcp", mcp_app)`** — relocates the endpoint to `/mcp/mcp` and the metadata to `/mcp/.well-known/oauth-protected-resource/mcp`, which Claude never probes. `[VERIFIED: both paths returned 404 in a live run]`
- **Omitting `mcp.session_manager.run()`** — every MCP request 500s with `RuntimeError: Task group is not initialized. Make sure to use run().` `[VERIFIED]`
- **`from mcp.server.fastmcp import FastMCP`** — removed in v2. Every pre-2026 tutorial uses it.
- **Creating a second engine inside `mcp_lifespan`** — violates the Phase 1 invariant documented in `main.py` and doubles the Postgres connection count against a free-tier DB.
- **`@mcp.custom_route("/health", ...)`** — *"Custom routes are never authenticated, even when the rest of the server is."* `[CITED: py.sdk.modelcontextprotocol.io/v2/run/asgi]` Health already lives on the FastAPI side; keep it there.
- **Calling `PyJWKClient` directly from `async def verify_token`** — blocks the event loop on a network round trip.
- **Adding `CORSMiddleware`** — unnecessary. Claude connectors call from Anthropic's servers (`160.79.104.0/21`), not a browser, and send no `Origin`. Setting `allowed_origins` to a non-empty list without need creates a 403 trap.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OAuth 2.1 authorization server | Custom `/authorize`, `/token`, `/register` endpoints | WorkOS AuthKit | The SDK's own docs say `auth_server_provider` "should be avoided in new implementations"; FastMCP calls self-hosted AS "an extremely advanced pattern that most users should avoid". This is health data |
| RFC 9728 protected-resource metadata | A hand-written `/.well-known/...` FastAPI route | `AuthSettings.resource_server_url` | The SDK derives the exact path Claude probes and the exact `resource_metadata=` value in the 401 header. Hand-writing it is how the two drift apart |
| The `401` + `WWW-Authenticate` challenge shape | Custom auth dependency raising `HTTPException(401)` | `token_verifier` + SDK `RequireAuthMiddleware` | Claude requires `401` (not 403, not a tool error) with a `resource_metadata=` parameter, and *"does not honor a `WWW-Authenticate` header on a `200` response"*. The SDK emits the compliant shape |
| JWT signature verification | Manual JWKS fetch + RSA reconstruction | `jwt.PyJWKClient` + `jwt.decode` | Already in the dependency tree via `mcp`. Key rotation, `kid` matching, and caching are handled |
| Streamable HTTP transport / envelope parsing | Custom JSON-RPC POST handler | `mcp.streamable_http_app()` | The 2026-07-28 envelope (`_meta` keys, `Mcp-Method`/`Mcp-Name` headers, dual-era negotiation) is non-obvious and versioned |
| DNS-rebinding / Host validation | Custom middleware | `TransportSecuritySettings` | Already built in — and on by default, which is why it bites you |
| Migration orchestration on deploy | App-startup `alembic upgrade head` | Render pre-deploy (paid) or a local run (free) | Startup migrations race across restarts. The Phase 1 `lifespan` docstring already commits to this |

**Key insight:** In this phase, nearly every "custom" solution is worse *specifically because Claude's client behaviour is a compatibility contract you can't see*. The exact 401 shape, the exact metadata path, the exact `resource` string — these have no local test that proves them; the only oracle is a real connector round-trip. Using the SDK's generated forms means the contract is maintained by the people who also write the client.

---

## Common Pitfalls

### Pitfall 1: `RuntimeError: Task group is not initialized`

**What goes wrong:** Every request to `/mcp` returns a 500. The mount itself looks correct.
**Why it happens:** Starlette does not run a mounted sub-application's lifespan, and `streamable_http_app()` puts `session_manager.run()` in exactly that lifespan.
**How to avoid:** `await stack.enter_async_context(mcp.session_manager.run())` inside the parent FastAPI lifespan.
**Warning signs:** Traceback ends in `mcp/server/streamable_http_manager.py:174`. `[VERIFIED: reproduced live]`

### Pitfall 2: `421 Misdirected Request — Invalid Host header`

**What goes wrong:** Works perfectly on localhost, then every deployed request returns 421 with no MCP-level error body.
**Why it happens:** When `transport_security` is `None` and `host` defaults to `"127.0.0.1"`, the SDK **auto-enables** DNS-rebinding protection with `allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]`. Render forwards the real `Host`, which is not in that list.
**How to avoid:** Pass `TransportSecuritySettings(allowed_hosts=["<service>.onrender.com"], allowed_origins=[])`.
**Warning signs:** Body is the literal string `Invalid Host header`. A wrong `Origin` produces `403 Invalid Origin header` instead.
**Verified matrix** `[VERIFIED: live run]`:

| Config | Request | Result |
|---|---|---|
| `transport_security=None` | `Host: brett.onrender.com` | **421** `Invalid Host header` |
| `allowed_hosts=["brett.onrender.com"]` | matching Host, no Origin | **200** |
| `allowed_hosts=["brett.onrender.com"]` | `Origin: https://evil.com` | **403** `Invalid Origin header` |
| `allowed_hosts=["brett.onrender.com"]` | `Host: wrong.example.com` | **421** `Invalid Host header` |
| `enable_dns_rebinding_protection=False` | any Host | **200** |

Adding a Render custom domain later requires adding it to `allowed_hosts` — make it a comma-separated config value, not a literal.

### Pitfall 3: Mounting at `/mcp` silently breaks OAuth discovery

**What goes wrong:** Static-bearer auth via Claude Code works fine. The real connector fails with "Couldn't reach the MCP server" and WorkOS sees no traffic at all.
**Why it happens:** The sub-app owns `/.well-known/oauth-protected-resource/mcp` at *its* root. Mounted under `/mcp`, that becomes `/mcp/.well-known/...`, which Claude never probes.
**How to avoid:** `app.mount("/", mcp_app)` with `streamable_http_path="/mcp"`.
**Warning signs:** *"A common symptom of a discovery failure is that your MCP server receives the initial request but your authorization server sees no traffic at all."* `[CITED: claude.com/docs/connectors/building/authentication]`
**This pitfall is invisible during Stage A** — the D-01 CLI proof never triggers a 401, so discovery is never exercised. Add an explicit `curl` assertion on the metadata path (see Auth Verification Matrix) rather than waiting for the connector to fail.

### Pitfall 4: `ValueError: Cannot specify auth_server_provider or token_verifier without auth settings`

**What goes wrong:** `MCPServer(..., token_verifier=StaticTokenVerifier(secret))` raises at import time.
**Why it happens:** The constructor rejects a verifier without an `AuthSettings`, and `AuthSettings` requires **both** `issuer_url` and `resource_server_url` (both are `PydanticUndefined`, i.e. mandatory).
**How to avoid:** Supply `AuthSettings` from the very first commit, with `issuer_url` pointing at the eventual WorkOS AuthKit domain. During Stage A the value is never exercised (a valid header means no 401, so no discovery), but it must be a syntactically valid `AnyHttpUrl`.
**Warning signs:** Import-time `ValueError` from `mcp/server/mcpserver/server.py:242`. `[VERIFIED: reproduced live]`

### Pitfall 5: A naive `curl` gets `-32602`, not a tool result

**What goes wrong:** Hand-written verification `curl` returns `400` with *"params._meta must be an object carrying the required 'io.modelcontextprotocol/protocolVersion' and 'io.modelcontextprotocol/clientCapabilities' envelope keys"*, and it looks like the server is broken.
**Why it happens:** The 2026-07-28 transport requires a per-request envelope in `params._meta` — this is new in SDK v2 and absent from every older example.
**How to avoid:** Use the exact body in the Auth Verification Matrix below, or verify with `claude mcp get` / `mcp.Client` instead of raw curl for the *functional* check. Raw curl is still the right tool for the *auth* check, because the 401 fires in middleware before envelope parsing.
**Warning signs:** JSON-RPC error code `-32602`. `[VERIFIED: reproduced live]`

### Pitfall 6: Render free tier has no way to run migrations

**What goes wrong:** The service deploys, `/health` returns `{"status":"degraded","database":"error"}` or the tables simply don't exist, and there's no obvious way to fix it.
**Why it happens:** Three independent free-tier restrictions compound:

| Mechanism | Free tier | Source |
|---|---|---|
| `preDeployCommand` | **Unavailable** — *"available for paid web services, private services, and background workers"* | `[CITED: render.com/docs/deploys]` |
| Shell access (SSH or dashboard) | **Unavailable** | `[CITED: render.com/docs/free]` |
| One-off jobs | **Unavailable** | `[CITED: render.com/docs/free]` |

**How to avoid:** Run migrations from the developer machine against Render Postgres's **external** connection string:

```bash
DATABASE_URL="<render external connection string>" \
  uv run --directory backend python -m alembic upgrade head
```

This matches the existing pattern exactly — `backend/tests/conftest.py` already invokes Alembic this way (`cwd=backend`, `DATABASE_URL` injected via env), and `migrations/env.py` reads the URL from `get_settings().async_database_url`. Add `preDeployCommand` to `render.yaml` at the same time as the Starter upgrade (D-07), not before.
**Warning signs:** Blueprint sync errors mentioning `preDeployCommand`, or a healthy service with an empty schema.

### Pitfall 7: `uv.lock` must sit at the **service root**, but the app lives in `backend/`

**What goes wrong:** Render falls back to pip, or `uv sync` can't find the lockfile.
**Why it happens:** *"To use uv, a `uv.lock` file must be present in your service's root directory."* `[CITED: render.com/docs/python-version]` This repo's `pyproject.toml` and `uv.lock` are at the **repo root**; the package is `backend/app`.
**How to avoid:** Leave `rootDir` unset (repo root) and point uvicorn at the package directory:

```yaml
startCommand: uv run uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
```

Note `pyproject.toml`'s `pythonpath = ["backend"]` is under `[tool.pytest.ini_options]` — it applies to pytest only and does **not** help uvicorn. `--app-dir backend` (or `PYTHONPATH=backend`) is required. Likewise Alembic must run with `cwd=backend`, since `alembic.ini` and `migrations/` both live there.

### Pitfall 8: The `resource` string must match what the user types, character for character

**What goes wrong:** OAuth completes, then every request 401s, or WorkOS refuses the token request.
**Why it happens:** Three values must agree exactly:
1. `AuthSettings.resource_server_url` → becomes the `resource` field in the metadata document
2. The URL the user pastes into Claude's "Add custom connector" dialog
3. The Resource Indicator registered in the WorkOS dashboard

*"The protected resource metadata document's `resource` field must match your MCP server URL exactly as the user enters it in Claude, including any path component."* `[CITED: claude.com/docs/connectors/building/authentication]`
**How to avoid:** Fix on `https://<service>.onrender.com/mcp` (no trailing slash) and use that literal string in all three places. Put it in config once.
**Warning signs:** Token requests rejected by WorkOS, or `aud` mismatch in the verifier.

### Pitfall 9: `authorization_servers[0]` wins and there is no fallback

*"If you list more than one, Claude uses the first entry and does not fall back to later entries."* `[CITED: claude.com/docs/connectors/building/authentication]` The SDK builds this list as `[auth.issuer_url]` — a single entry — so this is safe by construction, but do not be tempted to add a second.

### Pitfall 10: Free-tier cold start vs. Claude's 10-second budget

`[CITED: render.com/docs/free]` free web services stop after **15 minutes** without inbound traffic and spin up in **about one minute**; the workspace gets **750 free instance hours/month**. `[CITED: claude.com/docs/connectors/building/authentication]` Claude waits up to **10 seconds** for discovery, registration, and token endpoints (30 s for refresh). A cold start therefore *always* exceeds the budget and presents as "Couldn't reach the MCP server." This is exactly D-07's rationale and is now confirmed from primary sources on both sides. Free Postgres additionally **expires 30 days after creation**, with a 14-day grace period, and is capped at 1 GB.

---

## Auth Verification Matrix (Success Criterion #3)

Success criterion #3 — *"an unauthenticated request to the MCP endpoint is rejected and an authenticated one succeeds, verified against the deployed URL"* — concretely means the following, all against `https://$HOST/mcp`. Status codes below are `[VERIFIED: live run against a real MCPServer]`.

```bash
HOST=brett.onrender.com
URL="https://$HOST/mcp"

# The 2026-07-28 per-request envelope. Omitting _meta yields -32602, not an auth error.
BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{
  "io.modelcontextprotocol/protocolVersion":"2026-07-28",
  "io.modelcontextprotocol/clientCapabilities":{}}}}'

HDRS=(-H "Content-Type: application/json"
      -H "Accept: application/json, text/event-stream"
      -H "MCP-Protocol-Version: 2026-07-28"
      -H "Mcp-Method: tools/list"
      -H "Mcp-Name: tools/list")
```

| # | Command | Expected | Proves |
|---|---------|----------|--------|
| 1 | `curl -si -X POST "$URL" "${HDRS[@]}" -d "$BODY"` | **401**, body `{"error":"invalid_token",...}`, header `WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://$HOST/.well-known/oauth-protected-resource/mcp"` | MCP-04 reject half + Claude's discovery pointer is present and correct |
| 2 | same, `-H "Authorization: Bearer wrong-token"` | **401**, identical body | The verifier actually verifies; it isn't just presence-checking the header |
| 3 | same, `-H "Authorization: Bearer $MCP_AUTH_SECRET"` | **200**, `result.tools[0].name == "fitness_ping"` | MCP-04 accept half + tool discovery |
| 4 | `tools/call` body with `"params":{"name":"fitness_ping","arguments":{},"_meta":{...}}` and `Mcp-Name: fitness_ping` | **200**, `structuredContent == {"status":"ok","database":"connected"}` | D-08 real DB round-trip through the lifespan-wired context |
| 5 | `curl -s "https://$HOST/.well-known/oauth-protected-resource/mcp"` | **200**, `{"resource":"https://$HOST/mcp","authorization_servers":["https://<project>.authkit.app"],"bearer_methods_supported":["header"]}` | Pitfall 3 caught before the connector test; `resource` matches Pitfall 8 |
| 6 | `curl -s -o /dev/null -w '%{http_code}' "https://$HOST/health"` | **200** | Render health check path is reachable and unauthenticated |
| 7 | `curl -si -X POST "$URL" "${HDRS[@]}" -H "Host: wrong.example.com" -d "$BODY"` | **421** `Invalid Host header` | `TransportSecuritySettings` is active rather than disabled |

**Claude Code CLI verification (D-01)** `[VERIFIED: claude 2.1.237 --help output]` — exact syntax:

```bash
claude mcp add --transport http brett "https://$HOST/mcp" \
  --header "Authorization: Bearer $MCP_AUTH_SECRET"

claude mcp list          # approved servers are health-checked
claude mcp get brett     # shows connection status + discovered tools
claude mcp remove brett
```

Confirmed flags on `claude mcp add`: `-t/--transport {stdio,sse,http}`, `-H/--header` (repeatable), `-s/--scope {local,user,project}`, `--client-id`, `--client-secret`, `--callback-port`. Note the options list mislabels `--header` as *"Set WebSocket headers"*, but the command's own example is `claude mcp add --transport http corridor https://app.corridor.dev/api/mcp --header "Authorization: Bearer ..."` — HTTP is the intended use.

Also available and useful: `claude mcp login <name>` (drives the OAuth flow for an HTTP server or claude.ai connector) and `claude mcp logout <name>` (clears stored credentials) — these let the WorkOS OAuth path be smoke-tested from the CLI before touching Desktop/Web/Mobile.

---

## Auth Mechanism Decision: CIMD vs DCR

D-03 locks "managed IdP with Dynamic Client Registration." Research surfaced a nuance the planner should account for — **the locked substance holds, but the specific registration mechanism deserves a second look**, and the choice is a dashboard toggle either way.

| | `oauth_dcr` (RFC 7591) | `oauth_cimd` (Client ID Metadata Document) |
|---|---|---|
| Claude support | Supported out of the box `[CITED]` | Supported out of the box `[CITED]` |
| WorkOS AuthKit | *"available as a backwards-compatibility option for older MCP clients but **is not enabled by default**"* `[CITED: workos.com/docs/authkit/mcp]` | Enabled under **Connect → Configuration**; the WorkOS MCP guide leads with it `[CITED]` |
| Anthropic's own guidance | *"For servers expecting high traffic from the directory, prefer CIMD or `oauth_anthropic_creds` over DCR. DCR causes Claude to register a new client on every fresh connection"* `[CITED]` | Preferred |
| Selection rule | Claude's fallback if CIMD isn't advertised | Claude selects CIMD **only** when the AS metadata advertises **both** `"client_id_metadata_document_supported": true` **and** `"none"` in `token_endpoint_auth_methods_supported` `[CITED]` |
| Claude Code | Uses its own CIMD document regardless `[CITED]` | Native fit |

**Recommendation for the planner:** enable **both** toggles in WorkOS. CIMD is the preferred path and what WorkOS documents first; DCR remains on as the automatic fallback, which is precisely what D-03 asked for. Nothing in the MCP server code differs between the two — `AuthSettings` and the `TokenVerifier` are identical. This is a WorkOS dashboard decision, not an architecture decision, so it does not overturn D-03.

**Note on the `static_headers` blocker in STATE.md:** the concern was that `static_headers` is "org-admin-shaped" and unconfirmed for a personal account. That is confirmed correct — `static_headers` is described as *"entered by an organization administrator"* and remains **Beta**. However, `[CITED: claude.com/docs/connectors/custom/remote-mcp]` **Free, Pro, and Max plans can add custom connectors** (Customize → Connectors → "Add custom connector", with optional OAuth credentials in Advanced settings). The OAuth path is therefore fully available on a personal account, which is what makes D-02/D-03/D-04 viable.

---

## WorkOS AuthKit Setup

Confidence: **MEDIUM**. WorkOS's MCP documentation is JavaScript-only (`jose`); there are no Python examples, and I have no tenant to probe. Dashboard labels should be confirmed at execution time.

**Dashboard steps** `[CITED: workos.com/docs/authkit/mcp]`:

| # | Step | Location | Note |
|---|------|----------|------|
| 1 | Create a WorkOS project; note the **AuthKit domain** | Dashboard | Format is `https://<project-name>-<id>.authkit.app` `[VERIFIED: probing `https://divine-heart-45-staging.authkit.app/.well-known/oauth-authorization-server` returned a WorkOS-shaped `entity_not_found` error naming the AuthKit domain — confirming both the hostname pattern and the metadata path are real]` |
| 2 | **Enable CIMD** | Connect → Configuration | Required for modern MCP clients to identify themselves |
| 3 | **Enable DCR** | Connect → Configuration | Off by default; enable as the fallback per D-03 |
| 4 | **Add a Resource Indicator** = `https://<host>/mcp` | Connect → Configuration | AuthKit stamps this into the token's `aud`. Must match Pitfall 8's single literal string |
| 5 | *(optional)* set a default Resource Indicator | | For clients that omit the `resource` parameter |
| 6 | Confirm redirect URI acceptance | | Hosted Claude: `https://claude.ai/api/mcp/auth_callback`. Claude Code: RFC 8252 loopback on an **ephemeral port** — the AS must accept `http://localhost/callback` and `http://127.0.0.1/callback` with the port component ignored `[CITED]` |

**Endpoints the plan needs** `[CITED: workos.com/docs/authkit/mcp]`:

| Purpose | URL |
|---------|-----|
| Issuer (`AuthSettings.issuer_url`) | `https://<project>.authkit.app` |
| AS metadata (RFC 8414) — Claude fetches this | `https://<project>.authkit.app/.well-known/oauth-authorization-server` |
| JWKS — our verifier fetches this | `https://<project>.authkit.app/oauth2/jwks` |
| Protected-resource metadata (RFC 9728) — **we** serve this | `https://<host>/.well-known/oauth-protected-resource/mcp` (SDK-generated) |

**Claims to validate:** `iss` == the AuthKit domain, `aud` == the configured Resource Indicator (or the environment client ID), `exp` (implicit in `jwt.decode`). `[CITED: workos.com/docs/authkit/mcp]`

**Network requirement:** *"that host must also be reachable from Anthropic's published egress range. Discovery requests to the authorization server come from the same IP range as requests to your MCP server, so a WAF in front of your identity provider can break the flow even when your MCP server is reachable."* `[CITED]` WorkOS is a public SaaS host, so this is satisfied by default — noted only so it isn't a mystery if it ever fails.

**Reference implementation** to consult if the Python wiring resists: `https://github.com/mcp-use/mcp-oauth-workos-template` (TypeScript). `[CITED: WebSearch]` — useful for confirming the dashboard flow, not the code.

---

## Render Deployment

### `render.yaml` (repo root)

```yaml
services:
  - type: web
    name: brett
    runtime: python
    region: oregon
    plan: free                 # D-07: bump to `starter` before connector testing
    autoDeployTrigger: commit
    healthCheckPath: /health
    # preDeployCommand: cd backend && uv run python -m alembic upgrade head
    #   ^ PAID PLANS ONLY. Uncomment at the same commit as `plan: starter`.
    buildCommand: uv sync --frozen
    startCommand: uv run uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: brett-db
          property: connectionString
      - key: ENVIRONMENT
        value: production
      - key: LOG_LEVEL
        value: INFO
      - key: UV_VERSION
        value: "0.12.5"
      - key: MCP_ALLOWED_HOSTS
        value: brett.onrender.com          # must match the real hostname
      - key: MCP_RESOURCE_URL
        value: https://brett.onrender.com/mcp
      - key: MCP_ISSUER_URL
        sync: false                        # WorkOS AuthKit domain, set in dashboard
      - key: MCP_AUTH_SECRET
        generateValue: true                # or sync:false and paste a token_urlsafe(48)

databases:
  - name: brett-db
    plan: free                 # D-07: bump to `basic-256mb` before connector testing
    databaseName: brett
```

`[CITED: render.com/docs/blueprint-spec]` — field names and valid values verified: `plan` accepts `free|starter|standard|pro|pro plus|pro max|pro ultra`; database `plan` accepts `free|basic-256mb|basic-1gb|basic-4gb|pro-*`; `autoDeployTrigger` accepts `commit|checksPass|off`; `region` accepts `oregon|ohio|virginia|frankfurt|singapore`; `fromDatabase.property` accepts `connectionString|connectionPoolString|user|password|database|host|port`.

**`preDeployCommand` semantics** `[CITED: render.com/docs/deploys]`: runs after build, before the build is deployed, **on a separate instance** from the running service — fine for migrations (they touch the DB, not the filesystem), and it is why filesystem side effects there are pointless.

### Python and uv pinning

| Concern | Setting | Source |
|---|---|---|
| Default Python on Render | **3.14.3** for services created on/after 2026-02-11 | `[CITED: render.com/docs/python-version]` |
| Precedence | `PYTHON_VERSION` env var (fully qualified, e.g. `3.13.5`) → `.python-version` file (patch optional) → default | `[CITED]` |
| This repo | `.python-version` contains `3.13` and `pyproject.toml` declares `requires-python = ">=3.13,<3.14"` — Render will honour the file. **No `PYTHON_VERSION` env var needed.** The `<3.14` ceiling also means an accidental 3.14 build fails loudly at `uv sync` rather than silently | `[VERIFIED: repo files]` |
| uv activation | `uv.lock` must be present **in the service's root directory** | `[CITED]` — it is, at the repo root; leave `rootDir` unset |
| uv version | `UV_VERSION` env var | `[CITED]`; latest is **0.12.5** `[VERIFIED: PyPI, 2026-08-24]` (local machine has 0.12.1 — pin explicitly so build and dev agree) |

### Free → Starter upgrade checklist (D-07 trigger)

Per D-07 this happens after the D-01 CLI proof and **before** any connector attempt:

1. `plan: free` → `plan: starter` (web) and `plan: free` → `plan: basic-256mb` (database)
2. Uncomment `preDeployCommand` — now that it is available, migrations move server-side and match the Phase 1 `lifespan` docstring's stated intent
3. Confirm the service no longer spins down (no 15-minute idle stop)
4. Re-run Auth Verification Matrix rows 1-7 against the upgraded service before adding the connector

Free Postgres is capped at 1 GB, has no backups and no managed connection pooling, and **expires 30 days after creation** with a 14-day grace period `[CITED: render.com/docs/free]` — so the upgrade also protects the data, not just latency.

---

## Code Examples

### Config additions

```python
# backend/app/config.py -- additions only
_SECRET_FIELDS = ("database_url", "hevy_api_key", "mcp_auth_secret")
# ^ mcp_auth_secret is ALREADY listed. If a WorkOS client secret is ever added,
#   it must be appended here too, or the log scrubber will not redact it.


class Settings(BaseSettings):
    ...
    mcp_auth_secret: SecretStr | None = None          # exists since Phase 1
    mcp_issuer_url: str = "https://example.authkit.app"
    mcp_resource_url: str = "http://localhost:8000/mcp"
    mcp_allowed_hosts_raw: str = "localhost,127.0.0.1"

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        """Comma-separated so a Render custom domain can be added without a code change."""
        return [h.strip() for h in self.mcp_allowed_hosts_raw.split(",") if h.strip()]
```

`Settings.model_config` sets `extra="ignore"`, so new env vars are additive and cannot break existing tests. `[VERIFIED: config.py]`

### In-memory MCP test (no HTTP, no auth)

```python
# Source: verified against mcp 2.0.0 -- Client accepts an MCPServer directly
from mcp import Client

async def test_ping_tool_returns_structured_output(...):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert [t.name for t in tools.tools] == ["fitness_ping"]

        result = await client.call_tool("fitness_ping", {})
        assert result.is_error is False
        assert result.structured_content == {"status": "ok", "database": "connected"}
```

`Client.__init__` signature `[VERIFIED]`: `Client(server: Server | MCPServer | Transport | str, *, raise_exceptions=False, read_timeout_seconds=None, ...)`. It accepts a URL string too, so the same helper can drive an over-HTTP test.

**Caveat:** in-memory connections bypass `RequireAuthMiddleware` entirely — this test proves the tool and the lifespan wiring, never the auth. Auth must be tested over HTTP.

### HTTP auth test (TestClient)

```python
MCP_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {}}
MCP_HDRS = {"Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list", "Mcp-Name": "tools/list"}
BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
        "params": {"_meta": MCP_META}}


@pytest.mark.integration
def test_mcp_rejects_unauthenticated(client: TestClient) -> None:
    r = client.post("/mcp", json=BODY, headers=MCP_HDRS)
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]


@pytest.mark.integration
def test_mcp_accepts_valid_bearer(client: TestClient) -> None:
    r = client.post("/mcp", json=BODY,
                    headers={**MCP_HDRS, "Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 200
    assert r.json()["result"]["tools"][0]["name"] == "fitness_ping"
```

Note the existing `client` fixture sets `base_url` to `http://testserver`, so `TransportSecuritySettings.allowed_hosts` must include `"testserver"` under test — drive it from `MCP_ALLOWED_HOSTS` in the test environment rather than hardcoding.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` | `mcp` 2.0.0, 2026-07-28 | Every pre-2026 example and most LLM completions are wrong |
| Session handshake, `Mcp-Session-Id` | Stateless per-request envelope | spec `2026-07-28` | No `Mcp-Session-Id` response header at all — `[VERIFIED]` with both `stateless_http=True` and `False` |
| `params` carries only tool arguments | `params._meta` must carry `io.modelcontextprotocol/protocolVersion` + `clientCapabilities` | spec `2026-07-28` | Naive curl gets `-32602` (Pitfall 5) |
| Dual `/sse` + `/messages` HTTP+SSE transport | Single `POST /mcp` Streamable HTTP | deprecated since `2025-03-26` | `sse_app()` still exists in the SDK — do not use it |
| DCR as the default MCP registration path | CIMD preferred by both Anthropic and WorkOS | 2026 | DCR still works; it is now the fallback, and off by default in AuthKit |
| `httpx` | `httpx2` | — | `mcp` requires `httpx2>=2.5.0`; `respx`/`pytest-httpx` cannot intercept it |

**Deprecated/outdated in CLAUDE.md — corrections:**

- **`StaticTokenVerifier`** — CLAUDE.md §"Stack Patterns by Variant" says *"Keep `StaticTokenVerifier` + `AuthSettings`"*. **No such class exists anywhere in `mcp` 2.0.0** `[VERIFIED: grep across the installed site-packages returned zero matches]`. Write the ~10-line class yourself (Pattern 5).
- **Mount path** — CLAUDE.md's integration-pattern note implies `app.mount("/mcp", ...)`. That breaks OAuth discovery (Pitfall 3). Mount at `/`.
- **"`streamable_http_app()` MUST be called at import time"** — true, but incomplete and it misses the actual failure. The load-bearing requirement is entering `mcp.session_manager.run()` in the parent lifespan (Pitfall 1).
- **`preDeployCommand` for migrations** — correct guidance, but CLAUDE.md doesn't note it is paid-only, which collides with D-07's free-tier start (Pitfall 6).
- **Dependency list** — CLAUDE.md omits `jsonschema`, `python-multipart`, `typing-inspection`, and `anyio` from `mcp`'s transitive set. Harmless, noted for completeness.
- **`mcp` has no `__version__` attribute** `[VERIFIED]` — a runtime version assertion must read package metadata, not `mcp.__version__`.

---

## Runtime State Inventory

Not applicable — this is a greenfield/additive phase (new package, new config keys, new deploy target). No rename, refactor, migration, or string replacement is involved. No existing runtime state is being renamed or relocated.

One adjacent item worth flagging so it is not mistaken for an omission: the Render Postgres created in this phase will hold migrations `0001_initial_schema` and `0002_seed_default_user`. It starts empty and must be migrated (Pitfall 6). That is new-state creation, not state migration.

---

## Environment Availability

Probed on the development machine, 2026-08-24.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | Build, lockfile, `uv run` | ✓ | 0.12.1 (local) / pin 0.12.5 on Render | — |
| Python 3.13 | `requires-python = ">=3.13,<3.14"` | ✓ | via `uv python` (system `python3` is 3.14.0 — **do not use it directly**) | `uv venv --python 3.13` |
| `claude` CLI | D-01 verification | ✓ | 2.1.237 | — |
| `curl` | Auth Verification Matrix | ✓ | 8.7.1 | — |
| `jq` | Parsing MCP JSON responses | ✓ | 1.7.1 | `python3 -m json.tool` |
| `psql` | Inspecting Render Postgres | ✓ | 18.6 | Render dashboard (paid tiers only) |
| `git` / `gh` | Deploy trigger via push | ✓ | 2.39.5 / 2.92.0 | — |
| Docker daemon | `testcontainers[postgres]` integration tests | **✗ (installed, daemon down)** | CLI 29.4.2 | Start Docker Desktop; otherwise run `pytest -m "not integration"` only |
| Render CLI | Optional convenience | ✗ | — | Render dashboard + `render.yaml` blueprint sync (the documented path) |
| Render account + Postgres | DEPLOY-01 | Assumed provisioned per PROJECT.md | — | — |
| WorkOS account | D-04 | **Not yet created** | — | None — blocking for D-03/D-04 |

**Missing dependencies with no fallback:**
- **WorkOS account/project** — must be created before the OAuth stage. Free tier is sufficient for a single-user MCP server. This is a manual, human-in-the-loop step the plan must call out explicitly rather than bury in a task.

**Missing dependencies with fallback:**
- **Docker daemon down** — every existing test marked `@pytest.mark.integration` requires it (`conftest.py` session-scoped `PostgresContainer`). The plan's Wave 0 should either start Docker or scope quick runs to `-m "not integration"`.
- **Render CLI absent** — `render.yaml` blueprint sync from the dashboard is the documented path and needs no CLI.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| Quick run command | `uv run pytest -m "not integration" -q` |
| Full suite command | `uv run pytest -q` (requires the Docker daemon) |
| Real-DB strategy | `testcontainers[postgres]` `postgres:18-alpine`, schema built by `alembic upgrade head` as a subprocess — never `MetaData.create_all` |
| Existing marker | `integration: test requires a live Postgres container` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCP-01 | `/mcp` is routed and the session manager is running | integration | `uv run pytest backend/tests/test_mcp_mount.py::test_mcp_endpoint_is_routed -x` | ❌ Wave 0 |
| MCP-01 | Mounting does not shadow `/health`, `/docs`, `/openapi.json` | unit | `uv run pytest backend/tests/test_mcp_mount.py::test_fastapi_routes_still_win -x` | ❌ Wave 0 |
| MCP-01 | Wrong `Host` → 421 (transport security is active) | integration | `uv run pytest backend/tests/test_mcp_mount.py::test_rejects_disallowed_host -x` | ❌ Wave 0 |
| MCP-04 | No `Authorization` → 401 with `resource_metadata=` in `WWW-Authenticate` | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_rejects_unauthenticated -x` | ❌ Wave 0 |
| MCP-04 | Wrong bearer → 401 | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_rejects_bad_token -x` | ❌ Wave 0 |
| MCP-04 | Correct bearer → 200 + `fitness_ping` in `tools/list` | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_accepts_valid_bearer -x` | ❌ Wave 0 |
| MCP-04 | 401 body leaks no secret (FOUND-05 continuity) | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_401_leaks_nothing -x` | ❌ Wave 0 |
| MCP-04 | RFC 9728 metadata is served at the path Claude probes, and `resource` matches config | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_protected_resource_metadata_path -x` | ❌ Wave 0 |
| DEPLOY-01 | `render.yaml` parses; every referenced env var exists in `Settings` | unit | `uv run pytest backend/tests/test_render_blueprint.py -x` | ❌ Wave 0 |
| DEPLOY-01 | Service live over HTTPS, `/health` → 200 | **manual** | Auth Verification Matrix row 6 against the deployed URL | manual-only — requires a real deploy |
| DEPLOY-02 | Connector discovers and calls `fitness_ping` from Desktop/Web/Mobile | **manual** | Add custom connector in Claude → authenticate → invoke the tool | manual-only — this *is* the phase's central unknown; no automated proxy for it exists |
| D-08 | `fitness_ping` performs a real DB round-trip via the lifespan context | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_ping_hits_database -x` | ❌ Wave 0 |
| D-08 | Unreachable DB degrades to `database: "error"`, never 500, never leaks a DSN | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_ping_degrades_cleanly -x` | ❌ Wave 0 |

**Justification for the two manual-only rows:** MCP-04's acceptance text is explicitly *"verified working end-to-end from an actual Claude client (not just a local test client)"* and DEPLOY-02 requires the Claude connector UI. Neither has an automated substitute — that is precisely why this phase exists as a spike. The automated tests above prove everything *up to* the client boundary, so a manual failure isolates to the client/IdP interaction rather than to our code.

### Sampling Rate

- **Per task commit:** `uv run pytest -m "not integration" -q`
- **Per wave merge:** `uv run pytest -q` (Docker daemon must be up)
- **Phase gate:** Full suite green **plus** all 7 Auth Verification Matrix rows passing against the deployed URL **plus** the two manual connector checks, before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_mcp_mount.py` — covers MCP-01
- [ ] `backend/tests/test_mcp_auth.py` — covers MCP-04
- [ ] `backend/tests/test_mcp_tools.py` — covers D-08
- [ ] `backend/tests/test_render_blueprint.py` — covers DEPLOY-01 (static config assertions)
- [ ] `backend/tests/conftest.py` — extend the existing `client` fixture so `MCP_ALLOWED_HOSTS` includes `testserver` and `MCP_AUTH_SECRET` is set before `app.main` is imported (the fixture already imports `app.main` lazily for exactly this reason)
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers and time-machine are all already in the dev group
- [ ] Ensure the Docker daemon is running (currently down) before any `-m integration` run

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | **yes** | Bearer token over HTTPS. Stage A: `secrets.compare_digest` against `MCP_AUTH_SECRET` (generate with `secrets.token_urlsafe(48)`). Stage B: RS256 JWT validated against WorkOS JWKS with `iss`/`aud`/`exp` all required |
| V3 Session Management | **no** | The 2026-07-28 transport is stateless; there are no server-side sessions to fixate or hijack |
| V4 Access Control | **partial** | Single-user, read-only in v1. `required_scopes=None` this phase; scope enforcement lands with the real tool set in Phase 6. No tool may write (MCP-05) |
| V5 Input Validation | **yes** | Pydantic tool-argument models + the SDK's `jsonschema` validation. The throwaway tool takes no arguments, so the surface is nil this phase |
| V6 Cryptography | **yes** | `pyjwt[crypto]` + `cryptography` for RS256. **Never hand-roll**: no manual base64/RSA, no `python-jose` (unmaintained, historical CVEs) |
| V7 Error Handling & Logging | **yes** | The existing structlog scrubber + `Settings.secret_values()`. **Any new secret must be appended to `_SECRET_FIELDS`.** The verifier must never log the token or decoded claims |
| V9 Communications | **yes** | HTTPS enforced by Render's TLS termination. `bearer_methods_supported: ["header"]` — never a query parameter |
| V13 API & Web Service | **yes** | RFC 9728 metadata, RFC 8414 discovery, PKCE S256 (client-side, Claude always sends it), Resource Indicators (RFC 8707) binding the token's `aud` to this specific server |
| V14 Configuration | **yes** | All secrets via Render env vars (`sync: false` / `generateValue: true`); nothing committed (FOUND-05) |

### Known Threat Patterns for FastAPI + MCP + OAuth resource server

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| DNS rebinding against the MCP endpoint | Spoofing | `TransportSecuritySettings(allowed_hosts=[...])` — on by default, verified 421/403 behaviour |
| Token replay across MCP servers ("confused deputy") | Elevation of Privilege | Resource Indicators (RFC 8707): AuthKit stamps `aud` = this server's URL; the verifier enforces `audience=` |
| Credential leakage via URL | Information Disclosure | Header-only bearer. The MCP authorization spec **prohibits** access tokens in the query string; Claude's docs call it a vulnerability |
| Credential leakage via logs | Information Disclosure | Existing three-layer defense (`SecretStr` → structlog scrubber → sanitized error handler). Extend `_SECRET_FIELDS` for any new secret |
| Timing attack on the static secret | Spoofing | `secrets.compare_digest`, never `==` |
| Unauthenticated bypass via a custom route | Elevation of Privilege | Never use `@mcp.custom_route` — *"custom routes are never authenticated"*. `/health` stays a FastAPI route and deliberately exposes only `{status, database}` |
| JWKS endpoint outage → auth fails open | Tampering | `verify_token` returns `None` (deny) on **any** exception — fail closed. `cache_jwk_set=True` (300 s) keeps a transient outage from becoming an immediate lockout |
| Event-loop starvation via blocking JWKS fetch | Denial of Service | `anyio.to_thread.run_sync` around `PyJWKClient` calls |
| Traceback / DSN disclosure from a failing tool | Information Disclosure | Mirror `health.py`: coarse status to the caller, full detail to the (scrubbed) log |
| Secret committed to the repo | Information Disclosure | Existing `gitleaks`/`detect-secrets` pre-commit hook; `MCP_AUTH_SECRET` via `generateValue: true` so it never touches a developer machine |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | WorkOS AuthKit's JWKS path is `/oauth2/jwks` and the issuer is the bare AuthKit domain with no path suffix | WorkOS AuthKit Setup | Verifier can't fetch keys; every token fails. **Cheap to check** — `curl https://<project>.authkit.app/.well-known/oauth-authorization-server` and read `jwks_uri` rather than hardcoding. Recommend the plan derive `jwks_uri` from discovery instead of assuming |
| A2 | WorkOS AuthKit advertises `"none"` in `token_endpoint_auth_methods_supported` (required for Claude to select CIMD) | Auth Mechanism Decision | Claude silently falls back to DCR. Low impact since the plan enables both toggles, but it changes which one is exercised. Verify from the same discovery document as A1 |
| A3 | Render forwards the original public `Host` header to the service unmodified | Pitfall 2 / `render.yaml` | `allowed_hosts` wouldn't match → 421 on every request. Standard reverse-proxy behaviour and consistent with Render's custom-domain docs, but unverified for this specific service. Diagnosable in one request via Matrix row 7's inverse |
| A4 | A personal (Pro/Max) Claude account can complete the full OAuth connector flow, not merely add the connector | Auth Mechanism Decision | This is the phase's central unknown by design. Docs confirm Free/Pro/Max can *add* custom connectors with optional OAuth credentials; the end-to-end consent flow on a personal plan is not separately documented |
| A5 | Render free Postgres exposes an external connection string usable from the developer machine | Pitfall 6 | If external connections were blocked, there'd be **no** way to migrate on free tier and the plan would have to deploy directly to Starter. Render Postgres has historically always provided an external URL; confirm in the dashboard before committing to the free-tier path |
| A6 | `stateless_http=True` is compatible with Claude's connector implementation | Pattern 5 | If Claude required session affinity the connector would fail. The 2026-07-28 spec removed protocol sessions and neither setting emitted an `Mcp-Session-Id` in testing, so this is low-risk — and it is a one-line flip if wrong |
| A7 | WorkOS free tier permits enabling CIMD/DCR and Resource Indicators without a paid plan | WorkOS AuthKit Setup | Would introduce unbudgeted cost. Not verified — no pricing page consulted |

---

## Open Questions (RESOLVED)

1. **Does the plan create the WorkOS account, or is that a human prerequisite?**
   - What we know: WorkOS setup is entirely dashboard-driven (project creation, two toggles, one Resource Indicator). No API/CLI path was found in the docs.
   - What's unclear: whether the executing agent has or should have WorkOS credentials.
   - Recommendation: treat WorkOS project creation and the three dashboard settings as an **explicit human checkpoint task** in the plan, with the resulting AuthKit domain handed back as `MCP_ISSUER_URL`. Do not model it as an automatable task.
   - **RESOLVED:** Implemented as Plan 02-06 Task 1 — an `autonomous: false` human checkpoint that hands back the AuthKit issuer domain.

2. **Free tier or straight to Starter?**
   - What we know: D-07 locks "start free, upgrade before connector testing." But free has no pre-deploy, no shell, and no one-off jobs, so migrations must run from the laptop (Pitfall 6), and free Postgres expires in 30 days.
   - What's unclear: whether the laptop-migration detour costs more effort than it saves in dollars, given the upgrade is mandatory within the same phase.
   - Recommendation: **follow D-07 as written** — it is a locked decision and the laptop migration is genuinely cheap (one command, already the pattern `conftest.py` uses). Flag the extra step in the plan so it isn't mistaken for a defect. If the planner wants to revisit, that is a discuss-phase question, not a research one.
   - **RESOLVED:** Followed as written across Plans 02-03 (render.yaml), 02-05 (free-tier deploy + laptop migration), and 02-07 (Starter upgrade before connector testing).

3. **Where should the `MCPServer` singleton live to avoid a circular import?**
   - What we know: `mcp_lifespan` needs `app.state.sessionmaker`, and `main.py` needs `mcp` and `mcp_app`. A naive module-level `from app.main import app` in `app/mcp/context.py` is circular.
   - What's unclear: nothing blocking — several clean shapes exist.
   - Recommendation: import `app` *inside* the `mcp_lifespan` function body (as shown in Pattern 3), which defers resolution to startup. Alternative if the planner prefers explicitness: a tiny `app/mcp/state.py` holder object that `main.py`'s lifespan populates and `mcp_lifespan` reads. Both are fine; this is Claude's-discretion territory per CONTEXT.md ("exact `mcp/server.py` internal file layout").
   - **RESOLVED:** Plan 02-02 implements the deferred-import shape in `app/mcp/context.py`.

4. **Should `required_scopes` be set?**
   - What we know: `AuthSettings.required_scopes` defaults to `None` and flows into both the metadata's `scopes_supported` and the middleware check. Claude requests whatever `scopes_supported` advertises unless the 401's `WWW-Authenticate` carries a `scope` parameter.
   - Recommendation: leave `None` for this phase. Scope design belongs with the real tool set (Phase 6). An empty scope list is the least likely thing to break a first connector handshake.
   - **RESOLVED:** Plan 02-02's `server.py` leaves `required_scopes=None`, deferring scope design to Phase 6.

---

## Sources

### Primary (HIGH confidence)

- **Live install + source introspection** — `mcp 2.0.0`, `mcp-types 2.0.0`, `fastapi 0.141.1`, `starlette 1.6.0`, `pyjwt 2.13.0`, `cryptography 50.0.0` into a clean Python 3.13.9 venv, 2026-08-24. Signatures via `inspect.signature`, source reads of `mcp/server/lowlevel/server.py`, `mcp/server/mcpserver/server.py`, `mcp/server/auth/{provider,routes,settings}.py`, `mcp/server/transport_security.py`, `jwt/jwks_client.py`. **Eight executable FastAPI test programs** exercised: mount-at-root, mount-without-lifespan (reproduced `Task group is not initialized`), transport-security 421/403 matrix, auth 401/200 matrix, `Context` schema stripping, `app.state` bridging under both `stateless_http` values, in-memory `mcp.Client`, and `token_verifier`-without-`AuthSettings` (reproduced the `ValueError`). *This is the strongest evidence in this document.*
- `https://py.sdk.modelcontextprotocol.io/v2/run/asgi` — mounting pattern, "define your own routes before the Mount", session-manager lifespan requirement, `TransportSecuritySettings`, `custom_route` authentication warning
- `https://py.sdk.modelcontextprotocol.io/v2/troubleshooting` — the `Task group is not initialized` fix, with a before/after code pair
- `/websites/py_sdk_modelcontextprotocol_io_v2` (Context7 via `ctx7` CLI) — ASGI mounting, multi-server `AsyncExitStack` pattern, CORS guidance
- `https://claude.com/docs/connectors/building/authentication` — auth-type table with current availability, DCR-vs-CIMD selection rule, discovery probe order, required `401` + `WWW-Authenticate` shape, `resource` exact-match rule, `authorization_servers[0]`-only rule, 10 s / 30 s timeouts, callback URLs, `160.79.104.0/21` egress, PKCE S256 requirement
- `https://claude.com/docs/connectors/custom/remote-mcp` — custom-connector add flow per plan tier (**Free/Pro/Max supported**), request-header beta details, header allowlist, 4-header max, "enter the full value including `Bearer `"
- `https://render.com/docs/blueprint-spec` — `render.yaml` field names, valid `plan` values for services and databases, `fromDatabase` properties, `preDeployCommand`, `autoDeployTrigger`, `region`
- `https://render.com/docs/deploys` — pre-deploy command is paid-only; runs after build, before deploy, on a separate instance
- `https://render.com/docs/free` — 15-min idle stop, ~1-min spin-up, 750 instance-hours/month, no shell, no one-off jobs, Postgres expires at 30 days + 14-day grace, 1 GB cap
- `https://render.com/docs/python-version` — 3.14.3 default, `PYTHON_VERSION` → `.python-version` → default precedence, `UV_VERSION`, `uv.lock` must be at the service root
- **PyPI JSON API**, queried 2026-08-24 — `mcp` 2.0.0 (uploaded 2026-07-28), full `requires_dist`, `uv` 0.12.5
- **`uv pip compile`** against the project's exact production pin set + `mcp==2.0.0` — zero-conflict resolution proof
- **`claude mcp add --help`** (Claude Code 2.1.237, local) — exact flags and examples
- **Repo file reads** — `pyproject.toml`, `uv.lock`, `backend/app/{main,config,db/session}.py`, `backend/app/api/routes/health.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`, `backend/migrations/env.py`, `.python-version`, `.env.example`, `docker-compose.yml`

### Secondary (MEDIUM confidence)

- `https://workos.com/docs/authkit/mcp` — CIMD/DCR toggles, DCR off by default, Resource Indicator registration, issuer format, `/oauth2/jwks`, `iss`/`aud`/`exp` validation. **JavaScript examples only; no Python.** Vendor-authored
- **Live probe** of `https://divine-heart-45-staging.authkit.app/.well-known/oauth-authorization-server` — returned a WorkOS-shaped `entity_not_found` naming the AuthKit domain, confirming both the `*.authkit.app` hostname pattern and that the RFC 8414 path is served per-tenant
- `https://workos.com/blog/mcp-resource-indicators`, `https://workos.com/blog/mcp-auth-developer-guide` — Resource Indicator rationale. Vendor-authored; treat as a shortlist, per D-04's own caveat
- `https://render.com/changelog/added-uv-to-the-python-native-runtime`, `https://render.com/docs/uv-version` — uv support timeline

### Tertiary (LOW confidence — flagged for validation)

- `https://github.com/mcp-use/mcp-oauth-workos-template` — community WorkOS + MCP reference. TypeScript; not inspected in depth. Useful only for confirming the dashboard flow
- CLAUDE.md's own §"Deployment (Render)" third-party figures for spin-down and Postgres deletion — **now superseded** by the primary Render docs cited above, which corroborate them

---

## Project Constraints (from CLAUDE.md)

Directives extracted from `./CLAUDE.md` that the plan must comply with:

| Constraint | This phase's compliance |
|---|---|
| Tech stack fixed: Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic, **MCP Python SDK**, pytest, Ruff, mypy where practical | `mcp==2.0.0` is the official SDK. FastMCP explicitly not used |
| Repo layout flat at BRETT root (`backend/`, `ios/`, `docs/`) | New code goes in `backend/app/mcp/`; `render.yaml` at repo root |
| MCP tools read-only in v1 | The single tool executes `SELECT 1` only |
| Never expose API keys, DB credentials, or internal tokens through MCP responses or logs | Tool returns `{status, database}` only; verifier logs nothing; `_SECRET_FIELDS` extended for any new secret |
| HTTPS everywhere; secrets only via environment/secret storage, never committed | Render TLS; `sync: false` / `generateValue: true` in `render.yaml`; existing gitleaks pre-commit hook |
| Deployment: Render for v1, architecture portable | Single web service, native Python runtime, no Render-specific code in the app |
| **GSD Workflow Enforcement** — no direct repo edits outside a GSD command | Research writes only `02-RESEARCH.md`; all code changes belong to `/gsd-execute-phase` |
| Ruff lint set includes `S` (bandit) | `secrets.compare_digest` not `==`; bare `except` needs `# noqa: BLE001` per the existing `health.py` precedent |
| mypy `disallow_untyped_defs = true`, `python_version = "3.13"` | Every new function needs annotations; `Context[AppContext]` is the correct tool-parameter form |

---

## Metadata

**Confidence breakdown:**

- **SDK integration pattern:** HIGH — every claim reproduced in a live FastAPI app against the exact pinned versions, and independently corroborated by the official ASGI/troubleshooting docs
- **Auth mechanics (401 shape, metadata path, verifier contract):** HIGH — empirically verified server-side and cross-checked against Anthropic's connector docs for the client-side contract
- **Standard stack / version compatibility:** HIGH — `uv pip compile` resolution proof plus PyPI metadata queried today
- **Render deployment:** HIGH for documented mechanics (blueprint fields, free-tier limits, Python/uv precedence); MEDIUM for the `Host`-forwarding assumption (A3) and external-DB-URL assumption (A5)
- **WorkOS specifics:** MEDIUM — vendor docs only, JavaScript examples, no tenant to probe. A1/A2/A7 are the soft spots and all three are resolvable with one `curl` against the discovery document once a project exists
- **Whether a personal Claude account completes the connector OAuth flow:** LOW — this is the phase's raison d'être and cannot be resolved by research (A4)

**Research date:** 2026-08-24
**Valid until:** 2026-09-07 (14 days). `mcp` 2.0.0 shipped 2026-07-28 and is a fresh major; Claude connector auth (`static_headers` beta status, CIMD rollout) and WorkOS's MCP surface are all moving. Re-verify `mcp`'s latest version and re-read the connector auth page before Phase 6.

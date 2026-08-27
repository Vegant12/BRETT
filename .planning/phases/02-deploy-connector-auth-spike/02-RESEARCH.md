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

---

## RESEARCH ADDENDUM 2026-08-27: Cloud Run Deployment Pivot

**Researched:** 2026-08-27
**Domain:** Google Cloud Run source deploys (Cloud Buildpacks + uv) + Neon Postgres + Secret Manager
**Confidence:** HIGH for build/deploy mechanics (verified against buildpack source and a live `gcloud` 578.0.0 install); HIGH for the app's Neon compatibility (verified by reading `backend/app/config.py`); MEDIUM for cold-start figures and Neon dashboard specifics (no tenant to probe).

**Status:** *Additive.* Everything above this line about the MCP SDK, the mount pattern, the auth verification matrix, WorkOS/CIMD/DCR, and the throwaway tool is **unchanged and still correct** — none of it has a host dependency. This addendum replaces only the Render-specific material.

| Section above | Status after the pivot |
|---|---|
| `## Standard Stack`, `## Architecture Patterns` (Patterns 1-5), `## Don't Hand-Roll` | **Unchanged** |
| `## Common Pitfalls` 1, 3, 4, 5, 8, 9 | **Unchanged** |
| Pitfall 2 (`421 Invalid Host header`) | **Still applies** — the hostname changes, the mechanism does not (see D-CR-04) |
| Pitfall 6 (free tier cannot run migrations) | **Superseded** by Q7 — same conclusion, different reason |
| Pitfall 7 (`uv.lock` at service root) | **Superseded** by Q1 — same underlying `--app-dir backend` requirement, enforced differently |
| Pitfall 10 (free-tier cold start) | **Superseded** by Q4 |
| `## Render Deployment` (render.yaml, Python/uv pinning, Free→Starter checklist) | **Dead.** Replaced by Q1/Q5/Q6 |
| `## Auth Verification Matrix` | **Unchanged** — all 7 rows are host-agnostic; only `HOST=` changes |
| `## Environment Availability` | **Extended** by section A below |
| `## Validation Architecture` | **One row changes** (DEPLOY-01) — see Q5 |

---

## A. Environment Availability — Cloud Run edition

Probed on the development machine, 2026-08-27. **This materially changes D-06a's premise.**

| Dependency | Required by | Available | Detail |
|---|---|---|---|
| `gcloud` CLI | Every deploy step | ✓ | **Google Cloud SDK 578.0.0**, core `2026.07.24` `[VERIFIED: gcloud version]` |
| `gcloud` authenticated account | All of the above | ✓ | `hovegant12@gmail.com` is the active credentialed account `[VERIFIED: gcloud auth list]` |
| Active `core/project` | `gcloud run deploy` | ⚠️ | Currently `idx-yfinance-mcp-1785725283` — **an unrelated project.** The deploy script must set `--project` explicitly rather than inherit this `[VERIFIED: gcloud config list]` |
| Billing account | Cloud Run + Neon paid tiers | ✓ | Two exist; **`01E8E3-6C54F5-D6B9B6` ("My Billing Account 1") is OPEN**. `01438D-49BD0E-61F138` is closed `[VERIFIED: gcloud billing accounts list]` |
| GCP projects | D-06a | ✓ (7 exist) | `angular-spider-306613`, `gen-lang-client-0735153694`, `gen-lang-client-0921756352`, `gen-lang-client-0928434030`, `habit-tracker-app-441414`, `idx-yfinance-mcp-1785725283`, `propertypulse-490701` `[VERIFIED: gcloud projects list]` |
| Neon account | D-06b | **Unknown — not probed** | Human checkpoint, same shape as the WorkOS checkpoint in 02-06 |
| `psql` | Inspecting Neon | ✓ | 18.6 |
| `uv` | Local dep management | ✓ | 0.12.1 local (0.12.5 is latest) |
| Docker daemon | `-m integration` tests | ✗ (client 29.4.2 installed, daemon down) | Unchanged from the 2026-08-24 probe |
| `pack` CLI | Local buildpack reproduction | ✗ | Optional. `gcloud run deploy --source` needs no local builder |

> **D-06a correction for the planner.** D-06a states *"No GCP project exists yet."* That is true for a *BRETT-specific* project, but the account, the CLI, and an **open billing account already exist**, and seven other projects are already linked. The human checkpoint therefore shrinks from *"create a Google Cloud account and a billing account"* to *"decide the project ID and confirm this billing account may be charged."* Every remaining step is scriptable (Q6). `[VERIFIED]`

---

## Q1. `gcloud run deploy --source` + Cloud Buildpacks + uv/uv.lock

**Answer: yes, buildpacks handle `uv`/`uv.lock` natively — but this repo will fail to build without a `Procfile`.** Both halves are source-verified.

### Q1.1 — uv detection and the exact install command

Read from `GoogleCloudPlatform/buildpacks` at `main` `[VERIFIED: source read, 2026-08-27]`:

`pkg/python/pyproject.go :: IsUVPyproject()` opts the uv buildpack in when **`pyproject.toml` and `uv.lock` both exist at the source root** and `requirements.txt` does **not**:

```go
if isBothPyprojectAndRequirementsPresent(ctx) {
    return false, "... prefer requirements.txt"      // requirements.txt WINS
}
if uvLockExists { return true, "found pyproject.toml and uv.lock" }
```

`pkg/python/pyproject.go :: UVInstallDependenciesAndConfigureEnv()` then runs, verbatim:

```
uv venv <layer>/.venv --clear --python <resolved-version>
uv sync --active --link-mode=copy --python <resolved-version>      # VIRTUAL_ENV=<layer>/.venv
uv pip check                                                        # hard-fails the build on conflicts
```

and prepends `<layer>/.venv/bin` to `PATH` in the layer's **shared** environment (build *and* launch), so `uvicorn` is directly on `PATH` at runtime — **`uv run` is not needed in the entrypoint.** `[VERIFIED: pyproject.go lines 317-360]`

Four consequences the plan must act on:

| # | Finding | Impact | Action |
|---|---|---|---|
| a | **No `--frozen` / `--locked`.** Plain `uv sync` re-locks if `uv.lock` is stale relative to `pyproject.toml`, and `EnsureUVLockfile()` runs `uv lock` outright if the lockfile is missing | Silent loss of build reproducibility — the Render plan's `uv sync --frozen` guarantee is gone | Set build env var `UV_FROZEN=1` (uv's documented env alias for `--frozen` `[VERIFIED: uv sync --help]`) |
| b | **No `--no-dev`.** uv's `default-groups` defaults to `["dev"]`, so the `[dependency-groups] dev` block ships to production | `uv sync --frozen` installs **32 extra packages** on top of the 41 production ones — pytest, coverage, mypy, ruff, pre-commit, testcontainers, docker `[VERIFIED: uv sync --frozen --dry-run` in this repo] — image bloat plus a needless supply-chain surface in a health-data service | Either `[tool.uv] default-groups = []` in `pyproject.toml` (**recommended**, see below) or build env var `UV_NO_DEV=1` |
| c | `uv pip check` gates the build | A resolver conflict fails the deploy with `found incompatible dependencies` | **Already clean:** `uv sync --frozen --no-dev` → 41 packages, `uv pip check` → *"All installed packages are compatible"* `[VERIFIED: run locally 2026-08-27]` |
| d | Python version resolution is `GOOGLE_PYTHON_VERSION` → **`.python-version` file** → per-stack default (`3.13.*` on Ubuntu 22.04, **`3.14.*` on Ubuntu 24.04**) | Same trap as Render's 3.14.3 default | **Already safe:** this repo has `.python-version` = `3.13` and `requires-python = ">=3.13,<3.14"`, so an accidental 3.14 build fails loudly at `uv sync` `[VERIFIED: python.go lines 79-83, 114-145 + repo files]` |

**Verified fix for (b):**

```toml
[tool.uv]
default-groups = []
```

`[VERIFIED: reproduced in a scratch project with uv 0.12.1 — plain `uv sync --frozen` installs nothing extra; `uv sync --frozen --group dev` installs the dev group]`. The cost is that local/CI invocations become `uv sync --group dev` (or `--all-groups`); that is a one-line change in the contributor docs and any CI file, and unlike a build env var it is **checked in and testable**.

**Does a build env var actually reach `uv sync`?** Yes. `pkg/gcpbuildpack/exec.go:210` reads `ecmd.Env = append(append(ecmd.Env, os.Environ()...), params.env...)`, and the `uv sync` call passes `gcp.WithEnv("VIRTUAL_ENV=...")`, so the whole build-container environment is inherited `[VERIFIED: source read]`. Whether gcloud's `--set-build-env-vars` accepts non-`GOOGLE_`-prefixed keys is `[ASSUMED]` (see A-CR-1) — which is why the `pyproject.toml` route is the primary recommendation and `UV_NO_DEV`/`UV_FROZEN` are belt-and-braces.

**Optional: pin the build's uv version.** `RequestedUVVersion()` reads `[tool.uv] required-version` from `pyproject.toml` and passes it straight to `pip install uv<constraint>` `[VERIFIED: pyproject.go lines 227-279]`. This is the exact analog of Render's `UV_VERSION` env var. Caveat: uv *itself* enforces `required-version` locally too, and the dev machine has 0.12.1 — so `">=0.12.1"` works everywhere while `"==0.12.5"` would break local `uv` until it is upgraded.

### Q1.2 — **The blocker: a `Procfile` is mandatory for this repo**

The GCP base builder's Python order groups come in two tiers `[VERIFIED: builders/gcp/base/builder.toml]`:

```toml
# "Python 1/2" — UV order group           # "Python 2/2" — UV order group
google.python.runtime                     google.python.runtime
google.python.uv                          google.python.webserver  (optional)
google.config.entrypoint     <-- REQUIRED google.python.uv
google.utils.label-image                  google.python.missing-entrypoint  <-- REQUIRED
                                          google.utils.label-image
```

CNB picks the **first** order group whose required members all pass detect.

- `google.config.entrypoint.DetectFn` opts in **only** if `GOOGLE_ENTRYPOINT` is set, a `Procfile` exists, or an `app.yaml` entrypoint exists — otherwise it opts out and tier 1 fails `[VERIFIED: cmd/config/entrypoint/lib/lib.go]`.
- Falling through to tier 2, `google.python.missing-entrypoint.BuildFn` runs. For **this repo** — no `main.py` or `app.py` at the source root (the app is `backend/app/main.py`), `pyproject.toml` present, no `[project.scripts]`, and Python 3.13 so the "smart default entrypoint" path (gated on `>= 3.14`) is off — it takes this branch:

```go
} else if !hasMain && !hasApp && !adkPresent {
    return gcp.UserErrorf("for Python with pyproject.toml, provide a main.py or app.py file "+
        "or a script command in pyproject.toml or set an entrypoint with %q env var "+
        "or by creating a %q file", env.Entrypoint, "Procfile")
}
```

`[VERIFIED: cmd/python/missing_entrypoint/lib/lib.go]`

**So `gcloud run deploy --source .` fails today with a clear-but-fatal error.** The fix is a two-line file at the repo root:

```
# Procfile  (repo root, committed)
web: uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
```

Three details that make this correct rather than merely plausible:

1. **`$PORT` expands.** `ctx.AddProcess` wraps every process as `bash -c "<command>"` `[VERIFIED: pkg/gcpbuildpack/gcpbuildpack.go:504-514]`, and Cloud Run injects `PORT` (default `8080`) `[CITED: cloud.google.com/run/docs/container-contract]`.
2. **`--app-dir backend` is still load-bearing.** `uv.lock` records the root project as `source = { virtual = "." }` `[VERIFIED: uv.lock:133]`, so `uv sync` installs *dependencies only* and never puts `backend/` on `sys.path`. This is the identical constraint the existing `test_render_blueprint.py::test_start_command_points_at_the_backend_package` guards — carry that assertion over verbatim.
3. **`--host 0.0.0.0` is required**, not stylistic: *"the ingress container should not listen on `127.0.0.1`"* `[CITED: cloud.google.com/run/docs/container-contract]`.

`Procfile` is also strictly better than `GOOGLE_ENTRYPOINT` here: it is checked in, reviewable, and testable (Q5), and it avoids having to escape `$PORT` through the deploy shell.

### Q1.3 — Fallback if buildpacks misbehave (D-06c's escape hatch)

The fallback is unusually cheap, because `--source` already prefers a Dockerfile:

> *"If a Dockerfile is present in the source code directory, it will be built using that Dockerfile, otherwise it will use Google Cloud buildpacks."* `[VERIFIED: gcloud run deploy --help, --source flag]`

So **the fallback is "add a `Dockerfile`", with the deploy command unchanged.** A minimal one:

```dockerfile
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./backend/
ENV PATH="/app/.venv/bin:$PATH"
CMD exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8080}
```

Explicit two-step (only needed if the plan wants to inspect or reuse the image):

```bash
gcloud builds submit --project="$PROJECT_ID" \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/brett:$(git rev-parse --short HEAD)" .
gcloud run deploy brett --project="$PROJECT_ID" --region="$REGION" \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/brett:$(git rev-parse --short HEAD)" ...
```

**Recommendation: take the buildpack path.** The only real gap it has (entrypoint) is closed by a two-line `Procfile`, and the Dockerfile route would put dependency-install semantics in a file nobody re-reads. Keep the Dockerfile drafted in the plan as a documented fallback, per D-06c, but do not ship it pre-emptively — a `Dockerfile` in the repo **silently overrides** buildpacks, which is a nasty surprise if it is added "just in case" and then drifts.

### Q1.4 — `.gcloudignore` is not optional here

`--source .` uploads the source directory to Cloud Storage. This repo root currently holds:

| Path | Size | Gitignored? |
|---|---|---|
| `export.xml` (Apple Health export) | **182 MB** | yes |
| `records.csv` | **131 MB** | yes |
| `.venv/` | **177 MB** | yes |
| `.git/` | 2.7 MB | n/a |
| **repo total** | **515 MB** | |

`[VERIFIED: du -sh, 2026-08-27]`

Today gcloud saves us by accident: *"If a `.gcloudignore` file is absent and a `.gitignore` file is present ... gcloud will use a generated Git-compatible `.gcloudignore`"* `[VERIFIED: gcloud run deploy --help]`. That safety net **disappears the moment anyone adds a `.gcloudignore` for any other reason** — after which every deploy uploads ~490 MB of personal health data to a Cloud Storage bucket. Commit an explicit one:

```
# .gcloudignore  (repo root)
.git/
.gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.DS_Store
# Personal health-data exports — must never reach a build bucket
export.xml
export_cda.xml
records.csv
workouts.csv
activity_summary.csv
BRETT blueprint.md
.planning/
```

> Note it does **not** exclude `backend/`, `pyproject.toml`, `uv.lock`, `.python-version`, or `Procfile` — all five must reach the builder.

**Confidence: HIGH** for Q1 throughout — every claim is either read out of the buildpack source at `main` or executed locally today.

---

## Q2. Neon Postgres from Cloud Run (D-06b)

### Q2.1 — No special networking. Confirmed.

Neon is reached over the public internet on TCP 5432 with TLS. Cloud Run gives every instance unrestricted **egress** by default; a Serverless VPC Access connector is required only for reaching *private* IPs (VPC-internal resources, Cloud SQL over private IP). **No `--vpc-connector`, no `--network`/`--subnet`, no Cloud SQL Auth Proxy sidecar, no `--add-cloudsql-instances`.** The deploy command is correspondingly shorter than a Cloud SQL one. `[CITED: cloud.google.com/run/docs/configuring/connecting-vpc — VPC access is for private-IP destinations]`, `[VERIFIED: no networking flags are required in `gcloud run deploy --help`'s minimal form]`

This is exactly the property D-06b was chosen for, and it holds.

### Q2.2 — Connection string format

`[CITED: neon.com/docs/connect/connect-from-any-app]` and `[CITED: neon.com/docs/connect/connection-pooling]`:

| Variant | Host | Example |
|---|---|---|
| **Pooled** (default in the console) | `-pooler` suffix | `postgresql://USER:PW@ep-cool-darkness-a1b2c3d4-pooler.us-east-2.aws.neon.tech/brett?sslmode=require&channel_binding=require` |
| **Direct / unpooled** | no suffix | `postgresql://USER:PW@ep-cool-darkness-a1b2c3d4.us-east-2.aws.neon.tech/brett?sslmode=require&channel_binding=require` |

Both carry `?sslmode=require&channel_binding=require`. Neon mandates TLS.

### Q2.3 — **The libpq-parameter trap is already solved in this repo**

`asyncpg.connect()` has no `sslmode` parameter and no `**kwargs`; `channel_binding` is likewise libpq-only. Passing Neon's DSN through unchanged raises at connect time. **`backend/app/config.py::Settings.async_database_url` already translates it:**

```python
sslmode = query.pop("sslmode", None)
if sslmode in _SSL_REQUIRING_MODES and "ssl" not in query:
    query["ssl"] = "require"
query.pop("channel_binding", None)  # libpq-only
```

`[VERIFIED: read backend/app/config.py, 2026-08-27]`

**So Neon's connection string can be pasted into `DATABASE_URL` verbatim, with zero code change.** This is the single strongest argument that D-06b's "minimise rework" rationale was correct — the translation layer was written for Render's libpq-flavoured URL and covers Neon exactly.

Two further pre-existing defences that matter more on Neon than they did on Render:

- `make_engine(...)` sets **`pool_pre_ping=True`** with the comment *"A spun-down or restarted managed Postgres silently kills idle connections"* `[VERIFIED: backend/app/db/session.py]`. Neon's compute suspends after 5 minutes idle on the Free plan and **cannot be disabled there** `[CITED: neon.com/docs/introduction/plans]`, which kills every pooled connection. Pre-ping is what turns that from a 500 into a transparent reconnect.
- `migrations/env.py` uses `NullPool` `[VERIFIED: docstring]` — correct for a short-lived migration process against a serverless compute.

### Q2.4 — Pooled or direct for the app?

| | Pooled (`-pooler`) | Direct |
|---|---|---|
| Backing | PgBouncer, `pool_mode = transaction`, `max_client_conn = 10000`, `default_pool_size = 0.9 × max_connections` `[CITED: neon.com/docs/connect/connection-pooling]` | Postgres directly; `max_connections` = **104** at 0.25 CU `[CITED: same]` |
| asyncpg prepared statements | Supported — Neon runs PgBouncer ≥1.21 with protocol-level prepared statement support `[CITED: neon.com/blog/pgbouncer-the-one-with-prepared-statements]`. SQL-level `PREPARE`/`EXECUTE` is not | Fully supported |
| Session state (`SET`, `LISTEN/NOTIFY`, temp tables, advisory locks) | Not usable | Usable |
| Neon's own guidance for migrations | Do **not** use | **Use this** |

**Recommendation for v1: direct/unpooled for the Cloud Run service, direct/unpooled for Alembic.**

Rationale: a Cloud Run instance is a long-lived process with SQLAlchemy's own `QueuePool` (`pool_size=5, max_overflow=5` → 10 connections max per instance), not a connection-per-request Lambda. Bounding `--max-instances` bounds total connections deterministically — at `--max=4` the worst case is 40 of 104. That keeps PgBouncer's transaction-mode semantics entirely out of the picture for a system that has exactly one user. Revisit only if instance count ever needs to exceed ~8.

**If the planner prefers pooled anyway** (it is a defensible choice), the one-line hedge is a query parameter, which `async_database_url` preserves untouched and SQLAlchemy's asyncpg dialect consumes as a dialect kwarg:

```
...-pooler.<region>.aws.neon.tech/brett?sslmode=require&channel_binding=require&prepared_statement_cache_size=0
```

`[VERIFIED: sqlalchemy/dialects/postgresql/asyncpg.py:1160 — `util.coerce_kw_type(opts, "prepared_statement_cache_size", int)` in `create_connect_args`, documented at lines 78-94]`

### Q2.5 — Neon Free plan facts worth putting in the plan

`[CITED: neon.com/docs/introduction/plans]`

| Limit | Value | Comment |
|---|---|---|
| Storage | 0.5 GB / project | Ample for years of Hevy sets |
| Compute | 100 CU-hours / month | At the 0.25 CU minimum that is 400 wall-clock hours of *active* compute |
| Scale-to-zero | after **5 min** idle, **cannot be disabled on Free** | The wake-up is the first-query latency, ~300-500 ms typical `[MEDIUM: third-party measurements]` |
| Projects | 100 | |
| **Data retention** | *"None of these limits delete your data"* | **Strictly better than Render's free Postgres**, which is deleted 30 days after creation. Old Assumption A5 and old Pitfall 6's data-loss concern are both retired |

**Idle-connection interaction (checked, and it is fine):** Neon's scale-to-zero *"works even if clients are connected"* — suspension is triggered by absence of query activity, not absence of connections, though an `idle-in-transaction` connection is deliberately treated as active `[CITED: neon.com/docs/introduction/scale-to-zero]`. So a Cloud Run instance held warm by `--min=1` with 5 idle pooled connections will **not** burn CU-hours, and `pool_pre_ping` absorbs the connection kill on the next request. Do **not** add a keep-alive `SELECT 1` — it would convert a free database into a 180 CU-hour/month one.

**Confidence: HIGH** for the code-compatibility findings (read from this repo); **MEDIUM** for the Neon plan limits (vendor docs, no tenant probed).

---

## Q3. Google Secret Manager + Cloud Run (D-06d)

### Q3.1 — Exact syntax

`--set-secrets` maps `ENV_VAR=SECRET_NAME:VERSION`, comma-separated. **It removes every existing secret binding first**, so the deploy script must always list the complete set. `[VERIFIED: gcloud run deploy --help — "List of key-value pairs to set as secrets. All existing secrets will be removed first."]`

```bash
# 1. Create the secrets (once). Note `printf`, not `echo` — echo appends \n,
#    which becomes part of the secret value and silently breaks compare_digest.
printf '%s' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  | gcloud secrets create brett-mcp-auth-secret --project="$PROJECT_ID" --data-file=-

printf '%s' "$NEON_DIRECT_URL" \
  | gcloud secrets create brett-database-url --project="$PROJECT_ID" --data-file=-

# 2. Rotate later (never `create` twice — it errors)
printf '%s' "$NEW_VALUE" | gcloud secrets versions add brett-database-url --data-file=-

# 3. Bind at deploy time
gcloud run deploy brett ... \
  --set-secrets="MCP_AUTH_SECRET=brett-mcp-auth-secret:latest,DATABASE_URL=brett-database-url:latest"
```

`[VERIFIED: gcloud secrets create --help, gcloud secrets versions add --help, both from SDK 578.0.0]`

Cross-project form, if it is ever needed: `ENV_VAR=projects/PROJECT_NUMBER/secrets/NAME:VERSION` `[CITED: cloud.google.com/run/docs/configuring/services/secrets]`. Not needed here.

### Q3.2 — IAM: yes, an explicit grant is required

The Cloud Run **runtime** service account needs `roles/secretmanager.secretAccessor`. By default that account is the Compute Engine default SA (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`), which is *not* granted the role automatically. `[CITED: cloud.google.com/run/docs/configuring/services/secrets]`

Given CLAUDE.md's *"never expose API keys, DB credentials, or internal tokens"* constraint, **create a dedicated runtime service account** rather than reusing the broad Compute Engine default (which typically also carries `roles/editor`):

```bash
gcloud iam service-accounts create brett-run \
  --project="$PROJECT_ID" --display-name="BRETT Cloud Run runtime"

RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant per-secret, not project-wide — least privilege.
for S in brett-mcp-auth-secret brett-database-url; do
  gcloud secrets add-iam-policy-binding "$S" --project="$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done

# The deploying human needs this to attach the SA to the service.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --project="$PROJECT_ID" \
  --member="user:$(gcloud config get-value account)" \
  --role="roles/iam.serviceAccountUser"
```

then `gcloud run deploy ... --service-account="$RUNTIME_SA"`.

### Q3.3 — Which values are actually secrets

D-06d names *"`MCP_AUTH_SECRET`, the Neon connection string, WorkOS issuer/JWKS values"*. Flagging a tension for the planner rather than re-deciding it:

| Value | Genuinely secret? | Note |
|---|---|---|
| `MCP_AUTH_SECRET` | **yes** | In `_SECRET_FIELDS`; feeds the log scrubber |
| `DATABASE_URL` | **yes** | In `_SECRET_FIELDS`; contains the Neon password |
| `MCP_ISSUER_URL`, `MCP_JWKS_URI` | **no** | `config.py` documents these as *"public hostnames and URLs that appear in the RFC 9728 metadata document Claude fetches anonymously"* and explicitly keeps them **out** of `_SECRET_FIELDS`, because adding a public hostname to the value scrubber would redact it from every log line `[VERIFIED: backend/app/config.py]` |
| WorkOS client secret | **n/a** | The Stage-B design is a pure resource server validating JWTs against JWKS. No client secret exists (Pattern 5 above) |

Secret Manager works perfectly well for non-secret values, so honouring D-06d literally costs nothing but friction. The mechanical constraint that *does* matter: **a key may not appear in both `--set-secrets` and the env-var source** — Cloud Run rejects a deploy where one name is bound twice. Whichever way the planner goes, the deploy artifacts must partition the key set cleanly, and the Q5 test should assert that partition.

**Confidence: HIGH** (gcloud help read locally; IAM role name confirmed against Google's docs).

---

## Q4. Cold start (D-06f)

### Q4.1 — Is Cloud Run at `min=0` materially better than Render free?

**Yes, by roughly an order of magnitude — but not enough to skip D-06f.**

| | Render free | Cloud Run `min=0` |
|---|---|---|
| Idle-to-stop | 15 min `[CITED: render.com/docs/free]` | Instance may be reclaimed at any point after the last request |
| Restart cost | **~60 s** (`"about one minute"`) `[CITED: render.com/docs/free]` | image pull (streamed, usually near-zero when node-cached) + container start + app import |
| Measured app-side contribution | — | **~2.5 s** cold-filesystem `import app.main`; **~0.45 s** warm `[VERIFIED: `/usr/bin/time` and `-X importtime` on the production-only venv, 2026-08-27]` |
| Realistic total | ~60 s | **~3-5 s** `[MEDIUM: app import measured; sandbox/image-pull figures are third-party, 0.5-2 s typical for Python]` |
| Claude's discovery budget | **10 s** (30 s for refresh) `[CITED: claude.com/docs/connectors/building/authentication]` | same |

Import breakdown, for anyone tempted to optimise: of the ~515 ms warm import, `app.mcp.server` accounts for ~250 ms (almost all of it `import mcp`) and `fastapi` ~105 ms `[VERIFIED: -X importtime]`. There is nothing worth lazy-loading here — the MCP server object *must* exist at import time (Pattern 5), and 0.5 s warm is not the problem.

So Cloud Run at `min=0` would probably squeak under Claude's 10 s budget where Render free provably could not. **That is not a reason to skip the upgrade.** The 10 s ceiling applies to discovery, registration *and* token endpoints, a cold start lands squarely in the 3-5 s range with real variance above it, and a marginal pass presents as the same undiagnosable *"Couldn't reach the MCP server"*. D-06f's trigger point — flip before the first real connector round-trip — is correct and should be followed as written.

### Q4.2 — Does `min-instances=1` actually eliminate it?

Close, with an honest caveat Google states directly:

> minimum instances are *"a best-effort target to keep instances warm and ready"*; residual risks are infrastructure rebalancing, application crashes, and capacity exhaustion. `[CITED: cloud.google.com/run/docs/configuring/min-instances]`

For a one-user personal service that is a non-issue: the warm instance keeps the Python process, every import, and the SQLAlchemy pool alive, so the connector round-trip pays neither the 2.5 s import nor a TCP/TLS handshake to Neon. What it does *not* remove is Neon's own 5-minute autosuspend wake (~0.3-0.5 s) on the first query after idle — irrelevant to the 10 s discovery probe, which never touches the database, and comfortably inside a tool-call timeout.

### Q4.3 — The exact flag: use `--min`, not `--min-instances`

This distinction is new-ish and matters for D-06f's "Claude's discretion on upgrade mechanics":

| Flag | Scope | Behaviour |
|---|---|---|
| `--min=MIN` | **Service** | *"divided among all Revisions receiving a percentage of traffic and **can be modified without deploying a new Revision**"* |
| `--min-instances=MIN` | **Revision** | *"immutably set on each new Revision and modifying its value will deploy another Revision. Consider using `--min` ..."* |

`[VERIFIED: gcloud run deploy --help, SDK 578.0.0 — gcloud's own help text steers you to `--min`]`

Therefore:

```bash
# Deploy-time default (D-06f start state)
gcloud run deploy brett --project="$PROJECT_ID" --region="$REGION" --source=. --min=0 ...

# The D-06f upgrade — no rebuild, no new revision, takes effect in seconds
gcloud run services update brett --project="$PROJECT_ID" --region="$REGION" --min=1

# Revert after the connector test if cost matters
gcloud run services update brett --project="$PROJECT_ID" --region="$REGION" --min=0
```

Because `--min` is revision-independent, the cleanest shape for the deploy script is to read it from an env var (`BRETT_MIN_INSTANCES`, default `0`) *and* to have plan 02-07's equivalent flip it with `services update` — the two are consistent, and the flip is instant and reversible. That fully satisfies the discretion item in CONTEXT.md.

**Also set `--cpu-boost`** (*"allocate extra CPU to containers on startup to reduce the perceived latency of a cold start"*, already default-on for new services `[VERIFIED: gcloud run deploy --help]`) and **cap `--max`** — see Q2.4.

**Startup probe — do not point it at `/health`.** Cloud Run's default startup probe is TCP on the container port, and the deploy waits for it (`--deploy-health-check` on by default). `/health` performs a live `SELECT 1`, so an HTTP startup probe against it would make every deploy's success depend on Neon being awake, which is a slow and needless coupling. Keep the default TCP probe. The Render `healthCheckPath: /health` assertion in `test_render_blueprint.py` has **no Cloud Run analog** and should be dropped rather than translated.

**Confidence: HIGH** on the flag semantics (read from the installed CLI) and on Claude's 10 s budget (Anthropic docs); **MEDIUM** on the absolute cold-start figure (app import measured locally; platform overhead is third-party).

---

## Q5. Reproducibility artifact + its test (D-06e)

### Q5.1 — Shape: script + a **YAML** config file, not a monolithic script

A shell script alone cannot be drift-tested the way `render.yaml` could, because `test_render_blueprint.py`'s real power came from `yaml.safe_load` + comparison against `Settings.model_fields`. Recover that by moving the env vars into a file `gcloud` already understands:

> `--env-vars-file=FILE_PATH`: *"Path to a local YAML file with definitions for all environment variables. All existing environment variables will be removed before the new environment variables are added."* — example content `KEY_1: "value1"` `[VERIFIED: gcloud run deploy --help]`

`--env-vars-file` and `--set-secrets` sit in **separate** mutually-exclusive groups, so they compose `[VERIFIED: gcloud run deploy --help synopsis]`. That gives a near-exact structural analog of `render.yaml`'s `envVars` block, and the existing test's assertions port over almost verbatim.

**Files:**

```
Procfile                          # NEW  (Q1.2 — mandatory)
.gcloudignore                     # NEW  (Q1.4)
deploy/cloud-run.env.yaml         # NEW  — the render.yaml `envVars` analog
scripts/deploy-cloud-run.sh       # NEW  — the D-06e artifact
backend/tests/test_cloud_run_deploy.py   # NEW  — the test_render_blueprint.py analog
render.yaml                       # DELETE (D-06e / "Plans Requiring Rework")
backend/tests/test_render_blueprint.py   # DELETE
```

### Q5.2 — `deploy/cloud-run.env.yaml`

```yaml
# Non-secret runtime configuration for the Cloud Run service. Secrets are bound
# separately via --set-secrets and must NOT appear here: a key present in both
# the env-vars file and --set-secrets is rejected by Cloud Run.
ENVIRONMENT: "production"
LOG_LEVEL: "INFO"
# Host allowlist for the MCP transport's DNS-rebinding guard. Cloud Run forwards
# the ORIGINAL public Host header to the container, so this must match the real
# hostname or every request returns 421 Invalid Host header with no MCP-level
# error body (RESEARCH Pitfall 2). Cloud Run assigns BOTH a deterministic and a
# legacy hash URL; list both if `gcloud run services describe` shows two.
MCP_ALLOWED_HOSTS: "brett-PROJECT_NUMBER.REGION.run.app"
# Must match, character for character, the URL typed into Claude's connector
# dialog and the Resource Indicator registered in WorkOS. No trailing slash.
MCP_RESOURCE_URL: "https://brett-PROJECT_NUMBER.REGION.run.app/mcp"
MCP_AUTH_MODE: "static"          # flipped to "authkit" by the 02-07 equivalent
MCP_ISSUER_URL: "https://PROJECT.authkit.app"
MCP_JWKS_URI: ""
```

> **The hostname is knowable before the first deploy.** Cloud Run's deterministic URL — `https://[TAG---]SERVICE_NAME-PROJECT_NUMBER.REGION.run.app` — is **GA** `[CITED: cloud.google.com/run/docs/triggering/https-request]`. `brett-<12-digit-project-number>` is ~18 characters, far inside the 63-character DNS-segment limit. This **removes the "hostname reconciliation → redeploy" round trip** the Render plan needed: once `gcloud projects describe --format='value(projectNumber)'` returns the number, `MCP_ALLOWED_HOSTS` and `MCP_RESOURCE_URL` can be filled in *before* the first deploy. Caveat: Cloud Run assigns a legacy random-hash URL **as well**, and both are served — verify with `gcloud run services describe brett --format='value(status.url)'` and add the second host to the allowlist if it appears.

### Q5.3 — `scripts/deploy-cloud-run.sh`

```bash
#!/usr/bin/env bash
# The single reproducible description of how BRETT deploys (D-06e). Replaces
# render.yaml. Every flag here is load-bearing; see backend/tests/test_cloud_run_deploy.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"   # never inherit `gcloud config`
REGION="${BRETT_GCP_REGION:-us-central1}"
SERVICE="${BRETT_SERVICE:-brett}"
MIN_INSTANCES="${BRETT_MIN_INSTANCES:-0}"   # D-06f: 1 before any connector test
MAX_INSTANCES="${BRETT_MAX_INSTANCES:-2}"   # bounds Neon connections: 10 per instance
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

exec gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source="$REPO_ROOT" \
  --service-account="$RUNTIME_SA" \
  --allow-unauthenticated \
  --port=8080 \
  --min="$MIN_INSTANCES" \
  --max="$MAX_INSTANCES" \
  --cpu-boost \
  --memory=512Mi \
  --timeout=300 \
  --env-vars-file="$REPO_ROOT/deploy/cloud-run.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
  --set-build-env-vars="UV_FROZEN=1,UV_NO_DEV=1" \
  --quiet
```

Notes on two flags that look optional and are not:

- **`--allow-unauthenticated` is required.** Claude's connectors cannot mint a Google ID token, so Cloud Run's IAM invoker check must be off; MCP-level auth (the `TokenVerifier` + `AuthSettings`, Pattern 5) is the real gate. This is a deliberate, testable choice, not an oversight — the Auth Verification Matrix rows 1-3 are exactly what proves the service is not actually open.
- **`--project` from an env var, never from `gcloud config`.** The active project on this machine is an unrelated one (section A); a script that inherits it would deploy BRETT into `idx-yfinance-mcp-1785725283`.

### Q5.4 — `backend/tests/test_cloud_run_deploy.py`: what it should assert

Direct translations from `test_render_blueprint.py` (reuse its `_settings_env_names()` helper wholesale — the `validation_alias` handling for `MCP_ALLOWED_HOSTS` is still needed):

| # | Assertion | Ported from |
|---|---|---|
| 1 | `deploy/cloud-run.env.yaml` parses to a flat `dict[str, str]` | `test_blueprint_parses` |
| 2 | Every key maps to a real `Settings` field (minus platform vars `PORT`) — `extra="ignore"` still means a typo'd key is silently dropped | `test_every_env_var_maps_to_a_settings_field` |
| 3 | `ENVIRONMENT` is one of `Settings.environment`'s `Literal` values | `test_environment_value_is_a_valid_literal` |
| 4 | **No** key matching `SECRET\|KEY\|TOKEN\|PASSWORD\|DATABASE_URL` appears in the env file at all — on Cloud Run there is no `sync: false`/`generateValue` escape hatch, so the rule sharpens from *"no literal value"* to *"not present"* | `test_no_secret_is_committed_as_a_literal` |
| 5 | `MCP_RESOURCE_URL` is https, ends in `/mcp`, has no query string, and its host is in `MCP_ALLOWED_HOSTS` | `test_resource_url_and_allowed_hosts_agree` (unchanged) |

New assertions, over `scripts/deploy-cloud-run.sh` read as text:

| # | Assertion | Catches |
|---|---|---|
| 6 | Contains `--source`, `--region`, `--project`, `--service-account`, `--allow-unauthenticated`, `--env-vars-file`, `--set-secrets` | A flag silently dropped during an edit |
| 7 | Every `--set-secrets` right-hand side matches `^[a-z0-9-]+:(latest\|[0-9]+)$` — i.e. a Secret Manager reference, never a literal | A credential pasted into the script and committed (the Cloud Run analog of T-02-10) |
| 8 | The union of env-file keys and `--set-secrets` keys is **disjoint**, and together covers every `Settings` field that has no usable default in production | The "bound twice → deploy rejected" failure, and the reverse (a required var forgotten entirely) |
| 9 | Does **not** contain `--set-env-vars` (which would silently wipe `--env-vars-file`) or `--add-cloudsql-instances`/`--vpc-connector` (D-06b says neither is needed) | Drift back toward a Cloud SQL shape |
| 10 | `Procfile` exists at the repo root, its `web:` line contains `--app-dir backend`, `--host 0.0.0.0`, and `$PORT` | `test_start_command_points_at_the_backend_package` — the `ModuleNotFoundError: No module named 'app'` failure, which is remote and silent |
| 11 | `.gcloudignore` exists and lists `export.xml`, `records.csv`, `.venv/` | 490 MB of personal health data uploaded to a build bucket |
| 12 | `render.yaml` does **not** exist | Resurrection of the abandoned target |

All twelve are static file reads — no container, no network, **no `integration` marker**, so the drift fails the fast suite on the commit that introduces it. That is the same design rationale the docstring of `test_render_blueprint.py` already states, and it should be carried into the new file's docstring.

**Confidence: HIGH** — every flag referenced was read from `gcloud run deploy --help` on SDK 578.0.0, and every ported assertion exists today in `backend/tests/test_render_blueprint.py`.

---

## Q6. GCP project + billing checkpoint (D-06a)

### Q6.1 — What genuinely needs a human

Given section A (CLI installed, account authenticated, **an open billing account already linked to seven projects**), the irreducibly-human decisions are:

1. **Choose the project ID** and confirm creating an 8th project is acceptable (personal accounts have a project-creation quota).
2. **Authorise charging `01E8E3-6C54F5-D6B9B6`.** Spending money is a human decision, not an agent's — this is the real content of the `checkpoint:human-action` gate, and it is the same shape as plan 02-05 Task 1's original "create the Render Blueprint" gate.
3. **Create the Neon project** and hand back the direct connection string (dashboard-only, exactly like the WorkOS checkpoint in 02-06).

Everything else below is scriptable and should be a normal task, not a checkpoint.

### Q6.2 — The exact bootstrap sequence

```bash
PROJECT_ID="brett-fitness"          # must be globally unique
REGION="us-central1"
BILLING_ACCOUNT="01E8E3-6C54F5-D6B9B6"

gcloud projects create "$PROJECT_ID" --name="BRETT"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  --project="$PROJECT_ID"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

# --- the trap: build permissions in a NEW project ---
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder"

# Deterministic URL is now knowable, BEFORE the first deploy:
echo "https://brett-${PROJECT_NUMBER}.${REGION}.run.app/mcp"
```

`[VERIFIED: every command's syntax read from `gcloud <cmd> --help` on SDK 578.0.0]`

### Q6.3 — Three traps in a brand-new project

| Trap | Why | Fix |
|---|---|---|
| **The Compute Engine default service account may not exist.** `gcloud run deploy --source` builds with it by default; Google's own troubleshooting page names *"The default Compute Engine service account doesn't exist in the project"* as a common cause of first-deploy failure | The `PROJECT_NUMBER-compute@developer.gserviceaccount.com` identity is materialised when `compute.googleapis.com` is enabled — a Run-only project never has it | Enable `compute.googleapis.com` (above), **or** pass `--build-service-account` `[CITED: cloud.google.com/run/docs/troubleshooting]` |
| **Insufficient build permissions.** *"Starting in July 2024, Cloud Build changed the default behavior for how Cloud Build uses service accounts in new projects"* — the Compute Engine default SA does not inherit the legacy Cloud Build role | Manifests as an opaque build failure, often *"could not write logs"* | Grant `roles/run.builder` (above); `roles/cloudbuild.builds.builder` is the broader alternative `[CITED: cloud.google.com/build/docs/securing-builds/configure-access-for-cloud-build-service-account]` |
| **Artifact Registry repo is created implicitly.** First `--source` deploy auto-creates a repo named `cloud-run-source-deploy` in the target region | Harmless, but it is a resource nobody declared and it accrues storage cost | Note it in the plan so it is not mistaken for stray state; it is also where the fallback `gcloud builds submit --tag` path should push |

Deployer-side roles, for completeness: `roles/run.sourceDeveloper`, `roles/serviceusage.serviceUsageConsumer`, and `roles/iam.serviceAccountUser` on the runtime SA `[CITED: cloud.google.com/run/docs/deploying-source-code]`. As project **Owner** (the creator), the human satisfies all three implicitly — worth stating so the plan does not add ceremony that is already covered.

### Q6.4 — Region

CONTEXT.md leaves this to Claude's discretion. Recommend **`us-central1`**: it is Cloud Run's most feature-complete region, it is the cheapest tier, and — the only consideration that actually affects latency here — it should be chosen to sit **in the same cloud region family as the Neon project** (Neon offers `aws-us-east-2`, `aws-us-west-2`, `azure-eastus2`, `aws-eu-central-1`, `aws-ap-southeast-1`, and others). Cross-continent Cloud Run↔Neon adds ~100-200 ms to *every* query. Since the user is in Asia/Jakarta but Claude's connector traffic originates from Anthropic's US egress range (`160.79.104.0/21`), **US co-location beats Asia co-location** for this workload. Pick a Neon region in the same US area (e.g. Neon `aws-us-east-2` with Cloud Run `us-east4`, or accept the ~30 ms `us-central1`↔`us-east-2` hop). Whatever is chosen must be used consistently for Cloud Run, Secret Manager replication, and Artifact Registry.

**Confidence: HIGH** for command syntax (local CLI); **HIGH** for the new-project traps (Google troubleshooting docs, corroborated by the July-2024 Cloud Build change).

---

## Q7. Migrations from a Cloud Run context

### Q7.1 — Confirmed: Cloud Run has no pre-deploy hook

`gcloud run deploy`'s full flag list contains no pre-deploy, release-phase, or migration hook of any kind `[VERIFIED: gcloud run deploy --help synopsis, SDK 578.0.0]`. Cloud Run's model is "build image → create revision → shift traffic"; anything that must run *between* build and traffic-shift has to be an external step. CONTEXT.md's note is correct.

Running migrations at app startup remains forbidden for the reason `backend/app/main.py`'s lifespan docstring already gives: concurrent revisions race. On Cloud Run this is strictly worse than on Render, because a deploy briefly runs old and new revisions simultaneously by design.

### Q7.2 — Recommended: run Alembic from the developer machine (unchanged pattern)

```bash
DATABASE_URL="postgresql://USER:PW@ep-xxxx.REGION.aws.neon.tech/brett?sslmode=require&channel_binding=require" \
  uv run --directory backend python -m alembic upgrade head
```

Everything needed for this already exists and is verified:

- `Settings.async_database_url` strips `sslmode`/`channel_binding` for asyncpg (Q2.3) `[VERIFIED]`
- `migrations/env.py` injects the URL at runtime (`alembic.ini` deliberately carries no `sqlalchemy.url`, per FOUND-05) and uses `NullPool` `[VERIFIED]`
- `backend/tests/conftest.py` already invokes Alembic exactly this way — `[sys.executable, "-m", "alembic", "upgrade", "head"]`, `cwd=backend`, `DATABASE_URL` injected via env `[VERIFIED: conftest.py:127-134]`

Use the **direct/unpooled** Neon endpoint, per Neon's explicit guidance that migrations belong on the unpooled connection `[CITED: neon.com/docs/connect/connection-pooling]`.

**Ordering:** migrate **before** the first `gcloud run deploy`, not after. Otherwise the first revision's `/health` reports `{"status":"degraded","database":"error"}` and the first `fitness_ping` returns `database: "error"` — a confusing signal in the exact step where the plan is trying to prove the MCP path works. (Both degrade cleanly rather than 500, per the existing `health.py` pattern and D-08 — but a green first deploy is worth more here than a graceful failure.)

### Q7.3 — The GCP-native alternative, if the planner wants server-side migrations

`gcloud run jobs` is the closest analog to Render's paid `preDeployCommand`, and it accepts `--source`, `--set-secrets`, and `--execute-now --wait` `[VERIFIED: gcloud run jobs deploy --help]`:

```bash
gcloud run jobs deploy brett-migrate \
  --project="$PROJECT_ID" --region="$REGION" --source=. \
  --service-account="$RUNTIME_SA" \
  --command="bash" --args="-c","cd backend && python -m alembic upgrade head" \
  --set-secrets="DATABASE_URL=brett-database-url:latest" \
  --max-retries=0 --task-timeout=10m \
  --execute-now --wait
```

**Recommendation: do not do this in Phase 2.** It doubles the build surface (a second source build of the same repo) to solve a problem the laptop already solves in one command, and it introduces a second Cloud Run resource for a phase whose entire purpose is to isolate one unknown (connector auth). Note it in the plan as the Phase-7 hardening path — that is where "migrations should not depend on a developer's laptop" becomes a real requirement.

**Confidence: HIGH** — the "no pre-deploy hook" claim is verified negatively against the complete flag list, and every component of the laptop path is already exercised by the test suite.

---

## New and revised pitfalls (Cloud Run)

### Pitfall CR-1: `--source` deploy fails with "provide a main.py or app.py file"
**What goes wrong:** The build fails before any dependency is installed, with a message about `main.py`/`app.py` that seems to have nothing to do with a FastAPI app in `backend/`.
**Why:** No `Procfile`/`GOOGLE_ENTRYPOINT` → CNB falls through to the `missing-entrypoint` order group, which looks for `main.py`/`app.py` **at the source root** and finds neither. Q1.2.
**Avoid:** Commit the two-line `Procfile`.
**Warning sign:** The literal string `for Python with pyproject.toml, provide a main.py or app.py file` in the Cloud Build log. `[VERIFIED: buildpack source]`

### Pitfall CR-2: dev dependencies silently ship to production
**What goes wrong:** Nothing visibly breaks. The image is ~2× larger and contains pytest, mypy, ruff, pre-commit and the `docker` client.
**Why:** The buildpack runs bare `uv sync` — no `--no-dev` — and uv's `default-groups` is `["dev"]`. Q1.1(b).
**Avoid:** `[tool.uv] default-groups = []`.
**Warning sign:** `Installing dependencies with 'uv sync'` followed by ~73 packages instead of 41 in the build log. `[VERIFIED: uv sync --frozen --dry-run` → 32 extra packages]

### Pitfall CR-3: `--set-env-vars` / `--env-vars-file` / `--set-secrets` wipe what they do not list
**What goes wrong:** A one-off `gcloud run services update --set-env-vars=LOG_LEVEL=DEBUG` removes every other environment variable, and the next request 500s on a missing `DATABASE_URL`.
**Why:** *"All existing environment variables will be removed before the new environment variables are added"* / *"All existing secrets will be removed first."* `[VERIFIED: gcloud run deploy --help]`
**Avoid:** Only ever change configuration by re-running `scripts/deploy-cloud-run.sh`; use `--update-env-vars`/`--update-secrets` for genuine one-offs. Never both bind a key as a secret and list it in the env-vars file.

### Pitfall CR-4: `421 Invalid Host header` — Pitfall 2, relocated
Unchanged in mechanism. Cloud Run **forwards the original public `Host` header** to the container rather than rewriting it to an internal name (it sets `X-Forwarded-For`/`X-Forwarded-Proto` but leaves `Host` alone) `[MEDIUM: corroborated by multiple practitioner reports; the same behaviour is what makes Cloud Run custom domains work]`. So `TransportSecuritySettings(allowed_hosts=[...])` behaves exactly as on Render — and so does the failure. **New wrinkle:** Cloud Run assigns *two* default URLs (deterministic + legacy hash) and serves both `[CITED: cloud.google.com/run/docs/triggering/https-request]`. Run `gcloud run services describe brett --format='value(status.url,status.urls)'` after the first deploy and add every hostname it reports to `MCP_ALLOWED_HOSTS`.

### Pitfall CR-5: 490 MB of health data uploaded on every deploy
See Q1.4. Currently prevented only by gcloud's implicit `.gitignore` fallback. Commit `.gcloudignore`.

### Pitfall CR-6: `echo` corrupts a Secret Manager secret
`echo "$TOKEN" | gcloud secrets create ... --data-file=-` stores a **trailing newline** as part of the value. The runtime then compares `"<token>\n"` against the header token with `secrets.compare_digest` and every authenticated request 401s, while the secret "looks right" in the console. Use `printf '%s'`. Google's own examples use `printf`. `[VERIFIED: gcloud secrets create --help examples]`

---

## Revised Validation Architecture rows

Only the DEPLOY-01 rows change; every MCP-01 / MCP-04 / D-08 row above stands.

| Req ID | Behavior | Test Type | Automated Command | File |
|---|---|---|---|---|
| DEPLOY-01 | `deploy/cloud-run.env.yaml` parses; every key maps to a `Settings` field; no secret-shaped key present | unit | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ❌ Wave 0 |
| DEPLOY-01 | `scripts/deploy-cloud-run.sh` carries every required flag and no literal credential | unit | same file | ❌ Wave 0 |
| DEPLOY-01 | `Procfile` `web:` line has `--app-dir backend`, `--host 0.0.0.0`, `$PORT` | unit | same file | ❌ Wave 0 |
| DEPLOY-01 | `.gcloudignore` excludes the health-data exports and `.venv/` | unit | same file | ❌ Wave 0 |
| DEPLOY-01 | `render.yaml` and `test_render_blueprint.py` are gone | unit | same file | ❌ Wave 0 |
| DEPLOY-01 | Service live over HTTPS, `/health` → 200 | **manual** | Auth Verification Matrix row 6 against `https://brett-<num>.<region>.run.app` | manual-only |

**Wave 0 delta:** add `backend/tests/test_cloud_run_deploy.py`; **delete** `backend/tests/test_render_blueprint.py` and `render.yaml`. No new dev dependency — `pyyaml==6.0.3` is already in the dev group (it was added for the render.yaml test) `[VERIFIED: pyproject.toml]`.

---

## Downstream doc-language updates (from CONTEXT.md "Downstream Doc Updates Required")

Concrete, so the planner can task them rather than rediscover them:

| File | Text to change |
|---|---|
| `.planning/REQUIREMENTS.md` | **DEPLOY-01** currently reads *"deployed to Render over HTTPS with environment-based secrets"* → Cloud Run + Google Secret Manager |
| `.planning/ROADMAP.md` | Phase 2 goal, success criterion #1, and the 02-03/02-05/02-07 plan descriptions all say "Render" |
| `.planning/PROJECT.md` | Key Decisions row + the *"Render account is already set up"* note |
| `CLAUDE.md` | §"Deployment (Render)" — the whole table is Render-specific. Also §"Constraints" (*"Deployment: Render for v1"*) and §"Stack Patterns by Variant". The portability claim in that section (*"Fly.io, Railway, and a $6 VPS ... all take it unchanged"*) is now **empirically confirmed** by this pivot: the only code-level change required for Cloud Run is zero — the entire delta is deploy artifacts |
| `backend/app/config.py` | Two comments reference Render by name (`"a Render custom domain"`, `"the name render.yaml sets"`). Cosmetic, but they are the kind of stale pointer the CONTEXT.md instruction is aimed at |

---

## Addendum Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| **A-CR-1** | `gcloud run deploy --set-build-env-vars` accepts arbitrary non-`GOOGLE_`-prefixed keys (`UV_FROZEN`, `UV_NO_DEV`) and they reach the buildpack's `uv sync` process environment | Q1.1 | Dev deps ship to production and the lockfile can drift. **Low impact, cheaply mitigated:** the primary recommendation is `[tool.uv] default-groups = []` in `pyproject.toml`, which is verified and needs no env var. Confirm by grepping the first build log for the package count |
| **A-CR-2** | `gcloud run deploy --source` uses the `gcr.io/buildpacks/builder` order groups read from `builders/gcp/base/builder.toml` at `main` | Q1.2 | If Cloud Run pins an older builder, `missing-entrypoint` might behave differently. **Does not change the conclusion** — a `Procfile` satisfies every version of the entrypoint logic. Falsifiable in one deploy |
| **A-CR-3** | Cloud Run forwards the original public `Host` header unmodified | Pitfall CR-4 | Every MCP request returns 421. This is the Cloud Run successor to old assumption A3 and is diagnosable in one request (Auth Verification Matrix row 7's inverse). Setting `enable_dns_rebinding_protection=False` is the emergency escape, but do not ship it |
| **A-CR-4** | The Neon Free plan permits creating a project and a direct connection string without a paid upgrade, and 0.5 GB is enough for v1 | Q2.5 | Unbudgeted cost. Vendor pricing page only; no tenant probed. Hevy set data is tiny — 0.5 GB is not a real constraint |
| **A-CR-5** | Creating an 8th GCP project on this personal account is within quota | Q6.1 | `gcloud projects create` fails with a quota error. Fallback: reuse an existing project (not recommended — mixes unrelated IAM and billing) or request a quota increase |
| **A-CR-6** | Cloud Run cold start at `min=0` totals ~3-5 s for this app | Q4.1 | If it is materially worse, `min=0` is unusable even for the CLI-proof stage. The app-import component (~2.5 s cold, ~0.45 s warm) **is** measured; only the platform overhead is estimated. D-06f's upgrade already covers this |
| **A-CR-7** | Secret Manager env-var bindings are resolved at instance start, so a rotated `:latest` version reaches a running service only after the next instance start | Q3.1 | A rotated `MCP_AUTH_SECRET` appears not to take effect. Mitigation is trivial: redeploy or `gcloud run services update` after rotating |

---

## Addendum Sources

### Primary (HIGH confidence)

- **`GoogleCloudPlatform/buildpacks` @ `main`, source read 2026-08-27** — `cmd/python/uv/lib/lib.go`, `cmd/python/missing_entrypoint/lib/lib.go`, `cmd/python/runtime/lib/lib.go`, `cmd/python/webserver/main.go`, `cmd/config/entrypoint/lib/lib.go`, `pkg/python/pyproject.go`, `pkg/python/python.go`, `pkg/gcpbuildpack/{exec,filepath,gcpbuildpack}.go`, `builders/gcp/base/builder.toml`. *This is the strongest evidence in the addendum* — uv detection, the exact `uv sync` invocation, the Procfile requirement, `bash -c` wrapping, `.python-version` precedence, and the order-group fallthrough all come from reading the code that runs.
- **Local `gcloud` SDK 578.0.0 (core 2026.07.24)** — `gcloud run deploy --help`, `gcloud run services update --help`, `gcloud run jobs deploy --help`, `gcloud secrets create --help`, `gcloud secrets versions add --help`, `gcloud projects create --help`, `gcloud billing projects link --help`, `gcloud services enable --help`. Every flag, every semantic ("all existing … removed first"), and the `--min` vs `--min-instances` distinction are quoted from the installed CLI.
- **Local environment probes, 2026-08-27** — `gcloud auth list`, `gcloud config list`, `gcloud billing accounts list`, `gcloud projects list`, `gcloud services list --enabled`, `du -sh`.
- **Local execution against this repo, 2026-08-27** — `uv sync --frozen --no-dev` (41 packages) + `uv pip check` (clean); `uv sync --frozen --dry-run` (32 extra dev packages); `UV_NO_DEV=1 uv sync --frozen --dry-run` (no changes); a scratch-project verification of `[tool.uv] default-groups = []`; `python -X importtime -c "import app.main"` and `/usr/bin/time` (2.5 s cold / 0.45 s warm).
- **Repo file reads** — `pyproject.toml`, `uv.lock` (`source = { virtual = "." }`), `.python-version`, `.gitignore`, `render.yaml`, `backend/app/config.py`, `backend/app/db/session.py`, `backend/migrations/env.py`, `backend/tests/conftest.py`, `backend/tests/test_render_blueprint.py`.
- **Installed SQLAlchemy 2.0.52 source** — `dialects/postgresql/asyncpg.py` (`prepared_statement_cache_size` as a URL query parameter).
- `https://docs.cloud.google.com/docs/buildpacks/python` — package-manager precedence, `GOOGLE_PYTHON_PACKAGE_MANAGER`, entrypoint precedence, `.python-version`.
- `https://docs.cloud.google.com/run/docs/deploying-source-code` — required APIs, `roles/run.builder` on the Compute Engine default SA, implicit `cloud-run-source-deploy` Artifact Registry repo, deployer roles.
- `https://docs.cloud.google.com/run/docs/configuring/services/secrets` — `--set-secrets` / `--update-secrets` syntax, cross-project form, `roles/secretmanager.secretAccessor`.
- `https://docs.cloud.google.com/run/docs/configuring/min-instances` — `--min` vs `--min-instances`, "best-effort target", idle billing.
- `https://docs.cloud.google.com/run/docs/container-contract` — `PORT` injection, `0.0.0.0` requirement, 4-minute listen deadline, TLS termination, `K_SERVICE`/`K_REVISION`.
- `https://docs.cloud.google.com/run/docs/triggering/https-request` — deterministic URL format (**GA**), legacy hash URL, both assigned.
- `https://docs.cloud.google.com/run/docs/troubleshooting` — "The default Compute Engine service account doesn't exist in the project".
- `https://docs.cloud.google.com/build/docs/securing-builds/configure-access-for-cloud-build-service-account` — the July-2024 default-service-account change.
- `https://docs.cloud.google.com/run/docs/tips/general` — cold-start stages, startup CPU boost, request pending window.

### Secondary (MEDIUM confidence)

- `https://neon.com/docs/connect/connect-from-any-app` — pooled vs direct DSN, `sslmode`/`channel_binding`.
- `https://neon.com/docs/connect/connection-pooling` — `-pooler` hostname, `pool_mode = transaction`, `max_client_conn = 10000`, `max_connections` per CU, unpooled-for-migrations guidance.
- `https://neon.com/docs/introduction/plans` — Free plan: 0.5 GB, 100 CU-hours, 5-min scale-to-zero (not disableable), data never deleted.
- `https://neon.com/docs/introduction/scale-to-zero` — suspension is activity-driven, not connection-driven; `idle-in-transaction` counts as active.
- `https://neon.com/blog/pgbouncer-the-one-with-prepared-statements` — protocol-level prepared statements through Neon's pooler.
- `https://docs.cloud.google.com/run/docs/runtimes/python-dependencies` — `GOOGLE_PYTHON_PACKAGE_MANAGER`, `pyproject.toml` GA for source deploys.

### Tertiary (LOW confidence — flagged)

- Practitioner reports that Cloud Run leaves the `Host` header intact (siipo.la, dotnet/yarp#1804). Corroborative only; A-CR-3 remains the honest label.
- Third-party Cloud Run cold-start benchmarks (0.5-2 s platform overhead for Python). Used only to bracket A-CR-6; the app-side 2.5 s figure is measured, the platform figure is not.

---

## Addendum Metadata

**Confidence breakdown:**

- **Buildpack + uv behaviour, and the Procfile requirement:** HIGH — read from the buildpack source that executes, cross-checked against Google's published docs, with the dependency-set behaviour reproduced locally against this repo's actual `pyproject.toml`/`uv.lock`.
- **`gcloud` flag semantics:** HIGH — quoted from the installed SDK 578.0.0, not from memory.
- **Neon compatibility with this codebase:** HIGH — `Settings.async_database_url` already performs exactly the `sslmode`→`ssl` translation and `channel_binding` drop that Neon's DSN requires, and `pool_pre_ping=True` already covers scale-to-zero. Zero code change.
- **Neon plan limits and pooler internals:** MEDIUM — vendor docs only; no tenant probed.
- **Secret Manager + IAM:** HIGH for syntax and role names; MEDIUM for the new-project default-SA edge cases, which are documented but vary by project age.
- **Cold-start figures:** MEDIUM — the app's own import cost is measured on this machine; platform overhead is third-party.
- **Environment/account state:** HIGH — probed directly today, and it materially relaxes D-06a.

**Research date:** 2026-08-27
**Valid until:** 2026-09-10 (14 days). Cloud Buildpacks' Python/uv support is actively changing (the `pyproject.toml` path went GA recently, and the `>= 3.14` "smart default entrypoint" branch is new), and Cloud Build's default service-account behaviour has shifted twice since 2024. Re-read `cmd/python/missing_entrypoint` and re-run `gcloud run deploy --help` before Phase 7.

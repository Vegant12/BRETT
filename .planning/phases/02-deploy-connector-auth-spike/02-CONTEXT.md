# Phase 2: Deploy & Connector Auth Spike - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Resolve the project's single highest-uncertainty question — whether and how a real Claude client (Desktop/Web/Mobile) can authenticate to a remote MCP server — while it is still cheap to change the answer. Delivers: the service live on Render over HTTPS with env-based secrets, a real (non-disposable) MCP mount at `/mcp` carrying exactly one throwaway tool, and a working connector auth mechanism verified end-to-end and recorded in PROJECT.md Key Decisions.

**Explicitly NOT this phase:** Hevy integration (Phase 3), real analytics, the real MCP tool set (Phase 6), rate limiting / production hardening (Phase 7).

</domain>

<decisions>
## Implementation Decisions

### Auth Strategy & Fallback
- **D-01:** Prove the deploy + MCP mount + auth-check pipeline first via Claude Code CLI header auth (`claude mcp add --header "Authorization: Bearer $TOKEN"`) — zero extra infra, de-risks the plumbing before touching connector-specific auth.
- **D-02:** Do NOT email Anthropic to request `static_headers` beta access. Skip the beta-access wait entirely and go straight to the fallback mechanism below.
- **D-03:** Connector auth mechanism is a **managed IdP with Dynamic Client Registration (DCR)** — not a hand-rolled OAuth 2.1 resource-server shim. The MCP SDK's `TokenVerifier` validates tokens via JWKS/introspection against the IdP; the SDK itself never issues tokens.
- **D-04:** The managed IdP is **WorkOS**. Set `AuthSettings.issuer_url` to the WorkOS issuer. Note: CLAUDE.md's IdP comparison source (workos.com/blog) is vendor-authored — treat their self-comparison as a shortlist, not a verdict, if setup surfaces unexpected gaps.
- This is the phase's central uncertainty and the primary reason it exists — get D-03/D-04 working and verified end-to-end from an actual Desktop/Web/Mobile client before considering the phase done, per ROADMAP.md success criterion #2.

### Spike vs. Foundation (MCP Scaffolding)
- **D-05:** Build the **real** `mcp/server.py` structure now, not a disposable script: `MCPServer` with lifespan-based `AppContext` wired to `app.state.engine`/`app.state.sessionmaker`, `TransportSecuritySettings(allowed_hosts=[...])` configured correctly from the start (CLAUDE.md flags the `421 Misdirected Request` default-reject as "the single most likely Phase-5 blocker"), mounted at `/mcp` inside the existing FastAPI app per the CLAUDE.md "FastAPI + MCP Integration Pattern".
- Only the **one tool** registered on this server is throwaway — Phase 6 replaces it with the real tool set, but does not rebuild the mount/lifespan/security plumbing.

### Render Commitment & Cost
- **D-06:** Deployment platform is **Render**, not Google Cloud Run. Considered and rejected: Cloud Run reintroduces the same cold-start problem unless `min-instances=1` (costing about the same as Render Starter anyway), and needs separate Cloud SQL provisioning + a connector/proxy — more surface area while this phase is already resolving one hard unknown (auth). Render account is already provisioned per PROJECT.md.
- **D-07:** Start on Render's **free** web-service tier + free Postgres. Upgrade to Starter tier + paid Postgres **before** testing against the actual Desktop/Web/Mobile connector (free tier's 30-60s cold start exceeds Claude's 10s OAuth discovery timeout and will masquerade as a broken server). The CLI-proof step (D-01) does not require the paid tier, so cost is deferred until it's actually load-bearing.
  - **Trigger point for the upgrade:** once CLI-proof auth (D-01) is working and before attempting a real connector round-trip. Claude has discretion on exact timing within the plan, but the upgrade must happen before connector testing, not after a confusing failure.

### Throwaway Tool Design
- **D-08:** The one registered tool performs a **real DB round-trip** (e.g. `fitness_ping` running `SELECT 1` through `app.state.engine`), not a bare echo/no-op. This proves the lifespan-wired `AppContext` → DB-session pattern that every real Phase 6 tool will depend on, not just that the endpoint responds to a call.

### Claude's Discretion
- Exact tool name/response shape for the throwaway DB-ping tool, beyond "real SELECT 1 through the lifespan engine"
- Exact `mcp/server.py` internal file layout (single file vs. small package) as long as it mirrors the CLAUDE.md pattern (lifespan → AppContext → tool reads `ctx.request_context.lifespan_context`)
- Precise WorkOS configuration details (application setup, redirect URIs, JWKS endpoint wiring) — implementation detail of D-04
- Exact Render upgrade trigger mechanics (manual dashboard change vs. `render.yaml` tier bump) as long as it happens before connector testing per D-07

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Auth strategy (the phase's core question)
- `CLAUDE.md` §"Critical Findings" #2 — connector auth types table (`oauth_dcr`, `oauth_cimd`, `oauth_anthropic_creds`, `static_headers` beta, `none`); confirms `static_headers` requires emailing Anthropic (D-02: skipped) and a bearer-token-in-URL is prohibited by the MCP authorization spec
- `CLAUDE.md` §"Authentication Decision Path" — the exact staged plan this phase follows: Phase 4 local verify via Claude Code CLI header auth (D-01) → Phase 5 fallback via managed IdP + DCR (D-03/D-04)
- `CLAUDE.md` §"Alternatives Considered" — FastMCP's `RemoteAuthProvider`/`OAuthProxy` row, relevant only if the official SDK + WorkOS combination hits a wall
- `CLAUDE.md` §"What NOT to Use" — hand-rolled OAuth AS explicitly discouraged (rejected as D-03's alternative)
- `BRETT blueprint.md` §32 "Authentication" — "prefer OAuth-compatible authentication for the remote MCP if supported"; never expose `HEVY_API_KEY`, DB credentials, or internal tokens through MCP responses
- `.planning/PROJECT.md` Key Decisions — "MCP auth = bearer token for v1, not OAuth" is the decision this phase's outcome will confirm or explicitly overturn (per ROADMAP.md success criterion #4); D-03/D-04 overturn it in favor of OAuth/DCR via WorkOS
- `.planning/STATE.md` Blockers/Concerns — records the exact risk this phase resolves (GitHub issue #112 closed "not planned"; `static_headers` beta unconfirmed for a personal account)

### MCP server integration pattern
- `CLAUDE.md` §"The FastAPI + MCP Integration Pattern" — `streamable_http_app()` must be called at import time before lifespan runs; `TransportSecuritySettings(allowed_hosts=[...])` required or Render deploy fails with an unexplained 421; `@mcp.custom_route` is never authenticated — health stays on the FastAPI side, not the MCP side; tools reach the DB via `ctx.request_context.lifespan_context`, never a fresh HTTP call
- `CLAUDE.md` §"Version Compatibility" — `mcp 2.0.0` / `starlette` version-conditional pin table; re-verify on the actual Python version pinned in this repo
- `BRETT blueprint.md` §29 "MCP Server" — do not expose raw DB access; purpose-built tools only (only one throwaway tool exists this phase — the real set is Phase 6, blueprint §30-31)
- `BRETT blueprint.md` §46 "MCP Production Endpoint" — `/mcp` path convention; "do not assume a specific transport implementation without checking the current MCP SDK documentation"

### Deployment
- `CLAUDE.md` §"Deployment (Render)" — full table: one Web Service for both `/api` and `/mcp` (D-06 confirms Render, single service already settled prior to this phase); free-tier cold-start and free-Postgres 30-day-deletion figures backing D-07; migrations via Render pre-deploy command, not app startup
- `BRETT blueprint.md` §45 "Deployment" — Render target, may run as one service initially, required env vars (`DATABASE_URL`, `HEVY_API_KEY`, `MCP_AUTH_SECRET`, `JWT_SECRET`, `ENVIRONMENT`), never commit values
- `BRETT blueprint.md` §47 "Claude Connection" — the manual verification steps this phase's success criteria are checked against (deploy → verify HTTPS → verify handshake/discovery → add custom connector in Claude → authenticate → enable)

### Requirements & roadmap
- `.planning/ROADMAP.md` Phase 2 section — goal, 4 success criteria (Render live over HTTPS; connector discovers + calls throwaway tool from an actual Desktop/Web/Mobile client, not just a local test client; unauthenticated request rejected / authenticated succeeds against the deployed URL; auth mechanism chosen and recorded in PROJECT.md)
- `.planning/REQUIREMENTS.md` — MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 (exact acceptance criteria for this phase)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/config.py` — `Settings.mcp_auth_secret: SecretStr | None` already exists (unused since Phase 1), anticipated for this phase's auth work. `Settings.secret_values()` already feeds the log-redaction scrubber; any new WorkOS client secret must be added to `_SECRET_FIELDS` the same way.
- `backend/app/main.py` — `lifespan()` already creates `app.state.engine`/`app.state.sessionmaker` and disposes them on shutdown; the MCP server's `AppContext` should read from the same `app.state`, not create a second engine.
- `backend/app/logging.py` / `configure_logging` — structlog + secret redaction already wired; new MCP-layer logging should route through the same `log = structlog.get_logger()` pattern used in `main.py`/`health.py`.

### Established Patterns
- Engine lifetime is owned by lifespan, never a module-level global (`main.py` docstring is explicit about this — pytest-asyncio and connection leaks are the reason).
- Routes/tools read `app.state.*` directly rather than going through a DI layer, "until there is a consumer" — the MCP throwaway tool should follow this same minimalism rather than introducing a DI abstraction early.
- Bare `except` + degrade-to-error-status is the established pattern for external dependency failures (see `health.py`'s DB-unreachable handling) — the DB-ping tool (D-08) should follow the same "coarse status to caller, full detail to log" split as `/health`.

### Integration Points
- New MCP mount goes in `backend/app/api/` alongside the existing `routes/` package, or a new sibling `backend/app/mcp/` package (Claude's discretion — no existing MCP code to match yet).
- `app.include_router(health.router)` in `main.py` is the existing mount-point pattern; the MCP ASGI app will be mounted similarly, per CLAUDE.md's integration pattern (`app.mount("/mcp", mcp.streamable_http_app(...))` or equivalent — confirm exact call against current SDK docs at research/plan time).

</code_context>

<specifics>
## Specific Ideas

No further specific idea beyond the decisions above — this is an infrastructure/spike phase and the discussion resolved the actual points of ambiguity (auth mechanism, scaffolding permanence, deployment tier, tool scope) rather than surfacing new freeform requirements.

</specifics>

<deferred>
## Deferred Ideas

- Emailing Anthropic for `static_headers` beta access — explicitly declined for this phase (D-02). Not lost, just not pursued now; if WorkOS/DCR setup hits a wall, revisit requesting beta access as an alternate path rather than assuming it's permanently off the table.
- Cloud Run as a deployment platform — considered and explicitly rejected for this phase (D-06). The stack is already host-agnostic per CLAUDE.md ("uv + uvicorn + Postgres... Fly.io, Railway, and a $6 VPS all take it unchanged"), so this remains revisitable later without architectural rework, just not during this auth-focused phase.
- Rate limiting on the MCP endpoint — blueprint §32 lists it as part of minimum private-dev auth, but it's not in this phase's ROADMAP.md success criteria or REQUIREMENTS.md (MCP-01/MCP-04/DEPLOY-01/DEPLOY-02); belongs with Phase 7 (Production Hardening).

</deferred>

---

*Phase: 02-deploy-connector-auth-spike*
*Context gathered: 2026-08-24*

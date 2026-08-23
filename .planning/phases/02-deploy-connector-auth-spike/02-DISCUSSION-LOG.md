# Phase 2: Deploy & Connector Auth Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-24
**Phase:** 2-deploy-connector-auth-spike
**Areas discussed:** Auth strategy & fallback, Spike vs. foundation, Render commitment & cost, Throwaway tool design

---

## Auth strategy & fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, CLI first | Prove the pipeline via Claude Code CLI header auth before connector auth | ✓ |
| Skip straight to connector auth | Go directly for Desktop/Web/Mobile connector auth | |

**User's choice:** Yes, CLI first.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, request it now | Email Anthropic for static_headers beta access | |
| No, skip straight to a fallback | Assume beta won't arrive in time, go straight to fallback | ✓ |

**User's choice:** No, skip the beta-access wait.

| Option | Description | Selected |
|--------|-------------|----------|
| Managed IdP with DCR | WorkOS/Keycloak + TokenVerifier via JWKS | ✓ |
| Minimal OAuth 2.1 resource-server shim | Custom AS, more work/security surface | |

**User's choice:** Managed IdP with DCR.

| Option | Description | Selected |
|--------|-------------|----------|
| WorkOS | Purpose-built, generous free tier, DCR support | ✓ |
| Keycloak | Self-hosted, no third-party dependency, extra service to run | |

**User's choice:** WorkOS.
**Notes:** No follow-up questions requested — user moved directly to next area.

---

## Spike vs. foundation

| Option | Description | Selected |
|--------|-------------|----------|
| Real structure, throwaway tool | Real mcp/server.py with lifespan/AppContext/TransportSecuritySettings now; only the tool is disposable | ✓ |
| Literal one-file spike | Separate throwaway script, Phase 6 rebuilds structure from scratch | |

**User's choice:** Real structure, throwaway tool.
**Notes:** No follow-up questions requested.

---

## Render commitment & cost

Mid-discussion, the user asked "what if we use google cloud run instead?" — a platform switch, not one of the presented options. This revisits a PROJECT.md Constraint ("Deployment: Render for v1"), so it was treated as a real decision point rather than scope creep: Claude summarized the Cloud Run tradeoff (same cold-start problem unless min-instances=1 pinned; separate Cloud SQL + proxy/connector setup) and asked the user to confirm platform choice before continuing to the tier question.

| Option | Description | Selected |
|--------|-------------|----------|
| Stick with Render | Already provisioned, one less unknown during the auth spike | ✓ |
| Switch to Cloud Run | Untested for this stack, more setup, reintroduces cold-start risk | |

**User's choice:** Stick with Render.

| Option | Description | Selected |
|--------|-------------|----------|
| Starter tier from day one | Avoids cold-start/30-day-Postgres-deletion traps, costs money immediately | |
| Start free, upgrade later | Defer cost until CLI-proof auth works, upgrade before connector testing | ✓ |

**User's choice:** Start free, upgrade later — upgrade must land before real connector testing (before the cold-start timeout would actually bite).

---

## Throwaway tool design

| Option | Description | Selected |
|--------|-------------|----------|
| DB round-trip | fitness_ping running a real SELECT 1 through app.state.engine | ✓ |
| Bare no-op / echo | Static string/echo, no DB involvement | |

**User's choice:** DB round-trip — proves the lifespan-wired AppContext/DB-session pattern Phase 6 tools depend on.

---

## Claude's Discretion

- Exact tool name/response shape for the DB-ping tool
- Internal file layout of mcp/server.py (single file vs. small package)
- Precise WorkOS configuration details (app setup, redirect URIs, JWKS wiring)
- Exact mechanics of the Render tier upgrade (dashboard vs. render.yaml), as long as it happens before connector testing

## Deferred Ideas

- Emailing Anthropic for static_headers beta access — declined for this phase, not permanently ruled out
- Cloud Run as a deployment platform — considered mid-discussion and explicitly rejected for this phase; revisitable later since the stack is host-agnostic
- Rate limiting on the MCP endpoint — blueprint-mentioned but belongs to Phase 7 (Production Hardening), not in this phase's requirements

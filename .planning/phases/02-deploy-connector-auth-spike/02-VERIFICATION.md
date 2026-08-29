---
phase: 02-deploy-connector-auth-spike
verified: 2026-08-29T12:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 2: Deploy & Connector Auth Spike Verification Report

**Phase Goal:** Resolve the project's single highest-uncertainty question — whether and how a real Claude client can authenticate to a remote MCP server — while it is still cheap to change the answer
**Verified:** 2026-08-29T12:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Service is live on Google Cloud Run over HTTPS, backed by Neon Postgres, every credential from Secret Manager, nothing committed | VERIFIED | `deploy/cloud-run.env.yaml` contains no credential-shaped keys (enforced by `test_no_credential_shaped_key_is_present`); `scripts/deploy-cloud-run.sh` binds `DATABASE_URL`/`MCP_AUTH_SECRET` via `--set-secrets=...:latest` (Secret Manager references, not literals), cross-checked by `test_every_secret_binding_is_a_secret_manager_reference`; 02-05-SUMMARY.md records the live URL `https://brett-792870654598.us-central1.run.app`, GCP project `brett-fitness`, Neon DB migrated to Alembic head 0002; 02-07-SUMMARY.md re-confirms by reading the serving revision's environment back post-cutover; `uv run pre-commit run gitleaks --all-files` passes (re-verified independently in this session) |
| 2 | A Claude custom connector discovers a throwaway tool and calls it from an actual Desktop/Web/Mobile client | VERIFIED | 02-07-SUMMARY.md / 02-DEPLOY-LOG.md "Connector round-trip (DEPLOY-02)": developer report confirms Claude Desktop, WorkOS AuthKit consent completed, `fitness_ping` returned `{"status": "ok", "database": "connected"}` on first attempt; this is a human-verified checkpoint (`checkpoint:human-verify`), not a claim inferred from code |
| 3 | Unauthenticated request rejected, authenticated succeeds, verified against the deployed URL | VERIFIED | 02-DEPLOY-LOG.md Auth Verification Matrix (Stage A, pre-cutover): rows 1–2 return `401` byte-identical bodies, row 3–4 return `200` with `fitness_ping` present and correct `structuredContent`, row 5 metadata document reachable, row 7 `421` DNS-rebinding guard via negative control. Post-cutover (authkit) matrix re-confirms rows 1,2,5,6 unchanged and row 7 by configuration readback; rows 3/4 (which required reading the live secret) were substituted with four credential-free forged-token probes, all rejected `401` byte-identical, including an RS256 JWT with correct `iss`/`aud`/`kid` differing only in signature — a token nothing but real JWKS verification can reject. Minor unresolved item: the client-side "connector disabled ⇒ no path to tool" negative was not explicitly confirmed by the developer (recorded honestly as a gap in 02-07-SUMMARY.md), but this does not weaken MCP-04 since the requirement is server-side rejection, which is proven |
| 4 | Auth mechanism recorded in PROJECT.md Key Decisions, confirming or overturning "bearer token, not OAuth" | VERIFIED | `.planning/PROJECT.md` Key Decisions table: original row `~~MCP auth = bearer token for v1, not OAuth~~` is struck through and marked "Superseded 2026-08-29 by the row below. Overturned, not confirmed"; new row records "MCP connector auth = OAuth 2.1 via WorkOS AuthKit (managed IdP), with BRETT as a resource server only" with evidence pointer to `02-DEPLOY-LOG.md`. Static bearer explicitly retained as CLI/rollback path, not deleted |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/mcp/server.py` | MCPServer + AuthSettings + TransportSecuritySettings + module-level `mcp_app` | VERIFIED | 83 lines, substantive; `streamable_http_app()` called at import time as required; `TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts, allowed_origins=[])` present |
| `backend/app/mcp/auth.py` | StaticTokenVerifier + AuthKitJWTVerifier + build_token_verifier selector | VERIFIED | 141 lines; `secrets.compare_digest` on bytes (constant-time, confirmed by source read); AuthKitJWTVerifier pins `algorithms=["RS256"]`, enforces `iss`/`aud`/`exp` via `options={"require": [...]}`, JWKS fetch pushed to worker thread via `anyio.to_thread.run_sync` |
| `backend/app/mcp/context.py` | AppContext + mcp_lifespan borrowing `app.state.sessionmaker` | VERIFIED | 43 lines; deferred `from app.main import app` inside function body to break circular import; never calls `make_engine()` |
| `backend/app/mcp/tools/ping.py` | `fitness_ping` real DB round-trip via `SELECT 1` | VERIFIED | 44 lines; executes `text("SELECT 1")` through the lifespan sessionmaker; degrades to `{"status":"ok","database":"error"}` on failure without leaking connection details (mirrors `health.py` pattern) |
| `backend/app/main.py` | Mount at `/`, session_manager entered in parent lifespan | VERIFIED | `app.mount("/", mcp_app)` registered after `include_router`; `mcp.session_manager.run()` entered inside `AsyncExitStack` after `app.state.sessionmaker` is assigned |
| `scripts/deploy-cloud-run.sh` | Reproducibility artifact wrapping `gcloud run deploy` | VERIFIED | Uses `--env-vars-file` for non-secret config and `--set-secrets` for `DATABASE_URL`/`MCP_AUTH_SECRET`; no credential literals |
| `deploy/cloud-run.env.yaml` | Complete non-secret runtime environment | VERIFIED | Contains real assigned Cloud Run hostnames, `MCP_AUTH_MODE: "authkit"`, real WorkOS issuer/JWKS URI (not placeholders — resolved in 02-07) |
| `render.yaml` / `test_render_blueprint.py` | Should be deleted per D-06e (superseded by Cloud Run) | VERIFIED (absent) | Confirmed absent from repo — deliberate deletion documented in 02-08, not a regression |
| `backend/tests/test_cloud_run_deploy.py` | 12+ drift assertions | VERIFIED | 13 `test_` functions present |
| `.planning/PROJECT.md` | Key Decision row recording auth mechanism | VERIFIED | See Truth 4 above |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `backend/app/mcp/context.py` | `app.state.sessionmaker` | deferred import inside `mcp_lifespan` | WIRED | Confirmed by source read; no second engine created |
| `backend/app/mcp/server.py` | `backend/app/mcp/auth.py` | `token_verifier=build_token_verifier(settings)` | WIRED | Confirmed in `server.py:45` |
| `backend/app/mcp/tools/ping.py` | `AppContext` | `ctx.request_context.lifespan_context` | WIRED | Confirmed in `ping.py:35` |
| `backend/app/main.py` | `mcp_app` | `app.mount("/", mcp_app)` | WIRED | Confirmed in `main.py:77`, registered after FastAPI's own routes to avoid shadowing |
| `scripts/deploy-cloud-run.sh` | `deploy/cloud-run.env.yaml` | `--env-vars-file` | WIRED | Confirmed by grep |
| `deploy/cloud-run.env.yaml MCP_JWKS_URI` | WorkOS AuthKit JWKS endpoint | `AuthKitJWTVerifier PyJWKClient` fetch | WIRED | Real JWKS URI present, not a placeholder; verified live in 02-07 (`GET /oauth2/jwks` → `200` in deploy log) |
| Claude custom connector | `https://<host>/mcp` | RFC 9728 metadata → WorkOS AuthKit → Bearer JWT | WIRED (human-verified) | Connector round-trip confirmed by developer at checkpoint |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full non-integration test suite passes | `uv run pytest -m "not integration" -q` | `72 passed, 28 deselected` | PASS |
| No committed secrets | `uv run pre-commit run gitleaks --all-files` | `Passed` | PASS |
| Render artifacts removed | `ls render.yaml backend/tests/test_render_blueprint.py` | both absent | PASS |
| MCP package substantive (not stub) | `grep -rn "TODO\|FIXME\|placeholder\|not implemented" backend/app/mcp/**/*.py` | no matches | PASS |
| Requirement IDs covered by plan frontmatter | `grep requirements: 02-0*-PLAN.md` | MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 all present across 8 plans | PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| MCP-01 | 02-01, 02-02, 02-04, 02-05 | Remote MCP server deployed and reachable over HTTPS, independent of local config | SATISFIED | Live at `https://brett-792870654598.us-central1.run.app/mcp`; local + deployed HTTP contract tests all pass |
| MCP-04 | 02-01, 02-02, 02-04, 02-05, 02-06, 02-07 | MCP server authenticates requests, rejects unauthenticated ones, verified end-to-end from an actual Claude client | SATISFIED | Server-side 401/401/200 matrix proven against deployed URL both pre- and post-cutover; end-to-end proven via Claude Desktop connector round-trip (human-verified) |
| DEPLOY-01 | 02-01, 02-03(superseded), 02-05, 02-07, 02-08 | Backend + MCP server deployed to Google Cloud Run over HTTPS, every credential from Secret Manager, nothing committed | SATISFIED | See Truth 1 above; gitleaks clean, Secret Manager bindings verified by static tests |
| DEPLOY-02 | 02-06, 02-07 | Claude custom connector can be added and successfully discovers/calls tools | SATISFIED | Human-verified Claude Desktop round-trip, `fitness_ping` called successfully at first attempt |

**Orphan check:** REQUIREMENTS.md maps exactly MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 to Phase 2 (line 176: `| 2. Deploy & Connector Auth Spike | MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 | 4 |`). All four are claimed across the 8 plans' `requirements:` frontmatter. No orphaned requirements.

**Tracking discrepancy (non-blocking, documentation only):** `.planning/REQUIREMENTS.md` still lists MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 as `- [ ]` (unchecked) and "Pending" in its status table, even though all four are functionally satisfied and 02-07-SUMMARY.md explicitly instructed them to be marked complete ("Not touched by this agent... Mark DEPLOY-02, MCP-04 and DEPLOY-01 complete"). This mirrors the same convention used for Phase 1 (`FOUND-01..05` are `[x]`/"Complete" in the same file), so the convention exists and simply wasn't applied here. This is a paperwork gap, not a functional one — flagged for cleanup, not blocking phase completion.

### Anti-Patterns Found

None blocking. One informational item:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `.planning/ROADMAP.md` | 16 | Phase-level checkbox `- [ ] **Phase 2: Deploy & Connector Auth Spike**` not ticked despite all 8 plan-level checkboxes being `[x]` and 02-07-SUMMARY.md's handoff explicitly requesting it be ticked | ℹ️ Info | Cosmetic tracking gap only. Note: Phase 1's top-level checkbox is *also* unticked despite being fully complete, so this appears to be a pre-existing, repo-wide convention gap rather than a regression specific to this phase's handoff. Commit `91d8fc5` ("update tracking after wave 7") applied the STATE.md handoff correctly (blocker resolved, decision recorded, "deploy target Render" → "deploy target Google Cloud Run", `Open (Phase 3)`→2, `Open (Phase 6)`→1 all verified) and ticked the `02-07-PLAN.md` line, but missed the phase-level summary checkbox at line 16 |
| `.planning/REQUIREMENTS.md` | 62,65,71,72,130-133 | Requirement checkboxes/status table not updated to Complete | ℹ️ Info | Same paperwork-gap class as above; does not affect functional correctness |

### Human Verification Required

None outstanding — DEPLOY-02's required human verification (real Claude Desktop connector round-trip) was already completed and recorded in 02-07-SUMMARY.md / 02-DEPLOY-LOG.md as part of plan execution, with the developer's report captured verbatim. No further human action is needed to close this phase.

One narrow item is recorded as an accepted, non-blocking gap by the phase's own summary rather than something requiring new human verification: the client-side "connector disabled ⇒ no path to tool" negative was not explicitly confirmed by the developer during the checkpoint. This does not affect MCP-04 (server-side rejection is independently proven) and is cheap to close later if desired — not required for phase passage.

### Gaps Summary

No gaps block phase completion. All four ROADMAP.md success criteria are verified with strong, specific evidence (live deployment details, byte-level auth matrix comparisons, a human-verified connector round-trip, and a recorded PROJECT.md decision). The Render→Cloud Run pivot was handled correctly: `render.yaml`/`test_render_blueprint.py` are cleanly deleted, and no `.planning/*.md` document still names Render as the deploy target (CLAUDE.md's Render-era research section is explicitly marked `SUPERSEDED` at its header, which is expected and appropriate — it is retained as historical rationale, not a live claim).

The only findings are two paperwork-only tracking gaps: (1) `.planning/ROADMAP.md`'s top-level Phase 2 summary checkbox (line 16) was not ticked despite the 02-07-SUMMARY.md handoff explicitly requesting it — though this same checkbox is also unticked for the already-complete Phase 1, suggesting a pre-existing convention gap rather than a regression; and (2) `.planning/REQUIREMENTS.md` still shows MCP-01/MCP-04/DEPLOY-01/DEPLOY-02 as Pending rather than Complete, despite the established Phase-1 convention of marking satisfied requirements `[x]`/"Complete". Neither affects the phase's functional goal achievement; both are cheap, mechanical fixes recommended before/during the next phase transition.

---

_Verified: 2026-08-29T12:00:00Z_
_Verifier: Claude (gsd-verifier)_

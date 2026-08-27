# Phase 2: Deploy & Connector Auth Spike - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-24 (original) · updated 2026-08-27
**Phase:** 2-deploy-connector-auth-spike
**Areas discussed:** Auth strategy & fallback, Spike vs. foundation, Render commitment & cost, Throwaway tool design
**2026-08-27 update areas:** Reconsidering Render vs. Cloud Run, GCP project setup, database choice, container build method, secrets storage, IaC-equivalent reproducibility artifact

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

## Claude's Discretion (2026-08-24)

- Exact tool name/response shape for the DB-ping tool
- Internal file layout of mcp/server.py (single file vs. small package)
- Precise WorkOS configuration details (app setup, redirect URIs, JWKS wiring)
- Exact mechanics of the Render tier upgrade (dashboard vs. render.yaml), as long as it happens before connector testing

## Deferred Ideas (2026-08-24)

- Emailing Anthropic for static_headers beta access — declined for this phase, not permanently ruled out
- Cloud Run as a deployment platform — considered mid-discussion and explicitly rejected for this phase; revisitable later since the stack is host-agnostic
- Rate limiting on the MCP endpoint — blueprint-mentioned but belongs to Phase 7 (Production Hardening), not in this phase's requirements

---

# Update — 2026-08-27: Render → Google Cloud Run Pivot

**Trigger:** Mid-phase-execution question from the user during Wave 4 (plan 02-05, Render Blueprint checkpoint): "Is it possible to switch to google cloud run instead of render?" — the second time Cloud Run came up for this phase (first was 2026-08-24 above, and was rejected then).

## Reconsidering Render vs. Cloud Run

The 2026-08-24 rejection reasoning (min-instances=1 costs about the same as Render Starter; Cloud SQL adds provisioning/connector complexity) was surfaced again before proceeding, since the phase had already decided this once.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, switch anyway | User has a reason (unstated) that outweighs the added complexity | ✓ |
| Actually, stick with Render | Given the tradeoff is a wash, keep the original decision and resume the Wave 4 checkpoint | |

**User's choice:** Switch to Cloud Run anyway.
**Notes:** No specific reason volunteered when asked directly. Decision recorded as-is; the original rejection reasoning stays in CONTEXT.md in case this needs revisiting a third time.

---

## GCP Project Setup

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, already have one | User provides project ID, Claude configures against it | |
| No, need to create one | Requires a new checkpoint step (gcloud project + billing linkage), analogous to the Render account setup | ✓ |

**User's choice:** No existing project — needs to be created.

---

## Database

| Option | Description | Selected |
|--------|-------------|----------|
| Cloud SQL for Postgres | GCP-native, but real complexity: Auth Proxy/Unix-socket, separate provisioning, own IAM/networking | |
| External managed Postgres (Neon/Supabase/etc.) | Keeps the simple "external connection string" pattern from the Render plan; Cloud Run only needs outbound network access | ✓ (recommended) |

**User's choice:** External managed Postgres.

---

## Cold-Start Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| min-instances=0, upgrade to 1 before connector test | Mirrors the Render plan's D-07 — defers always-on cost until load-bearing | ✓ (recommended) |
| Go straight to min-instances=1 | Pay for always-warm from the start | |

**User's choice:** Start at 0, upgrade before connector test (mirrors original D-07 trigger point exactly).

---

## Database Provider

| Option | Description | Selected |
|--------|-------------|----------|
| Neon | Serverless Postgres, generous free tier, branching | ✓ |
| Supabase | Postgres + extras not needed here, solid free tier | |
| Other / decide later | Deferred to plan time | |

**User's choice:** Neon.

---

## Container Build Method

| Option | Description | Selected |
|--------|-------------|----------|
| `gcloud run deploy --source` (buildpacks) | No Dockerfile — auto-detects Python, closest analog to Render's zero-Dockerfile blueprint flow | ✓ (recommended) |
| Dockerfile + Cloud Build | More control, more to write/maintain — fallback if buildpacks can't handle uv/uv.lock | |

**User's choice:** Buildpacks (`gcloud run deploy --source`).

---

## Secrets Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Google Secret Manager | GCP-native secret store, analog to Render's generateValue/sync:false | ✓ (recommended) |
| Cloud Run environment variables directly | Simpler, but secrets sit in plain env var config | |

**User's choice:** Google Secret Manager.

---

## IaC / Reproducibility Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Checked-in deploy script | Committed `scripts/deploy-cloud-run.sh` wrapping `gcloud run deploy` — versioned, testable, analog to render.yaml + test_render_blueprint.py | ✓ (recommended) |
| Ad hoc CLI commands | Documented in plan instructions, run manually — less reproducible, nothing to test | |

**User's choice:** Checked-in deploy script.

---

## Claude's Discretion (2026-08-27 additions)

- GCP region choice
- Whether to delete or archive the now-obsolete `render.yaml` / `test_render_blueprint.py` (default: delete)
- Fallback to Dockerfile + Cloud Build if buildpacks can't handle `uv.lock` cleanly
- Exact `min-instances=1` upgrade trigger mechanics

## Deferred Ideas (2026-08-27)

None newly deferred in this update. Standing deferred items from 2026-08-24 (static_headers beta email, rate limiting) still apply — see above.

---
phase: 02
slug: deploy-connector-auth-spike
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-24
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| **Quick run command** | `uv run pytest -m "not integration" -q` |
| **Full suite command** | `uv run pytest -q` (requires the Docker daemon — currently down, must be started before Wave-boundary runs) |
| **Estimated runtime** | ~30s quick / ~90s full (testcontainers[postgres] spin-up dominates) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not integration" -q`
- **After every plan wave:** Run `uv run pytest -q` (Docker daemon must be up)
- **Before `/gsd-verify-work`:** Full suite green **plus** all 7 Auth Verification Matrix rows passing against the deployed URL (see RESEARCH.md) **plus** the two manual connector checks below
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

Test files are created inline within their implementing plans via `tdd="true"` tasks — there is no separate Wave 0 plan. Wave numbers below match each plan's actual `wave:` frontmatter.

| Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01 | 1 | MCP-01, MCP-04, DEPLOY-01 | — | `mcp==2.0.0` pin verified importable; `MCP_*` settings fields validated; test env seeded | unit | `uv run pytest -m "not integration" -q` (Task 1); `uv run pytest backend/tests/test_config.py -q` (Task 2) | ✅ created by plan | ⬜ pending |
| 02 | 2 | MCP-01, MCP-04 | — | `AppContext`/`fitness_ping` signatures correct | unit | `PYTHONPATH=backend uv run python -c "from app.mcp.context import AppContext, mcp_lifespan; ..."` (Task 1) | ✅ created by plan | ⬜ pending |
| 02 | 2 | MCP-04 | T-02-06 (unauth bypass), T-02-05 (timing attack), T-02-04 (log/response leakage) | Static bearer verifier: no/wrong/correct token → 401/401/200; constant-time comparison; no leak | integration | `uv run pytest backend/tests/test_mcp_auth.py -q` (Task 2) | ✅ created by plan | ⬜ pending |
| 02 | 2 | MCP-01 | — | Mount routes are exactly `['/mcp', '/.well-known/oauth-protected-resource/mcp']` — never under a `/mcp` prefix | unit | `uv run pytest backend/tests/test_mcp_mount.py -m "not integration" -q` (Task 3) | ✅ created by plan | ⬜ pending |
| 03 | 2 | DEPLOY-01 | T-02-10 (secret committed) | `render.yaml` parses; every `envVars` key bound to a real `Settings` field | unit | `uv run pytest backend/tests/test_render_blueprint.py -q` (Task 2) | ✅ created by plan | ⬜ pending |
| 04 | 3 | MCP-01 | T-02-06 | `/mcp` routed with session manager running; `/health`/`/docs`/`/openapi.json` unshadowed; wrong `Host` → 421 | integration | `uv run pytest backend/tests/test_mcp_mount.py -q` (Task 1) | ✅ created by plan | ⬜ pending |
| 04 | 3 | MCP-04 | — | Full local auth matrix incl. RFC 9728 metadata path against the live app | integration | `uv run pytest backend/tests/test_mcp_auth.py -q` (Task 2) | ✅ created by plan | ⬜ pending |
| 04 | 3 | D-08 | T-02-09 (traceback disclosure) | `fitness_ping` DB round-trip; unreachable DB degrades to `database: "error"`, never 500, never leaks a DSN | integration | `uv run pytest backend/tests/test_mcp_tools.py -q` (Task 3) | ✅ created by plan | ⬜ pending |
| 05 | 4 | DEPLOY-01 | — | Service live over HTTPS on Render free tier, `/health` → 200 | manual | Auth Verification Matrix row 6 (RESEARCH.md) against the deployed URL | manual-only | ⬜ pending |
| 05 | 4 | MCP-01, MCP-04 | A3, A5 (Host-forwarding, external DB URL) | Deployed matrix rows 1-7 pass; D-01 CLI proof via `claude mcp add` | manual + integration | `02-DEPLOY-LOG.md` entries verified by grep (Tasks 3-4) | manual-only | ⬜ pending |
| 06 | 5 | MCP-04, DEPLOY-02 | A1, A2 (WorkOS discovery) | WorkOS checkpoint resolves `jwks_uri`/issuer from discovery; `AuthKitJWTVerifier` validates real RSA-signed tokens | manual + unit | `curl .../.well-known/oauth-authorization-server` (Task 1); `uv run pytest backend/tests/test_mcp_auth.py -q` (Tasks 2-3) | ✅ created by plan | ⬜ pending |
| 07 | 6 | DEPLOY-02, MCP-04, DEPLOY-01 | A4 (personal-account OAuth) | Starter upgrade; `authkit` cutover; connector discovers and calls `fitness_ping` from Desktop/Web/Mobile; decision recorded in PROJECT.md | manual | Add custom connector in Claude → authenticate → invoke the tool (Task 3); PROJECT.md Key Decisions updated (Task 4) | manual-only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

No separate Wave 0 plan — existing infrastructure and inline `tdd="true"` tasks cover all phase requirements:

- [x] `backend/tests/test_mcp_mount.py` — created by Plan 02 Task 3, covers MCP-01 (mount routing, host-rejection, no route shadowing)
- [x] `backend/tests/test_mcp_auth.py` — created by Plan 02 Task 2, covers MCP-04 (401/200 matrix, metadata path, leak check)
- [x] `backend/tests/test_mcp_tools.py` — created by Plan 04 Task 3, covers D-08 (DB round-trip, clean degradation)
- [x] `backend/tests/test_render_blueprint.py` — created by Plan 03 Task 2, covers DEPLOY-01 (static `render.yaml` assertions)
- [x] `backend/tests/conftest.py` — extended by Plan 01 Task 3 so `MCP_ALLOWED_HOSTS` includes `testserver` and `MCP_AUTH_SECRET` is set in the session-scoped autouse fixture before `app.main` is imported
- [x] Framework install: none needed — pytest, pytest-asyncio, testcontainers, time-machine already in the dev group
- [ ] Docker daemon must be running before any `-m integration` run (currently down per RESEARCH.md environment note — an execution-time precondition, not a planning gap)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Service reachable and healthy on the deployed Render URL | DEPLOY-01 | Requires an actual deploy — no local proxy for Render's network/TLS layer | `curl -s https://<render-url>/health` → expect `{"status":"ok","database":"connected"}`; see RESEARCH.md Auth Verification Matrix row 6 |
| Claude custom connector discovers and calls `fitness_ping` from Desktop/Web/Mobile | DEPLOY-02, MCP-04 (client-side leg) | Requires the actual Claude connector UI and a real OAuth consent flow on a personal account — this is the phase's central unknown (RESEARCH.md assumption A4) and has no automatable substitute | In Claude: Settings → Connectors → Add custom connector → enter deployed `/mcp` URL → authenticate via WorkOS → enable in a conversation → invoke `fitness_ping` → confirm a real result (not an error) is returned |
| Claude Code CLI proves the pipeline via header auth (D-01) before connector auth is attempted | MCP-04 (pipeline proof) | Exercises deploy + mount + auth-check end-to-end through a real client, but is a CLI client not Desktop/Web/Mobile, so it de-risks without satisfying DEPLOY-02 itself | `claude mcp add brett --transport http --header "Authorization: Bearer $TOKEN" https://<render-url>/mcp`, then call `fitness_ping` from a Claude Code session |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or manual-only justification (plan-checker confirmed via `gsd-tools verify plan-structure`: all 7 plans `valid: true`)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (no separate Wave 0 plan needed — see above)
- [x] No watch-mode flags
- [ ] Feedback latency < 30s per task — **known deviation**: Plans 02, 04, 06 chain a full `uv run pytest -q` (~90s, Docker-backed) at the end of some task-level verifies rather than reserving it for wave-boundary sampling. Flagged non-blocking by plan-checker; acceptable for this phase's small file count.
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-24 (plan-checker: 1 blocker resolved via this doc + RESEARCH.md sync, 3 non-blocking warnings — see 02-CONTEXT.md and checker output for warning #4 follow-up in Plan 07 Task 4)

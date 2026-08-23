---
phase: 02
slug: deploy-connector-auth-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-xx | 01 | 0 | MCP-01 | — | Wave 0 test stubs created | scaffold | `test -f backend/tests/test_mcp_mount.py` | ❌ W0 | ⬜ pending |
| 02-01-xx | 01 | 1 | MCP-01 | — | `/mcp` is routed and the session manager is running | integration | `uv run pytest backend/tests/test_mcp_mount.py::test_mcp_endpoint_is_routed -x` | ❌ W0 | ⬜ pending |
| 02-01-xx | 01 | 1 | MCP-01 | — | Mounting does not shadow `/health`, `/docs`, `/openapi.json` | unit | `uv run pytest backend/tests/test_mcp_mount.py::test_fastapi_routes_still_win -x` | ❌ W0 | ⬜ pending |
| 02-01-xx | 01 | 1 | MCP-01 | T-02-06 (unauth bypass) | Wrong `Host` header → 421 (transport security active) | integration | `uv run pytest backend/tests/test_mcp_mount.py::test_rejects_disallowed_host -x` | ❌ W0 | ⬜ pending |
| 02-02-xx | 02 | 1 | MCP-04 | T-02-06 | No `Authorization` header → 401 with `resource_metadata=` in `WWW-Authenticate` | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_rejects_unauthenticated -x` | ❌ W0 | ⬜ pending |
| 02-02-xx | 02 | 1 | MCP-04 | T-02-05 (timing attack) | Wrong bearer → 401, constant-time comparison | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_rejects_bad_token -x` | ❌ W0 | ⬜ pending |
| 02-02-xx | 02 | 1 | MCP-04 | — | Correct bearer → 200 + `fitness_ping` in `tools/list` | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_accepts_valid_bearer -x` | ❌ W0 | ⬜ pending |
| 02-02-xx | 02 | 1 | MCP-04 | T-02-04 (log/response leakage) | 401 response body leaks no secret (FOUND-05 continuity) | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_401_leaks_nothing -x` | ❌ W0 | ⬜ pending |
| 02-02-xx | 02 | 1 | MCP-04 | — | RFC 9728 metadata served at the path Claude probes; `resource` matches config | integration | `uv run pytest backend/tests/test_mcp_auth.py::test_protected_resource_metadata_path -x` | ❌ W0 | ⬜ pending |
| 02-03-xx | 03 | 1 | D-08 | — | `fitness_ping` performs a real DB round-trip via the lifespan context | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_ping_hits_database -x` | ❌ W0 | ⬜ pending |
| 02-03-xx | 03 | 1 | D-08 | T-02-09 (traceback disclosure) | Unreachable DB degrades to `database: "error"`, never 500, never leaks a DSN | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_ping_degrades_cleanly -x` | ❌ W0 | ⬜ pending |
| 02-04-xx | 04 | 2 | DEPLOY-01 | T-02-10 (secret committed) | `render.yaml` parses; every referenced env var exists in `Settings` | unit | `uv run pytest backend/tests/test_render_blueprint.py -x` | ❌ W0 | ⬜ pending |
| 02-04-xx | 04 | 2 | DEPLOY-01 | — | Service live over HTTPS, `/health` → 200 | manual | Auth Verification Matrix row 6 (RESEARCH.md) against the deployed URL | manual-only | ⬜ pending |
| 02-05-xx | 05 | 3 | DEPLOY-02 | A4 (personal-account OAuth, open question) | Connector discovers and calls `fitness_ping` from Desktop/Web/Mobile | manual | Add custom connector in Claude → authenticate → invoke the tool | manual-only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_mcp_mount.py` — covers MCP-01 (mount routing, host-rejection, no route shadowing)
- [ ] `backend/tests/test_mcp_auth.py` — covers MCP-04 (401/200 matrix, metadata path, leak check)
- [ ] `backend/tests/test_mcp_tools.py` — covers D-08 (DB round-trip, clean degradation)
- [ ] `backend/tests/test_render_blueprint.py` — covers DEPLOY-01 (static `render.yaml` assertions)
- [ ] `backend/tests/conftest.py` — extend the existing `client` fixture so `MCP_ALLOWED_HOSTS` includes `testserver` and `MCP_AUTH_SECRET` is set before `app.main` is imported
- [ ] Framework install: none needed — pytest, pytest-asyncio, testcontainers, time-machine already in the dev group
- [ ] Docker daemon must be running before any `-m integration` run (currently down per RESEARCH.md environment note)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Service reachable and healthy on the deployed Render URL | DEPLOY-01 | Requires an actual deploy — no local proxy for Render's network/TLS layer | `curl -s https://<render-url>/health` → expect `{"status":"ok","database":"connected"}`; see RESEARCH.md Auth Verification Matrix row 6 |
| Claude custom connector discovers and calls `fitness_ping` from Desktop/Web/Mobile | DEPLOY-02, MCP-04 (client-side leg) | Requires the actual Claude connector UI and a real OAuth consent flow on a personal account — this is the phase's central unknown (RESEARCH.md assumption A4) and has no automatable substitute | In Claude: Settings → Connectors → Add custom connector → enter deployed `/mcp` URL → authenticate via WorkOS → enable in a conversation → invoke `fitness_ping` → confirm a real result (not an error) is returned |
| Claude Code CLI proves the pipeline via header auth (D-01) before connector auth is attempted | MCP-04 (pipeline proof) | Exercises deploy + mount + auth-check end-to-end through a real client, but is a CLI client not Desktop/Web/Mobile, so it de-risks without satisfying DEPLOY-02 itself | `claude mcp add brett --transport http --header "Authorization: Bearer $TOKEN" https://<render-url>/mcp`, then call `fitness_ping` from a Claude Code session |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---
phase: 07
slug: production-hardening-coaching-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-01
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| **Quick run command** | `uv run pytest backend/tests -x -q -m "not integration"` |
| **Full suite command** | `uv run pytest backend/tests -q --cov=backend/app` |
| **Estimated runtime** | ~120 seconds (quick), ~5 min (full, includes testcontainers[postgres]) |

Baseline: 650 passed as of Phase 6 verification `[VERIFIED: 06-VERIFICATION.md behavioral spot-checks]`.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest backend/tests -x -q -m "not integration"` — the bucket refill tests, malformed-parameter tests, coaching-doc tool-name test, and the `test_cloud_run_deploy.py` drift guard are all container-free, so the fastest loop covers most of the phase.
- **After every plan wave:** Run `uv run pytest backend/tests -q --cov=backend/app`
- **Before `/gsd-verify-work`:** Full suite green **plus** three signed-off manual records (deploy, restore drill, rotation) **plus** the D-09 coaching UAT record.
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-XX-XX | TBD | 0 | DEPLOY-03 | — | Mock-Hevy → sync → Postgres → analytics → MCP tool returns the hand-computed answer | integration | `uv run pytest backend/tests/test_full_chain_end_to_end.py -x -m integration` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | DEPLOY-03 | — | The chain's analytics value and MCP value are the same number | integration | `uv run pytest backend/tests/test_full_chain_end_to_end.py -k same_answer -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | DEPLOY-03 | V5 | A tool call with a wrong-typed argument is rejected before the body runs | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k malformed -x` | ❌ extend existing file | ⬜ pending |
| 07-XX-XX | TBD | 0 | DEPLOY-03 | V5 | A tool call missing a required argument is rejected before the body runs | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k missing_required -x` | ❌ extend existing file | ⬜ pending |
| 07-XX-XX | TBD | — | DEPLOY-03 | — | Blueprint §42's Hevy / analytics / MCP checklists stay green | full suite | `uv run pytest backend/tests -q` | ✅ (650 passing) | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | V11 | An over-limit request receives 429 | integration | `uv run pytest backend/tests/test_rate_limit.py -k over_limit -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | V7 | The 429 body's key set is exactly `{"error"}` and leaks no token/DSN/traceback | integration | `uv run pytest backend/tests/test_rate_limit.py -k leaks_nothing -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | — | The 429 carries a `Retry-After` header | integration | `uv run pytest backend/tests/test_rate_limit.py -k retry_after -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | — | The limiter runs ahead of auth — an unauthenticated flood is 429'd, not 401'd | integration | `uv run pytest backend/tests/test_rate_limit.py -k before_auth -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | V11 | `/health` is never rate-limited | integration | `uv run pytest backend/tests/test_rate_limit.py -k health -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | V11 | `/.well-known/oauth-protected-resource/mcp` is never rate-limited | integration | `uv run pytest backend/tests/test_rate_limit.py -k discovery -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | 0 | ROADMAP-2 | — | The bucket refills at the configured rate (fake clock, no sleeping) | unit | `uv run pytest backend/tests/test_rate_limit.py -k refill -x` | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | — | ROADMAP-2 | V14 | New `RATE_LIMIT_*` settings stay in sync with `deploy/cloud-run.env.yaml` | unit | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ✅ existing guard | ⬜ pending |
| 07-XX-XX | TBD | — | ROADMAP-2 | V2 | Unauthenticated `/mcp` is still 401 with `resource_metadata=` after the limiter is added | integration | `uv run pytest backend/tests/test_mcp_auth.py -x -m integration` | ✅ regression | ⬜ pending |
| 07-XX-XX | TBD | — | ROADMAP-2 | — | The deployed revision serves 13 tools | **manual** | `curl` the live `/mcp` with a valid credential and the `test_mcp_auth.py` envelope; record in deploy record | manual-only | ⬜ pending |
| 07-XX-XX | TBD | — | ROADMAP-3 | V8 | A Neon branch from a past timestamp matches production row-for-row | **manual** | Pattern 3's `psql` digest diff | manual-only (D-02) | ⬜ pending |
| 07-XX-XX | TBD | — | ROADMAP-3 | V14 | `MCP_AUTH_SECRET` rotates without breaking the connector | **manual** | Pattern 4's five-step runbook | manual-only (D-04) | ⬜ pending |
| 07-XX-XX | TBD | 0 | COACH-01 | — | `docs/coaching-instructions.md` exists and names only real tools | unit | `uv run pytest backend/tests/test_coaching_doc.py -x` — parse the doc, assert every `fitness_*` token it mentions is in the live registry, and all 12 non-ping tools appear | ❌ Wave 0 | ⬜ pending |
| 07-XX-XX | TBD | — | COACH-01 | — | Claude answers both criterion questions from real data and flags staleness | **manual** | Pattern 5's D-09 UAT script | manual-only (D-09) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are placeholders (TBD) — the planner fills in real plan/task IDs when PLAN.md files are created; this map's requirement/behavior/command columns are locked from research and must survive into the plans unchanged.*

---

## Wave 0 Requirements

- [ ] `backend/app/middleware.py` (or `app/middleware/rate_limit.py`) — the rate limiter itself
- [ ] `backend/tests/test_rate_limit.py` — covers ROADMAP criterion #2
- [ ] `backend/tests/test_full_chain_end_to_end.py` — covers DEPLOY-03 / blueprint §43
- [ ] `backend/tests/test_coaching_doc.py` — covers the automatable half of COACH-01
- [ ] Two new `Settings` fields (`rate_limit_per_minute`, `rate_limit_burst`) + matching keys in `deploy/cloud-run.env.yaml` if overridden — read `test_cloud_run_deploy.py` first, it cross-checks both directions
- [ ] Extensions to `backend/tests/test_mcp_tool_schemas.py` — malformed / missing-required params
- No framework install needed — every tool is already pinned.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Deployed revision serves the real 13-tool set | ROADMAP-2 | Requires the live Cloud Run service | `curl` the live `/mcp` with a valid credential using the `test_mcp_auth.py` request envelope; record tool count/names in the deploy record |
| Neon branch from a past timestamp matches production row-for-row | ROADMAP-3 (D-02) | Needs live Neon API/CLI access against the real project; not scriptable into CI | `neon branches create --parent <RFC3339>`, then `psql` digest diff against production per RESEARCH.md Pattern 3; document steps + result in a runbook doc; delete the drill branch after |
| `MCP_AUTH_SECRET` rotates without breaking the live connector | ROADMAP-3 (D-04) | Requires live Cloud Run + Secret Manager + a real redeploy | Five-step runbook per RESEARCH.md Pattern 4: add new secret version → flip `MCP_AUTH_MODE=static` → redeploy → verify old token 401s / new token succeeds → flip back to `authkit` → redeploy → verify |
| Claude answers "Am I progressing?" / "Which muscles are undertrained?" from real data and flags stale/sparse data | COACH-01 (D-09) | Human-in-the-loop by nature — requires a real Claude Project with the connector attached and the coaching doc loaded as custom instructions | Ask both example questions plus one expected to surface stale/sparse data; record the transcript/result in a verification doc per RESEARCH.md Pattern 5 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

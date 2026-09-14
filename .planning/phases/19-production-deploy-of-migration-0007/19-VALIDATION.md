---
phase: 19
slug: production-deploy-of-migration-0007
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-14
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
>
> This phase has no new application code. Validation maps onto existing,
> already-passing test suites (Phase 14, Phase 17) plus operational/manual
> verification of the real production deploy and live MCP call — which by
> definition cannot be pre-covered by a local test, since that IS the point
> of DEPLOY-05 (prove by execution, not by reading).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio (existing) |
| **Config file** | `backend/pyproject.toml` / `backend/pytest.ini` (pre-existing, not modified) |
| **Quick run command** | `uv run pytest backend/tests -m "not integration" -q` |
| **Full suite command** | `uv run pytest backend/tests -q` (includes `@pytest.mark.integration`, requires Docker) |
| **Estimated runtime** | ~30-60s (fast suite); Docker-dependent for full |

---

## Sampling Rate

- **Before triggering the deploy:** Run `uv run pytest backend/tests -m "not integration" -q` — must be green (this is `docs/runbook-deploy.md` Step 2, and gates the pre-deploy checklist task).
- **After the deploy script runs:** No new pytest run — the deploy script's own log ordering (`DEPLOY-04: using Secret Manager ...` → alembic upgrade output → `at head: [...]` → gcloud deploy output) is the verification artifact, read by a human.
- **Before closing the phase:** The live MCP smoke test response must be captured and checked against the documented expected shape.
- **Max feedback latency:** N/A — this phase's tasks are runbook/checkpoint steps, not iterative code changes.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | DEPLOY-05 | T-19-01 | Fast suite green, `0007` confirmed as local alembic head before deploy trigger | automated | `uv run pytest backend/tests -m "not integration" -q` | ✅ | ⬜ pending |
| 19-01-02 | 01 | 1 | DEPLOY-05 (criteria 1+2) | T-19-01 | No credential value echoed into deploy log/transcript; log ordering proves migration applied unattended | manual (operator-run, log read) | N/A — `docs/runbook-deploy.md` Step 4-5 followed verbatim | ✅ (script + predicate already tested in Phase 14) | ⬜ pending |
| 19-01-03 | 01 | 1 | DEPLOY-05 (criterion 3) | T-19-02 | Real OAuth-authenticated call over live `/mcp` endpoint; response matches documented empty-but-valid schema, no 401/500 | manual (live client or fallback curl) | N/A — external client-to-production round trip by design | ✅ (tool logic tested in Phase 17) | ⬜ pending |
| 19-01-04 | 01 | 1 | DEPLOY-05 | — | Record deployed revision name/timestamp; no secret values in the record | automated (grep for completion) | `grep -q "DEPLOY-05" .planning/REQUIREMENTS.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*None — existing test infrastructure (Phase 14's `test_migration_preflight.py`, `test_cloud_run_deploy.py`, `test_deploy_script_preflight.py`; Phase 17's physique MCP tool tests) fully covers everything this phase's mechanism depends on. The only uncovered surface is the live production round trip itself, which cannot be pre-covered by a local test by definition.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Migration `0007` reaches production via the pre-deploy mechanism | DEPLOY-05 (criterion 1) | Requires a real `gcloud secrets versions access` + `alembic upgrade head` against the live production DB — blocked for this agent's sandbox by the "Credential Materialization" classifier (NUTR-F01 precedent); must be operator-run | Follow `docs/runbook-deploy.md` Steps 1-5 verbatim: confirm clean git status, run fast suite, run `BRETT_GCP_PROJECT=brett-fitness ./scripts/deploy-cloud-run.sh`, confirm the 4-line log ordering (source-echo → alembic upgrade output → `at head: ['0007']` → gcloud deploy output) |
| `alembic current` == `alembic heads` on production | DEPLOY-05 (criterion 2) | The check itself requires the same blocked secret-access command; already discharged automatically by the deploy script's own pre-flight (`migration_preflight.py::check_at_head`), whose stdout is the proof | Read the deploy log's `at head: ['0007']` line — this is the criterion's proof, no separate post-hoc check needed |
| Live MCP tool call succeeds against deployed schema | DEPLOY-05 (criterion 3) | Requires OAuth 2.1 JWT auth (`MCP_AUTH_MODE=authkit`) through a real Claude client, or the documented temporary static-mode fallback — inherently an external-client-to-production round trip, not unit-testable without contradicting the "real deploy" intent | Call `fitness_get_latest_physique_observation` via a live Claude connector session against `https://brett-792870654598.us-central1.run.app/mcp`; confirm response is `{"data_available": true, "observation": null, "rating_scale": <non-empty>, "disclaimer": <non-empty>}` with no 401/500/schema error |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (pre-deploy checklist) or documented manual verification (deploy trigger, smoke test)
- [x] Sampling continuity: no 3 consecutive tasks without automated or manual-documented verify
- [x] Wave 0 covers all MISSING references — N/A, none missing
- [x] No watch-mode flags
- [x] Feedback latency — N/A (runbook phase, not iterative code)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

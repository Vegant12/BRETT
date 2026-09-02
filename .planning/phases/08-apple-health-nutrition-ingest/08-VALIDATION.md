---
phase: 8
slug: apple-health-nutrition-ingest
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-02
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| **Quick run command** | `uv run pytest -m "not integration"` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~20s quick / ~90s full (testcontainers[postgres] for the `integration` marker; Docker required) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not integration"`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | HEALTH-06 | — | Activity metrics normalize to canonical units/day | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-06 | — | Route resolves to FastAPI, not the MCP catch-all mount | integration | `uv run pytest backend/tests/test_health_ingest_route.py -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-07 | V2 Authentication | No credential → 401, writes nothing, no detail | integration | `uv run pytest backend/tests/test_health_ingest_auth.py -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-07 | V2 Authentication | Wrong credential → 401, identical response shape | integration | same file | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-08 | Tampering (Finding A) | Hevy-sourced `active_energy` never lands | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k hevy -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-08 | — | Volume/frequency/body-weight identical before & after ingest | integration | `uv run pytest backend/tests/test_health_ingest_isolation.py -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-09 | — | Identical payload twice → row counts + every value unchanged | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-09 | — | Overlapping (not identical) window → still unchanged | integration | same file | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HEALTH-11 | — | `sync_state` advances for `('apple_health','activity')` | integration | `uv run pytest backend/tests/test_sync_state.py -k apple_health -x -m integration` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | HEALTH-11 | — | `build_freshness` accepts `(provider, resource)` pairs | unit | `uv run pytest backend/tests/test_analytics_metadata.py -x` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | NUTR-02 | — | All 7 nutrition names parse; `dietary_sugar`/`total_fat` spelled right | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k nutrition -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | NUTR-02 | — | `sodium` mg preserved; `kJ` → kcal converts | unit | same file | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | NUTR-03 | — | Nutrition idempotent under re-send | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -k nutrition -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | NUTR-05 | — | `sync_state` advances for `('apple_health','nutrition')` independently | integration | `uv run pytest backend/tests/test_sync_state.py -k nutrition -x -m integration` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | D-04 | V5 Input Validation | Unlisted metric dropped, rest of payload still ingested | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k unrecognized -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Finding C | — | Fractional `count` values survive (no truncation to 0) | unit | same file | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | §4.2 | V5 Input Validation | Datapoint with no `source` key validates | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Pitfall N-4 | — | Midnight-anchored point, offset ≠ user tz → intended day | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k timezone -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Pitfall N-5 | — | HAE wire schemas do not leak; no HTTP client in the package | unit | `uv run pytest backend/tests/test_health_auto_export_isolation.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Pitfall 2 | V13 API/Web Service | Ingest burst does not drain the `/mcp` rate-limit bucket | unit | `uv run pytest backend/tests/test_rate_limit.py -k ingest -x` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | Pitfall 5 | V13 API/Web Service | Oversized body → 413 before parse | integration | `uv run pytest backend/tests/test_health_ingest_route.py -k oversized -x -m integration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Runtime state | V7 Error Handling/Logging | `health_ingest_secret` redacted from logs | unit | `uv run pytest backend/tests/test_secret_redaction.py -x` | ⚠️ extend | ⬜ pending |
| TBD | TBD | TBD | Runtime state | — | Deploy script sets `--memory=1Gi` + the new secret | unit | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ⚠️ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. `Task ID`/`Plan`/`Wave` columns are filled in by the planner once plans exist.*

---

## Wave 0 Requirements

- [ ] `backend/tests/fixtures/hae_*.json` — real captured payloads (seed from the verified third-party files cited in RESEARCH.md), covering NUTR-02, HEALTH-06
- [ ] `backend/tests/test_health_auto_export_schema.py` — wire-model shape, optional `source`
- [ ] `backend/tests/test_health_auto_export_normalize.py` — registry, units, dates, Hevy filter, D-04
- [ ] `backend/tests/test_health_auto_export_isolation.py` — provider-isolation guard (Pitfall N-5), mirrors `test_hevy_isolation.py`
- [ ] `backend/tests/test_health_ingest_route.py` — mount-order + size cap
- [ ] `backend/tests/test_health_ingest_auth.py` — HEALTH-07 negatives
- [ ] `backend/tests/test_health_ingest_idempotency.py` — HEALTH-09 / NUTR-03
- [ ] `backend/tests/test_health_ingest_isolation.py` — success criterion #4 (Hevy data unaffected)
- [ ] No framework install needed — pytest, testcontainers, time-machine all already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| A real Health Auto Export run from the user's phone lands steps, energy, distance, flights, calories + 6 macros in BRETT | Success criterion #1 | Requires the user's live iPhone, live HAE automation, and the live deployment — not reproducible in CI | Trigger a manual HAE export against the deployed `/api/v1/ingest/health-auto-export` endpoint; query `health_daily_metrics` for that day and confirm all expected metrics are present with plausible values |
| HAE aggregation interval is set to daily on-device (Pitfall N-2 deploy prerequisite) | HEALTH-09 / NUTR-03 (device-side precondition) | Lives entirely in iPhone Health Auto Export app settings, outside the repo and outside CI | Verify in the HAE app's automation settings; capture one payload afterward and confirm each metric has ≤1 datapoint per day |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

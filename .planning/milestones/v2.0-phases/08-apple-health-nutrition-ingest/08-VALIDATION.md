---
phase: 8
slug: apple-health-nutrition-ingest
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-02
updated: 2026-09-02
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
>
> **Updated 2026-09-02 by the planner.** The `Task ID` / `Plan` / `Wave` columns are now filled in
> against the eight plans in this directory. Rows below the original researcher-supplied set were
> added by the planner where a plan introduced a behaviour worth sampling that the research map
> did not enumerate; they are marked *(planner)*.

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

Every task in every Phase 8 plan carries an `<automated>` verify command. No plan has three
consecutive tasks without one, and no task depends on a test file that a later wave creates.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-05-T1/T2 | 08-05 | 3 | HEALTH-06 | — | Activity metrics normalize to canonical units/day | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | created by 08-05-T1 | ⬜ pending |
| 08-07-T2 | 08-07 | 5 | HEALTH-06 | T-08-43 | Route resolves to FastAPI, not the MCP catch-all mount | integration | `uv run pytest backend/tests/test_health_ingest_route.py -x -m integration` | created by 08-07-T2 | ⬜ pending |
| 08-07-T2 | 08-07 | 5 | HEALTH-07 | T-08-42, T-08-44 | No credential → 401, writes nothing, no detail | integration | `uv run pytest backend/tests/test_health_ingest_auth.py -x -m integration` | created by 08-04-T3, extended by 08-07-T2 | ⬜ pending |
| 08-07-T2 | 08-07 | 5 | HEALTH-07 | T-08-44 | Wrong credential → 401, byte-identical response shape | integration | same file | created by 08-04-T3, extended by 08-07-T2 | ⬜ pending |
| 08-04-T3 | 08-04 | 2 | HEALTH-07 | T-08-18, T-08-19, T-08-20 | Verifier: constant-time bytes compare, no raise on non-ASCII, fail closed on empty secret | unit | `uv run pytest backend/tests/test_health_ingest_auth.py -x -m "not integration"` | created by 08-04-T3 | ⬜ pending |
| **08-05-T3** | **08-05** | **3** | **HEALTH-08** | **T-08-27 (Finding A)** | **Hevy-sourced `active_energy` never lands** | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k hevy -x` | created by 08-05-T1 | ⬜ pending |
| 08-07-T3 | 08-07 | 5 | HEALTH-08 | T-08-50 | Volume/frequency/body-weight identical before & after ingest | integration | `uv run pytest backend/tests/test_health_ingest_isolation.py -x -m integration` | created by 08-07-T3 | ⬜ pending |
| 08-07-T3 | 08-07 | 5 | HEALTH-08 | T-08-27 | *(planner)* No `health_daily_metrics` row has `source_name='Hevy'`; the ingest wrote rows anyway | integration | `uv run pytest backend/tests/test_health_ingest_isolation.py -x -m integration` | created by 08-07-T3 | ⬜ pending |
| 08-01-T1 | 08-01 | 1 | HEALTH-08 | T-08-01, T-08-02 | *(planner)* `source_name` is inside the 5-column natural key and is NOT NULL | unit | `uv run pytest backend/tests/test_db_models.py -x -m "not integration"` | ⚠️ extend existing | ⬜ pending |
| 08-06-T2 | 08-06 | 4 | HEALTH-09 | T-08-34, T-08-35 | Identical payload twice → row counts + every value unchanged | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-06-T2 | 08-06 | 4 | HEALTH-09 | T-08-34 | Overlapping (not identical) window → still one row per key | integration | same file | created by 08-06-T2 | ⬜ pending |
| 08-01-T2 | 08-01 | 1 | HEALTH-09 | T-08-35 | *(planner)* Migration round-trips; the named unique constraint exists in the database | integration | `uv run pytest backend/tests/test_migrations.py -x` | ⚠️ extend existing | ⬜ pending |
| 08-06-T3 | 08-06 | 4 | HEALTH-11 | T-08-36 | `sync_state` advances for `('apple_health','activity')` after a real ingest | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-02-T3 | 08-02 | 1 | HEALTH-11 | T-08-09 | `sync_state` rows for `apple_health` are independent of Hevy's three | integration | `uv run pytest backend/tests/test_sync_state.py -k apple_health -x` | ⚠️ extend existing | ⬜ pending |
| 08-02-T2/T3 | 08-02 | 1 | HEALTH-11 | T-08-06, T-08-07 | `build_freshness` takes `(provider, resource)` pairs and has no provider default | unit | `uv run pytest backend/tests/test_analytics_metadata.py -x` | ⚠️ extend existing | ⬜ pending |
| 08-06-T3 | 08-06 | 4 | HEALTH-11 | T-08-06 | *(planner)* ROADMAP #5 — one `build_freshness` call reports Apple Health separately from Hevy | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-04-T1 | 08-04 | 2 | NUTR-02 | T-08-23 | All 7 nutrition names present; `dietary_sugar`/`total_fat` spelled right, no spurious `dietary_` prefix | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -x` | created by 08-04-T1 | ⬜ pending |
| 08-04-T1 | 08-04 | 2 | NUTR-02 | T-08-22 | `sodium` mg preserved; `kJ` → kcal converts; unknown unit rejects the datapoint | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -k unit_conversion -x` | created by 08-04-T1 | ⬜ pending |
| 08-05-T2 | 08-05 | 3 | NUTR-02 | — | Nutrition metrics normalize end to end from a real fixture | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k nutrition -x` | created by 08-05-T1 | ⬜ pending |
| 08-06-T2 | 08-06 | 4 | NUTR-03 | T-08-34 | Nutrition idempotent under re-send | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -k nutrition -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-06-T3 | 08-06 | 4 | NUTR-05 | T-08-37 | `('apple_health','nutrition')` advances independently, and NOT on an activity-only payload | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-05-T1 | 08-05 | 3 | D-04 | T-08-29 | Unlisted metric dropped, rest of payload still ingested, one log line per metric | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k unrecognized -x` | created by 08-05-T1 | ⬜ pending |
| 08-04-T2 | 08-04 | 2 | D-04 | T-08-24 | *(planner)* A `qty`-less, heart-rate-shaped metric does not fail whole-payload validation | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -x` | created by 08-04-T1 | ⬜ pending |
| 08-05-T2 | 08-05 | 3 | Finding C | T-08-31, T-08-03 | Fractional `count` values survive (no truncation to 0) | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | created by 08-05-T1 | ⬜ pending |
| 08-04-T2 | 08-04 | 2 | §4.2 | T-08-24 | Datapoint with no `source` key validates | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -x` | created by 08-04-T1 | ⬜ pending |
| 08-05-T2 | 08-05 | 3 | Finding D | T-08-01 | *(planner)* Two sources on one day for one metric produce two rows, not one | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | created by 08-05-T1 | ⬜ pending |
| 08-05-T2 | 08-05 | 3 | Pitfall N-2 | T-08-32 | *(planner)* `health_ingest_multi_point_day` fires once per multi-point key, carrying no value | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k multi_point -x` | created by 08-05-T1 | ⬜ pending |
| 08-05-T3 | 08-05 | 3 | Pitfall N-4 | T-08-33 | Midnight-anchored point, offset ≠ user tz → intended day, documented by the test | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k timezone -x` | created by 08-05-T1 | ⬜ pending |
| 08-04-T3 | 08-04 | 2 | Pitfall N-5 | T-08-25, T-08-26 | HAE wire schemas do not leak; no HTTP client and no MCP import inside the package | unit | `uv run pytest backend/tests/test_health_auto_export_isolation.py -x` | created by 08-04-T3 | ⬜ pending |
| 08-03-T2 | 08-03 | 1 | Pitfall 2 | T-08-11, T-08-12 | Ingest burst does not drain the `/mcp` rate-limit bucket; the prefix is not exempt | unit | `uv run pytest backend/tests/test_rate_limit.py -k ingest -x` | ⚠️ extend existing | ⬜ pending |
| 08-07-T2 | 08-07 | 5 | Pitfall 5 | T-08-45 | Oversized body → 413 before parse (the parse is never reached) | integration | `uv run pytest backend/tests/test_health_ingest_route.py -k oversized -x -m integration` | created by 08-07-T2 | ⬜ pending |
| 08-07-T2 | 08-07 | 5 | Pitfall 3 | T-08-42 | *(planner)* FastAPI route inventory drift guard — no new unauthenticated route | integration | `uv run pytest backend/tests/test_health_ingest_route.py -x -m integration` | created by 08-07-T2 | ⬜ pending |
| 08-03-T1 | 08-03 | 1 | Runtime state | T-08-14 | `health_ingest_secret` redacted from logs | unit | `uv run pytest backend/tests/test_secret_redaction.py -x` | ⚠️ extend existing | ⬜ pending |
| 08-03-T3 | 08-03 | 1 | Runtime state | T-08-13, T-08-15 | Deploy script sets `--memory=1Gi` and binds the new secret only via `--set-secrets` | unit | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ⚠️ extend existing | ⬜ pending |
| 08-05-T3 | 08-05 | 3 | FOUND-05 | T-08-30 | *(planner)* No log line emitted during normalization contains a `qty` from the fixtures | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | created by 08-05-T1 | ⬜ pending |
| 08-06-T3 | 08-06 | 4 | FOUND-05 | T-08-39 | *(planner)* No log line emitted during ingest contains a stored value | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | created by 08-06-T2 | ⬜ pending |
| 08-08-T1 | 08-08 | 6 | HEALTH-06 | T-08-56 | *(planner)* The setup doc names every allowlisted metric and states Daily aggregation | unit | inline `uv run python` assertion in the task's verify block | created by 08-08-T1 | ⬜ pending |
| 08-08-T2 | 08-08 | 6 | HEALTH-07 | T-08-58 | *(planner)* Live endpoint: 401 on missing and wrong credential; `/.well-known/...` still 200 | live smoke | `curl` assertions in the task's verify block | n/a (live) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky.*

---

## Wave 0 Requirements

Wave 0 is discharged by **plan 08-01 (wave 1)** and **plan 08-04 (wave 2)**. Nothing in a later
wave writes production code against a test file that does not yet exist: every code-producing task
in every plan carries `tdd="true"` with a `<behavior>` block and creates or extends its own test
file within the same task.

- [ ] `backend/tests/fixtures/hae/{activity_and_nutrition,hevy_active_energy,unrecognized_and_sourceless}.json` — **plan 08-01, task 3** (transcribed from the five real captured device payloads cited in RESEARCH.md); covers NUTR-02, HEALTH-06, HEALTH-08
- [ ] `backend/tests/conftest.py` — `hae_fixture()` loader + `health_daily_metrics` purge registration — **plan 08-01, task 3** (the dependency that puts 08-04 in wave 2)
- [ ] `backend/tests/test_health_auto_export_schema.py` — registry drift guard, wire-model shape, optional `source`, unit conversion — **plan 08-04, tasks 1 and 2**
- [ ] `backend/tests/test_health_auto_export_isolation.py` — the Pitfall N-5 guard — **plan 08-04, task 3**
- [ ] `backend/tests/test_health_ingest_auth.py` — verifier unit half — **plan 08-04, task 3**; HTTP half appended by **plan 08-07, task 2**
- [ ] `backend/tests/test_health_auto_export_normalize.py` — registry gate, units, dates, Hevy filter, D-04, aggregation, timezone, log safety — **plan 08-05, tasks 1-3**
- [ ] `backend/tests/test_health_ingest_idempotency.py` — HEALTH-09 / NUTR-03 / HEALTH-11 / NUTR-05 — **plan 08-06, tasks 2 and 3**
- [ ] `backend/tests/test_health_ingest_route.py` — mount order, size cap, route-inventory guard — **plan 08-07, task 2**
- [ ] `backend/tests/test_health_ingest_isolation.py` — ROADMAP criterion #4 — **plan 08-07, task 3**
- [ ] `backend/tests/fixtures/hae/device_capture.json` — the real, value-scrubbed capture that closes Assumption A1 — **plan 08-08, task 3** (checkpoint)
- [x] No framework install needed — pytest, testcontainers, time-machine all already present

---

## Manual-Only Verifications

| Behavior | Plan / Task | Requirement | Why Manual | Test Instructions |
|----------|-------------|-------------|------------|--------------------|
| A real Health Auto Export run from the user's phone lands steps, energy, distance, flights, calories + 6 macros in BRETT | **08-08, task 3** (`checkpoint:human-verify`) | Success criterion #1 | Requires the user's live iPhone, live HAE automation, and the live deployment — not reproducible in CI | Follow `docs/health-auto-export-setup.md`; trigger a manual export whose window includes a training day; then query `health_daily_metrics` for those days and confirm all 12 metrics with plausible values and sodium in `mg` |
| HAE aggregation interval is set to Daily on-device (Pitfall N-2 deploy prerequisite) | **08-08, task 3** | HEALTH-09 / NUTR-03 (device-side precondition) | Lives entirely in iPhone Health Auto Export app settings, outside the repo and outside CI | Verify in the app's automation settings, then confirm `health_ingest_multi_point_day` does NOT appear in the Cloud Run logs for the delivery — the machine-checkable proxy for the setting |
| Assumption A1 — the exact `source` string HAE sends for Hevy-originated data | **08-08, task 3** | HEALTH-08 | Only this user's phone has Hevy installed; no third-party capture can settle it | Confirm `health_ingest_hevy_source_excluded` fires on a training day. If it does not, read `SELECT DISTINCT source_name FROM health_daily_metrics WHERE metric='active_energy'`, add the observed spelling to `_HEVY_SOURCE_ALIASES`, and re-verify |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (discharged by plans 08-01 and 08-04)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner, 2026-09-02. `wave_0_complete` flips to `true` once plan 08-01 and plan
08-04 have executed and their test files exist on disk.

---
phase: 09
slug: historical-apple-health-backfill
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-03
---

# Phase 09 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`, `pythonpath = ["backend"]` |
| **Quick run command** | `uv run pytest -m 'not integration' -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~10s quick / ~60s full (testcontainers Postgres) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m 'not integration' -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green, **plus** one `--dry-run` against the
  real `export.xml`, whose printed summary is compared against RESEARCH.md's measured figures
  (8,077 rows; 209 Hevy exclusions; 224 workouts / 79 body-mass skipped; 2022-03-10 → 2026-08-26).
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 0 | HEALTH-10 | V5 | Wave 0 fixture + test file scaffolding exist | unit | `pytest backend/tests/test_health_auto_export_backfill.py -x --collect-only` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | HEALTH-10 | V5 | Every `METRIC_REGISTRY` key reachable from exactly one HealthKit identifier, and vice versa | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_mapping_is_total -x` | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 1 | HEALTH-10 | V5 | 5 naming traps map correctly (DietaryFatTotal→total_fat, DietaryProtein→protein, DietarySugar→dietary_sugar, DietaryEnergyConsumed→dietary_energy, DistanceWalkingRunning→walking_running_distance) | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_naming_traps -x` | ❌ W0 | ⬜ pending |
| 09-02-03 | 02 | 1 | HEALTH-10 / SC#4 | V4 | `Workout`, `WorkoutStatistics`, `ActivitySummary`, `BodyMass` elements never produce a row | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_non_record_elements_never_ingested -x` | ❌ W0 | ⬜ pending |
| 09-02-04 | 02 | 1 | HEALTH-10 / SC#4 | V4 | `sourceName="Hevy"` `ActiveEnergyBurned` is excluded and counted | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_hevy_active_energy_excluded -x` | ❌ W0 | ⬜ pending |
| 09-03-01 | 03 | 1 | SC#3 | V4 | Backfill `source_name` matches the live webhook's `source` for the same device (Pitfall 2 pin) | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_source_name_matches_device_capture -x` | ❌ W0 | ⬜ pending |
| 09-03-02 | 03 | 2 | SC#3 | Tampering | Backfill then webhook on the same day → exactly one row; value replaced not summed | integration | `uv run pytest -m integration backend/tests/test_backfill_idempotency.py -x` | ❌ W0 | ⬜ pending |
| 09-04-01 | 04 | 2 | SC#1 | — | Real 191 MB file parses within memory ceiling | integration (opt-in, `realfile` marker) | `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -x` | ❌ W0 | ⬜ pending |
| 09-04-02 | 04 | 1 | D-03 | — | `--dry-run` writes zero rows and still prints the full summary | unit + integration | `pytest backend/tests/test_health_auto_export_backfill.py::test_dry_run_writes_nothing -x` | ❌ W0 | ⬜ pending |
| 09-04-03 | 04 | 1 | D-07 | Tampering | A malformed `Record` is skipped, the run completes, the counter increments | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_malformed_record_does_not_abort -x` | ❌ W0 | ⬜ pending |
| 09-05-01 | 05 | 2 | CLAUDE.md | — | `cli.py` still does not import `registry`/`schemas` (provider isolation) | unit (existing) | `pytest backend/tests/test_health_auto_export_isolation.py -x` | ✅ exists | ⬜ pending |
| 09-05-02 | 05 | 2 | CLAUDE.md | — | `configure_logging` still precedes every log/engine call in `cli.py` | unit (existing) | `pytest backend/tests/test_cli.py::test_configure_logging_precedes_every_log_call -x` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_health_auto_export_backfill.py` — unit coverage for the mapping, the
      element filter, the Hevy exclusion, dry-run, and D-07 (HEALTH-10, SC#3, SC#4)
- [ ] `backend/tests/fixtures/hae/export_sample.xml` — a small synthetic Apple Health XML fixture.
      **Must include** the DOCTYPE, a `<Workout>` with a nested `<WorkoutStatistics
      type="HKQuantityTypeIdentifierActiveEnergyBurned">` (Pitfall 3), a Hevy-sourced
      `ActiveEnergyBurned` `Record`, a `BodyMass` `Record`, both U+2019 device names, and an
      unrecognized type. **Synthetic quantities only** — the real file is gitignored health data
      and no real measured value may be committed (Phase 8 fixture precedent).
- [ ] `backend/tests/test_backfill_idempotency.py` — integration, marked `integration`; the
      backfill-then-webhook-same-day case that proves SC#3
- [ ] `backend/tests/test_backfill_real_export.py` — opt-in, skipped unless `export.xml` is
      present; asserts SC#1 against the actual file. Needs a new `realfile` marker registered in
      `pyproject.toml`, since the file is gitignored and CI will not have it.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full real-file `--dry-run` summary matches RESEARCH.md's measured figures | SC#1, SC#4 | Requires the actual gitignored `export.xml` and the production-shaped counters; not something CI can assert without the file | Run `DATABASE_URL=<prod> uv run python -m app.cli backfill-apple-health export.xml --dry-run` locally; compare printed summary to RESEARCH.md's 8,077 rows / 209 Hevy exclusions / 224 workouts skipped / 79 body-mass skipped / 2022-03-10 → 2026-08-26 range |
| Real backfill run against production Neon completes and data is queryable | SC#1, SC#2 | One-time production write; not repeatable in CI | Run the real (non-dry-run) command once against production `DATABASE_URL`; spot-check `health_daily_metrics` row count and date range via `psql` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

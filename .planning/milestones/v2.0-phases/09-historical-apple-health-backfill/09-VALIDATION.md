---
phase: 09
slug: historical-apple-health-backfill
status: planned
nyquist_compliant: true
wave_0_complete: false  # closed by plan 09-01 (fixture, loader, marker) at execution time
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

> Rewritten 2026-09-03 to match the seven plans actually produced by `/gsd-plan-phase 9`.
> Task IDs are `{phase}-{plan}-{task}`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | HEALTH-10 | T-09-01/02/03 | Synthetic XML fixture carries every element shape, zero real quantities, zero `<!ENTITY>`, U+2019 device names | unit (structural) | `uv run python -c "..."` element-count assertion in the plan; then `pytest backend/tests/test_health_auto_export_backfill.py -q` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | HEALTH-10 | T-09-04 | `hae_xml_fixture` loader + `realfile` marker + six fixture-integrity tests | unit | `uv run pytest backend/tests/test_health_auto_export_backfill.py -q` | ❌ W0 | ⬜ pending |
| 09-01-03 | 01 | 1 | SC#3 | — | `normalize.py`'s stale Pitfall N-3 claim corrected; `_HEVY_SOURCE_ALIASES` unchanged | unit (existing) | `uv run pytest backend/tests/test_health_auto_export_normalize.py -q` | ✅ exists | ⬜ pending |
| 09-02-01 | 02 | 2 | HEALTH-10 | T-09-08 | Mapping is total both ways; five naming traps pinned; body mass unmapped; detail-free file error | unit | `uv run pytest backend/tests/test_health_auto_export_backfill.py::test_mapping_is_total backend/tests/test_health_auto_export_backfill.py::test_naming_traps -q` | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 2 | HEALTH-10 / SC#4 | T-09-05/06/07 | Tag-first filter (Pitfall 3), Hevy exclusion counted, malformed record skipped not fatal, accounting identity, source-name pin, multi-point suppression | unit | `uv run pytest backend/tests/test_health_auto_export_backfill.py -q` | ❌ W0 | ⬜ pending |
| 09-03-01 | 03 | 3 | HEALTH-10 | T-09-11/12/13/14/15/16 | `user_id` keyword-only; single transaction; replace semantics by constraint name; dry-run gate before any write; summary carries no quantity | unit + lint | `uv run pytest -m 'not integration' -q && uv run mypy backend/app` | ❌ W0 | ⬜ pending |
| 09-03-02 | 03 | 3 | SC#3 / D-03 / D-07 | Tampering | Backfill↔webhook same day → exactly one row; dry run writes nothing; both resources advance to one instant; one bad row skipped | integration | `uv run pytest -m integration backend/tests/test_backfill_idempotency.py -q` | ❌ W0 | ⬜ pending |
| 09-04-01 | 04 | 4 | HEALTH-10 / D-01 / D-02 / D-03 | T-09-17/18/19/20/21 | Required `--dry-run`/`--write` group; bootstrap order preserved; no `str(exc)`; no HAE wire import in `cli.py` | unit (existing + source guard) | `uv run pytest backend/tests/test_cli.py backend/tests/test_health_auto_export_isolation.py -q` | ✅ partly exists | ⬜ pending |
| 09-04-02 | 04 | 4 | D-03 | T-09-19/20 | Missing or doubled mode flag exits 2; positional path has no default | unit | `uv run pytest backend/tests/test_cli.py -q` | ❌ W0 | ⬜ pending |
| 09-05-01 | 05 | 3 | SC#1 / SC#2 / SC#4 | T-09-22/23/24 | Real 191 MB file streams under the memory and wall-clock ceilings; eleven measured figures pinned; deselected from the default suite | integration (opt-in, `realfile`) | `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` | ❌ W0 | ⬜ pending |
| 09-05-02 | 05 | 3 | RESEARCH OQ2 | T-09-25 | `sample_count` false-positive documented; four backfill events listed | doc assertion | `uv run python -c "assert '### After the historical backfill' in open('docs/health-auto-export-setup.md',encoding='utf-8').read()"` | ✅ exists | ⬜ pending |
| 09-06-01 | 06 | 5 | HEALTH-10 / D-01..D-07 | T-09-26/30 | §10 runbook: pre-flight `alembic current` vs `heads`, both invocations, expected figures, four verification queries; no real credential | doc assertion | `uv run python -c "..."` §10 content check + `uv run pre-commit run --files docs/health-auto-export-setup.md` | ✅ exists | ⬜ pending |
| 09-06-02 | 06 | 5 | SC#1 / D-03 / A2 | T-09-27/28/29 | Dry run executed against the real file and the local DB; summary compared figure by figure; overlap answered | manual + opt-in test | `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` | ❌ W0 | ⬜ pending |
| 09-07-01 | 07 | 6 | SC#1..SC#4 | T-09-31..36 | Production import; four verification queries; credential never leaves the operator's shell | MANUAL (see below) | mechanical equivalents: `uv run pytest -m integration backend/tests/test_backfill_idempotency.py -q` and `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` | ✅/❌ | ⬜ pending |
| 09-07-02 | 07 | 6 | SC#1..SC#4 | T-09-31/35 | Dated production record + STATE.md closure of A2/A3 and the two accepted divergences | doc assertion + full suite | `uv run pytest -q && uv run pre-commit run --files docs/health-auto-export-setup.md .planning/STATE.md` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** no three consecutive tasks lack an `<automated>` command. The only task
without one is `09-07-01`, which is bracketed on both sides by tasks that do have one, and whose
mechanical equivalents (`test_backfill_idempotency.py`, `test_backfill_real_export.py`) already run
in CI-able form.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full real-file `--dry-run` summary matches RESEARCH.md's measured figures | SC#1, SC#4 | Requires the actual gitignored `export.xml` and the production-shaped counters; not something CI can assert without the file | Run `DATABASE_URL=<prod> uv run python -m app.cli backfill-apple-health export.xml --dry-run` locally; compare printed summary to RESEARCH.md's 8,077 rows / 209 Hevy exclusions / 224 workouts skipped / 79 body-mass skipped / 2022-03-10 → 2026-08-26 range |
| Real backfill run against production Neon completes and data is queryable | SC#1, SC#2 | One-time production write; not repeatable in CI | Run the real (non-dry-run) command once against production `DATABASE_URL`; spot-check `health_daily_metrics` row count and date range via `psql` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a documented manual justification
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (assigned to plans 09-01/02/03/05)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-03 by the planner

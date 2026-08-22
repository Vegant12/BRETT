---
phase: 01
slug: backend-foundation
status: assigned
nyquist_compliant: true
wave_0_complete: false  # satisfied by 01-01-T1 (framework+config) and 01-03-T3 (conftest)
created: 2026-08-23
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 + pytest-cov 7.1.0 |
| **Config file** | none — Wave 0 installs (`[tool.pytest.ini_options]` in `pyproject.toml`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest backend/tests -x -q -m "not integration"` |
| **Full suite command** | `uv run pytest backend/tests -q --cov=backend/app` |
| **Estimated runtime** | ~10 seconds quick / ~30-40 seconds full (session-scoped Postgres container, startup cost paid once) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest backend/tests -x -q -m "not integration"` (plus `ruff check` and `mypy backend/app`)
- **After every plan wave:** Run `uv run pytest backend/tests -q --cov=backend/app`
- **Before `/gsd-verify-work`:** Full suite must be green, `ruff check` clean, `mypy` clean
- **Max feedback latency:** 40 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-05-T2 | 01-05 | 4 | FOUND-01 | — | `/health` returns 200 `{status, database:"connected"}` against a live DB | integration | `pytest backend/tests/test_health.py::test_health_reports_connected -x` | ❌ W0 | ⬜ pending |
| 01-05-T2 | 01-05 | 4 | FOUND-01 | — | `/health` returns 503 `database:"error"` when the DB is unreachable | integration | `pytest backend/tests/test_health.py::test_health_reports_db_error -x` | ❌ W0 | ⬜ pending |
| 01-05-T2 | 01-05 | 4 | FOUND-01 | — | `/health` requires no auth (D-04) | unit | `pytest backend/tests/test_health.py::test_health_is_open -x` | ❌ W0 | ⬜ pending |
| 01-03-T3 | 01-03 | 3 | FOUND-02 | — | empty → `upgrade head` → `downgrade base` → `upgrade head`, no manual SQL | integration | `pytest backend/tests/test_migrations.py::test_migrations_round_trip -x` | ❌ W0 | ⬜ pending |
| 01-03-T3 | 01-03 | 3 | FOUND-02 | — | seed migration creates exactly one user with `Asia/Jakarta` (D-01/D-02) | integration | `pytest backend/tests/test_migrations.py::test_default_user_seeded -x` | ❌ W0 | ⬜ pending |
| 01-03-T3 | 01-03 | 3 | FOUND-02 | — | `alembic revision --autogenerate` against head produces an empty diff | integration | `pytest backend/tests/test_migrations.py::test_no_pending_model_drift -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-03 | — | 23:30Z and 17:00Z bucket to the correct Jakarta local day | unit | `pytest backend/tests/test_time.py::test_local_day_uses_user_timezone -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-03 | — | tz read from `users.timezone`, not a constant | integration | `pytest backend/tests/test_time.py::test_timezone_is_configurable -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-03 | — | Python helper and SQL `AT TIME ZONE` agree | integration | `pytest backend/tests/test_time.py::test_python_and_sql_bucketing_agree -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-03 | — | week bucketing stable under a frozen clock | unit | `pytest backend/tests/test_time.py::test_week_start_with_frozen_clock -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-04 | — | every timestamp column is `timestamp with time zone` | integration | `pytest backend/tests/test_time.py::test_timestamps_are_timestamptz -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-04 | — | round-trip returns an aware datetime with zero UTC offset | integration | `pytest backend/tests/test_time.py::test_roundtrip_is_aware_utc -x` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | FOUND-04 | — | naive datetimes rejected at the helper boundary | unit | `pytest backend/tests/test_time.py::test_naive_datetime_rejected -x` | ❌ W0 | ⬜ pending |
| 01-02-T3 | 01-02 | 2 | FOUND-05 | T-security | seeded secret absent from rendered log stream (value, traceback, third-party logger) | unit | `pytest backend/tests/test_secret_redaction.py::test_secret_never_appears_in_logs_or_response -x` | ❌ W0 | ⬜ pending |
| 01-02-T3 | 01-02 | 2 | FOUND-05 | T-security | 500 body is `{error, correlation_id}` with no traceback, dev AND prod (D-05) | unit | `pytest backend/tests/test_secret_redaction.py::test_error_body_sanitized_in_all_environments -x` | ❌ W0 | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | FOUND-05 | T-security | `repr(Settings())` and `model_dump_json()` mask every secret field | unit | `pytest backend/tests/test_config.py::test_secrets_masked -x` | ❌ W0 | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | FOUND-05 | T-security | missing required env var fails fast at construction | unit | `pytest backend/tests/test_config.py::test_missing_env_fails_fast -x` | ❌ W0 | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | FOUND-05 | T-security | `.env` gitignored, no secret-looking literal committed | unit | `pytest backend/tests/test_config.py::test_env_is_gitignored -x` (+ gitleaks pre-commit) | ❌ W0 | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | FOUND-05 | T-security | `?sslmode=require` in `DATABASE_URL` normalized (asyncpg incompatibility) | unit | `pytest backend/tests/test_config.py::test_async_url_normalizes_sslmode -x` | ❌ W0 | ⬜ pending |

*Task/Plan/Wave columns assigned by the planner on 2026-08-23. Test files are created by the task that owns the behavior (test-alongside), so there is no separate Wave 0 plan; the framework install and `[tool.pytest.ini_options]` config are Plan 01-01 Task 1, and `conftest.py` is Plan 01-03 Task 3.*

---

## Wave 0 Requirements

Greenfield repo — zero existing test infrastructure. Everything below is a gap:

- [ ] `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and an `integration` marker
- [ ] `backend/tests/conftest.py` — session-scoped `testcontainers.community.postgres` fixture (`driver="asyncpg"`), `alembic upgrade head` bootstrap, `session` and `client` fixtures, `alembic()` subprocess helper
- [ ] `backend/tests/test_health.py`
- [ ] `backend/tests/test_migrations.py`
- [ ] `backend/tests/test_time.py`
- [ ] `backend/tests/test_secret_redaction.py`
- [ ] `backend/tests/test_config.py`
- [ ] Framework install: `uv add --dev pytest pytest-asyncio pytest-cov "testcontainers[postgres]" time-machine`

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification per RESEARCH.md's live-probe validation.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-assigned 2026-08-23 — every row has an `<automated>` command owned by a specific task; no 3 consecutive tasks lack automated verification.

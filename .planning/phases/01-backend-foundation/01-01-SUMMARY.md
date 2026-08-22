---
phase: 01-backend-foundation
plan: 01
subsystem: infra
tags: [uv, pydantic-settings, secretstr, ruff, mypy, pytest, pre-commit, gitleaks, docker-compose, postgres, asyncpg]

# Dependency graph
requires: []
provides:
  - "uv project at the repo root with a committed uv.lock and Python pinned to 3.13"
  - "pytest (asyncio_mode=auto, pythonpath=backend, integration marker), Ruff (E,F,I,UP,B,ASYNC,S,DTZ) and mypy configuration"
  - "pre-commit with ruff, ruff-format, gitleaks and hygiene hooks"
  - "docker-compose.yml local Postgres 18 for development"
  - "backend/app/config.py: Settings, get_settings, Settings.async_database_url, Settings.secret_values()"
  - "backend/app and backend/tests packages"
affects: [01-02-logging, 01-03-migrations, 01-04-database, 01-05-health, 02-deploy-mcp-spike, 03-hevy-integration]

# Tech tracking
tech-stack:
  added: [uv, fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic, pydantic-settings, structlog, asgi-correlation-id, tzdata, pytest, pytest-asyncio, pytest-cov, testcontainers, time-machine, ruff, mypy, pre-commit]
  patterns:
    - "Secrets are SecretStr fields on a frozen BaseSettings; nothing else in the process holds a raw secret string"
    - "hide_input_in_errors=True on the settings model so no ValidationError can echo a credential"
    - "Database URL normalization happens once, at config load, via Settings.async_database_url"
    - "Settings.secret_values() is the single source of truth for the log scrubber's deny-list"

key-files:
  created:
    - pyproject.toml
    - uv.lock
    - .python-version
    - .gitignore
    - .env.example
    - .pre-commit-config.yaml
    - docker-compose.yml
    - backend/app/__init__.py
    - backend/app/config.py
    - backend/tests/__init__.py
    - backend/tests/test_config.py
  modified: []

key-decisions:
  - "Set hide_input_in_errors=True on Settings — `raise ... from None` alone does NOT stop Pydantic leaking the password, because the echoed value comes from the error's own `input` field, not the chained exception"
  - "Added [tool.ruff.lint.isort] known-first-party = [\"app\"] because backend/ is the import root but not a top-level repo directory"
  - "get_settings() carries `# type: ignore[call-arg]` — mypy cannot know BaseSettings populates database_url from the environment"
  - "pre-commit hooks were NOT installed into .git/hooks during this parallel wave; the config is committed and validated via `pre-commit run --all-files`"

patterns-established:
  - "Three-layer FOUND-05 secret defense, layer 1: SecretStr + hide_input_in_errors + no logging of settings values"
  - "TDD for config-layer behavior: RED test commit, then GREEN implementation commit"
  - "Local dev credentials in docker-compose.yml are annotated inline as non-secret for gitleaks triage"

requirements-completed: [FOUND-05]

# Metrics
duration: 18min
completed: 2026-08-23
---

# Phase 1 Plan 01: Project Skeleton and Typed Configuration Summary

**uv-managed Python 3.13 project with locked deps, Ruff/mypy/pytest/gitleaks tooling, a local Postgres 18 compose file, and a fail-fast `Settings` module whose secrets cannot leak through `repr`, `model_dump_json`, or a Pydantic `ValidationError`.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2 of 2
- **Files created:** 11
- **Commits:** 3 (Task 1, then TDD RED + GREEN for Task 2)

## Accomplishments

- Repo skeleton stood up flat at the BRETT root per the layout constraint: `pyproject.toml`, committed `uv.lock`, `.python-version` (3.13), `backend/app/`, `backend/tests/`.
- Every version pinned in the plan resolved cleanly with **zero deviations** — `fastapi 0.141.1`, `starlette 1.6.0` (transitive), `sqlalchemy 2.0.52`, `asyncpg 0.31.0`, `alembic 1.19.1`, `pydantic 2.13.4` / `pydantic-core 2.46.4`, `pydantic-settings 2.15.0`, `structlog 26.1.0`, `asgi-correlation-id 5.0.1`, `tzdata 2026.3`, `uvicorn 0.52.4`, `greenlet 3.5.5`, `pytest 9.1.1`, `pytest-asyncio 1.4.0`, `pytest-cov 7.1.0`, `testcontainers 4.15.0`, `time-machine 3.4.0`, `ruff 0.16.4`, `mypy 2.3.1`, `pre-commit 4.6.2`. Interpreter resolved to **Python 3.13.13**.
- All three pre-commit `rev:` pins in the plan exist as written — no `autoupdate` was needed: `ruff-pre-commit v0.16.4`, `gitleaks v8.30.0`, `pre-commit-hooks v6.0.0`. Gitleaks reports **no findings** across the repo.
- `backend/app/config.py` (120 lines) delivers `Settings`, `get_settings`, `async_database_url`, and `secret_values()` — **`secret_values()` is available and stable for Plan 02's log scrubber** (returns raw secret strings plus the DB password component, deduplicated, sorted longest-first).
- 8 tests pass, `ruff check .` clean, `ruff format --check` clean, `mypy backend/app` clean.

## Task Commits

1. **Task 1: Initialize uv project, pin tooling, add secret-hygiene and local-dev files** — `4752d1e` (chore)
2. **Task 2 (RED): failing FOUND-05 config tests** — `0480f46` (test)
3. **Task 2 (GREEN): typed fail-fast Settings** — `a886abf` (feat)

No REFACTOR commit was needed — the GREEN implementation was already formatted, typed, and lint-clean.

## Files Created/Modified

- `pyproject.toml` — uv project, pinned runtime + dev deps, pytest (`asyncio_mode="auto"`, `pythonpath=["backend"]`, `integration` marker), Ruff (`E,F,I,UP,B,ASYNC,S,DTZ`), mypy (`disallow_untyped_defs`, `mypy_path="backend"`)
- `uv.lock` — reproducible resolution for Render's `uv sync --frozen`
- `.python-version` — `3.13`
- `.gitignore` — `.env` / `.env.*` excluded, `.env.example` re-included, plus caches and `.venv/`
- `.env.example` — variable **names only**, every value empty
- `.pre-commit-config.yaml` — ruff, ruff-format, gitleaks, large-file/EOF/whitespace hooks
- `docker-compose.yml` — Postgres 18 Alpine on 5432 with a named volume; the literal password is annotated inline as a local-dev-only non-secret
- `backend/app/config.py` — the settings module
- `backend/tests/test_config.py` — 8 FOUND-05 tests
- `backend/app/__init__.py`, `backend/tests/__init__.py` — package markers

## Decisions Made

**1. `hide_input_in_errors=True` is required; `from None` is not sufficient.**
The plan (and RESEARCH Pattern 6 Layer 1) specified re-raising validator errors `from None` with no input interpolation. The RED test `test_invalid_url_error_does_not_echo_input` proved this is **insufficient**: Pydantic attaches the original input to the error object itself, so `str(ValidationError)` rendered `input_value='mysql://u:pw@h/db'` — password included — even though the validator never touched the value. `hide_input_in_errors=True` on `SettingsConfigDict` closes it for every field, not just `database_url`. This is a genuine hardening of the researched pattern and should be carried into any future settings model.

**2. `known-first-party = ["app"]`.** Ruff's isort classified `app` as third-party because `backend/` (the import root, per `pythonpath`) is not a top-level repo directory. Declaring it keeps import blocks stable across every future module.

**3. pre-commit hooks not installed into `.git/hooks`.** This plan ran as a parallel worktree agent; installing hooks would mutate the shared `.git` hooks directory mid-wave and break sibling agents' commits. The config is committed and was fully exercised via `pre-commit run --all-files`. **Follow-up for a later plan or the developer: run `uv run pre-commit install` once, post-merge.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Secret leak through Pydantic `ValidationError` (threat T-01-01)**
- **Found during:** Task 2, GREEN phase
- **Issue:** The plan's verbatim `config.py` still leaked the DB password. A rejected `DATABASE_URL` produced `Value error, DATABASE_URL must be a postgresql:// URL [type=value_error, input_value='mysql://u:pw@h/db', input_type=str]`. `raise ... from None` suppresses the *chained cause*, not the error's `input` field.
- **Fix:** Added `hide_input_in_errors=True` to `SettingsConfigDict`, with an inline comment recording why `from None` is not enough.
- **Files modified:** `backend/app/config.py`
- **Verification:** `test_invalid_url_error_does_not_echo_input` fails without it and passes with it. `test_secrets_masked` also passes.
- **Committed in:** `a886abf`

**2. [Rule 3 - Blocking] Ruff isort misclassified the `app` package**
- **Found during:** Task 2, RED phase
- **Issue:** `ruff check` reported `I001` on `backend/tests/test_config.py` because it sorted `from app.config import ...` as third-party, making the plan's `uv run ruff check .` gate unpassable for any file importing `app`.
- **Fix:** Added `[tool.ruff.lint.isort] known-first-party = ["app"]` to `pyproject.toml`.
- **Files modified:** `pyproject.toml`
- **Verification:** `uv run ruff check .` exits 0.
- **Committed in:** `0480f46`

**3. [Rule 3 - Blocking] mypy `call-arg` error on `Settings()`**
- **Found during:** Task 2, GREEN phase
- **Issue:** `uv run mypy backend/app` failed with `Missing named argument "database_url" for "Settings"` — mypy cannot model environment-sourced `BaseSettings` fields. This blocked the plan's mypy gate.
- **Fix:** `return Settings()  # type: ignore[call-arg]` with an explanatory comment. `warn_unused_ignores = true` is on, so the ignore is verified as actually needed.
- **Files modified:** `backend/app/config.py`
- **Verification:** `uv run mypy backend/app` exits 0.
- **Committed in:** `a886abf`

**4. [Documented, not fixed] `uv self update` failed**
- **Found during:** Task 1, step 1
- **Issue:** `uv self update` refuses to run: the active binary is at `/Volumes/Samsung SSD 990 EVO Plus Media/.local/bin/uv` while the standalone installer targeted a different volume. Installed version remains **0.11.7**; CLAUDE.md specifies 0.12.5.
- **Why not fixed:** The plan explicitly permits recording the installed version and continuing. 0.11.7 resolved every pin with no conflicts and produced a valid `uv.lock`. Logged in `deferred-items.md`.

---

**Total deviations:** 3 auto-fixed (1 missing-critical/security, 2 blocking) + 1 documented environment issue
**Impact on plan:** No scope creep. Deviation 1 is a material security improvement over the researched pattern and closes threat T-01-01 properly rather than nominally.

## Issues Encountered

- The `end-of-file-fixer` pre-commit hook rewrites `.planning/config.json` (a pre-existing orchestrator-owned file with no trailing newline). Reverted both times rather than committing a change to a shared artifact mid-wave. Logged in `.planning/phases/01-backend-foundation/deferred-items.md`.
- The plan's `<read_first>` references `.planning/phases/01-backend-foundation/01-PATTERNS.md`, which does not exist in the repo. `01-RESEARCH.md` (the stated source of record for the config pattern) supplied everything needed, so this was not blocking.
- `mypy` emits a benign note: `unused section(s): module = ['asgi_correlation_id.*', 'testcontainers.*']`. Those overrides become live once Plans 02–05 import them; exit code is 0.

## Threat Model Coverage

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-01-01 Info disclosure via validation errors | mitigate | **Closed, and hardened beyond the plan** — `SecretStr` + `from None` + `hide_input_in_errors=True`; asserted by `test_invalid_url_error_does_not_echo_input` |
| T-01-02 Info disclosure via repr/model_dump | mitigate | Closed — asserted by `test_secrets_masked` |
| T-01-03 Info disclosure via git | mitigate | Closed — `.gitignore`, empty `.env.example`, gitleaks passing; asserted by `test_env_is_gitignored` |
| T-01-04 Dependency supply chain | mitigate | Closed — `uv.lock` committed, Ruff `S` ruleset enabled |
| T-01-05 DoS via missing config | mitigate | Closed — asserted by `test_missing_env_fails_fast` |
| T-01-06 docker-compose literal password | accept | Accepted and annotated inline as documented |

No new threat surface was introduced beyond the register.

## Known Stubs

None. Every artifact this plan claims is fully implemented and exercised by a passing test.

## Verification Results

```
uv run pytest backend/tests -q -m "not integration"   ->  8 passed
uv run ruff check .                                    ->  All checks passed!
uv run ruff format --check backend/app backend/tests   ->  2 files already formatted
uv run mypy backend/app                                ->  Success: no issues found in 2 source files
git check-ignore -q .env                               ->  exit 0
uv run pre-commit run --all-files                      ->  gitleaks Passed, no findings
uv run python -V                                       ->  Python 3.13.13
```

Test names present as required by `01-VALIDATION.md`: `test_secrets_masked`, `test_missing_env_fails_fast`, `test_env_is_gitignored`, `test_async_url_normalizes_sslmode`, plus `test_async_url_drops_channel_binding`, `test_secret_values_includes_password_longest_first`, `test_invalid_url_error_does_not_echo_input`, `test_get_settings_is_cached`.

## TDD Gate Compliance

Task 2 was `tdd="true"` and followed the full gate sequence:
- **RED:** `0480f46` `test(01-01)` — tests written first, verified failing with `ModuleNotFoundError: No module named 'app.config'`
- **GREEN:** `a886abf` `feat(01-01)` — 8/8 passing
- **REFACTOR:** not needed, no commit

## User Setup Required

None for this plan. Two optional developer conveniences, post-merge:
- `uv run pre-commit install` — activate hooks locally (deliberately skipped during the parallel wave)
- `docker compose up -d db` then copy `.env.example` to `.env` and set `DATABASE_URL=postgresql://brett:brett_local_dev@localhost:5432/brett`

## Next Phase Readiness

Ready. The contracts Plans 02–05 depend on are in place and verified:
- **Plan 02** (`app/logging.py`) can call `settings.secret_values()` — returns `list[str]`, longest-first, including the DB password component.
- **Plan 03** (`migrations/env.py`) can call `settings.async_database_url` — guaranteed `postgresql+asyncpg://` with `sslmode` translated to `ssl` and `channel_binding` dropped.
- `pythonpath = ["backend"]` means `from app.config import get_settings` resolves under pytest without any per-file path manipulation.
- **Carry forward:** the `hide_input_in_errors=True` finding. Any future Pydantic model that validates a value containing a credential needs it; `from None` alone is a false sense of security.

## Self-Check: PASSED

All 13 claimed files verified present on disk; all 3 claimed commit hashes (`4752d1e`, `0480f46`, `a886abf`) verified in `git log`.

---
*Phase: 01-backend-foundation*
*Completed: 2026-08-23*

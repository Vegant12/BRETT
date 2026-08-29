---
phase: 3
slug: hevy-integration-normalization
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-29
updated: 2026-08-29
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) + pytest-cov 7.1.0 |
| **HTTP mocking** | `pytest-httpx2` 1.0.0 (added by plan 03-01). Fallback with zero new deps: `httpx2.MockTransport` |
| **Database** | `testcontainers[postgres]` 4.15.0 → `postgres:18-alpine`, driver `asyncpg`, migrated by a real `alembic upgrade head` subprocess. **Never SQLite** — `ON CONFLICT`, `ON DELETE CASCADE`, `TIMESTAMPTZ`, `NUMERIC` and `information_schema` are exactly what this phase asserts on |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| **Quick run command** | `uv run pytest backend/tests -x -q -m "not integration"` |
| **Full suite command** | `uv run pytest backend/tests -q --cov=backend/app` (Docker daemon required) |
| **Lint / type gates** | `uv run ruff check .` and `uv run mypy backend/app` |
| **Estimated runtime** | quick ~2 s (baseline before this phase: 72 passed / 28 deselected in 0.75 s); full ~60-90 s including container startup |
| **Integration marker** | `@pytest.mark.integration` — anything touching the Postgres container |
| **Existing fixtures** | `postgres_url` (session, migrated to head), `engine`, `session`, `alembic`, `restore_schema`, `client` |
| **Added by this phase** | `hevy_fixture(name)` loader + `backend/tests/fixtures/hevy/*.json` (plan 03-01) |

**Mocking rule that will otherwise cost an hour:** `pytest-httpx2` adapts `respx`, which asserts
internally on `httpx` **0.x** `Response` objects, while the client under test is `httpx2`.
**Responses use `httpx.Response`; exceptions use `httpx2` types.** Passing `httpx2.Response(429)`
into `side_effect` fails with a bare `AssertionError: assert isinstance(resolved.response,
httpx.Response)` from inside `respx/router.py`. The rule is recorded in `conftest.py`.

**Shared-container hygiene:** the container is session-scoped and shared, and
`test_migrations.py` asserts `count(*) == 1` on `users`. Hevy sync tests **commit by design**
(per-page commit is the thing under test), so every one of them cleans up in a `finally` block
rather than rolling back.

---

## Sampling Rate

- **After every task commit:** `uv run pytest backend/tests -x -q -m "not integration"`
- **After every plan completes:** `uv run pytest backend/tests -q` (full suite, Docker required)
- **After every wave:** full suite + `uv run ruff check .` + `uv run mypy backend/app`
- **Before `/gsd-verify-work`:** full suite green, ruff clean, mypy clean
- **Max feedback latency:** 5 s for the quick suite, 120 s for the full suite

No watch-mode flags anywhere. Every command terminates.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | HEVY-08 | T-03-02 / T-03-03 | Test-only HTTP stack never ships to production | build | `uv sync --group dev && uv run python -c "import tenacity, httpx2"` | ✅ pyproject.toml | ⬜ pending |
| 3-01-02 | 01 | 1 | HEVY-08 (FOUND-05) | T-03-01 | A record keyed `api-key` is redacted | unit | `uv run pytest backend/tests/test_secret_redaction.py -x -q` | ✅ exists — extend | ⬜ pending |
| 3-01-03 | 01 | 1 | HEVY-08 | — | Fixtures mirror the live schema, not the stale blueprint | unit | `uv run pytest backend/tests/test_hevy_fixtures.py -q` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 1 | HEVY-03, HEVY-04 | T-03-04 | `user_id` NOT NULL in every unique constraint | unit | `uv run pytest backend/tests/test_db_models.py -x -q` | ✅ exists — extend | ⬜ pending |
| 3-02-02 | 02 | 1 | HEVY-03, HEVY-04 | T-03-05 | Cascade FKs and unique index exist in real DDL | integration | `uv run pytest backend/tests/test_migrations.py -q` | ✅ exists | ⬜ pending |
| 3-02-03 | 02 | 1 | HEVY-03, HEVY-04 | T-03-03 / T-03-05 | Duplicate rejected; cascade leaves siblings intact | integration | `uv run pytest backend/tests/test_hevy_schema.py -x -q` | ❌ W1 | ⬜ pending |
| 3-03-01 | 03 | 1 | NORM-01, NORM-03 | T-03-09 / T-03-10 | Unknown enum value degrades, never raises | unit | `uv run pytest backend/tests/test_normalization_taxonomy.py -q -k "canonical or classified or unknown"` | ❌ W1 | ⬜ pending |
| 3-03-02 | 03 | 1 | NORM-01, NORM-03 | T-03-07 / T-03-08 | Curated data immutable; `full_body` never fanned out | unit | `uv run pytest backend/tests/test_normalization_taxonomy.py -q -k "delt or abdominal or unmapped"` | ❌ W1 | ⬜ pending |
| 3-03-03 | 03 | 1 | NORM-01, NORM-03 | T-03-07 | Exhaustive: a new Hevy value fails the build | unit | `uv run pytest backend/tests/test_normalization_taxonomy.py -q` | ❌ W1 | ⬜ pending |
| 3-04-01 | 04 | 2 | HEVY-06, HEVY-07, HEVY-09, NORM-02 | T-03-11 / T-03-15 | No credential column; `user_id` in every constraint | unit | `uv run pytest backend/tests/test_db_models.py -x -q` | ✅ exists | ⬜ pending |
| 3-04-02 | 04 | 2 | HEVY-07, HEVY-09 | T-03-11 | `information_schema` proves zero credential columns | integration | `uv run pytest backend/tests/test_migrations.py backend/tests/test_hevy_schema.py -q` | ✅ W1 | ⬜ pending |
| 3-04-03 | 04 | 2 | HEVY-09 | T-03-12 | `last_error` stores a class name, never a payload | integration + unit | `uv run pytest backend/tests/test_sync_state.py -q` | ❌ W2 | ⬜ pending |
| 3-05-01 | 05 | 2 | HEVY-01, HEVY-02, HEVY-05..08 | T-03-16 / T-03-17 / T-03-18 | Discriminated union; no key or payload in any exception | unit | `uv run pytest backend/tests/test_hevy_client.py -q -k "schema or event or malformed"` | ❌ W2 | ⬜ pending |
| 3-05-02 | 05 | 2 | HEVY-01, HEVY-08 | T-03-16 / T-03-19 / T-03-20 | 401 not retried; explicit timeouts; key never logged | unit | `uv run pytest backend/tests/test_hevy_client.py -x -q` | ❌ W2 | ⬜ pending |
| 3-05-03 | 05 | 2 | HEVY-05 | T-03-17 / T-03-21 | No Hevy wire type or `httpx2` import escapes the package | static | `uv run pytest backend/tests/test_hevy_client.py backend/tests/test_hevy_isolation.py -q` | ❌ W2 | ⬜ pending |
| 3-06-01 | 06 | 3 | HEVY-03, HEVY-08 | T-03-22 / T-03-23 | Bound parameters only; skip log carries a class name | integration | `uv run pytest backend/tests/test_hevy_sync.py -q -k "idempotent or replaces_children or delete"` | ❌ W3 | ⬜ pending |
| 3-06-02 | 06 | 3 | HEVY-01, HEVY-09 | T-03-24 / T-03-25 / T-03-26 | Checkpoint commits with its page; loop always terminates | integration | `uv run pytest backend/tests/test_hevy_sync.py backend/tests/test_hevy_resilience.py -q` | ❌ W3 | ⬜ pending |
| 3-06-03 | 06 | 3 | HEVY-01, HEVY-03, HEVY-08 | T-03-24 / T-03-27 | Real `DataError` proves SAVEPOINT quarantine | integration | `uv run pytest backend/tests/test_hevy_sync.py backend/tests/test_hevy_resilience.py -q` | ❌ W3 | ⬜ pending |
| 3-07-01 | 07 | 3 | HEVY-06, NORM-01 | T-03-28 / T-03-32 | Raw Hevy strings preserved as the audit baseline | integration | `uv run pytest backend/tests/test_hevy_templates.py -q` | ❌ W3 | ⬜ pending |
| 3-07-02 | 07 | 3 | NORM-02, NORM-03 | T-03-29 / T-03-30 / T-03-31 | Override replaces base; base rows provably untouched | integration + unit | `uv run pytest backend/tests/test_normalization_mapping.py -q` | ❌ W3 | ⬜ pending |
| 3-07-03 | 07 | 3 | HEVY-06, HEVY-09, NORM-01 | T-03-28 | Deltoid split proven through a real round trip | integration | `uv run pytest backend/tests/test_hevy_templates.py -q` | ❌ W3 | ⬜ pending |
| 3-08-01 | 08 | 3 | HEVY-07, HEVY-09 | T-03-34 / T-03-35 / T-03-36 | 404 terminates; cleared metric cleared locally | integration | `uv run pytest backend/tests/test_hevy_body.py -q` | ❌ W3 | ⬜ pending |
| 3-08-02 | 08 | 3 | HEVY-07, HEVY-09 | T-03-33 / T-03-37 | No measurement value reaches the log stream | integration | `uv run pytest backend/tests/test_hevy_body.py -q` | ❌ W3 | ⬜ pending |
| 3-09-01 | 09 | 4 | HEVY-02 | T-03-39 / T-03-40 | Frozen `since`; unknown event type fails loudly | unit | `uv run pytest backend/tests/test_hevy_events.py -q -m "not integration"` | ❌ W4 | ⬜ pending |
| 3-09-02 | 09 | 4 | HEVY-02, HEVY-04, HEVY-09 | T-03-38 / T-03-41 / T-03-43 | Cursor advances once; refuses an epoch drain | integration | `uv run pytest backend/tests/test_hevy_events.py -q` | ❌ W4 | ⬜ pending |
| 3-09-03 | 09 | 4 | HEVY-02, HEVY-04 | T-03-38 / T-03-39 / T-03-42 | Newest payload wins; cursor held on failure | integration | `uv run pytest backend/tests/test_hevy_events.py -q` | ❌ W4 | ⬜ pending |
| 3-10-01 | 10 | 5 | HEVY-01, HEVY-02, HEVY-09 | T-03-46 | Lifecycle logs carry counts and modes only | integration | `uv run pytest backend/tests/test_hevy_end_to_end.py -q` | ❌ W5 | ⬜ pending |
| 3-10-02 | 10 | 5 | HEVY-05, HEVY-09 | T-03-44 / T-03-45 / T-03-47 | Logging configured before anything can log | static + unit | `uv run pytest backend/tests/test_cli.py -q` | ❌ W5 | ⬜ pending |
| 3-10-03 | 10 | 5 | HEVY-01, HEVY-02, HEVY-09 | T-03-46 / T-03-48 | No health data in the rendered log stream | integration | `uv run pytest backend/tests/test_cli.py backend/tests/test_hevy_end_to_end.py -q` | ❌ W5 | ⬜ pending |
| 3-11-01 | 11 | 6 | HEVY-01 | T-03-49 | `.env` gitignored; key never echoed | checkpoint + smoke | `PYTHONPATH=backend uv run python -c "from app.config import get_settings; assert get_settings().hevy_api_key is not None" && git check-ignore -q .env` | n/a | ⬜ pending |
| 3-11-02 | 11 | 6 | HEVY-01, HEVY-02, HEVY-07, HEVY-09 | T-03-50 / T-03-51 / T-03-53 | No credential or health dump committed | live smoke | `PYTHONPATH=backend uv run python -m app.cli sync-status` + the three-resource assertion in the plan | n/a | ⬜ pending |
| 3-11-03 | 11 | 6 | HEVY-01, HEVY-07 | T-03-51 / T-03-52 | No speculative correction factor applied | **manual** + guard | `grep -q 'PENDING' docs/hevy-api-observations.md` (verdict gate) | n/a | ⬜ pending |
| 3-12-01 | 12 | 7 | NORM-01, NORM-02, HEVY-06 | T-03-54 / T-03-55 / T-03-58 | `full_body` documented, never fanned out | unit + live smoke | `uv run pytest backend/tests/test_normalization_curation.py backend/tests/test_normalization_taxonomy.py -q` | ❌ W7 | ⬜ pending |
| 3-12-02 | 12 | 7 | NORM-01, NORM-03 | T-03-56 / T-03-57 | Gaps are inspectable, never a build gate | unit | `uv run pytest backend/tests/test_normalization_curation.py backend/tests/test_cli.py -q` | ❌ W7 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*File Exists column: ✅ = the test file already exists; ❌ Wn = created in wave n by the plan in that row.*

**Sampling continuity check:** all 34 tasks carry an `<automated>` verify command. There is no
run of even two consecutive tasks without one, so the Nyquist constraint (no 3 consecutive tasks
unsampled) holds by a wide margin. The two checkpoint tasks (3-11-01, 3-11-03) each carry an
automated guard in addition to their human step.

---

## Wave 0 Requirements

Framework install: **none needed**. pytest, pytest-asyncio, pytest-cov and
`testcontainers[postgres]` are all present and the suite is green at 72 passed / 28 deselected.

Plan **03-01 is this phase's Wave 0** and must complete before any plan that mocks Hevy:

- [ ] `uv add tenacity==9.1.4` (runtime) and `uv add --group dev pytest-httpx2==1.0.0`
- [ ] **Move `httpx2==2.12.0` from the dev group into `[project].dependencies`** — `HevyClient`
      imports it at runtime and `[tool.uv] default-groups = []` means a bare `uv sync` (the Cloud
      Run buildpack) would otherwise ship a production image that `ImportError`s on first sync
- [ ] `backend/tests/fixtures/hevy/{workouts_page1,workouts_page2,workout_events_page1,exercise_templates_page1,body_measurements_page1}.json`
      — transcribed from the **live** OpenAPI, never from `BRETT blueprint.md`, which is wrong
      about `rir`, `weight_unit` and child-object ids
- [ ] `backend/tests/conftest.py` — `hevy_fixture()` loader + the `httpx.Response`-for-responses /
      `httpx2`-for-exceptions rule recorded as a block comment
- [ ] `backend/tests/test_hevy_fixtures.py` — guards the fixtures against schema drift
- [ ] `"api-key"` added to `app.logging.DENY_KEYS` + an assertion in `test_secret_redaction.py`

Test files created later, by the plan that owns the code they cover:

| Wave | Files created |
|------|---------------|
| 1 | `test_hevy_schema.py`, `test_normalization_taxonomy.py` |
| 2 | `test_sync_state.py`, `test_hevy_client.py`, `test_hevy_isolation.py` |
| 3 | `test_hevy_sync.py`, `test_hevy_resilience.py`, `test_hevy_templates.py`, `test_normalization_mapping.py`, `test_hevy_body.py` |
| 4 | `test_hevy_events.py` |
| 5 | `test_hevy_end_to_end.py`, `test_cli.py` |
| 7 | `test_normalization_curation.py` |

Existing files edited deliberately (both are currently green and **will** fail otherwise):

- `backend/tests/test_db_models.py::test_metadata_contains_only_users_table` asserts
  `set(Base.metadata.tables) == {"users"}` — updated in plan 03-02 and again in 03-04. Keep the
  **equality** form; a subset check would forfeit the guard against a stray table.
- `backend/tests/test_secret_redaction.py` — extended in plan 03-01.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Obtaining a Hevy API key | HEVY-01 | The key is minted in the Hevy mobile app's Pro-only Developer settings. There is no CLI, API or automation path to it. | Plan 03-11 task 1: Hevy app → Settings → Developer → copy key → write `HEVY_API_KEY=` into a gitignored `.env`. Automated guard: `get_settings().hevy_api_key is not None` and `git check-ignore -q .env`. |
| Dumbbell `weight_kg`: per-dumbbell or combined | HEVY-01, VOL-01 (Phase 4) | Hevy documents no semantics for the field and the API cannot report its own convention. Only comparing a known session against what the app *displays* answers it. Getting it wrong makes every dumbbell tonnage and 1RM figure wrong by exactly 2×. | Plan 03-11 task 3: open the session named in `docs/hevy-api-observations.md`, read the app's displayed weights, compare with the recorded `weight_kg`. Report per-dumbbell or combined. No correction factor is ever applied in code. |
| Body-measurement units for the seven unsuffixed fields | HEVY-07 | Hevy declares no unit for `abdomen`, `waist`, `hips`, `left_thigh`, `right_thigh`, `left_calf`, `right_calf` — unlike their seven `*_cm` siblings. Nothing in the payload distinguishes cm from inches. | Plan 03-11 task 3: open the latest body-measurement entry in the app, read the displayed waist value and unit, compare with the stored `waist_cm`. Confirms or corrects RESEARCH assumption A2. |
| Real workout content matches the source | ROADMAP criteria 1-2 | Fixture-based tests prove the pipeline; only a human comparing a real session against the Hevy app proves the *data* is right. | Plan 03-11 task 3: pick a workout from the last two weeks, confirm exercise list, set count, weights and reps match. |
| Hevy's true rate limits | HEVY-08, D-10 | Undocumented by design — an exhaustive keyword scan of the live OpenAPI found zero mentions of rate limiting, `429`, `retry-after` or quotas. Only a real full sync generates the evidence. | Plan 03-11 task 2: capture `hevy_rate_limit_headers` log lines across the full sync and record them (or record their absence, with the request count and duration). |

Everything else in this phase has automated verification.

---

## Validation Sign-Off

- [x] All 34 tasks have an `<automated>` verify command or a Wave-0 dependency recorded above
- [x] Sampling continuity: no 2 — let alone 3 — consecutive tasks without an automated verify
- [x] Wave 0 (plan 03-01) covers every `MISSING` test-infrastructure reference
- [x] No watch-mode flags; every command terminates
- [x] Feedback latency: quick suite ~2 s, full suite ~90 s
- [x] Every requirement ID (HEVY-01..09, NORM-01..03) appears in at least one row of the
      per-task map
- [x] Every plan's `<threat_model>` threats are referenced from the task rows that mitigate them
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-29

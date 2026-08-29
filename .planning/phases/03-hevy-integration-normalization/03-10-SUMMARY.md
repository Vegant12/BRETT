---
phase: 03-hevy-integration-normalization
plan: 10
subsystem: api
tags: [hevy, sync-orchestration, cli, argparse, structlog, postgres, sqlalchemy, respx]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization (plan 03-06)
    provides: "sync_workouts / WorkoutSyncResult — the full-import driver and its result shape"
  - phase: 03-hevy-integration-normalization (plan 03-07)
    provides: "sync_exercise_templates / TemplateSyncResult and the materialised canonical muscle mapping"
  - phase: 03-hevy-integration-normalization (plan 03-08)
    provides: "sync_body_measurements / BodyMeasurementSyncResult"
  - phase: 03-hevy-integration-normalization (plan 03-09)
    provides: "sync_workout_events / EventSyncResult — the incremental driver"
  - phase: 03-hevy-integration-normalization (plan 03-04)
    provides: "sync_state repository: SYNC_RESOURCES, get_sync_state, STATUS_IDLE/STATUS_ERROR"
  - phase: 01-backend-foundation
    provides: "get_settings, configure_logging, make_engine/make_sessionmaker — the bootstrap order this CLI mirrors"
provides:
  - "HevySyncService: composes the four Hevy drivers, templates -> workouts -> body, with no transaction or exception handling of its own"
  - "resolve_mode: auto resolves to incremental iff the workouts resource has a last_synced_at, never keyed on the events cursor"
  - "SyncReport: exactly one of workouts_full / workouts_incremental is populated, so a caller can tell which path ran"
  - "resource_status / HevySyncService.status(): HEVY-09 in one call, including never-synced resources, and without a Hevy API key"
  - "python -m app.cli sync-hevy / sync-status: the phase's verification and operations trigger"
  - "backend/tests/test_hevy_end_to_end.py: mock-Hevy -> PostgreSQL -> normalized state in one run (blueprint 42/43)"
affects: [04-analytics, 05-mcp-tools, 07-scheduling, hevy-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition tier owns ORDER only: every commit, checkpoint and retry stays in the driver it belongs to"
    - "Source-order invariant enforced by a static test over the module text, in the style of test_cloud_run_deploy.py"
    - "Module-alias import (`from app.db import session as db_session`) to keep a construction site below a bootstrap line"
    - "Transport-free status function so a freshness query never needs the credential it is not using"

key-files:
  created:
    - backend/app/integrations/hevy/sync.py
    - backend/app/cli.py
    - backend/tests/test_hevy_end_to_end.py
    - backend/tests/test_cli.py
  modified:
    - README.md
    - .planning/phases/03-hevy-integration-normalization/deferred-items.md

key-decisions:
  - "resolve_mode keys on workouts.last_synced_at, not cursor_timestamp: the events cursor only exists after the first incremental run, so keying on it would make every second run a full re-import"
  - "sync_all has no try/except at all — each driver already records its own failure into sync_state before re-raising, and catching here would report a green sync over a resource that never ran"
  - "status() reports a resource with no bookkeeping row as STATUS_NEVER rather than omitting it or calling it idle"
  - "resource_status() added as a free function so `sync-status` works without HEVY_API_KEY; HevySyncService.status() delegates to it so the never-synced rule has one implementation"
  - "cli.py defines build_parser -> main -> the coroutines, because everything that touches a logger or an engine must sit below configure_logging(settings) in the source"
  - "`--only` calls the individual service methods rather than threading a filter into sync_all, keeping the default path branch-free"

patterns-established:
  - "Facade over drivers, not over transactions: the composing tier picks the order and nothing else"
  - "Bootstrap-order test reads the module as text — a runtime test cannot prove the absence of a log line on a stream that does not exist yet"
  - "Operator output goes to stdout via print(); lifecycle records go to the structlog pipeline. The two never share a channel"
  - "respx routes are registered per test rather than in one blanket helper, because assert_all_called turns an unregistered-but-uncalled route into a teardown failure"

requirements-completed: [HEVY-01, HEVY-02, HEVY-05, HEVY-09]

# Metrics
duration: 14min
completed: 2026-08-29
---

# Phase 3 Plan 10: Sync Service & CLI Summary

**`HevySyncService` composes the four Hevy drivers into one ordered call that picks full-vs-incremental from stored state, `python -m app.cli sync-hevy` invokes it behind a bootstrap order enforced by a source-order test, and a 8-test end-to-end suite drives mock Hevy through the whole stack into a normalized database.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-08-29T07:37:14Z
- **Completed:** 2026-08-29T07:51:00Z
- **Tasks:** 3
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments

- `HevySyncService.sync_all()` walks exercise templates → workouts → body measurements. The order is not arbitrary: D-03 already guarantees a workout syncs whether or not its template exists, but templates-first means a fresh database is never briefly in the state where every exercise is unmapped — the state that makes Phase 4's output look broken.
- `resolve_mode("auto")` reads `workouts.last_synced_at` and nothing else. `test_second_sync_all_takes_the_incremental_path` proves the switch **on the wire**, not just in the returned dataclass: it inspects every request the second run recorded and asserts none of them hit `/v1/workouts` with a `page` parameter.
- `status()` answers HEVY-09 in one call for all three resources, reporting a resource with no bookkeeping row as `never` rather than omitting it — "never synced" is the answer to "when was this last synced", and a missing row would be indistinguishable from a resource that does not exist.
- `python -m app.cli sync-hevy` and `sync-status` exist, own the engine's lifetime through a `finally`, and fail with a credential-free one-liner. Verified by hand: with `HEVY_API_KEY` unset the command prints `Hevy sync failed: HEVY_API_KEY is required to run a Hevy sync`, logs `hevy_cli_started`/`hevy_cli_failed`/`hevy_cli_stopped`, and exits 1.
- 15 new tests, taking the suite from 266 to **281 passing**. The eight end-to-end tests cover the full path on a virgin database, the canonical deltoid mapping through the override resolver, the three-resource freshness report, the incremental switch, the edit-and-deletion round trip, whole-schema idempotency, partial-failure isolation, and the log stream.
- `test_a_failing_resource_does_not_roll_back_a_completed_one` is the one that justifies `sync_all` having no exception handling: templates succeed and keep their `last_synced_at`, workouts fail with `status='error'`, and body measurements — the resource that never started — has no row at all.

## Task Commits

Each task was committed atomically, RED then GREEN for the two TDD tasks:

1. **Task 1: HevySyncService facade**
   - `ca92f9e` (test) — the end-to-end module with the three composition tests; RED, `app.integrations.hevy.sync` did not exist
   - `f8e8c38` (feat) — `HevySyncService`, `SyncReport`, `ResourceStatus`, `SyncMode`
2. **Task 2: CLI entrypoint**
   - `e7b7d86` (test) — five parser tests; RED, `app.cli` did not exist
   - `713943a` (feat) — `backend/app/cli.py`, `resource_status()`, README section
3. **Task 3: End-to-end and CLI tests**
   - `81a523d` (test) — the remaining five end-to-end tests and the two static CLI assertions

_No REFACTOR commits: neither GREEN pass left anything to clean up._

## TDD Gate Compliance

| Gate | Task 1 | Task 2 |
|------|--------|--------|
| RED (`test(...)`, verified failing) | `ca92f9e` — `ModuleNotFoundError: No module named 'app.integrations.hevy.sync'` | `e7b7d86` — `ModuleNotFoundError: No module named 'app.cli'` |
| GREEN (`feat(...)`, verified passing) | `f8e8c38` — 3 passed | `713943a` — 5 passed |
| REFACTOR | not needed | not needed |

No test passed unexpectedly during a RED phase.

## Files Created/Modified

- `backend/app/integrations/hevy/sync.py` (233 lines, created) — `SyncMode`, `STATUS_NEVER`, `ResourceStatus`, `SyncReport`, `resource_status()`, `HevySyncService`. Contains no `try:` and no `make_engine`, both asserted by the plan's acceptance greps: transaction handling belongs to the drivers and the engine belongs to the caller.
- `backend/app/cli.py` (219 lines, created) — `DEFAULT_USER_ID`, `RESOURCE_CHOICES`, `build_parser()`, `main()`, `_requested_mode()`, `_safe_detail()`, `_sync_selected()`, `_run_sync()`, `_run_status()`. Definition order is load-bearing, not stylistic.
- `backend/tests/test_hevy_end_to_end.py` (521 lines, created) — 8 tests, all `@pytest.mark.integration`, 9 `finally` blocks cleaning `workouts`, `exercise_templates`, `exercise_muscles`, `exercise_muscle_overrides`, `body_measurements` and `sync_state` for the seeded user.
- `backend/tests/test_cli.py` (128 lines, created) — 7 tests, no container and no marker, so bootstrap-order drift goes red in the fast suite on the commit that introduces it.
- `README.md` — new "Syncing Hevy data" section documenting both commands verbatim, the `HEVY_API_KEY` requirement, why `PYTHONPATH=backend` is needed, and that production scheduling is Phase 7.
- `.planning/phases/03-hevy-integration-normalization/deferred-items.md` — one new out-of-scope entry (see below).

## Decisions Made

- **`resolve_mode` keys on `last_synced_at`, never `cursor_timestamp`.** The events cursor is only written after the *first* incremental run, so a service keyed on it would resolve "auto" to `full` on the second run and re-import the whole history every other time. The plan called this out and the code comments it at the decision site.
- **`sync_all` contains no exception handling whatsoever.** Every driver already writes `status='error'` into `sync_state` through a fresh session before re-raising. A `try/except` here could only either swallow that (reporting a green sync over a resource that never ran) or duplicate it. The acceptance criterion `grep -q 'try:' sync.py` exits 1, which also meant avoiding the substring in prose — `retry:` and `entry:` both contain it.
- **`resource_status()` is a free function and `status()` delegates to it.** `HevySyncService` requires a `HevyClient`, and `build_hevy_client` refuses to construct one without `HEVY_API_KEY`. Without the split, answering "when did this last sync?" would demand the very credential that is most likely to be what is broken. Delegation keeps the never-synced rule in one place, mirroring how `effective_muscles` delegates to `effective_muscles_bulk`.
- **`cli.py` is ordered `build_parser` → `main` → coroutines.** `structlog.get_logger` contains the substring `log.` and `from app.db.session import make_engine` contains `make_engine`, so both would land *above* `configure_logging(settings)` under a conventional layout and fail `test_configure_logging_precedes_every_log_call`. The engine factory is therefore reached through a module alias (`db_session.make_engine`) and the two coroutines are defined after `main`. Python resolves the forward references at call time; the file documents why in its own docstring.
- **`_safe_detail(exc)` reads `exc.args[0]`, never renders the exception.** `str(exc)` is banned by the plan and asserted absent, because `pydantic.ValidationError.__str__` prints `input_value=` — this person's workout titles — onto a stderr channel that sits outside the redaction pipeline. `args[0]` is used only for the `RuntimeError` this codebase raises itself, whose message names the env var and never its value.
- **respx routes are registered per test rather than by one blanket helper.** `assert_all_called` is on by default, so a helper that registered `/v1/workouts/events` for a test that legitimately never goes incremental fails at teardown for a route it was right not to touch. `_mock_hevy` serves the full path; `_mock_events` is opted into.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `sync-status` would have required `HEVY_API_KEY`**

- **Found during:** Task 2 (CLI entrypoint)
- **Issue:** The plan's Task 1 interface gives `HevySyncService.__init__` a required `client: HevyClient`, and `_run_status` was specified to reach `status()` through the service. But `build_hevy_client` raises `RuntimeError("HEVY_API_KEY is required to run a Hevy sync")` when the key is absent, so `sync-status` — a read of three local timestamps that makes no HTTP request at all — would have failed on any machine without a Hevy key. That is precisely the machine where an operator most wants to ask when data was last synced.
- **Fix:** Added `resource_status(sessionmaker, *, user_id)` as a module-level function in `sync.py` holding the never-synced logic, and reduced `HevySyncService.status()` to a one-line delegation to it. `_run_status` calls the free function and never constructs a client.
- **Files modified:** `backend/app/integrations/hevy/sync.py`, `backend/app/cli.py`
- **Verification:** `grep -q 'async def status' sync.py` still exits 0 (plan acceptance criterion intact); `test_status_reports_all_three_resources` still exercises the method form; `grep -q 'HevySyncService' cli.py` still exits 0 (plan key_link intact).
- **Committed in:** `713943a` (Task 2 commit)

**2. [Rule 3 - Blocking] `HevySyncService` had no per-resource workout methods for `--only workouts`**

- **Found during:** Task 2 (CLI entrypoint)
- **Issue:** The plan requires `--only` to be implemented "by calling the individual service methods rather than by adding a filter parameter to `sync_all`", and lists `sync_templates()` and `sync_body()` on the class — but no workout equivalent, so `--only workouts` had nothing to call.
- **Fix:** Added `sync_workouts_full()` and `sync_workouts_incremental()` as two methods rather than one returning a union: a `WorkoutSyncResult | EventSyncResult` return type would push an `isinstance` check onto every caller. `_sync_selected` picks between them via the existing `resolve_mode`, so the `--only workouts` path honours `--full`/`--incremental`/auto exactly as `sync_all` does.
- **Files modified:** `backend/app/integrations/hevy/sync.py`, `backend/app/cli.py`
- **Verification:** `test_only_accepts_the_three_resources` parses all three; `uv run mypy backend/app` exits 0 with both concrete return types.
- **Committed in:** `f8e8c38` (method definitions) and `713943a` (the `--only` caller)

**3. [Rule 1 - Bug] The shared respx helper failed teardown on tests that never go incremental**

- **Found during:** Task 1 (GREEN verification)
- **Issue:** `_mock_hevy` registered all five endpoints including `/v1/workouts/events`. respx's `assert_all_called` then failed the teardown of both full-path-only tests with `RESPX: some routes were not called!` — the three tests themselves passed. Left as-is, every future test that legitimately stays on the full path would fail for a route it was correct not to touch.
- **Fix:** Split `/v1/workouts/events` out into its own `_mock_events(mock)` helper, opted into only by the tests that drain the feed. Documented in `_mock_hevy`'s docstring so the omission reads as deliberate.
- **Files modified:** `backend/tests/test_hevy_end_to_end.py`
- **Verification:** `uv run pytest backend/tests/test_hevy_end_to_end.py -q` — 3 passed, 0 errors (was 3 passed, 2 errors).
- **Committed in:** `f8e8c38` (Task 1 GREEN commit)

**4. [Structure] TDD test files were created in their driving task, not deferred to Task 3**

- **Found during:** Tasks 1 and 2
- **Issue:** Tasks 1 and 2 are marked `tdd="true"` and their `<verify>` blocks run `test_hevy_end_to_end.py` and `test_cli.py`, but the plan assigns both files to Task 3. Following the file assignment literally would have meant implementing both modules with no RED gate at all.
- **Fix:** Each test file was created in the task that drives it, holding only the tests that make that task's module fail to import (3 end-to-end, 5 CLI). Task 3 then completed both suites to the full 8 + 7 test names the plan specifies, in the order it specifies them.
- **Files modified:** `backend/tests/test_hevy_end_to_end.py`, `backend/tests/test_cli.py`
- **Verification:** Every test name listed in Task 3's `<action>` is present and passing; both RED commits are recorded with their `ModuleNotFoundError` above.
- **Committed in:** `ca92f9e`, `e7b7d86` (RED) and `81a523d` (suite completion)

---

**Total deviations:** 3 auto-fixed (1 missing critical, 1 blocking, 1 bug) + 1 structural TDD arrangement
**Impact on plan:** Every auto-fix was required for the plan's own acceptance criteria to be satisfiable. No scope creep: no new dependency, no new table, no change to any driver.

## Deferred Issues

One out-of-scope discovery logged to `deferred-items.md` rather than fixed:

- An **unreachable database** makes `python -m app.cli` exit 1 with a raw Python traceback rather than a one-line message. Verified by hand against a closed port that the traceback names only host and port (`ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 1)`) and does **not** contain the DSN password — so this is a UX gap, not a FOUND-05 leak. The plan specifies exactly two handled failures (`HevyError` and the missing-key `RuntimeError`) and says nothing about database reachability; an exit-code taxonomy belongs with Phase 7's scheduling work.

## Issues Encountered

- **respx `assert_all_called` on the shared mock helper** — described as deviation 3 above. Caught on the first GREEN run of Task 1 and fixed in the same commit. One auto-fix attempt.
- No other issue. Every other gate passed on the first attempt.

## Verification Evidence

| Gate | Command | Result |
|------|---------|--------|
| Plan suites | `uv run pytest backend/tests/test_cli.py backend/tests/test_hevy_end_to_end.py -q` | **15 passed** (7 + 8) |
| Full suite | `uv run pytest backend/tests -q` | **281 passed** (was 266) |
| Types | `uv run mypy backend/app` | Success, no issues in 41 source files |
| Lint | `uv run ruff check .` | All checks passed |
| CLI help | `PYTHONPATH=backend uv run python -m app.cli --help` | exit 0; output contains `sync-hevy` and `sync-status` |
| Flag exclusivity | `... sync-hevy --full --incremental` | exit **2**, `argument --incremental: not allowed with argument --full` |
| Missing key path | `DATABASE_URL=... python -m app.cli sync-hevy` (no `HEVY_API_KEY`) | exit **1**, `Hevy sync failed: HEVY_API_KEY is required to run a Hevy sync` |
| Bootstrap order | `assert 'log.' not in src[:i] and 'make_engine' not in src[:i]` | passes |
| No driver-level handling | `grep -q 'try:' backend/app/integrations/hevy/sync.py` | exit 1 (absent) |
| No second engine | `grep -q 'make_engine' backend/app/integrations/hevy/sync.py` | exit 1 (absent) |
| No arbitrary rendering | `grep -q 'str(exc)' backend/app/cli.py` | exit 1 (absent) |
| Fast-suite CLI tests | `grep -q 'integration' backend/tests/test_cli.py` | exit 1 (absent) |
| Cleanup discipline | `grep -c 'finally' backend/tests/test_hevy_end_to_end.py` | **9** (required: ≥ 7) |
| README | `grep -q 'Syncing Hevy data' README.md` | exit 0 |
| File sizes | `sync.py` / `cli.py` | 233 / 219 lines (required: ≥ 130 / ≥ 100) |

Threat-register coverage:

| Threat ID | Covered by |
|-----------|------------|
| T-03-44 (bootstrap order) | `test_configure_logging_precedes_every_log_call` — static, in the fast suite |
| T-03-45 (stderr output) | `test_cli_never_formats_an_arbitrary_exception`; verified by hand that the missing-key path prints only the curated message |
| T-03-46 (lifecycle logs) | `test_no_health_data_reaches_the_log_stream` — `"Push Day"`, `"80.5"`, `"18.5"` and the api-key all absent from the rendered stream across a full `sync_all` |
| T-03-47 (connection leak) | `try/finally: await engine.dispose()` in both `_run_sync` and `_run_status`; `async with build_hevy_client(...)` for the HTTP pool |
| T-03-48 (`--user-id`) | **Accepted** per the plan, unchanged: single-user personal deployment, CLI reachable only with shell access |

## Known Stubs

None. Every function in `sync.py` and `cli.py` is on a real caller path. `_run_sync` and `_run_status` have no automated runtime test — the plan deliberately covers the CLI by parsing and source-order assertions — but both were exercised by hand and the evidence is in the table above.

## Threat Flags

None. This plan adds no network endpoint, no auth path and no schema change. `app/cli.py` opens a new trust boundary (operator shell → process), which the plan's own `<threat_model>` already enumerates as T-03-44/45/47/48.

## User Setup Required

None — no external service configuration required. `HEVY_API_KEY` is already a documented environment variable; the CLI names it in its failure message when absent.

## Next Phase Readiness

- **ROADMAP Phase 3 success criteria 1–5 are now provable in a single test run.** `test_sync_all_on_a_virgin_database_takes_the_full_path`, `test_second_sync_all_takes_the_incremental_path`, `test_incremental_run_applies_the_edit_and_the_deletion`, `test_sync_all_populates_the_canonical_mapping` and `test_status_reports_all_three_resources` cover them in order.
- **Phase 4 (analytics)** can rely on `sync_all` having left a consistent database: templates and their canonical mapping are written before any workout row is read back, and `effective_muscles` resolves through the override layer as `test_sync_all_populates_the_canonical_mapping` asserts.
- **Phase 5 (MCP tools)** gets `resource_status()` as the data-freshness source. It takes only a sessionmaker, which is exactly what `AppContext` already carries, so a `fitness_get_sync_status` tool needs no new plumbing.
- **Phase 7 (scheduling)** gets a stable invocation surface. `python -m app.cli sync-hevy` is the command a Cloud Run job would run; the only open question there is the failure taxonomy noted in `deferred-items.md`.
- Carried-forward concern, unchanged from 03-09: D-09's accepted deletion-drift risk. The detector (`hevy_workout_count_mismatch`) fires from inside the full sync, which `sync_all` now runs on every virgin database.

## Self-Check: PASSED

Files claimed as created, verified present on disk:

- `backend/app/integrations/hevy/sync.py` — FOUND (233 lines)
- `backend/app/cli.py` — FOUND (219 lines)
- `backend/tests/test_hevy_end_to_end.py` — FOUND (521 lines)
- `backend/tests/test_cli.py` — FOUND (128 lines)
- `README.md` — FOUND (modified, contains "Syncing Hevy data")

Commits claimed, verified in `git log`: `ca92f9e`, `f8e8c38`, `e7b7d86`, `713943a`, `81a523d` — all FOUND.

Post-commit deletion check: `git diff --diff-filter=D --name-only 969a9f2..HEAD` returned nothing. No tracked file was removed by this plan. `git status --short` is clean apart from this summary.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-29*

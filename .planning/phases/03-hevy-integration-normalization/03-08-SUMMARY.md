---
phase: 03-hevy-integration-normalization
plan: 08
subsystem: api
tags: [hevy, body-measurements, upsert, on-conflict, pagination, sync-state, structlog, respx]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization
    provides: "plan 03-04: the BodyMeasurement model with its seven `*_cm` renames and uq_body_measurements_user_source_measured_on, plus the provider-neutral sync_state repository (ensure_sync_state / mark_running / advance_cursor_page / complete_sync / record_sync_error)"
  - phase: 03-hevy-integration-normalization
    provides: "plan 03-05: HevyClient.get_body_measurements(page=) returning None on the 404 terminator, PAGE_SIZE_BODY_MEASUREMENTS = 10, and the HevyBodyMeasurement / PaginatedBodyMeasurements wire schemas"
  - phase: 03-hevy-integration-normalization
    provides: "plan 03-01: body_measurements_page1.json (one fully-populated date, one 16/17-empty date) behind hevy_fixture()"
  - phase: 01-backend-foundation
    provides: "app.core.time.utc_now, the three-layer structlog redaction pipeline, and the migrated-container test fixtures"
provides:
  - "upsert_body_measurement — one dated row written through an explicit 17-entry wire->column map, resolved on uq_body_measurements_user_source_measured_on"
  - "sync_body_measurements — the full-sync driver for /v1/body_measurements: D-08 resume, per-page commit of rows + checkpoint, SAVEPOINT-quarantined rows, 404 as terminator"
  - "BodyMeasurementSyncResult(pages_fetched, rows_upserted) — counts only, never a measurement"
  - "SOURCE_HEVY / _WIRE_TO_COLUMN — the single place the seven unsuffixed Hevy fields become `*_cm`"
  - "An independent last_synced_at for the body_measurements resource (HEVY-09)"
affects: [03-12 CLI sync command, phase-04 body-weight trend analytics, phase-05 BODY-01/BODY-02]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Row-replacement upsert: ON CONFLICT DO UPDATE writes EVERY metric column including the now-None ones, mirroring the provider's own PUT semantics, so a value cleared upstream is cleared locally"
    - "An explicit wire->column mapping with identity entries spelled out, so a field added upstream is a visible omission rather than a silent drop"
    - "Endpoint-specific pagination terminators live in the client (404 -> None) and the driver treats None as end-of-pages, keeping HTTP status semantics out of the sync logic"
    - "Per-test try/finally DELETE rather than fixture teardown, so one test's rows can never decide another test's row count"
    - "Log-stream assertions parse the rendered JSON and drop `timestamp` before scanning, so an unconstrained microsecond field cannot make a redaction test flaky"

key-files:
  created:
    - backend/app/integrations/hevy/body.py
    - backend/tests/test_hevy_body.py
  modified: []

key-decisions:
  - "Inlined the constraint name at the ON CONFLICT instead of hoisting it to a module constant: there is exactly one use site, the plan's acceptance criterion greps for it there, and the name is the most important thing to see when reading the upsert"
  - "test_server_error_records_an_error_and_keeps_the_cursor pre-seeds cursor_page=3 rather than failing a virgin run. On a fresh row the cursor is NULL both before and after, so the assertion would have held no matter what the driver did — the seeded value also proves the run RESUMED at page 3, asserted on the recorded request"
  - "Dropped the `timestamp` key before scanning the log stream for metric values. The fixture's lean_mass_kg is 65, and an ISO timestamp's six-digit microsecond field will eventually contain '65' by chance; a suite that reddens once a fortnight teaches people to re-run it rather than read it"
  - "test_no_metric_value_reaches_the_log_stream also asserts a `hevy_body_sync_completed` line is present. Without it the test passes trivially on an empty buffer, which is the failure mode a mis-wired capture actually produces"
  - "Did NOT touch REQUIREMENTS.md, STATE.md or ROADMAP.md — shared files owned by the orchestrator while sibling wave-3 agents are running"

patterns-established:
  - "Pattern: a redaction test states its own capture is live (assert the expected event is in the buffer) before asserting what is absent from it"
  - "Pattern: a 'the cursor is kept' test seeds a non-default cursor, because the default value makes the assertion vacuous"
  - "Pattern: the local column list is transcribed into the test module rather than derived from the model, so a column dropped from the sync mapping fails a test instead of reading back NULL forever"

requirements-completed: [HEVY-07, HEVY-09]

# Metrics
duration: 12min
completed: 2026-08-29
---

# Phase 3 Plan 8: Hevy Body Measurements Summary

**Date-keyed body-measurement sync: all 17 metrics land in one row per calendar date through an explicit wire→column map, `ON CONFLICT` on `(user_id, source, measured_on)` replaces every metric including the nulls so an upstream deletion propagates, and a 404 on the next page ends the run at `status='idle'` instead of failing it.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-29T07:00:00Z
- **Completed:** 2026-08-29T07:12:00Z
- **Tasks:** 2 of 2
- **Files modified:** 2 (2 created, 0 modified)

## Accomplishments

- **The date really is the identity, and the database proves it.** `upsert_body_measurement` resolves on `uq_body_measurements_user_source_measured_on` by *name*, so renaming the constraint raises immediately rather than silently degrading into a duplicate-row insert. `id` is a fresh `uuid4()` on every call and `external_id` is always `NULL` — the endpoint has no id to store — which means the constraint is the only thing standing between a re-sync and a second row for the same day. `test_resync_upserts_on_the_date` runs the sync twice and asserts two rows, not four.

- **A metric the user deletes upstream disappears locally.** The `set_` clause writes *every* one of the 17 columns from `excluded`, including the ones that just became `None`. This mirrors Hevy's own `PUT /v1/body_measurements/{date}` ("all fields are overwritten; omitted fields are set to null"), and it is what stops a stale body-fat figure from lingering into Phase 5's recomposition verdict (T-03-35). `test_metric_cleared_upstream_is_cleared_locally` syncs `fat_percent: 18.5`, re-syncs the same date with `fat_percent: null`, and asserts the column is `NULL` afterwards *while `weight_kg` survives* — a replacement, not a truncation.

- **The seven unsuffixed fields are renamed in exactly one place.** `_WIRE_TO_COLUMN` is a 17-entry `MappingProxyType` in which the ten identity mappings are spelled out alongside the seven renames (`abdomen`→`abdomen_cm`, `waist`→`waist_cm`, `hips`, both thighs, both calves). Listing the identity entries is the point: a field Hevy adds upstream shows up as a visible gap in this dict rather than being silently dropped by a `getattr` loop over the model's columns. `test_all_seventeen_metrics_persist` asserts the renamed columns by value and then that none of the 17 is `NULL`.

- **A 404 ends the walk; it does not fail it.** The client already converts `HevyPageNotFound` to `None` (Pitfall 5), and the driver treats `None` as the terminator with a `hevy_body_pagination_terminated` log line. `test_404_terminates_pagination_cleanly` advertises `page_count: 5` on page 1 precisely so the run *cannot* stop for the ordinary reason, then asserts `pages_fetched == 1`, `status == 'idle'` and `last_error is None`. `test_404_consumes_no_retry_budget` asserts the page-2 route was called exactly once — if `HevyPageNotFound` ever moved under a retryable base, every body-measurement sync would spend its whole backoff budget on its last, entirely normal, page (T-03-36).

- **No measurement reaches a log line.** The six log events carry a page number, a start page, two counts, an ISO date and an exception *class name* — never a value. The skipped-row warning uses `type(exc).__name__` rather than `str(exc)`, because `str(DataError)` renders the bound parameters, which here are this person's body-composition numbers (T-03-34). `test_no_metric_value_reaches_the_log_stream` runs a full sync through the real rendered pipeline and asserts `"80.5"`, `"18.5"` and `"65"` appear nowhere in it (T-03-33).

- **Freshness is genuinely per-resource.** `test_last_synced_at_for_body_measurements_is_independent` creates the `workouts` and `exercise_templates` bookkeeping rows *before* the run, so the `NULL`s afterwards are a positive statement that this sync touched only its own resource rather than an artefact of two rows never existing (HEVY-09).

## Task Commits

1. **Task 1: Body-measurement upsert and sync driver** — `4e9991b` (test, RED) → `231d573` (feat, GREEN)
2. **Task 2: Body-measurement integration suite** — `df2f59d` (test)

No REFACTOR commit: the GREEN implementation needed no cleanup, and `ruff check` / `mypy` were clean on first run.

## TDD Gate Compliance

- **RED** — `4e9991b`: six integration tests covering all five `<behavior>` bullets, failing at collection with `ModuleNotFoundError: No module named 'app.integrations.hevy.body'`. Verified red before any implementation was written.
- **GREEN** — `231d573`: `body.py` created; 6 passed.
- **REFACTOR** — not required (no changes to make).

Gate sequence `test(...)` → `feat(...)` is present in `git log`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Dead 404 responses in the mock queue made three tests pass for the wrong reason**

- **Found during:** Task 1, GREEN
- **Issue:** The RED tests queued `side_effect=[_ok(), httpx.Response(404)]`, on the assumption that every run pages until a 404. It does not: the fixture advertises `page_count: 1`, so the driver correctly stops on `page >= payload.page_count` and never issues a second request. The queued 404 therefore survived into the *next* sync within the same test. `test_metric_cleared_upstream_is_cleared_locally` failed outright (its second run consumed the leftover 404 and wrote nothing), and `test_resync_upserts_on_the_date` was green only because run 1 had already written the two rows it asserted.
- **Fix:** Removed the unreachable 404s from the four single-page tests; `test_resync_upserts_on_the_date` now queues `[_ok(), _ok()]` and the cleared-metric test `[_ok(), <cleared page>]`. The two tests that genuinely exercise the terminator keep it, on a `page=2`-matched route with `page_count: 5` on page 1 so the 404 is the only thing that can stop the walk.
- **Files modified:** `backend/tests/test_hevy_body.py`
- **Commit:** `231d573`

**2. [Rule 3 - Blocking] The constraint name was hoisted to a module constant, hiding it from the acceptance grep**

- **Found during:** Task 1, acceptance verification
- **Issue:** The first draft mirrored `app/db/repositories/sync_state.py` and extracted `_CONFLICT_CONSTRAINT = "uq_body_measurements_user_source_measured_on"`. The plan's acceptance criterion greps for `constraint="uq_body_measurements_user_source_measured_on"` at the call site, which returned zero matches.
- **Fix:** Inlined the literal at the `on_conflict_do_update`, moving the "bound by name, not by column list" rationale into a comment there. With exactly one use site the indirection bought nothing and cost the reader the most important detail of the statement.
- **Files modified:** `backend/app/integrations/hevy/body.py`
- **Commit:** `231d573`

### Deliberate Departures from the Plan Text

**3. `test_server_error_records_an_error_and_keeps_the_cursor` seeds the cursor before failing the run**

The plan specified `page=1` always 500 with `max_attempts=2`. On a run starting from a fresh bookkeeping row, `cursor_page` is `NULL` both before and after the failure, so "keeps the cursor" would have been true of a driver that cleared it, kept it, or never set it. The test now seeds `cursor_page=3`, asserts the recorded request actually went to `page=3` (proving D-08 resume works), and asserts the cursor is still `3` after the failure. The plan's other three assertions — `pytest.raises(HevyServerError)`, `status == 'error'`, `last_error` ≤ 500 chars with no metric value — are unchanged.

**4. The log-stream scan drops the `timestamp` field**

The plan asked that `"80.5"`, `"18.5"` and `"65"` not appear "anywhere in" the rendered stream. Taken literally that test is time-dependent: `TimeStamper(fmt="iso")` emits a six-digit microsecond field, and `"65"` will appear in it roughly one run in fifty. Each line is parsed as JSON and `timestamp` removed before the scan, so the assertion is about content the code controls. A companion assertion (`hevy_body_sync_completed` is present) rules out the empty-buffer false pass this refactor could otherwise introduce.

## Verification

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_hevy_body.py -q` | 12 passed |
| `uv run pytest backend/tests -q` (full suite) | 207 passed |
| `uv run mypy backend/app` | Success, no issues in 35 source files |
| `uv run ruff check .` | All checks passed |
| `select count(*) from body_measurements` after the suite | 0 — verified with a temporary end-of-session integration test (alphabetically last so it ran after every other module), which also asserted 0 `sync_state` rows for `provider='hevy'`. The check ran green (208 passed) and the scratch file was then deleted. |

## Acceptance Criteria

| Criterion | Result |
|---|---|
| `body.py` defines `_WIRE_TO_COLUMN`, `upsert_body_measurement`, `sync_body_measurements`, `BodyMeasurementSyncResult` | Yes |
| `len(_WIRE_TO_COLUMN) == 17`, `waist`→`waist_cm`, `abdomen`→`abdomen_cm`, `left_calf`→`left_calf_cm` | Exit 0 |
| `grep 'constraint="uq_body_measurements_user_source_measured_on"'` | 1 match |
| `grep 'if payload is None'` / `grep 'hevy_body_pagination_terminated'` | 1 match each |
| `grep 'str(exc)'` | 0 matches (exit 1) |
| No metric value on any `log.` call | 6 log calls, all counts/pages/ISO dates/class names |
| `body.py` ≥ 110 lines | 232 |
| 12 named tests present, all `@pytest.mark.integration` | 12 / 12 |
| `grep -c 'finally'` ≥ 10 | 13 |
| `grep 'httpx.Response(404)'` / `grep 'datetime.date'` | 2 / 5 matches |

## Known Stubs

None. Every metric column is wired from the wire schema to the database and asserted by an integration test.

## Threat Flags

None. This plan adds no network endpoint, no auth path and no schema change; the `body_measurements` write surface and its trust boundary were both already in the plan's `<threat_model>` (T-03-33 through T-03-37), and all five dispositions are implemented and asserted.

## Notes for the Next Phase

- **The centimetre assumption is still unconfirmed (RESEARCH A2).** Hevy does not document a unit for `abdomen`, `waist`, `hips`, the thighs or the calves. `_WIRE_TO_COLUMN` renames all seven to `*_cm`, which is highly likely given the sibling `_cm` fields, but it has not been checked against the app. Confirm on the first live sync before Phase 4 draws a circumference trend — every one of those seven trends is wrongly scaled if this is wrong.
- **`sync_body_measurements` has no caller yet.** Plan 03-12's CLI is what wires it to `build_hevy_client` and a real sessionmaker.
- **`external_id` is permanently `NULL` for `source='hevy'`.** Any future manual-entry or second-provider path must not read it as a discriminator; `source` is the discriminator.

## Self-Check: PASSED

- Files claimed created: `backend/app/integrations/hevy/body.py`, `backend/tests/test_hevy_body.py`, `.planning/phases/03-hevy-integration-normalization/03-08-SUMMARY.md` — all three present on disk.
- Commits claimed: `4e9991b`, `231d573`, `df2f59d` — all three present in `git log`, in the RED → GREEN → test order stated.
- No shared orchestrator artifacts (`STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`) were modified.

---
phase: 09-historical-apple-health-backfill
plan: 03
subsystem: api
tags: [apple-health, upsert, savepoint, idempotency, sync-state, postgres, testcontainers]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    provides: "upsert_health_metric and its four-column ON CONFLICT set_, _CONFLICT_CONSTRAINT bound by name, _KIND_TO_RESOURCE (D-03), _user_timezone (FOUND-03), ingest_payload's SAVEPOINT loop / freshness block / fresh-session failure branch, and the health_daily_metrics natural key"
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-02's scan_export(path, tz=) -> BackfillScan (the pure read half), the export_sample.xml fixture and hae_xml_fixture loader, and plan 09-01's device_capture.json source-name pin"
provides:
  - "backend/app/integrations/health_auto_export/backfill.py — run_backfill(sessionmaker, *, user_id, path, dry_run) -> BackfillSummary, the single public entry point cli.py will call"
  - "_upsert_many: one multi-row INSERT ... ON CONFLICT DO UPDATE per chunk, bound to the IMPORTED _CONFLICT_CONSTRAINT and setting exactly the four columns upsert_health_metric sets"
  - "_write_rows: chunk of 500 inside a begin_nested, falling back to ingest.py's per-row SAVEPOINT path for a failing chunk only (D-07), with a D-05 heartbeat every 500 written rows"
  - "BackfillSummary + _summarize — the operator-facing counts, derived in exactly one place and shared by both of run_backfill's exits"
  - "format_summary(summary, *, path) -> list[str] — the D-06 block as pure lines: counts, metric names, HealthKit identifiers, units and dates only"
  - "backend/tests/test_backfill_idempotency.py — eight integration cases against a real Postgres container, including SC#3 in both directions"
  - "Two fast-suite tests pinning format_summary: no measured quantity on stdout, and the records: line's own arithmetic reconciles"
affects: [09-04, 09-05, 09-06, 09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hybrid write: a chunked multi-row upsert as the fast path with the house SAVEPOINT-per-row loop kept as the fallback arm for a failing chunk — the D-07 guarantee at ~1/1400 the round trips, not instead of it"
    - "A shared conflict clause is IMPORTED, never restated: `_CONFLICT_CONSTRAINT` and `upsert_health_metric` come from `ingest.py` so the two write paths cannot drift on what 'the same row' means"
    - "One derivation for one number: `_summarize` builds the summary for both the dry-run and the real-run exit, so a dry run cannot report a different date range from the real run over the same file"
    - "A dry-run gate is placed before the first `session.execute` AND before any `sync_state` contact, and is proven by a test that seeds rows the dry run WOULD have rewritten"
    - "Freshness is claimed only by a run that wrote: `complete_sync` is guarded on `written > 0`, so neither a dry run nor an empty real run can mark Apple Health fresh"

key-files:
  created:
    - backend/tests/test_backfill_idempotency.py
  modified:
    - backend/app/integrations/health_auto_export/backfill.py
    - backend/tests/test_health_auto_export_backfill.py

key-decisions:
  - "The chunked upsert and the per-row loop are not alternatives — the per-row loop is the CHUNK's exception handler. A failing chunk's SAVEPOINT has already rolled back when the fallback runs, so no row is written twice, and the blast radius of one bad value is 500 rows' worth of retries rather than 8,077 lost rows or one lost row's worth of speed"
  - "`_summarize` was extracted rather than inlining the `rows_by_metric`/`first_day`/`last_day` arithmetic at both of `run_backfill`'s exits. Two copies is how the dry run would eventually report a different date range from the real run over the same file — which is precisely the number a dry run exists to be trusted on"
  - "`test_dry_run_writes_nothing` seeds a real webhook delivery FIRST and then dry-runs a file that would rewrite every one of those rows. Snapshotting an empty table before and after would pass whether or not the gate existed; this version was verified to FAIL under a deliberate mutation of the gate"
  - "`_read_one` is keyed on the FULL natural key `(metric, source_name, local_day)`, unlike the webhook analog's `(metric, source_name)` pair. The backfill legitimately writes the same metric from the same source on more than one day, so the analog's helper would have raised on correct data"
  - "requirements-completed stays empty, matching 09-01 and 09-02. All seven Phase 9 plans carry `requirements: [HEALTH-10]`; this plan ships the write half and no CLI subcommand exists yet, so nothing an operator can run satisfies HEALTH-10"

patterns-established:
  - "A no-change assertion is only worth writing if it can fail: seed state the operation under test WOULD have changed, then assert it did not. An equality between two empty snapshots is a test of nothing"
  - "Mutation-check the load-bearing gate before committing it. `if dry_run:` was temporarily weakened, the test was confirmed red with a readable message, and the mutation reverted — a two-minute check that turns 'the test passed' into 'the test would have caught it'"
  - "A summary block rendered for operators is scanned for leaked quantities by NUMERIC TOKEN, not by substring: substring matching both false-positives on a count that contains the digits and false-negatives on a real leak rendered with a trailing `.0`"

requirements-completed: []

# Metrics
duration: 16min
completed: 2026-09-03
---

# Phase 9 Plan 03: The Backfill Write Pass Summary

**`run_backfill` turns a `BackfillScan` into `health_daily_metrics` rows through a chunked `ON CONFLICT DO UPDATE` bound to the same named constraint the webhook uses, with `ingest.py`'s own per-row SAVEPOINT loop kept as the fallback arm — so 8,077 historical rows cost ~17 statements instead of 24,231 round trips, and a day covered by both the backfill and the live webhook is proven, against a real Postgres container, to hold exactly one row.**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-09-03T05:21Z
- **Completed:** 2026-09-03T05:37Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- **Success criterion #3 is now proven in both directions against a real constraint, not argued.** `test_backfill_then_webhook_on_the_same_day_is_one_row` backfills `export_sample.xml`, then delivers `device_capture.json` through the untouched `ingest_payload`, and asserts that `(step_count, V’s iPhone, 2026-09-02)` holds exactly one row whose value is the webhook's `6500` and not the sum `8000`. `test_webhook_then_backfill_on_the_same_day_is_one_row` runs the same collision the other way round, which matters because the two orders exercise different halves of the design: the first has `ingest.py`'s per-row statement landing on a backfilled row, the second has `backfill.py`'s chunked multi-row statement landing on a webhook row. A conflict clause that was right in one direction and wrong in the other would pass the first test unchanged.
- **The collision is per `source_name`, and that is asserted rather than assumed.** Both tests check that `Vegant’s iPhone`'s `step_count` row for the SAME day is still present and still `700`, and that the total row count does not move — all twelve of the webhook's metrics collide with a backfilled row, so a single extra row anywhere would be visible. This is the assertion that fails the day the phone is renamed or an editor folds U+2019 to an ASCII apostrophe, which is the only way that failure is ever detectable: the upsert would otherwise simply INSERT, silently.
- **The 24,231-round-trip problem is gone without giving up D-07.** `_write_rows` issues one statement per 500 rows and only replays `ingest.py`'s per-row path for a chunk that raised. `test_one_bad_row_is_skipped_and_the_rest_of_the_chunk_lands` builds a genuinely unwritable row (a 200-character `sourceName` against `String(128)`), confirms the run returns normally with `rows_skipped == 1` and `rows_written == 2`, and — because `active_energy` sorts first — proves the transaction is still usable *after* the failure and not merely before it.
- **The dry-run gate was mutation-checked, not just exercised.** `if dry_run:` was temporarily weakened to `if dry_run and not path:` and the suite re-run: `test_dry_run_writes_nothing` failed with `D-03 violated: --dry-run wrote to health_daily_metrics` and a diff showing the seeded `active_energy` value moving from `560` to `300`. The mutation was reverted and `git status` confirmed clean before committing. The test is discriminating because it seeds a real webhook delivery first and then dry-runs a file that would rewrite every one of those rows — an empty-table snapshot comparison would have passed either way.
- **Nothing a run claims about freshness is unbacked.** `complete_sync` is guarded on `written > 0` and lives inside the same transaction as the rows, so a dry run, an empty run and a crashed run all leave `sync_state` alone. `test_a_real_run_advances_both_apple_health_resources` pre-seeds both resources at a distinct past instant so "advanced" is observable, and asserts the two timestamps are **equal to each other** — one `utc_now()` for the whole run, so activity and nutrition cannot report fractionally different ages.
- **The D-06 operator block carries no measured quantity, in either mode.** `format_summary` is a pure function returning lines, so what the operator will see is asserted in the fast suite with no stdout capture and no container. `test_summary_prints_no_measured_quantity` extracts every numeric token from the rendered block and checks the fixture's distinctive values (`1500`, `6500`, `2300`, `228`, `4.5`) against that set — by token, so a count containing those digits is not a false positive and a leak rendered as `228.0` is not a false negative.

## Task Commits

Each task was committed atomically:

1. **Task 1: The write pass — chunked upsert, per-row fallback, freshness, run_backfill** — `4c48f98` (feat)
2. **Task 2: Idempotency and dry-run proof against a real Postgres container** — `7691a5a` (test)
3. **Formatting follow-up on the new test module** — `7395622` (style)

**Plan metadata:** see the final `docs(09-03)` commit.

## Files Created/Modified

- `backend/app/integrations/health_auto_export/backfill.py` — grew from 442 to ~890 lines. New module-docstring sections state the measured write cost, why the multi-row upsert is safe here specifically (`CardinalityViolationError` cannot fire because `normalize_payload` keys rows by a dict), why the conflict clause is imported rather than restated, and that the logging rule covers stdout. New code: `_CHUNK`, `_HEARTBEAT_ROWS`, `BackfillSummary`, `_upsert_many`, `_write_rows`, `_summarize`, `run_backfill`, `_METRIC_COLUMN`/`_HK_TYPE_COLUMN`, `format_summary`. `scan_export` and everything above it is byte-for-byte unchanged.
- `backend/tests/test_backfill_idempotency.py` — new, 674 lines, eight `@pytest.mark.integration` cases with a per-test `finally` cleanup. Copies the analog's `Snapshot`/`_maker`/`_read_all_rows`/`_cleanup`/`_run_capturing_logs` shapes; adds `_read_one` on the full natural key, `_duplicate_keys` (a `GROUP BY ... HAVING count(*) > 1` asked of the database rather than derived from the snapshot list), `_all_apple_state`, `_seed_apple_health`, and `_BAD_ROW_EXPORT`, a minimal three-record HealthKit document written to `tmp_path`.
- `backend/tests/test_health_auto_export_backfill.py` — grew from 20 to 23 tests. A third layer in the module docstring for the D-06 block, plus `_rendered_summary`, `test_summary_prints_no_measured_quantity` (parametrized over both modes) and `test_summary_reports_the_record_accounting_identity`.

## Decisions Made

- **`_upsert_many` imports `_CONFLICT_CONSTRAINT` from `ingest.py` rather than re-declaring the string.** The plan required it and the reason is worth restating: binding by name exists so a rename raises instead of silently degrading into duplicate rows, and a second literal would keep working through exactly the rename it is supposed to catch. `grep -c` for the constraint name in `backfill.py` returns 0.
- **The per-row fallback is `ingest.upsert_health_metric`, not a copy of it.** The fallback arm is the *webhook's* write, called on the *backfill's* row. That is what makes "the two paths write the same shape" true by construction rather than by review, and it is why the four `set_` keys are identical: there is only one of them.
- **`_summarize` was extracted.** Not in the plan, which spelled the arithmetic out inside `run_backfill`'s dry-run branch and again at its return. Two copies would let the dry run and the real run disagree about a date range over the same file. As a bonus, the fast-suite `format_summary` tests now drive the same derivation the CLI will, instead of a hand-built `BackfillSummary` that could satisfy every assertion while the real one differed.
- **`unrecognized types` is sorted by count descending, `rows by metric` by name.** They are different kinds of list. The metric table is a diff target — two runs over the same file must produce byte-identical blocks — while the unrecognized table is a triage queue, where the identifier that cost the most records is the one worth considering for the registry. Ties break on name so both stay deterministic.
- **`path.name`, never `path`, in the summary block.** The full path is the location of this person's entire health history and the operator typed it thirty seconds ago; the file name is enough to confirm the right file was read. Same reasoning `HAEExportFileError` already applies to its own message.
- **An eighth integration test was added beyond the plan's seven.** `test_the_second_local_day_is_written_too` pins that the run spans two local days and that `summary.first_day`/`last_day` report both. Every other count in the file would still look plausible if 2026-09-03's `step_count` had been collapsed into 2026-09-02 — a missing day surfaces only as a gap in a trend months later, which is the failure the record accounting identity closes on the read side and this closes on the write side.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's `SEEDED_USER_ID` does not exist; the fixture constant is `DEFAULT_USER_ID`**

- **Found during:** Task 2
- **Issue:** The plan's test bodies call `run_backfill(..., user_id=SEEDED_USER_ID, ...)`. `backend/tests/conftest.py` exports `DEFAULT_USER_ID` (the id migration 0002 seeds); there is no `SEEDED_USER_ID` anywhere in the tree, so the file would have failed at import with `ImportError`.
- **Fix:** Used `DEFAULT_USER_ID` throughout, matching `test_health_ingest_idempotency.py`, which is the analog the plan names.
- **Files modified:** `backend/tests/test_backfill_idempotency.py`
- **Verification:** `uv run pytest -m integration backend/tests/test_backfill_idempotency.py -q` — 8 passed.
- **Committed in:** `7691a5a`

**2. [Rule 2 - Missing Critical] The plan's `test_dry_run_writes_nothing` would have passed vacuously**

- **Issue:** As written the test snapshots rows, runs with `dry_run=True`, and asserts the snapshot is unchanged. At that point in the test the table is empty (the per-test `finally` cleanup guarantees it), so the assertion is `[] == []` and holds whether or not the dry-run gate exists at all. The same applies to the `sync_state` half: with no bookkeeping rows, "no `last_synced_at` changed" is true because there are none. This is the single most load-bearing safety property in the phase — D-03 calls it "cheap insurance before committing 4.5 years of writes to production on a command that has no practical rollback" — and it would have been guarded by a test that could not fail.
- **Fix:** The test now delivers `device_capture.json` through the real webhook path first. That writes twelve rows and both `sync_state` rows, and the dry-run file would rewrite every one of them (`step_count` on 2026-09-02 would move from `6500` to `1500`). The test additionally asserts the seeded value is still `6500` afterwards, so the equality is discriminating on a specific, named row rather than only in aggregate.
- **Verification:** Confirmed by deliberate mutation. `if dry_run:` was temporarily changed to `if dry_run and not path:`; the test failed with `D-03 violated: --dry-run wrote to health_daily_metrics` and a diff showing `active_energy` moving from `560` to `300`. The mutation was reverted and `git status --short` confirmed `backfill.py` unmodified before Task 2 was committed.
- **Files modified:** `backend/tests/test_backfill_idempotency.py`
- **Committed in:** `7691a5a`

**3. [Rule 2 - Missing Critical] `test_a_real_run_advances_both_apple_health_resources` had the same vacuity, in the other direction**

- **Issue:** Asserting that two `sync_state` rows exist with equal non-null timestamps after a run does not distinguish "the run advanced them" from "the run created them from nothing" — and, more importantly, would pass unchanged if a future edit advanced them on a run that wrote no rows, which is exactly what RESEARCH Open Question 4 forbids.
- **Fix:** `_seed_apple_health` pre-creates both rows at a distinct past instant (`2026-07-04T09:15Z`) through the repository's own `ensure_sync_state`/`complete_sync`, mirroring the analog's `_seed_hevy`. The test then asserts the timestamps moved strictly *past* that instant as well as being equal to each other.
- **Files modified:** `backend/tests/test_backfill_idempotency.py`
- **Committed in:** `7691a5a`

**4. [Rule 2 - Missing Critical] A substring scan for leaked quantities is wrong in both directions**

- **Found during:** Task 2(b)
- **Issue:** The plan asks the summary test to assert the fixture's quantities do not appear "as standalone tokens" but does not say how. A plain `"228" not in text` check false-positives the moment a legitimate count reaches 1228 or 2280, and false-negatives on a real leak rendered as `228.0` — and a suite that goes red for the wrong reason teaches people to re-run it rather than read it, which is how the real leak eventually ships.
- **Fix:** The rendered block is tokenised with `re.compile(r"\d+(?:\.\d+)?")` and the forbidden values are checked for membership in that token SET. The test is also parametrized over both `dry_run` modes, because they take different branches through `format_summary` and a quantity leaking on only one of them is still a leak.
- **Files modified:** `backend/tests/test_health_auto_export_backfill.py`
- **Committed in:** `7691a5a`

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend` remains red on the same 18 pre-existing files.** Diagnosed and deferred by plan 09-01 (see `deferred-items.md`); the list is unchanged and none of the three files this plan touched is on it. All three pass `ruff format --check` individually — the new test module needed one `style(09-03)` follow-up commit (`7395622`) to get there, joining four hand-wrapped call sites that fit inside `line-length = 100`.

---

**Total deviations:** 4 auto-fixed (1 blocking, 3 missing-critical) + 1 out-of-scope item carried
**Impact on plan:** The blocking fix is a name correction. The three missing-critical fixes all have the same shape and are the substantive change: three of the plan's tests, as written, asserted a property against state that could not have violated it. Each now seeds state the operation under test *would* have changed, and the most important of the three was verified red under a deliberate mutation before being committed. No production behaviour differs from the plan; `_summarize`'s extraction is the only structural change to the shipped code, and it removes a duplication the plan's own text created.

## Issues Encountered

- **`health_ingest_multi_point_day` still reaches stdout during an integration run.** Visible in the captured output of the mutation check. This is plan 09-02's documented behaviour, not a regression: a process that never called `configure_logging` uses structlog's `PrintLoggerFactory` and bypasses stdlib logging entirely, so no `LogRecord` reaches the root handler and `_MultiPointDayCounter` never runs. It cannot happen on the real path — `cli.py` calls `configure_logging(settings)` as the first thing `main()` does — and `test_multi_point_day_warning_is_suppressed_and_counted` covers the configured case.
- **`ruff format` and `ruff check` disagreed about one line.** Four call sites were hand-wrapped across three lines to stay clearly under the limit; `ruff format` wanted them joined. Both states pass `ruff check`, so this was invisible until `ruff format --check` was run explicitly. Resolved by running `ruff format` on the one new file rather than by re-wrapping by hand — the same fix `deferred-items.md` recommends for the tree as a whole.

## Known Stubs

None. `run_backfill` writes real rows through the real constraint, `format_summary` renders real counts, and every branch of both is exercised by a test. The two files RESEARCH's test map names for later plans still do not exist and are still not this plan's scope:

- `test_backfill_real_export.py` (behind the `realfile` marker, SC#1) — the memory ceiling can only be measured against the user's gitignored 191 MB file.
- No CLI subcommand exists yet, so nothing an operator can type reaches `run_backfill`. That is plan 09-04.

## Threat Flags

None. This plan adds no network endpoint, no auth path and no schema change. Its write surface is `health_daily_metrics` and `sync_state`, both already in the phase threat model, and both reached only through helpers that take `user_id` as a keyword-only argument with no default (T-09-11). The four `mitigate` dispositions this plan owns are each pinned by an assertion:

| Threat | Where it is enforced | Where it is pinned |
|---|---|---|
| T-09-11 cross-tenant write | `user_id` keyword-only on `_upsert_many`, `_write_rows`, `run_backfill`; never read from the file | `_run` resolves it server-side; no code path reads a user id from XML |
| T-09-12 partial-write corruption | one transaction, whole-file aggregate, constraint bound by imported name, chunk `begin_nested` + per-row fallback, fresh session for `record_sync_error` | `test_running_the_backfill_twice_changes_nothing`, `test_one_bad_row_is_skipped_and_the_rest_of_the_chunk_lands` |
| T-09-13 skip-log disclosure | `reason=type(exc).__name__`; `grep -c "str(exc)"` is 0 | `test_one_bad_row_is_skipped_and_the_rest_of_the_chunk_lands` scans the rendered stream for `312.44` |
| T-09-14 stdout disclosure | `format_summary` emits counts, names, units, dates and `path.name` only | `test_summary_prints_no_measured_quantity`, both modes, by numeric token |
| T-09-15 unbacked freshness claim | `complete_sync` inside the row transaction, guarded on `written > 0`, skipped entirely on a dry run | `test_dry_run_writes_nothing`, `test_a_real_run_advances_both_apple_health_resources` |
| T-09-16 round-trip DoS | chunked upsert (~17 statements for 8,077 rows), heartbeat every 500 written rows | `health_backfill_progress` observed in the integration run's captured output |

## User Setup Required

None. No dependency was added; `pyproject.toml` and `uv.lock` are untouched. No new environment variable, no config file, no deploy artifact — this phase never deploys.

## Next Phase Readiness

**Ready for plan 09-04 (the CLI subcommand).** What it can rely on:

- `run_backfill(sessionmaker, *, user_id, path, dry_run) -> BackfillSummary` and `format_summary(summary, *, path) -> list[str]` are the ONLY two names `cli.py` needs. Neither exposes a HealthKit identifier, a wire metric name or an HAE schema type in its signature, so Pitfall 1 holds: `cli.py` can import these two and nothing else from the package, and `test_health_auto_export_isolation.py` still passes.
- `format_summary` returns lines, not printed output. `cli.py` prints them; it composes no strings of its own and therefore cannot introduce a quantity into the block.
- `run_backfill` takes an `async_sessionmaker`, matching what `db_session.make_sessionmaker(engine)` returns and what `_run_sync`/`_run_mapping_gaps` already build.
- `HAEExportFileError` is the one exception a bad path or a structurally broken file raises. It is an `HAEError`, so `format_sync_error`'s `safe_message` channel already bounds it, and `cli.py` can report it without rendering anything from the file.
- `BackfillSummary.rows_skipped` is the natural exit-code signal if 09-04 wants one; `rows_written == 0` on a real run is the other. Both are already computed.

**Carried concerns:**

- **The `--dry-run` / `--write` mutual exclusion is 09-04's to enforce, and it is the whole safety story.** `run_backfill` takes `dry_run` as a required keyword with no default precisely so no caller can omit it, but nothing at this layer stops a CLI that defaults it to `False`. 09-04's stated must-have — "invoking the subcommand with neither `--dry-run` nor `--write` exits 2 without touching the database" — is the guard.
- **RESEARCH Open Question 2 is now live in the database, not just in prose.** On any day both paths cover, `sample_count` flips between the backfill's raw-sample count and the webhook's `1`. Phase 8 documented a *falling* `sample_count` as its batch-split data-loss detector; on those days it is a false positive. Asserted deliberately in `test_backfill_then_webhook_on_the_same_day_is_one_row` and `test_webhook_then_backfill_on_the_same_day_is_one_row` so the behaviour is pinned rather than discovered.
- **Overlap between the export and live webhook data is expected to be zero days** (the export ends 2026-08-26, webhook data starts 2026-09-02), which means SC#3 will be exercised vacuously in production. The container tests are the only place it is exercised for real. Plan 09-06/09-07's dry run against the real file plus a `SELECT min(local_day), max(local_day)` is what confirms the assumption before the real write.
- **`uv run ruff format --check backend` is still red on 18 untouched files.** Any later Phase 9 plan whose verification block includes that whole-tree command will hit the same wall.

## Self-Check: PASSED

| Claim | Result |
|---|---|
| `backend/app/integrations/health_auto_export/backfill.py` | FOUND |
| `backend/tests/test_backfill_idempotency.py` | FOUND |
| `backend/tests/test_health_auto_export_backfill.py` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-03-SUMMARY.md` | FOUND |
| commit `4c48f98` | FOUND |
| commit `7691a5a` | FOUND |
| commit `7395622` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `uv run pytest -q` (full suite, container included) | PASS — 883 passed in 19.09s |
| `uv run pytest -m integration backend/tests/test_backfill_idempotency.py -q` | PASS — 8 passed |
| `uv run ruff check backend` | PASS — All checks passed |
| `uv run mypy backend/app` | PASS — no issues in 74 source files |
| `test_health_auto_export_isolation.py` still passes | PASS — 5 passed; the HAE boundary is unmoved |
| `test_health_ingest_idempotency.py` still passes | PASS — inside the 883; the webhook path is byte-for-byte untouched |

Task 1 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| `async def run_backfill(` with keyword-only `user_id`, `path`, `dry_run` | PASS |
| `_CHUNK = 500` and `_HEARTBEAT_ROWS = 500` present | PASS |
| imports `_CONFLICT_CONSTRAINT`, `_KIND_TO_RESOURCE`, `upsert_health_metric` from `ingest` | PASS |
| `grep -c 'uq_health_daily_metrics_...'` in `backfill.py` | PASS — 0 |
| all four conflict-set keys present | PASS — `value`, `units`, `sample_count`, `updated_at` |
| `if dry_run:` precedes the first `complete_sync(` by byte offset | PASS |
| `reason=type(exc).__name__` present, `grep -c "str(exc)"` | PASS — present; 0 |
| `format_summary` signature exact | PASS |
| block contains `records:`, `datapoints:`, `skipped elements:`, `date range:`, `rows by metric:`, `unrecognized types`, `freshness:` | PASS — all seven |

Task 2 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| every test function decorated `@pytest.mark.integration` | PASS — 8 of 8 |
| `grep -c "V<U+2019>s iPhone"` in `test_backfill_idempotency.py` | PASS — 0 |
| `grep -c "\\u2019"` in `test_backfill_idempotency.py` | PASS — 3 |
| `test_summary_prints_no_measured_quantity` defined | PASS |
| `test_summary_reports_the_record_accounting_identity` defined | PASS |

Plan `<success_criteria>`:

| Criterion | Result |
|---|---|
| `run_backfill` writes through a chunked `ON CONFLICT DO UPDATE` bound to the named constraint, with a per-row SAVEPOINT fallback | PASS — `test_backfill_writes_one_row_per_metric_source_and_day`, `test_one_bad_row_is_skipped_and_the_rest_of_the_chunk_lands` |
| Backfill → webhook and webhook → backfill each leave exactly one row per key | PASS — both directions, both asserting value, `sample_count`, the other phone's row, and the total row count |
| `dry_run=True` produces the full summary and changes no row and no `sync_state` timestamp | PASS — and verified red under a deliberate mutation of the gate |
| A real run advances both resources to one shared instant, in the same transaction as the rows | PASS — equality asserted, past a seeded distinct instant |
| `format_summary` renders the complete D-06 block with no measured quantity in it | PASS — both modes, scanned by numeric token |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*

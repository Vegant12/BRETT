---
phase: 09-historical-apple-health-backfill
plan: 02
subsystem: api
tags: [apple-health, healthkit, xml, iterparse, structlog, pydantic, hevy-exclusion]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    provides: "normalize_payload (allowlisting, unit conversion, is_hevy_sourced, day bucketing, aggregation), METRIC_REGISTRY's 12 wire metrics, the HAEPayload/HAEMetric/HAEDataPoint wire models, HAEError's safe_message discipline, and the HAE package isolation boundary"
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-01's export_sample.xml fixture, the hae_xml_fixture(name) -> Path loader, and the corrected Pitfall N-3 source-name convergence claim"
provides:
  - "backend/app/integrations/health_auto_export/backfill.py — HK_TO_WIRE (the twelve HealthKit identifier -> wire metric entries), an import-time totality assertion against METRIC_REGISTRY, BackfillScan, and scan_export(path, tz=) "
  - "scan_export: a pure, synchronous, database-free streaming read of export.xml that hands a literal HAEPayload to the UNCHANGED normalize_payload and returns every D-04/D-06 counter"
  - "_MultiPointDayCounter + _suppressing_multi_point_days — a stdlib handler-level filter that suppresses and counts normalize.py's health_ingest_multi_point_day warning for the backfill only"
  - "HAEExportFileError — a detail-free error for an unreadable path, a non-HealthData root, or a structural parse failure"
  - "Fourteen tests in test_health_auto_export_backfill.py (five mapping, nine behavioural) plus run_capturing_logs, the two-module log-capture helper"
affects: [09-03, 09-04, 09-05, 09-06, 09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "The backfill re-uses the webhook's normalizer LITERALLY: build an in-memory HAEPayload and call normalize_payload once for the whole file, rather than re-deriving allowlisting/conversion/exclusion/bucketing/aggregation for XML"
    - "Streaming XML in this codebase uses the two-clear discipline: elem.clear() AND root.clear() on every end event, with the root captured from the first start event (stdlib Element has no getparent())"
    - "Element-shape filtering comes BEFORE attribute reads: branch on elem.tag first, so a look-alike child element cannot enter through a shared attribute name"
    - "A per-path log-noise policy is a scoped logging.Filter on the root HANDLERS inside a context manager, never an edit to the module that emits the warning"
    - "Advisory counters vs. enforcing code: the backfill COUNTS Hevy datapoints and lets normalize_payload do the dropping, so HEALTH-08 keeps exactly one implementation"

key-files:
  created:
    - backend/app/integrations/health_auto_export/backfill.py
  modified:
    - backend/app/integrations/health_auto_export/errors.py
    - backend/tests/test_health_auto_export_backfill.py

key-decisions:
  - "The HK_TO_WIRE/METRIC_REGISTRY totality check raises at IMPORT time, not only in a test: both divergence directions are silent (an unmapped registry entry never fills; an unlisted wire name is dropped by normalize_payload's D-04 branch with one log line), so the check has to fire on the import the broken code needed anyway"
  - "The Hevy exclusion is COUNTED in backfill.py and ENFORCED in normalize_payload. Dropping the datapoint here as well would be a second implementation of HEALTH-08 that can drift from the webhook's"
  - "Buckets are keyed on (wire_metric, unit_string), not on the metric name alone: HAE units are a per-metric user preference that can change mid-history, and one HAEMetric carries exactly one metric-level `units`"
  - "The multi-point-day suppression is a stdlib handler filter in a context manager, not a change to normalize.py — the webhook path must keep warning, because there the condition is a real incident"
  - "requirements-completed stays empty, matching 09-01's precedent: all seven Phase 9 plans carry `requirements: [HEALTH-10]`, and this plan ships the read half only (no CLI subcommand, no database write, no row persisted)"

patterns-established:
  - "Counts-only result objects carry an accounting identity in their docstring and a test that pins it (`records_total == datapoints_seen + unrecognized + body_mass + malformed`), so a silently vanishing record has nowhere to hide"
  - "Log-capture helpers patch EVERY module whose logger participates in the assertion; a helper that patches one module can leave a cross-module suppression assertion vacuously green"
  - "Per-DISTINCT-key log lines, never per-record: one line per unrecognized HealthKit identifier (~35 on the real file) instead of one per unrecognized record (208,175)"

requirements-completed: []

# Metrics
duration: 34min
completed: 2026-09-03
---

# Phase 9 Plan 02: The Backfill Reader Summary

**`scan_export(path, tz=)` streams a 191 MB Apple Health `export.xml` with the two-clear `iterparse` discipline, maps twelve HealthKit identifiers onto the webhook's own wire metric names, and hands a literal `HAEPayload` to the unchanged `normalize_payload` — so the historical rows are produced by the same code path as the live ones rather than by a second parser that can drift.**

## Performance

- **Duration:** ~34 min
- **Started:** 2026-09-03T11:52Z
- **Completed:** 2026-09-03T12:26Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- **The ROADMAP's stated Phase 9 failure mode is now structurally impossible.** "Two parsers produce two shapes and the historical trend silently disagrees with the ongoing one" was the risk; `backfill.py` contains no allowlist, no unit conversion, no Hevy predicate, no day bucketing and no aggregation. It builds an in-memory `HAEPayload` and calls `normalize_payload` once. The only new domain logic in this plan is the XML tag walk and the twelve-entry identifier table.
- **Pitfall 3's back door is closed and tested.** The fixture's `<Workout sourceName="Hevy">` nests a `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="228"/>` that carries an allowlisted `type=` and no `sourceName` — so `is_hevy_sourced(None)` returns `False` by design and would not filter it. `scan_export` branches on `elem.tag == "Record"` before it ever reads `type=`, and `test_non_record_elements_never_ingested` asserts the total `active_energy` across all rows is exactly `Decimal("300")` — the one legitimate record. If the 228 kcal ever leaked in, the total would read 528 while the D-04 counter still reported "1 workout skipped".
- **The record accounting identity holds on the fixture.** All 21 `<Record>` elements are explained: 16 datapoints + 2 unrecognized + 1 body mass + 2 malformed. A record the tag walk silently drops has nowhere to hide, because the row set would still look plausible and the missing days would only surface as a gap in a trend months later.
- **The Pitfall 4 flood is suppressed and counted without touching the webhook path.** `normalize_payload` emits `health_ingest_multi_point_day` for 7,403 of 8,077 rows on the real file (91.7%) — normal for raw HealthKit samples, an incident for the webhook. A `logging.Filter` attached to the root *handlers* inside a context manager swallows and counts it for the duration of the backfill's one `normalize_payload` call. `test_multi_point_day_warning_is_suppressed_and_counted` asserts both halves: nothing reached the stream during the scan, and a direct `normalize_payload` call afterwards *does* still warn.
- **T-09-07 is pinned at the log line, not just at the exception class.** Malformed records log a fixed token (`unparsable_value`, `missing_start_date`) and the HealthKit type identifier — never the offending attribute string. `test_malformed_record_does_not_abort` serialises every captured log entry and asserts `not-a-number` appears nowhere in it.

## Task Commits

Each task was committed atomically:

1. **Task 1: backfill.py skeleton — module docstring, HK_TO_WIRE, counters, mapping tests** — `5793100` (feat)
2. **Task 2: The streaming scan — iterparse loop, per-record validation, HAEPayload handoff** — `599d949` (feat)

**Plan metadata:** see the final `docs(09-02)` commit.

## Files Created/Modified

- `backend/app/integrations/health_auto_export/backfill.py` — new. A ~78-line module docstring in the house decision-record style (why `normalize_payload` is reused literally, the measured two-clear memory table, why `type=` alone is never enough, why the parse cannot be chunked, the logging rule, the XML trust argument), then `HK_TO_WIRE` with all five naming traps named in a comment block, the import-time totality assertion, `BackfillScan`, `_MultiPointDayCounter`, `_suppressing_multi_point_days`, `scan_export` and `_read_quantity`.
- `backend/app/integrations/health_auto_export/errors.py` — appended `HAEExportFileError`, constructed from nothing, carrying a fixed `safe_message` and no path.
- `backend/tests/test_health_auto_export_backfill.py` — grew from 6 fixture-integrity tests to 20. Five mapping tests (totality, the five naming traps line by line, the `HKQuantityTypeIdentifier` prefix, body mass absent, the error signature) and nine behavioural tests over `scan_export`, plus `run_capturing_logs`, which renders the REAL logging pipeline into a buffer and patches both `backfill.log` and `normalize.log`.

## Decisions Made

- **`_MultiPointDayCounter` attaches to the root HANDLERS, not to a logger.** `configure_logging` installs one root `StreamHandler`, every module in the HAE package logs through its own `structlog.get_logger()` (so the stdlib logger name differs per module), and a logger-level filter does not see propagated records. A handler-level filter sees all of them. With `ProcessorFormatter.wrap_for_formatter`, `record.msg` *is* the structlog event dict, which is why the filter reads a key rather than matching a rendered string.
- **The handler list is snapshotted on entry and the same list is used on exit.** `configure_logging` replaces `root.handlers` wholesale, so iterating the live list on the way out could remove the filter from a different handler than the one it was added to — leaving a process-wide filter installed that silently eats the webhook's warning for the rest of the run.
- **`unrecognized_types` leaves `scan_export` as a `MappingProxyType(dict(...))`, not the live `defaultdict`.** Handing the `defaultdict` out would let a caller's missing-key read silently create a zero entry and change what the D-06 summary reports.
- **`requirements-completed: []`.** Same reasoning 09-01 recorded. This plan has no CLI entry point and writes no row; `HEALTH-10` is not satisfiable until the write half and the CLI land. Marking it now would be a false completion claim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] A mid-stream `ET.ParseError` would have escaped with a byte offset into the user's health history**

- **Found during:** Task 2 (`scan_export`)
- **Issue:** The plan's `try`/`except` covers only `ET.iterparse(...)` and the first `next(it)`. A structural XML break *later* in the file (a truncated export is the realistic case) raises `ET.ParseError` from inside the loop and propagates to the caller unhandled. `str(ParseError)` renders `not well-formed (invalid token): line 91, column 19` — exactly the "byte offset into a document that is this person's entire health history" that the plan's own `HAEExportFileError` docstring says must never be exposed (T-09-07). The plan's docstring for that class explicitly claims it covers "a parse failure that is structural rather than per-record", so the intent was clear; the code shape did not implement it.
- **Fix:** Wrapped the `for event, elem in it:` loop in `except ET.ParseError`, logging `type(exc).__name__` only and raising `HAEExportFileError from None`. This does not weaken D-07: D-07 is about malformed *records* (bad attribute values), which `_read_quantity` still skips and counts; a structural break means expat cannot continue and there is no remaining file to salvage.
- **Files modified:** `backend/app/integrations/health_auto_export/backfill.py`
- **Verification:** `uv run pytest -m 'not integration' -q` green; `test_unreadable_file_raises_a_detail_free_error` asserts `str(exc)` contains neither the path nor the word `line` for both the missing-file and non-`HealthData` cases.
- **Committed in:** `599d949` (Task 2 commit)

**2. [Rule 2 - Missing Critical] `Decimal("NaN")` and `Decimal("Infinity")` parse successfully and would have reached the database**

- **Found during:** Task 2 (`_read_quantity`)
- **Issue:** The plan's validation catches `InvalidOperation`/`ValueError` from `Decimal(raw_value)`. Neither fires for `"NaN"`, `"Infinity"` or `"-Infinity"` — `Decimal` accepts all three. A non-finite quantity would flow through `normalize_payload`'s `sum` (poisoning the whole `(metric, source_name, local_day)` bucket, not just its own datapoint) into a `Numeric(14, 4)` column, which PostgreSQL accepts for `NaN`. The result is a plausible-looking number that is quietly wrong, which CLAUDE.md and `registry.to_canonical`'s docstring both name as this project's primary risk.
- **Fix:** Added a `qty.is_finite()` check after the parse, logging a fourth fixed reason token `non_finite_value` and returning `None` (skip-and-count, same as the other three paths). The record accounting identity is unaffected — it is still a malformed record.
- **Files modified:** `backend/app/integrations/health_auto_export/backfill.py`
- **Verification:** `uv run pytest -m 'not integration' -q` green (the fixture carries no non-finite value, so no existing count changed); `uv run mypy backend/app` clean.
- **Committed in:** `599d949` (Task 2 commit)

**3. [Rule 3 - Blocking] The plan's `HK_TO_WIRE` totality-assertion snippet references `METRIC_REGISTRY` at import time, but Task 1's import list would have been unused**

- **Found during:** Task 1 (`uv run ruff check backend`)
- **Issue:** The plan's Task 1 action lists the full import block including `HAEExportFileError`, `is_hevy_sourced`, `normalize_payload`, `HAEPayload`, `Path`, `Decimal`, `defaultdict`, `contextmanager` and `logging` — all of which are first *used* in Task 2. Written verbatim, Task 1's commit would fail `ruff check` on nine `F401` unused-import errors, and Task 1's own acceptance criterion is that `ruff check backend` exits 0.
- **Fix:** Task 1 imports only what Task 1 uses; Task 2 adds the rest. The `from xml.etree import ElementTree as ET  # noqa: S314` line (a Task 1 acceptance criterion) is kept in Task 1 and made genuinely used by the `_XMLEvent = tuple[str, ET.Element]` type alias, which Task 2 then uses to annotate the `iterparse` iterator.
- **Files modified:** `backend/app/integrations/health_auto_export/backfill.py`
- **Verification:** `ruff check backend` exits 0 at both Task 1 and Task 2 commits.
- **Committed in:** `5793100` (Task 1) and `599d949` (Task 2)

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend` still exits 1 on 18 pre-existing files.** Diagnosed and deferred by plan 09-01 (see `deferred-items.md`); the count is unchanged. All three files this plan touched pass `ruff format --check` individually.

---

**Total deviations:** 3 auto-fixed (2 missing-critical, 1 blocking) + 1 out-of-scope item carried
**Impact on plan:** Both missing-critical fixes close a path by which a raw health-data string or a silently-wrong number reaches a log sink or the database — the two failure classes this phase's threat model is built around, and both were already asserted as impossible in prose the plan itself supplied. The blocking fix is a commit-ordering detail with no behavioural effect. No scope creep; `normalize.py` and `registry.py` are byte-for-byte unchanged.

## Issues Encountered

- **`multi_point_days` reads 0 in a process that never called `configure_logging`.** Unconfigured structlog uses `PrintLoggerFactory` and bypasses stdlib logging entirely, so no `LogRecord` reaches the root handler and the filter never runs — the warnings print and the count stays 0. This cannot happen on the real path (`cli.py` calls `configure_logging(settings)` as the first thing `main()` does, before any logger or engine exists) and the behaviour is now stated explicitly in `_suppressing_multi_point_days`' docstring. It is the reason `test_multi_point_day_warning_is_suppressed_and_counted` runs the scan *inside* `run_capturing_logs` rather than bare.
- **`ET.iterparse` opens the file eagerly on Python 3.13.** Verified by reading the installed `xml/etree/ElementTree.py` rather than assuming: `open(source, "rb")` happens before the generator is created, so `FileNotFoundError` surfaces at the `ET.iterparse(...)` call and the plan's `_, root = next(it)` really does yield the `("start", HealthData)` pair. On some earlier CPython versions the first `next()` yielded `None`, which would have made the plan's unpacking raise `TypeError`.

## Known Stubs

None in this plan's own surface. The two files RESEARCH's test map names for later plans still do not exist and are not this plan's scope:

- `test_backfill_idempotency.py` (integration, SC#3) — whether a second write of the same key is an update or an insert is a property of the upsert, which plan 09-04 owns.
- `test_backfill_real_export.py` (behind the `realfile` marker, SC#1) — the memory ceiling can only be measured against the user's gitignored 191 MB file.

`scan_export` itself is complete and returns real data; nothing in it is a placeholder.

## Threat Flags

None. `backfill.py` introduces no network endpoint, no auth path and no schema change. Its only new surface is a local file read, which is T-09-05 in the plan's own register (disposition: accept, with the justification recorded on the `noqa` rather than only in the plan).

## User Setup Required

None — no external service configuration required. No dependency was added; `uv.lock` and `pyproject.toml` are untouched (this phase is stdlib-only).

## Next Phase Readiness

**Ready for plan 09-03 (the CLI subcommand) and 09-04 (the write half).** What they can rely on:

- `scan_export(path, tz=...) -> BackfillScan` is pure and synchronous. It takes no session, opens no connection, and can be called from a `--dry-run` path with no write machinery in place at all.
- `BackfillScan` already carries every number D-06's summary block needs: `records_total`, `records_unrecognized`, `records_malformed`, `body_mass_skipped`, `workouts_skipped`, `activity_summaries_skipped`, `hevy_datapoints_excluded`, `multi_point_days`, `unrecognized_types`, and `normalized` (which carries `rows`, `kinds_present` and the three normalize counters). D-06 explicitly requires the workout/summary skip counts and the Hevy-exclusion count; none of them needs re-deriving.
- `normalized.rows` is the ONLY safe input to a batched upsert. RESEARCH Pitfall 5 measured `CardinalityViolationError` against real Postgres 18 for a multi-row `ON CONFLICT DO UPDATE` with duplicate conflict keys; `normalize_payload` returns rows keyed by a dict, so duplicates are structurally impossible — but only if the chunk list is built from a single `NormalizeResult` and never from two concatenated ones.
- `HAEExportFileError` is the one exception `scan_export` raises for a structural failure. It is an `HAEError`, so `format_sync_error`'s `safe_message` channel already handles it.

**Carried concerns:**

- `multi_point_days` under-reports as 0 if a future caller invokes `scan_export` before `configure_logging`. The CLI path is safe; a test or a script that calls it bare is not.
- Pitfall 1 stands and now has teeth: `cli.py` may not import `registry` or `schemas`, and `test_health_auto_export_isolation.py` enforces it. Plan 09-03's CLI must reach `scan_export` (and only `scan_export`) from `backfill.py`, which is inside the package.
- RESEARCH Open Question 2 is unresolved and now concrete: `sample_count` on backfilled days holds the raw-sample count (91.7% of rows aggregate more than one datapoint) while the webhook writes `sample_count = 1` for its daily aggregate. Phase 8 documented a *falling* `sample_count` as its batch-split-data-loss detector, so on any day covered by both paths that detector will produce a false positive. The fixture already exercises this (`step_count` on 2026-09-02 has `sample_count == 2`).
- `uv run ruff format --check backend` remains red on 18 untouched files (`deferred-items.md`). Any later Phase 9 plan whose verification block includes that whole-tree command will hit the same wall.

## Self-Check: PASSED

| Claim | Result |
|---|---|
| `backend/app/integrations/health_auto_export/backfill.py` | FOUND |
| `backend/app/integrations/health_auto_export/errors.py` | FOUND |
| `backend/tests/test_health_auto_export_backfill.py` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-02-SUMMARY.md` | FOUND |
| commit `5793100` | FOUND |
| commit `599d949` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `uv run pytest -m 'not integration' -q` | PASS — 550 passed, 322 deselected |
| `uv run pytest backend/tests/test_health_auto_export_backfill.py -q` | PASS — 20 passed |
| `uv run pytest backend/tests/test_health_auto_export_isolation.py -q` | PASS — 5 passed |
| `uv run pytest backend/tests/test_health_auto_export_normalize.py -q` | PASS — 54 passed (webhook path unchanged) |
| `uv run ruff check backend` | PASS — the only suppressed rule is the single scoped `S314` |
| `uv run mypy backend/app` | PASS — no issues in 74 source files |
| Importing `backfill` raises nothing; `HK_TO_WIRE` and `METRIC_REGISTRY` agree | PASS — `len(HK_TO_WIRE) == 12` |

Plan `<success_criteria>`:

| Criterion | Result |
|---|---|
| `scan_export` returns a `BackfillScan` whose `normalized` came from the unchanged `normalize_payload` | PASS — `normalize.py` byte-for-byte unchanged in this plan's diff |
| The record accounting identity holds on the fixture (21 records fully explained) | PASS — 16 + 2 + 1 + 2 == 21 |
| `Workout`, `WorkoutStatistics`, `ActivitySummary` and `BodyMass` contribute zero datapoints | PASS — total `active_energy` == `Decimal("300")`, no `unknown` source name |
| A Hevy-sourced `ActiveEnergyBurned` record is excluded by `is_hevy_sourced` and counted separately | PASS — `hevy_datapoints_excluded == 1`, `datapoints_dropped == 1`, no `Hevy` row |
| Two malformed records are skipped and counted; the scan reaches the end of the file | PASS — `records_malformed == 2`, rows still produced for 2026-09-02 |
| The Pitfall 4 flood is suppressed and counted for the backfill only; the webhook path still warns | PASS — both halves asserted |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*

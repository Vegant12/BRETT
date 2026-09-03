---
phase: 09-historical-apple-health-backfill
plan: 05
subsystem: testing
tags: [apple-health, healthkit, xml, pytest, realfile, memory, docs, sample-count]

# Dependency graph
requires:
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-01's `realfile` pytest marker, and plan 09-02's `scan_export(path, tz=) -> BackfillScan` — the pure, database-free streaming read this plan measures against the actual 191 MB export.xml"
  - phase: 08-apple-health-nutrition-ingest
    provides: "normalize_payload's NormalizeResult/NormalizedRow shape (rows, datapoints_seen, datapoints_dropped, sample_count), configure_logging's single-root-handler pipeline, and docs/health-auto-export-setup.md §7"
provides:
  - "backend/tests/test_backfill_real_export.py — eleven opt-in tests that prove SC#1 against the ACTUAL export.xml and pin its measured shape, gated by both the `realfile` marker and a `skipif` on the gitignored file's existence"
  - "The pinned ground truth for the export dated 2026-08-26 10:09:33 +0700: 191,257,897 bytes, 438,649 records, the accounting identity 438,649 == 230,395 + 208,175 + 79 + 0, 224/1,443/79/209 exclusions, 8,077 rows across 1,631 local days, twelve per-metric row counts, 7,403 suppressed multi-point-day warnings, ~34 grouped unrecognized types"
  - "A traced-allocation and wall-clock ceiling (800 MB / 120 s) that fails loudly if the streaming discipline is replaced by an unbounded read"
  - "docs/health-auto-export-setup.md §7's `sample_count` false-positive subsection — the discriminator between the one-time backfill artefact and a real batch-split data loss, closing RESEARCH Open Question 2"
  - "The four `health_backfill_*` log events documented in §7's events table"
affects: [09-06, 09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A test whose input is gitignored user data carries TWO gates, not one: a marker CI deselects explicitly, and a `skipif` on file existence so absence is a skip and never a failure"
    - "Assertions against real health data are restricted to counts, element names, HealthKit identifiers, units and dates — the same class of information the project's logging rule already permits a log line to carry"
    - "Every pinned figure's assertion message names the remedy (`re-derive from a fresh --dry-run summary`), so a re-export reads as a re-pin rather than an invitation to edit one number until it goes green"
    - "A module-scoped fixture performs the expensive real-file pass once and returns (result, elapsed, peak_traced_bytes)"

key-files:
  created:
    - backend/tests/test_backfill_real_export.py
  modified:
    - docs/health-auto-export-setup.md

key-decisions:
  - "The `scan` fixture installs the REAL logging pipeline (pointed at a throwaway buffer) before calling scan_export, because `multi_point_days` is produced by a `logging.Filter` on the root handlers and reads 0 in a process that never called `configure_logging` — the plan's bare-call fixture would have pinned a number that only means 'logging was not set up'"
  - "`-m 'not integration'` does NOT deselect these tests where export.xml is present; the marker's own contract is `-m 'not realfile'`. The correct fast-suite invocation is `-m 'not integration and not realfile'`"
  - "The §7 events table gained exactly the four rows the plan specified. `health_backfill_record_skipped` and `health_backfill_unrecognized_type` (which plan 09-02 already emits) were deliberately NOT added — the complete operator event catalogue belongs to plan 09-06's runbook"
  - "`requirements-completed: []`, matching 09-01 and 09-02. All seven Phase 9 plans carry `requirements: [HEALTH-10]`; this plan writes no row and adds no CLI entry point"

patterns-established:
  - "Ceiling-not-measurement constants carry a comment saying so, with the measured figure beside them, so a later reader does not tighten a ceiling into a flaky equality"
  - "A loose bound (`< 60` distinct unrecognized identifiers against ~34 observed) where the property under test is an order of magnitude ('per type, not per record'), so a new Apple Health release adding identifiers is not a failing test"

requirements-completed: []

# Metrics
duration: 13min
completed: 2026-09-03
---

# Phase 9 Plan 05: The Real-File Proof Summary

**Eleven opt-in tests run `scan_export` over the user's actual 191,257,897-byte `export.xml` and prove success criterion #1 the only way a 21-record fixture cannot — 438,649 elements stream to completion inside an 800 MB traced-allocation ceiling — while pinning the file's measured shape so a re-export or a parser regression announces itself; and §7 of the operator doc now explains why a `sample_count` falling from N to 1 on a backfilled day is a false positive rather than the data loss Phase 8 taught the reader to fear.**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-09-03T05:22Z
- **Completed:** 2026-09-03T05:35Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- **Criterion #1 is measured, not argued.** Every figure the plan supplied was independently reproduced against the real file before a single assertion was written: 438,649 records, 208,175 unrecognized, 79 body mass, 224 workouts, 1,443 activity summaries, 209 Hevy datapoints, 230,395 datapoints seen, 8,077 rows, 230,186 samples aggregated, 2022-03-10 → 2026-08-26 over 1,631 distinct local days, all twelve per-metric row counts, 7,403 multi-point days and 34 distinct unrecognized identifiers. All matched. The scan peaks at **244.5 MB of traced allocation in ~23 s under `tracemalloc`** (~4.5 s without), against ceilings of 800 MB and 120 s.
- **The record accounting identity now holds against 438,649 real records, not 21 synthetic ones.** `438,649 == 230,395 + 208,175 + 79 + 0` is asserted term by term, and the assertion message prints every term when it fails. A record the tag walk silently drops has nowhere to hide on the file that actually matters.
- **The Hevy exclusion is confirmed rather than inherited.** `normalize.py` documents "209 records across 209 training days" as a measured claim. This module re-derives 209 from the export itself, asserts that `normalize_payload` independently dropped the same 209, and asserts no surviving row carries a Hevy source name. Pitfall N-3's stated warning sign — "a filter that never excludes anything" — now has a detector on the one dataset where Hevy demonstrably did write back to HealthKit.
- **CI can never read this file, by two independent mechanisms.** A `realfile` marker it deselects explicitly, and a `skipif` so a developer without the file gets a clean skip. Verified both ways: `-m realfile` → 11 passed; `-m 'not realfile'` → 11 deselected.
- **No measured quantity crosses into the repository.** `grep -cE "Decimal\(|\.value\b"` returns 0. The module docstring states the rule explicitly — counts, element names, HealthKit identifiers, units and dates only — so a later edit that adds a step total has to walk past it.
- **RESEARCH Open Question 2 is closed in the place it will be needed.** Not in a planning file, but in §7 of the operator doc, immediately below the alarm it produces a false positive for — with a three-row discriminator table (which day, what happens to the total, how often) so the inverse error, dismissing a real batch-split loss as "just the backfill", is guarded too.

## Task Commits

Each task was committed atomically:

1. **Task 1: The opt-in real-file test** — `9dfb65a` (test)
2. **Task 2: Document the `sample_count` false positive** — `5ff9d19` (docs)

**Plan metadata:** see the final `docs(09-05)` commit.

## Files Created/Modified

- `backend/tests/test_backfill_real_export.py` — new, 449 lines. A module docstring stating why this file is unlike every other test in the suite (gitignored input, two gates), what may and may not be asserted, and that the pinned figures describe one specific export. Then the ceilings with their measured counterparts, a `_REPIN` message appended to every pinned assertion, twenty pinned constants, the `pytestmark` gate pair, the module-scoped `scan` fixture, and eleven tests.
- `docs/health-auto-export-setup.md` — §7 only. Four `health_backfill_*` rows appended to the events table, its lead-in changed from "Two related events, both safe to read" to "Related events, all safe to read" plus a clause distinguishing the backfill events from the phone's, and a new `### After the historical backfill: a falling \`sample_count\` is expected, once` subsection ahead of the `---` that opens §8. Every pre-existing heading (`## 1.` through `## 9.` and both dated `###` subsections) is intact.

## Decisions Made

- **The fixture configures logging; the plan's version did not.** See Deviations — this is the one substantive departure and it is the difference between `multi_point_days == 7_403` and `multi_point_days == 0`.
- **`-m 'not integration'` was not made to deselect these tests.** The plan's acceptance criteria assert both that `-m 'not integration'` "does not run these tests" *and* that `-m 'not realfile'` reports 11 deselected. Only the second is true where `export.xml` is present; `not integration` has nothing to say about a `realfile` marker. Making it true would mean adding `addopts` to `pyproject.toml` — a shared file, mid-wave, that plan 09-03 is concurrently able to touch, to change a suite-wide default this plan does not own. The marker's registered help text already states its own contract (`deselect with -m 'not realfile'`). Recorded here rather than silently satisfied.
- **The events table gained four rows, not six.** `health_backfill_record_skipped` and `health_backfill_unrecognized_type` already ship in `backfill.py` and are absent from the table. That is the plan's scope boundary, not an oversight: plan 09-06 owns the operator runbook and the complete event catalogue, and pre-empting it here would put two partial lists in two documents.
- **A loose bound on the unrecognized-type count.** `< 60` against 34 observed. The property under test is the order of magnitude — one log line per *type* (~34) instead of per *record* (208,175) — and an Apple Health release that adds two identifiers must not read as a regression.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's `scan` fixture would have pinned `multi_point_days == 0`, not 7,403**

- **Found during:** Task 1, pre-flight measurement against the real file (before writing a line of the test)
- **Issue:** The plan's fixture calls `scan_export` bare. `multi_point_days` is produced by `_MultiPointDayCounter`, a `logging.Filter` that `backfill.py` attaches to the **root log handlers**; a process that never called `configure_logging` has no root handler and unconfigured structlog bypasses stdlib logging entirely, so the filter never runs and the counter reads 0. Plan 09-02's own summary flagged this exact hazard ("`multi_point_days` under-reports as 0 if a future caller invokes `scan_export` before `configure_logging`… a test or a script that calls it bare is not [safe]"), and this plan is that caller. Written as specified, `test_the_real_export_multi_point_day_warnings_are_counted_not_emitted` would have failed against `7_403`; "fixing" it by pinning 0 would have produced a test asserting that logging was not set up.
- **Fix:** The fixture installs the real pipeline for the duration of the scan — `configure_logging(Settings(_env_file=None))`, `cache_logger_on_first_use=False`, fresh proxies on `backfill.log` and `normalize.log`, the root handler's stream pointed at a discarded `io.StringIO` — and restores handlers, level, module loggers and the structlog cache setting in a `finally`. This mirrors `run_capturing_logs` in `test_health_auto_export_backfill.py` and, more importantly, mirrors the real run: `cli.py` calls `configure_logging` as the first thing `main()` does.
- **Files modified:** `backend/tests/test_backfill_real_export.py`
- **Verification:** `multi_point_days == 7_403` as pinned; the full fast suite is 561 passed with no ordering effects from the module-scoped logging swap.
- **Committed in:** `9dfb65a` (Task 1 commit)

**2. [Rule 3 - Blocking] The worktree had neither `export.xml` nor a virtualenv**

- **Found during:** Task 1 setup
- **Issue:** `export.xml` is gitignored, so a fresh git worktree does not have it — the `skipif` would have skipped all eleven tests and the plan's acceptance criterion ("exits 0 with 11 passed, the real `export.xml` is present at the repo root") would have been unverifiable. The worktree also had no `.venv`.
- **Fix:** A read-only symlink at the worktree root pointing at the real file in the main repo, plus `uv sync --group dev --frozen`. `git check-ignore` confirms the symlink is covered by `.gitignore:16`, and `git status` stayed clean throughout; nothing about it is committed, and it disappears with the worktree.
- **Files modified:** none (untracked, gitignored setup only)
- **Verification:** `EXPORT_XML.stat().st_size == 191_257_897` through the symlink; `git status --short` empty at both commits.
- **Committed in:** n/a — no repository change

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend` still exits 1 on 18 pre-existing files.** Diagnosed and deferred by plan 09-01 (`deferred-items.md`), unchanged by 09-02, unchanged here. `backend/tests/test_backfill_real_export.py` passes `ruff format --check` individually.

**The `-m 'not integration'` / `realfile` interaction.** See Decisions Made. Not a defect in anything this plan produced; recorded because the phase's later plans and the verifier will run that command and see 561 tests where they may expect 550.

---

**Total deviations:** 1 auto-fixed bug + 1 blocking setup fix + 2 out-of-scope items recorded
**Impact on plan:** The logging fix is the difference between a test that proves the Pitfall 4 suppression works on the real file and one that proves nothing. Everything else is environment. No file outside the plan's `files_modified` list was touched; `backfill.py`, `normalize.py` and `pyproject.toml` are byte-for-byte unchanged.

## Issues Encountered

- **A one-character database password silently broke the log filter during measurement.** The first pre-flight run reported `multi_point_days: 0` *with* logging configured. Cause: the probe used `postgresql://u:p@…`, and `make_value_scrubber` replaces every occurrence of a secret value in every string — including the event name, which became `health_ingest_multi_***REDACTED***oint_day` and no longer matched the filter's comparison. Not a defect (the redaction layer is doing exactly its job on a degenerate secret), but worth writing down: **a short or common `DATABASE_URL` password corrupts log-event names**, and any future test that matches on an event string can be broken by the environment it runs in. The suite's own `_PLACEHOLDER_DB_URL` (`postgresql://test:test@…`) is long enough to be safe.
- **`tracemalloc` costs ~5x wall time on this file** — ~23 s traced against ~4.5 s bare. That is why the wall-clock ceiling is 120 s and not, say, 30 s: the ceiling has to survive the measurement apparatus it is measured through.

## Known Stubs

None in this plan's surface. The two files this plan's module docstring points at as living elsewhere are correctly elsewhere:

- `test_backfill_idempotency.py` (integration, SC#3) — plan 09-04 owns the upsert.
- The CLI `--dry-run` summary that every assertion message tells a future reader to re-derive from — plan 09-03. Its absence does not weaken the messages: the remedy they name is the one that will exist by the time anyone hits a re-pin.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no schema change and no new file read outside the one the phase already reads. Its only new surface is a test module whose input is a local, gitignored, user-owned file, guarded by the two gates T-09-23 asks for.

## User Setup Required

None for the repository. **To run these tests locally you need `export.xml` at the repo root** — it is gitignored and is the user's own Health app export. Without it all eleven skip with a message saying so.

## Next Phase Readiness

**Ready for 09-06 (operator runbook) and 09-07 (the dated run record).** What they can rely on:

- Every figure the runbook and the run record need to quote is now asserted rather than transcribed: record totals, exclusion counts, row count, sample total, date range and per-metric rows. If any of them is wrong in a doc, `pytest -m realfile` says so.
- §7 of `docs/health-auto-export-setup.md` already carries the four `health_backfill_*` events and the `sample_count` discriminator, so 09-06's runbook can reference §7 instead of restating it.
- The `--dry-run` summary is now load-bearing in committed prose: eleven assertion messages tell a future reader to re-derive the pinned figures from it. Plan 09-03 should make sure the summary it prints actually contains every one of them (records total, unrecognized, malformed, body mass, workouts, activity summaries, Hevy excluded, datapoints seen/dropped, rows, date range, per-metric counts).

**Carried concerns:**

- `-m 'not integration'` runs these eleven tests on the user's machine (~27 s) because `not integration` does not imply `not realfile`. If a later plan or the phase verifier wants the old 550-test fast suite, the invocation is `-m 'not integration and not realfile'`.
- The pinned figures are a snapshot of one export. If the user re-exports before 09-07's real run, this module goes red in eleven places at once — which is the intended behaviour, and the messages say what to do.
- `uv run ruff format --check backend` remains red on 18 untouched files (`deferred-items.md`).

## Self-Check: PASSED

| Claim | Result |
|---|---|
| `backend/tests/test_backfill_real_export.py` | FOUND |
| `docs/health-auto-export-setup.md` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-05-SUMMARY.md` | FOUND |
| commit `9dfb65a` | FOUND |
| commit `5ff9d19` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` | PASS — 11 passed in 26.99s |
| `uv run pytest -m 'not integration' -q` | PASS — 561 passed, 322 deselected (includes the 11 realfile tests; see Decisions Made) |
| `uv run ruff check backend` | PASS — all checks passed |
| `uv run pre-commit run --files docs/health-auto-export-setup.md` | PASS — gitleaks, large-files, end-of-file, trailing-whitespace all passed; ruff hooks correctly skipped |
| `backend/tests/test_health_auto_export_isolation.py` still passes | PASS — 5 passed |
| `uv run mypy backend/app` (not required, run anyway) | PASS — no issues in 74 source files |
| `uv run pytest -m 'not realfile' backend/tests/test_backfill_real_export.py -q` | PASS — 11 deselected |
| `grep -cE "Decimal\(\|\.value\b" backend/tests/test_backfill_real_export.py` | PASS — 0 |

Plan `<success_criteria>`:

| Criterion | Result |
|---|---|
| The real 191,257,897-byte `export.xml` streams under an 800 MB traced-allocation ceiling and 120 s | PASS — 244.5 MB, ~23 s under `tracemalloc` |
| The record accounting identity `438,649 == 230,395 + 208,175 + 79 + 0` is asserted against the actual file | PASS |
| 224 workouts, 1,443 activity summaries, 79 body-mass records and 209 Hevy datapoints all proven excluded | PASS |
| 8,077 rows spanning 2022-03-10 → 2026-08-26 across 1,631 distinct local days proven produced | PASS |
| The tests skip cleanly without the file and are deselected from the default suite | PASS on both gates — `skipif` on `EXPORT_XML.exists()`, and `-m 'not realfile'` reports 11 deselected |
| §7 explains the one-time `sample_count` false positive and lists the four backfill log events | PASS |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*

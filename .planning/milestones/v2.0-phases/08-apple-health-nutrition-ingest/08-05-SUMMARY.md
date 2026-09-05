---
phase: 08-apple-health-nutrition-ingest
plan: 05
subsystem: integrations
tags: [health-auto-export, apple-health, nutrition, normalization, aggregation, tdd, structlog]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    plan: 01
    provides: "HealthDailyMetric's 5-column natural key (source_name IS a key column) and the three real-shape HAE fixtures"
  - phase: 08-apple-health-nutrition-ingest
    plan: 04
    provides: "METRIC_REGISTRY + to_canonical, the HAEPayload wire quarantine, parse_hae_datetime, the payload-free error taxonomy"
  - phase: 01-backend-foundation
    provides: "app.core.time.local_day -- the only sanctioned local-day resolution, with tz always a parameter"
  - phase: 03-hevy-integration
    provides: "hevy/body.py SOURCE_HEVY as the constant-beside pattern; hevy/events.py's frozen-slotted counts-only result type and structured-log-on-skip shape"
provides:
  - "is_hevy_sourced(): the HEALTH-08 source-level exclusion predicate, case-folded and whitespace-stripped over a frozenset of aliases"
  - "NormalizedRow: one day-grained row in BRETT's vocabulary, carrying the CANONICAL unit and a truthful sample_count"
  - "NormalizeResult: rows sorted by (metric, source_name, local_day), kinds_present, and three counters satisfying an accounting identity"
  - "normalize_payload(payload, *, tz): the whole-payload collapse plan 08-06's replace-semantics upsert depends on"
  - "SOURCE_APPLE_HEALTH / UNKNOWN_SOURCE_NAME: the two column constants plan 08-06 writes"
  - "health_ingest_multi_point_day: Pitfall N-2's silent data-loss mode made observable"
  - "health_ingest_hevy_source_excluded: Pitfall N-3's 'filter that never matches' made observable"
affects: [08-06, 08-07, 08-08, 09-historical-backfill, 13-reports-and-nutrition-trends]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exclusion at WRITE time, not read time: a requirement phrased as 'never count X' becomes a row-count fact instead of a rule every future reader must remember"
    - "Aggregate the whole payload before the first write, so idempotency is a property of the type rather than a discipline the caller remembers"
    - "An accounting identity across a result type's counters (seen - dropped == sum of sample_counts), so a silently vanishing datapoint has nowhere to hide"
    - "A negative-space assertion beside every exclusion assertion: a filter that excluded everything must fail, not pass vacuously"

key-files:
  created:
    - backend/app/integrations/health_auto_export/normalize.py
    - backend/tests/test_health_auto_export_normalize.py
  modified: []

key-decisions:
  - "Open Question 1 resolved as the plan directed: the Hevy exclusion runs at write time, so a Hevy-sourced datapoint never becomes a row"
  - "Open Question 2 resolved as the plan directed: kinds_present carries only kinds with >= 1 ACCEPTED row, so a fully-dropped payload advances neither D-03 sync_state resource"
  - "Pitfall N-4 resolved as the plan directed: local_day wins over the payload's own date part, pinned by four zones over one instant"
  - "datapoints_seen counts EVERY datapoint including those under an unrecognised metric, which makes the counters an accounting identity rather than three unrelated numbers"
  - "The avg branch tests `== \"avg\"` rather than `!= \"sum\"`: a future third aggregation then sums (the registry's overwhelming default) and fails a test, instead of silently averaging"
  - "REQUIREMENTS.md deliberately left unmodified -- HEALTH-06/08 and NUTR-02 are also claimed by 08-06/07/08 and nothing ingests yet"

patterns-established:
  - "Mutation-checking a security guard before trusting it: a temporary leak was injected into a log call and the log-safety test was confirmed to fail, then reverted"
  - "A log-safety forbidden set walked out of the fixtures it protects, keyed on the value and valued by the origin -- so the failure message names the metric without printing the measurement"
  - "run_capturing_logs(): the real logging pipeline into a buffer, with structlog's first-use cache defeated and the module handed a fresh proxy, so a capture cannot silently check nothing"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-09-02
---

# Phase 8 Plan 05: HAE Normalization and Aggregation Summary

**`is_hevy_sourced` drops Hevy's `ActiveEnergyBurned` write-back before it can become a row, and `normalize_payload` collapses a 189-datapoint day into the single row the table holds — so HEALTH-08 is a row-count fact and plan 08-06's replace-semantics upsert is unconditionally correct.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-02T08:52:00Z
- **Completed:** 2026-09-02T09:17:00Z
- **Tasks:** 3 of 3 (all TDD; five commits)
- **Files created:** 2 (1 source at 320 lines, 1 test at 1,018 lines)
- **Tests added:** 54

## Accomplishments

- **HEALTH-08 stopped being a rule and became a row count.** Finding A measured Hevy writing `ActiveEnergyBurned` into Apple Health on **209 of 209 training days at 70–88 %** of that day's total — and `active_energy` is *inside* this phase's allowlist. `is_hevy_sourced` drops those datapoints at write time, so no future analytics reader has to remember to exclude them. The fixture test asserts it against the measured 2026-01-02 day (Hevy 666.5 kcal in one lump record, the iPhone 94.2 kcal across three).
- **The vacuous-pass trap is closed explicitly.** Pitfall N-3's stated warning sign is "a source-exclusion filter that never excludes anything" — and a predicate that excluded *everything* would satisfy `"Hevy" not in sources` perfectly. So the same test also asserts `result.rows` is non-empty and that the three iPhone datapoints survived as one 94.2 kcal row. The runtime counterpart is `health_ingest_hevy_source_excluded`, which turns "the filter never matched" from invisible into a grep.
- **Aggregation and its idempotency consequence are handled together.** 189 datapoints for one metric-day collapse into one row with `sample_count == 189`, and 59 fragments of `0.20163697817574894` sum exactly rather than truncating a real day to zero flights. `health_ingest_multi_point_day` fires whenever a key carries more than one datapoint — which under a correct (daily) HAE aggregation interval never happens, and when it does means replace semantics has become lossy.
- **The no-values-in-logs guard was mutation-checked, not assumed.** A `leak=str(values[0])` kwarg was temporarily injected into the multi-point warning; the test failed and named three payload:metric pairs. The mutation was then reverted and the module verified byte-identical. A log-safety test that has never been seen to fail is a comment.
- **Pitfall N-4 is documented rather than discovered.** Four timezones over one midnight-anchored instant produce three distinct days, so a hardcoded zone anywhere in the path fails here instead of on the user's next trip.
- **Whole suite green: 816 passed** (526 fast + 290 integration against a real Postgres testcontainer), up from 472 fast at the wave-2 base.

## Task Commits

| Task | Gate | Commit | Message |
|------|------|--------|---------|
| 1 | RED | `7e80028` | `test(08-05)`: failing per-datapoint normalization tests |
| 1 | GREEN | `05d968f` | `feat(08-05)`: per-datapoint normalization with the HEALTH-08 source exclusion |
| 2 | RED | `27d07e0` | `test(08-05)`: failing aggregation tests for the whole-payload collapse |
| 2 | GREEN | `2841232` | `feat(08-05)`: the multi-point-day guard and the avg aggregation branch |
| 3 | — | `7a65250` | `test(08-05)`: pin the timezone rule, the HEALTH-08 fixture case and log safety |

## TDD Gate Compliance

Tasks 1 and 2 each show a `test(...)` commit immediately followed by a `feat(...)` commit, both verified failing before implementation:

- **Task 1 RED** failed at collection with `ImportError: cannot import name 'normalize'` — the module did not exist.
- **Task 2 RED** was a *partial* RED and is recorded as such: **2 failed, 42 passed**. Task 1's GREEN necessarily included a working `normalize_payload` (every Task-1 behaviour is expressed through `NormalizeResult`, which only that function produces), so the 189-datapoint collapse, the fractional-fragment sum, the Finding D two-source case, `kinds_present`, ordering, determinism and the accounting identity were already satisfied when their tests were written. The two genuinely new behaviours — `health_ingest_multi_point_day` and the `avg` branch — did fail, and are what the GREEN commit adds.
- **Task 3 has no GREEN commit** because it adds no production code. Its 10 cases passed on first run. They are regression guards over behaviour Tasks 1–2 already got right, not behaviour specifications, and that is stated here rather than dressed up as a gate. The one case that *was* verified to fail on demand is the log-safety test, via the deliberate mutation described above.

## Files Created

- **`backend/app/integrations/health_auto_export/normalize.py`** (320 lines) — the module docstring is the load-bearing part. It records Finding A with the measured numbers, Pitfall N-3's app-name-not-device-name rule with the rename counts, Assumption A1 as still open, Open Questions 1 and 2 with their accepted costs, Pitfall N-4 with the worked example, and the logging rule. A future reader cannot widen `_HEVY_SOURCE_ALIASES` or reach for a metric-name-only allowlist without confronting why they are there.
  - `_scan_metric()` is the per-datapoint layer: registry gate → incomplete-datapoint drop → **Hevy exclusion before any conversion work** → `to_canonical` → `parse_hae_datetime` → `local_day` → source-name sentinel. Every rejection is per-datapoint, because HAE has no documented retry and the blast radius of one malformed element must be that element.
  - `normalize_payload()` buckets on `(metric, source_name, local_day)` across the *whole* payload before emitting anything, then walks `sorted(buckets.items())` — the order is part of the contract, since plan 08-06 writes rows in it.
- **`backend/tests/test_health_auto_export_normalize.py`** (1,018 lines, 54 tests) — module docstring names what it covers and what deliberately lives elsewhere (idempotency is 08-06's, against a real container; wire parsing is 08-04's; the route is 08-07's). Selector coverage: `-k hevy` → 17, `-k unrecognized` → 5, `-k nutrition` → 5, `-k timezone` → 5, `-k multi_point` → 1.

## Decisions Made

- **`datapoints_seen` counts every datapoint in the payload, including those under an unrecognised metric.** The plan did not specify this. Counting them makes the three counters satisfy an *identity* — `sum(row.sample_count) == datapoints_seen - datapoints_dropped` — which is pinned by `test_every_datapoint_is_either_inside_a_row_or_explained_by_a_drop`. The alternative (counting only datapoints under recognised metrics) leaves three unrelated numbers that cannot catch a datapoint vanishing between the registry gate and the bucket.
- **`NormalizeResult` ships with exactly the five fields the plan declared.** A sixth counter for Hevy exclusions was considered and rejected: plans 08-06 and Phase 9 build against the declared interface, and the observability that counter would have provided is already delivered by the `health_ingest_hevy_source_excluded` log line with no interface drift.
- **The `avg` branch tests `== "avg"`, not `!= "sum"`.** The plan's sketch used the latter. With a `Literal["sum", "avg"]` the two are equivalent today, but a future third aggregation would silently *average* under `!=` and merely *sum* under `==` — and summing is the registry's overwhelming default, so the wrong answer is at least the conventional one and shows up in a test rather than as a rate that grows with sampling frequency.
- **The log-capture helper defeats structlog's first-use cache.** `configure_logging` sets `cache_logger_on_first_use=True`. A module-level proxy already bound by an earlier test would keep that test's configuration and write somewhere else entirely, leaving the buffer empty — a capture that silently checks nothing, which is the exact failure mode the four positive `assert _events(...)` guards exist to catch. The helper disables the cache and hands the module a fresh proxy for the duration, then restores both.
- **REQUIREMENTS.md deliberately left unmodified.** `HEALTH-06`, `HEALTH-08` and `NUTR-02` are also claimed by plans 08-06, 08-07 and 08-08. This plan decides *which rows should exist*; nothing writes one yet. Marking them complete now would record a requirement as met while the code that meets it is unwritten. It is also a shared file the orchestrator owns. Consistent with 08-01 and 08-04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] The `avg`-branch test needs a registry entry that does not exist**

- **Found during:** Task 2
- **Issue:** The plan requires a test that "a `MetricSpec` with `aggregation="avg"` produces the Decimal mean" while also noting that no such metric is in the Phase 8 registry. There is nothing to feed the branch.
- **Fix:** `monkeypatch.setattr(normalize, "METRIC_REGISTRY", {**METRIC_REGISTRY, "walking_speed": MetricSpec("km/hr", frozenset({"km/hr"}), "avg", "activity")})`. Both registry lookups in `normalize_payload` are module-global, so one patch covers the gate and the row build. The metric chosen is the one RESEARCH Finding B names as the eventual Phase 13 candidate, so the test doubles as a rehearsal for that addition.
- **Files modified:** `backend/tests/test_health_auto_export_normalize.py`
- **Verification:** `test_an_avg_metric_produces_the_mean_rather_than_the_sum` fails on the pre-GREEN module and passes after
- **Committed in:** `27d07e0`, `2841232`

**2. [Rule 1 — Correctness of instructions] `-k timezone` cannot select the test the plan names**

- **Found during:** Task 3
- **Issue:** Two acceptance criteria are jointly unsatisfiable as written. One requires the exact name `test_midnight_anchored_point_uses_local_day_not_the_payload_date`; the other requires `-k timezone` to collect **≥ 2** tests. That name contains no substring `timezone`, and neither does the module name, so the plan's own two timezone tests would have collected one.
- **Fix:** Kept the required name verbatim and named the counterpart `test_the_same_instant_lands_on_the_next_day_in_a_matching_timezone`, then added a parametrized `test_the_timezone_parameter_alone_decides_the_day` over Asia/Tokyo, Asia/Jakarta, UTC and America/New_York. `-k timezone` now collects 5, and the four-zone case is a strictly stronger statement of "tz is genuinely read" than two zones were.
- **Files modified:** `backend/tests/test_health_auto_export_normalize.py`
- **Verification:** `pytest ... -k timezone` — 5 passed, 49 deselected; `grep -c test_midnight_anchored_point_uses_local_day_not_the_payload_date` — 1
- **Committed in:** `7a65250`

**3. [Rule 2 — Missing critical functionality] The log-safety assertion message would have leaked the thing it forbids**

- **Found during:** Task 3
- **Issue:** The plan asks the log-safety test to build its forbidden set from the fixtures' own `qty` values. The obvious `assert value not in scanned, f"... {value}"` interpolates a quantity into an assertion message, which Shared Pattern 8's explicit exception forbids.
- **Fix:** The forbidden set is a `dict[str, str]` keyed on the *value spelling* and valued by `"{fixture}:{metric}"`. The assertion collects the leaked **origins** and reports those, so a failure is fully actionable and carries no measurement. `PYEOF`-scripted mutation confirmed the failure path prints `['activity_and_nutrition:step_count', 'activity_and_nutrition:walking_running_distance', 'hevy_active_energy:active_energy']` and no numbers.
- **Files modified:** `backend/tests/test_health_auto_export_normalize.py`
- **Verification:** deliberate `leak=` kwarg injected into `health_ingest_multi_point_day` → test failed as designed → mutation reverted and the module verified to contain no `leak=`
- **Committed in:** `7a65250`

**4. [Rule 2 — Missing critical functionality] The log capture could have passed over an empty buffer**

- **Found during:** Task 1
- **Issue:** `test_hevy_body.py`'s precedent notes that a mis-wired capture produces an empty buffer and a green test. Two additional hazards apply here that do not apply there: this module's logger is a module-level proxy that structlog caches on first use after `configure_logging`, and the log-safety test asserts *absence*, so an empty buffer is indistinguishable from success.
- **Fix:** `run_capturing_logs` disables `cache_logger_on_first_use` and substitutes a fresh proxy for the duration; the log-safety test asserts all four event names are present *before* scanning for leaks; the `unit`-carrying drop path is exercised by a units-broken copy of the activity fixture, so no logging branch in the module goes unscanned.
- **Files modified:** `backend/tests/test_health_auto_export_normalize.py`
- **Verification:** `test_no_quantity_from_any_fixture_reaches_the_log_stream` asserts `health_ingest_unrecognized_metric`, `health_ingest_hevy_source_excluded`, `health_ingest_multi_point_day` and `health_ingest_datapoint_dropped` are all present
- **Committed in:** `7e80028`, `7a65250`

**5. [Rule 1 — Bug] A literal U+2019 was emitted into source despite the rule against it**

- **Found during:** Task 1 (and again in `normalize.py`'s docstring)
- **Issue:** Plan 08-04 recorded this exact failure and it recurred: writing `DEVICE_NAME = "Vegant's iPhone"` produced an actual U+2019 character, invisible in every rendering available, in both the test file and the module docstring. Editing it "to the escape form" was a no-op because the intended and actual strings were identical.
- **Fix:** Scripted replacement in both files, each with a post-condition asserting `ord(c) > 127` finds nothing anywhere in the file. Both now spell the character as a backslash-`u2019` escape in source.
- **Files modified:** `backend/app/integrations/health_auto_export/normalize.py`, `backend/tests/test_health_auto_export_normalize.py`
- **Verification:** a non-ASCII scan over both files reports an empty set
- **Committed in:** `7e80028`, `05d968f`

---

**Total deviations:** 5 auto-fixed (2 × Rule 1, 2 × Rule 2, 1 × Rule 3). No Rule 4 architectural decisions arose.
**Impact on plan:** No scope creep and no interface change. Every signature in the plan's `<interfaces>` block ships exactly as declared, so plans 08-06 and 08-07 build against what they were promised. Deviation 2 is the only change to a stated acceptance criterion, and it strengthens the test it touches.

## Threat Model Coverage

| Threat ID | Disposition | Where it landed |
|-----------|-------------|-----------------|
| T-08-27 | mitigate | `is_hevy_sourced` at write time + `test_the_hevy_fixture_excludes_hevy_and_keeps_the_iphone_rows`, which asserts both directions so the predicate cannot pass by excluding everything |
| T-08-28 | mitigate | Fixed-set membership on a case-folded, stripped string. `source` is never interpolated into a log format string; the worst a crafted value can do is create its own row, visible in `SELECT DISTINCT source_name` |
| T-08-29 | mitigate | D-04: `test_unrecognized_metric_does_not_cost_the_recognised_metrics_beside_it` and the `unrecognized_and_sourceless` fixture case, which still yields the `step_count` row |
| T-08-30 | mitigate | Every log call carries a name, a unit, a `local_day`, a `source_name`, a count or `type(exc).__name__`. Enforced by a fixture-derived forbidden set, **verified to fail under a deliberate mutation** |
| T-08-31 | mitigate | `Decimal(str(x))` end to end; `grep -E "\bint\(\|\bround\(\|\bfloat\("` over `normalize.py` returns 0 matches |
| T-08-32 | mitigate | `health_ingest_multi_point_day` and `health_ingest_hevy_source_excluded`, both counts and never values, both asserted present by the log-safety test |
| T-08-33 | accept | `local_day` applied uniformly; the known one-day shift is pinned by `test_midnight_anchored_point_uses_local_day_not_the_payload_date` with a docstring explaining why it is intended |

No new security-relevant surface was introduced: this module opens no connection, imports no HTTP client, and touches no route, schema or credential.

## Issues Encountered

- **The worktree arrived on the WRONG base, as the prompt warned — the fifth in a row.** `git merge-base HEAD 2b0acea` returned `b1d3eef` (`chore: finalize STATE.md after v1.0 milestone close`), which equalled `HEAD`. This worktree was created from the old milestone-close commit and was an *ancestor* of the required base, missing all of waves 1 and 2 — so `registry.py`, `schemas.py`, `errors.py` and the HAE fixtures this plan depends on were absent from the filesystem. Hard-reset to `2b0acead90c4bb8e43370b97b0834cfac9e5e69a` and confirmed `git rev-parse HEAD` matched before touching anything. Safe: `git status` was clean. **This is systematic across every executor in this phase and belongs in the worktree-creation step, not in five separate startup checks.**
- **No `.venv` in the worktree.** `uv sync --frozen --group dev` bootstrapped from cache. As 08-01 and 08-04 noted, `[tool.uv] default-groups = []` means `--group dev` is required.
- **`git clean` was never run**, per the destructive-git prohibition. The single startup `reset --hard` was the only history-affecting operation.

## Deferred Issues

1. **`backend/tests/conftest.py` still fails `ruff format --check`** at the two pre-existing `_mcp_purge_statements` spots 08-01 and 08-04 both documented. Still out of scope; this plan does not touch that file. One `ruff format backend/tests/conftest.py` fixes it, and it will trip the `ruff-format` pre-commit hook for anyone committing that file without `--no-verify`. Now recorded by three consecutive plans — recommend the orchestrator clear it once, centrally.
2. **A metric whose `units` are unknown logs one drop line per datapoint, not one per metric.** The plan places that log inside the per-datapoint step and it is implemented as specified. Under a device misconfiguration on a 189-point day that is 189 identical lines. It is bounded (units are metric-level, so the condition is uniform across the metric) and it never fires under a correct configuration, but a future plan may want to collapse it the way the Hevy-exclusion line already is. Not changed here because the behaviour is what the plan's acceptance criteria describe.
3. **Assumption A1 remains open**, unchanged: that HAE's *webhook* sends `source: "Hevy"` (the app name) rather than something else. `_HEVY_SOURCE_ALIASES` is a frozenset so plan 08-08's device capture can add the real spelling in one line, and `health_ingest_hevy_source_excluded` is what makes a never-matching filter noticeable. Only a captured payload from a real training day can settle it.

## Known Stubs

None. Every function is fully implemented; there are no placeholder returns, no `TODO`/`FIXME` markers, and no branch that returns empty data by construction. The `avg` aggregation branch is unreachable through the *current* registry but is fully implemented and exercised by a test that injects an `avg` spec — it is a deliberate forward accommodation for Phase 13, documented as such in a comment, not an unimplemented path.

## User Setup Required

None — this module is pure and configuration-free. `tz` is a parameter, supplied by the caller from `users.timezone`.

The two device-side prerequisites this phase depends on remain open and are not this plan's to close: the HAE **aggregation interval must be set to daily** (Pitfall N-2 — this plan makes a drift from that setting *observable* via `health_ingest_multi_point_day`, but cannot prevent it), and Cloud Run memory must be raised from 512Mi to 1Gi with a body-size cap before the first real device sync.

## Next Phase Readiness

**Ready.** Plan 08-06 has everything it was promised, at the promised signatures:

- `from app.integrations.health_auto_export.normalize import SOURCE_APPLE_HEALTH, NormalizedRow, NormalizeResult, normalize_payload`. Rows arrive pre-aggregated, one per `(metric, source_name, local_day)`, deterministically ordered — so `on_conflict_do_update(constraint="uq_health_daily_metrics_user_source_metric_source_name_day", ...)` with **replace** semantics (`SET value = excluded.value`) is unconditionally correct within a delivery.
- `NormalizedRow.units` is already the canonical unit and `NormalizedRow.value` is already a `Decimal` sized for `Numeric(14,4)`. `source_name` is never null — `UNKNOWN_SOURCE_NAME` is written at normalize time so the 5-column key works without `NULLS NOT DISTINCT`.
- `NormalizeResult.kinds_present` selects which of D-03's two `sync_state` resources to advance, and is empty when nothing was accepted.
- `NormalizeResult` is safe to log wholesale: counts only.

**One caution for 08-06:** the `health_ingest_multi_point_day` warning resolves only the *within-delivery* half of Pitfall N-2. A day split across two batched POSTs is still lossy under replace semantics, and that half is resolved at the device by the daily aggregation interval — which belongs in `docs/health-auto-export-setup.md`, not in code.

**One caution for Phase 9:** the historical backfill must call `normalize_payload` (or at minimum `_scan_metric`'s conversion order) rather than writing a second normalizer. `SOURCE_APPLE_HEALTH` in particular must be identical on both paths, or the same day arrives as two rows with different `source` values and the unique constraint never fires.

## Self-Check: PASSED

- Both claimed files verified present on disk: `backend/app/integrations/health_auto_export/normalize.py` (320 lines, above the 120-line minimum) and `backend/tests/test_health_auto_export_normalize.py` (1,018 lines).
- All 5 claimed commit hashes verified in `git log`: `7e80028`, `05d968f`, `27d07e0`, `2841232`, `7a65250`.
- `uv run pytest backend/tests/test_health_auto_export_normalize.py` — **54 passed** (required ≥ 20).
- Selector counts: `-k "hevy or unrecognized"` 20 (required ≥ 6), `-k nutrition` 5 (≥ 4), `-k timezone` 5 (≥ 2), `-k multi_point` 1, `-k hevy` 17.
- `uv run pytest -m "not integration"` — **526 passed**, 290 deselected.
- `uv run pytest` (full, real Postgres testcontainer) — **816 passed**.
- `uv run mypy backend/app/integrations/health_auto_export` — success, 6 source files.
- `uv run ruff check` and `ruff format --check` clean on both files.
- Every acceptance-criteria grep verified, including the negatives: `\bint\(|\bround\(|\bfloat\(` → 0, `\.date\(\)|utcnow|date\.today` → 0, `Decimal\(point\.qty\)|float\(` → 0, `log\.(info|warning|error)\(.*qty` → 0.
- No shared orchestrator artifacts modified: `STATE.md`, `ROADMAP.md` and `REQUIREMENTS.md` are untouched by every commit in this plan.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*

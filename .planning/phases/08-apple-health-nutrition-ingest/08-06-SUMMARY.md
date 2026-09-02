---
phase: 08-apple-health-nutrition-ingest
plan: 06
subsystem: integrations
tags: [health-auto-export, apple-health, nutrition, idempotency, upsert, sync-state, postgres, tdd]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    plan: 01
    provides: "health_daily_metrics and the named 5-column constraint the ON CONFLICT binds to"
  - phase: 08-apple-health-nutrition-ingest
    plan: 02
    provides: "PROVIDER_APPLE_HEALTH / RESOURCE_ACTIVITY / RESOURCE_NUTRITION, pair-based build_freshness, FRESHNESS_RESOURCES_APPLE_HEALTH"
  - phase: 08-apple-health-nutrition-ingest
    plan: 05
    provides: "normalize_payload's whole-payload aggregation, NormalizedRow, NormalizeResult.kinds_present, SOURCE_APPLE_HEALTH"
  - phase: 03-hevy-integration
    provides: "hevy/body.py -- the constraint-by-name upsert, the SAVEPOINT-per-row loop and the counts-only result type this module mirrors"
provides:
  - "upsert_health_metric: one day-grained row, ON CONFLICT bound BY NAME, REPLACE semantics"
  - "ingest_payload: the whole inbound path -- timezone read, normalize, SAVEPOINT loop, D-03 freshness, one commit"
  - "HealthIngestResult: the counts-only value plan 08-07's route logs and returns"
  - "Proof against a real PostgreSQL constraint that an overlapping re-send changes no row count and no stored value"
  - "Proof that activity and nutrition freshness advance independently and that Hevy's three resources are untouched"
affects: [08-07, 08-08, 09-historical-backfill, 13-reports-and-nutrition-trends]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Replace-semantics upsert made unconditionally safe by aggregating the whole payload upstream, rather than by a cleverer conflict clause"
    - "A total kind->resource map: an unmapped kind is a KeyError, never a plausible default"
    - "Mutation-checking a correctness guard before trusting it -- the additive clause and a value leak were both injected and confirmed to fail the suite"

key-files:
  created:
    - backend/app/integrations/health_auto_export/ingest.py
    - backend/tests/test_health_ingest_idempotency.py
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "REPLACE, never additive -- proven non-vacuous by injecting the additive clause and watching 5 tests fail"
  - "The skipped-row case is driven through a real payload with an over-long source_name rather than by calling upsert_health_metric directly, because rows_skipped is only produced by ingest_payload"
  - "The failing row is made to sort FIRST, so the test also proves the transaction is usable after a SAVEPOINT rollback"
  - "_cleanup purges every sync_state row for the user, not only the Apple Health pair, because the D-03 section seeds real Hevy rows"
  - "_run_capturing_logs patches BOTH ingest.log and normalize.log -- one ingest emits from both modules"
  - "All four declared requirements marked complete; what 'surfaced' means today is recorded explicitly below"

patterns-established:
  - "Filter a captured fixture by the registry's own `kind` field to build single-kind payloads, so fixtures and registry cannot drift and a metric changing kind fails a test"
  - "Pre-seed the rows an isolation claim is about at a distinct PAST instant, so 'untouched' is observable rather than two NULLs comparing equal"

requirements-completed: [HEALTH-09, NUTR-03, HEALTH-11, NUTR-05]

# Metrics
duration: 27min
completed: 2026-09-02
---

# Phase 8 Plan 06: Idempotent Health Ingest & D-03 Freshness Summary

**Replace-semantics upsert bound to the constraint by name, made unconditionally correct by plan 08-05's whole-payload aggregation — so a re-sent export window is a proven no-op, and `activity` and `nutrition` freshness move only when the payload actually carried that kind.**

## Performance

- **Duration:** ~27 min
- **Started:** 2026-09-02T16:26:00Z
- **Completed:** 2026-09-02T16:53:00Z
- **Tasks:** 3 of 3 (four commits, genuine RED→GREEN on Task 1)
- **Files created:** 2 (1 source at 288 lines, 1 test at 947 lines)
- **Tests added:** 17, all integration

## Accomplishments

- **HEALTH-09 and NUTR-03 stopped being a design intention and became a measured property.** `test_identical_payload_twice_changes_nothing` and `test_an_overlapping_window_replaces_rather_than_accumulates` run against a real PostgreSQL unique constraint. The overlapping case is the discriminating one: the second delivery is a strict superset built by *appending* a datapoint, so the stored total must equal that delivery's own aggregate (9427.5) and not the sum of both (17355.0).
- **The conflict clause was mutation-checked, not asserted.** Swapping `set_={"value": excluded.value}` for an additive form failed **5** of the 17 tests, including both idempotency cases, both nutrition cases and the Finding D two-source case. A test suite that has never been seen to fail against the wrong implementation is a comment.
- **D-03 is proven in both directions.** An activity-only payload leaves `('apple_health','nutrition')` absent, and the mirror case holds. Both are needed: a `_KIND_TO_RESOURCE` that returned `activity` for everything would pass the first test unchanged.
- **ROADMAP criterion #5 is asserted through `build_freshness`, not through `sync_state`.** A correct bookkeeping row behind a builder that resolved it under the wrong provider would satisfy a direct read and still answer wrongly — that is RESEARCH Pitfall 7, and the test pins the Hevy `workouts` timestamp at a distinct past instant so "unchanged" is observable rather than vacuous.
- **The no-values-in-logs guard was also mutation-checked.** A `leak=str(row.value)` kwarg injected into the skip log failed two tests and reported `['activity_and_nutrition:protein']` — the origin, with no measurement in the message. Reverted and the module verified to contain no `leak=`.
- **Full suite green: 833 passed** (was 816 at the wave-3 base), including the complete integration suite against a real Postgres testcontainer.

## Task Commits

| Task | Gate | Commit | Message |
|------|------|--------|---------|
| 1 | RED | `c02d1dc` | `test(08-06)`: add failing idempotency test for the health ingest upsert |
| 1 | GREEN | `5f7e13a` | `feat(08-06)`: idempotent health-metric upsert and ingest orchestration |
| 2 | — | `662b54c` | `test(08-06)`: prove idempotency against a real PostgreSQL constraint |
| 3 | — | `7479418` | `test(08-06)`: prove activity and nutrition freshness advance independently |

## TDD Gate Compliance

**Task 1 shows a genuine RED→GREEN pair.** The plan assigns `ingest.py` to Task 1 and the test file to Tasks 2–3, which would have made a conventional RED unobservable. Instead the defining idempotency case was written first, into the file Task 2 later expands, and confirmed failing:

```
E   ModuleNotFoundError: No module named 'app.integrations.health_auto_export.ingest'
```

`c02d1dc` (test) precedes `5f7e13a` (feat) in `git log`, satisfying the plan-level RED and GREEN gates. No REFACTOR commit: the module needed no cleanup after GREEN.

**Tasks 2 and 3 have no GREEN commit and that is stated rather than dressed up.** They add no production code — they are regression guards over behaviour Task 1's GREEN already implemented, and they passed on first run. Their non-vacuity was demonstrated empirically instead, by the two deliberate mutations described above (5 tests failed on the additive clause, 2 on the injected value leak). That is a stronger statement than a RED ordering would have been, because it names the exact wrong implementation each guard rejects.

## Files Created

- **`backend/app/integrations/health_auto_export/ingest.py`** (288 lines). The module docstring is the load-bearing part: it records why *both* obvious conflict clauses are wrong, why replace is nevertheless unconditionally safe here (08-05 aggregates the whole payload before the first write), where the residual batch-split risk is closed (at the device, via the daily aggregation interval) and how it is made observable (`health_ingest_multi_point_day`). It also records the caller-owns-the-transaction rule, D-03 / Open Question 2, and the logging rule.
  - `upsert_health_metric` binds `ON CONFLICT` to `uq_health_daily_metrics_user_source_metric_source_name_day` **by name**, and writes `value`, `units` and `sample_count` on conflict. `units` is included because HAE units are a per-metric phone-app preference: a row whose quantity moved to a new canonical basis while its `units` string stayed on the old one is a plausible number that is quietly wrong. `sample_count` is included because a count that *falls* on a re-sync is the cheapest batch-split detector available, and it only works if the column tracks the latest delivery.
  - `_user_timezone` is a deliberate module-private second copy of the MCP layer's `local_timezone`, with a docstring explaining that an integrations package must not depend on the MCP package and that analytics set the same precedent.
  - `ingest_payload` reads the zone *outside* the try block — an unknown user is a caller bug, not a failed sync, and recording it as one would create a bookkeeping row under a tenant that does not exist.
- **`backend/tests/test_health_ingest_idempotency.py`** (947 lines, 17 integration tests). Selector coverage: `-k nutrition` → 2, `-k "log_stream or bad_row"` → 2.

## Decisions Made

- **`_cleanup` purges every `sync_state` row for `DEFAULT_USER_ID`, not only the Apple Health pair.** The D-03 section seeds real `provider='hevy'` rows in order to prove an Apple Health ingest leaves them alone; a surviving one would make the *next* module's "never synced reports `None`" assertions depend on execution order. `test_hevy_body.py` deletes the same scope for the mirror-image reason.
- **Single-kind payloads are built by filtering the captured fixture on the registry's own `kind` field**, with a subscript rather than a `.get()`. Two more fixture files would drift from the registry; this way a metric that ever changes kind fails these tests, and a fixture metric that fell out of the registry is a `KeyError` rather than a silently smaller payload.
- **The mixed-payload test asserts the two freshness instants are *equal*, not merely both recent.** Two `utc_now()` calls inside the loop would make one delivery report activity and nutrition as fractionally different ages — a difference with no meaning that a future reader would eventually try to interpret.
- **`test_a_wholly_unrecognised_payload_advances_nothing` asserts the bookkeeping rows are *absent*, not merely stale.** This is Open Question 2's real content: advancing on "the POST succeeded" rather than "a row landed" would make a device exporting nothing but unrecognised metrics read as perfectly healthy.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Correctness of instructions] Three of Task 1's acceptance greps forbid the exact tokens the same task's action block requires**

- **Found during:** Task 1
- **Issue:** (a) `grep "mark_running\|advance_cursor_page"` must return nothing, while the action block requires a comment naming both as deliberate absences. (b) `grep "app.mcp"` must return nothing, while the action block requires `_user_timezone`'s docstring to explain why it does not import from there — and with an unescaped `.`, the path form `app/mcp/...` matches the same pattern. (c) The docstring must record the conflict-clause table "verbatim in substance", but writing the additive form as SQL would trip `grep -E "value \+ "`. This is the same class of internally-contradictory criteria plan 08-01 hit and recorded.
- **Fix:** Kept all three explanations in full and reworded them to avoid the literal tokens — "no `running` status phase", "no pagination and therefore no resume checkpoint", "an integrations package must not depend on the MCP package", and the conflict-clause contrast written as prose about accumulation rather than as SQL.
- **Files modified:** `backend/app/integrations/health_auto_export/ingest.py`
- **Verification:** all eight Task-1 acceptance greps return their required counts; every explanation survives intact
- **Committed in:** `5f7e13a`

**2. [Rule 1 — Correctness of instructions] Task 2's skipped-row instruction cannot produce the value it asks to assert**

- **Found during:** Task 2
- **Issue:** The action block says to "construct a `NormalizedRow` with a `source_name` longer than `String(128)` and call `upsert_health_metric` directly inside the batch, then assert `rows_skipped == 1`". `rows_skipped` is a field of `HealthIngestResult`, which only `ingest_payload` produces; a direct call to `upsert_health_metric` raises `DataError` and returns no counts at all.
- **Fix:** Drove the case through a real payload carrying a 200-character source name, which produces `rows_skipped == 1` from the actual code path. Strictly stronger than the literal instruction: it exercises the SAVEPOINT loop end to end, and the offending metric was chosen to sort **first** (`active_energy` precedes `protein` and `step_count`) so the test also proves the transaction is still usable after the rollback — the "current transaction is aborted" failure T-08-40 is actually about.
- **Files modified:** `backend/tests/test_health_ingest_idempotency.py`
- **Verification:** `test_one_bad_row_is_skipped_and_the_rest_of_the_batch_lands` — `rows_skipped == 1`, `rows_upserted == 2`, one `health_ingest_row_skipped` line carrying a class name and no quantity
- **Committed in:** `662b54c`

**3. [Rule 2 — Missing critical functionality] The log capture would have scanned only half the log stream**

- **Found during:** Task 3
- **Issue:** One `ingest_payload` call emits from `ingest.py` *and* from `normalize.py`. The precedent helper in `test_health_auto_export_normalize.py` patches a single module proxy, and copying it would have left every `normalize.py` line rendered through the previously-cached logger — invisible to the buffer, and therefore reported as clean by a test whose whole job is asserting absence.
- **Fix:** `_run_capturing_logs` saves and replaces **both** proxies, and the test asserts all four expected event names are present before scanning for leaks.
- **Files modified:** `backend/tests/test_health_ingest_idempotency.py`
- **Verification:** `health_ingest_hevy_source_excluded` and `health_ingest_unrecognized_metric` (both from `normalize.py`) are asserted present in the captured buffer; the injected-leak mutation was caught
- **Committed in:** `7479418`

**4. [Rule 1 — Bug] A literal katakana string was emitted into source despite the file's own rule against it**

- **Found during:** Task 2
- **Issue:** The recurrence plans 08-04 and 08-05 both recorded, in a different alphabet: the module docstring states that non-ASCII source names are written as escapes, and the constant beneath it was written as literal characters. Invisible in every rendering available, and one careless editor away from silently becoming a different test.
- **Fix:** Scripted replacement to the `カロミル` escape form, with a post-condition asserting no character with `ord(c) > 127` remains anywhere in the file. The same scan was run over `ingest.py`.
- **Files modified:** `backend/tests/test_health_ingest_idempotency.py`
- **Verification:** a non-ASCII scan over both created files reports an empty set
- **Committed in:** `662b54c`

### Additions Beyond the Plan's Test List

Four tests were added that the plan's `<behavior>` blocks do not name, each closing a gap the listed cases leave open. None changes an interface.

- `test_one_row_per_metric_source_and_local_day` — pins the row COUNT at 12 and the Pitfall N-4 two-day split, so a silently dropped metric fails here rather than in Phase 13.
- `test_an_empty_payload_commits_nothing_and_returns_zeroes` — Task 1's stated behaviour had no test anywhere in the plan.
- `test_a_mixed_payload_advances_both_resources_to_the_same_instant` — the plan asks for "to the same instant"; equality is what states it.
- `test_apple_health_freshness_reports_a_kind_that_never_arrived_as_none` — a missing key and a `None` value are different answers, and Phase 13 needs the difference.

---

**Total deviations:** 4 auto-fixed (2 × Rule 1 correctness-of-instructions, 1 × Rule 1 bug, 1 × Rule 2). No Rule 4 architectural decisions arose.
**Impact on plan:** No scope creep and no interface drift. Every signature in the plan's `<interfaces>` block ships exactly as declared, so plan 08-07's route builds against what it was promised. Deviations 1 and 2 reconcile internally contradictory plan text without weakening either intent; 2 strengthens the test it touches.

## Threat Model Coverage

All eight `mitigate` dispositions are implemented and test-guarded.

| Threat ID | Where it landed |
|-----------|-----------------|
| T-08-34 (additive double-count) | `set_={"value": statement.excluded.value, ...}`. Proven by 5 tests failing under the injected additive clause, and by an acceptance grep that returns 0 for `excluded\.value\s*\+|value \+ ` |
| T-08-35 (conflict bound by column list) | `on_conflict_do_update(constraint=_CONFLICT_CONSTRAINT)` — bound by name, so a rename raises instead of degrading into duplicate inserts |
| T-08-36 (freshness claiming rolled-back work) | `ensure_sync_state` + `complete_sync` execute in the SAME transaction as the rows and commit with them; `utc_now()` is passed explicitly to satisfy `complete_sync`'s tz-aware guard |
| T-08-37 (nutrition reported fresh when the app stopped) | Only kinds in `kinds_present` advance. `test_activity_only_payload_does_not_freshen_nutrition` and its mirror are the regression guards |
| T-08-38 (payload-supplied tenant) | `user_id` keyword-only with no default; nothing in the module reads a tenant from the payload. Acceptance grep asserts no default |
| T-08-39 (`str(exc)` leaking quantities) | Every skip path logs `type(exc).__name__`; the batch-error path goes through `format_sync_error`. Verified by injecting a leak and watching two tests fail |
| T-08-40 (one bad row aborting the transaction) | `session.begin_nested()` per row, with the failing row deliberately sorted first so post-rollback usability is asserted |
| T-08-41 (SQL injection via source_name/metric) | Values are bound parameters through SQLAlchemy Core `pg_insert(...).values(...)`; no string is interpolated into SQL anywhere in the module |

## Threat Flags

None. This plan creates no HTTP route (08-07 does), opens no network connection, imports no HTTP client, adds no schema and touches no credential. `test_health_auto_export_isolation.py` passes unchanged, which is machine proof that no HTTP client and no MCP import entered the package.

## Known Stubs

None. Every function is fully implemented; there are no placeholder returns, no `TODO`/`FIXME` markers, and no branch that returns empty data by construction.

## Requirements Status — all four marked complete, with the scope recorded

`REQUIREMENTS.md` was updated for **HEALTH-09, NUTR-03, HEALTH-11 and NUTR-05**, the four IDs this plan's frontmatter declares. Plans 08-01, 08-02 and 08-05 each deliberately deferred these on the grounds that "nothing ingests yet" — which was true then and is what this plan changes. 08-02's summary explicitly hands HEALTH-11 and NUTR-05 to this plan.

What is now true, precisely:

- **HEALTH-09** ("reprocessing an overlapping export window does not create duplicate records") and **NUTR-03** — proven against a real PostgreSQL constraint, in both the identical and the overlapping-superset form. Neither 08-07 (route) nor 08-08 (deploy and device setup) changes this property, so no later evidence is pending.
- **HEALTH-11** and **NUTR-05** ("freshness is surfaced through the same freshness/coverage envelope") — `build_freshness` returns real Apple Health timestamps after a real ingest, keyed separately from Hevy's, proven by `test_apple_health_freshness_is_reported_separately_from_hevy`. **The envelope carries it; no MCP tool consumes `FRESHNESS_RESOURCES_APPLE_HEALTH` yet** — 08-02 deliberately wired it into nothing, and Phase 13's activity and nutrition tools are what expose it to Claude. If the intended reading of "surfaced" is "visible to Claude" rather than "carried by the envelope", these two should be reopened until Phase 13; the orchestrator can flip them back in one command.

## Deferred Issues

1. **`backend/tests/conftest.py` still fails `ruff format --check`** at the two pre-existing `_mcp_purge_statements` spots that plans 08-01, 08-04 and 08-05 each documented. Untouched by this plan and still out of scope. Now recorded by four consecutive plans — one `ruff format backend/tests/conftest.py` fixes it and it should be cleared centrally rather than by a fifth plan noting it.
2. **`test_health_ingest_idempotency.py:162` reports a mypy `call-arg` error on `Settings(_env_file=None)`.** Byte-identical to the pre-existing error at `test_health_auto_export_normalize.py:101`; pydantic-settings' `_env_file` is not visible to mypy through the generated `__init__`. The project runs mypy over `backend/app/`, which is clean (7 source files, no issues). Not silenced with a `type: ignore` because `warn_unused_ignores = true` would then flag it the moment the stubs improve, and because diverging from the sibling file's pattern for one line is worse than the note.
3. **The whole-batch error path (`health_ingest_failed` + `record_sync_error` on a fresh session) has no test.** Reaching it requires forcing a `SQLAlchemyError` out of `complete_sync` or the commit, which needs invasive patching of the repository layer. The per-row skip path — the one that handles payload-derived data, and the one T-08-39 and T-08-40 are about — is fully covered. Worth adding when plan 08-07 wires the route, where a monkeypatched sessionmaker is already in play.
4. **Assumption A1 remains open**, unchanged by this plan: that HAE's webhook spells Hevy as `"Hevy"`. Only plan 08-08's capture from a real training day can settle it.

## Issues Encountered

- **The worktree arrived on the WRONG base — the sixth in a row, exactly as the prompt warned.** `git merge-base HEAD be8131a` returned `b1d3eef` (`chore: finalize STATE.md after v1.0 milestone close`), which equalled `HEAD`: this worktree was created from the old milestone-close commit and was an *ancestor* of the required base, missing all of waves 1–3. Every file this plan builds on — `health.py`, `normalize.py`, the sync-state constants, the HAE fixtures — was absent from the filesystem. Hard-reset to `be8131a5fd1cea7437b2b1cb4b54ca9d5584c569` and confirmed `git rev-parse HEAD` matched before touching anything. Safe: fresh worktree, `git status` clean. **This is now systematic across six consecutive executors and belongs in the worktree-creation step, not in six separate startup checks.**
- **No `.venv` in the worktree.** `uv sync --frozen --group dev` bootstrapped from cache. As three prior plans noted, `[tool.uv] default-groups = []` means `--group dev` is required.
- **`git clean` was never run**, per the destructive-git prohibition. The single startup `reset --hard` was the only history-affecting operation. Both temporary mutations were applied through a `.bak` copy and reverted with a post-condition assertion; `git status` confirmed `ingest.py` byte-identical to its committed form afterwards, and no `.bak` file was left behind.

## Verification

Every gate in the plan's `<verification>` block was run and passed:

```
uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration   # 17 passed
uv run pytest                                                                     # 833 passed
uv run mypy backend/app/integrations/health_auto_export                           # 7 source files, clean
uv run ruff check backend/app/integrations/health_auto_export                     # All checks passed
uv run ruff format --check <both created files>                                   # already formatted
grep -n "on_conflict_do_update" -A6 ingest.py                                     # constraint= by NAME
! grep -E "excluded\.value\s*\+|value \+ " ingest.py                              # 0 matches
uv run pytest backend/tests/test_health_auto_export_isolation.py -x               # 5 passed
uv run pytest backend/tests/test_sync_state.py -k "apple_health or nutrition" -x   # 2 passed
uv run pytest backend/tests/test_health_ingest_idempotency.py -k nutrition -x -m integration  # 2 passed
```

Success criteria:

- [x] `upsert_health_metric` binds the conflict by constraint NAME and uses replace semantics
- [x] `ingest_payload` reads `users.timezone` server-side, aggregates through `normalize_payload`, writes each row in its own SAVEPOINT, and commits rows and freshness together
- [x] `_KIND_TO_RESOURCE` is an immutable, total map — an unknown kind is a `KeyError`, not a default
- [x] Identical and overlapping re-sends leave row counts and every stored value unchanged, proven against a real PostgreSQL unique constraint
- [x] Activity and nutrition `sync_state` rows advance independently, and only when the payload carried that kind
- [x] Hevy's three `sync_state` rows are untouched by an Apple Health ingest
- [x] No stored value reaches a log line
- [x] The full suite, integration included, is green

## User Setup Required

None — this module is configuration-free and has no external service dependency. `user_id` is supplied by the caller and `tz` is read from `users.timezone`.

The two device-side prerequisites this phase depends on remain open and are **not** this plan's to close. Both are now more consequential than before, because this is the plan that writes the rows:

- **Health Auto Export's aggregation interval must be set to daily.** Replace semantics is unconditionally correct within a delivery but not across a batch boundary that falls inside a day. Plan 08-05's `health_ingest_multi_point_day` warning makes a drift from that setting observable; nothing in code can prevent it. This belongs in `docs/health-auto-export-setup.md` (plan 08-08).
- **Cloud Run memory must be raised from 512Mi to 1Gi with a body-size cap** before the first real device sync.

## Next Phase Readiness

**Ready.** Plan 08-07 has exactly the interface it was promised:

```python
from app.integrations.health_auto_export.ingest import HealthIngestResult, ingest_payload
result = await ingest_payload(sessionmaker, user_id=..., payload=validated_payload)
```

- `ingest_payload` owns its own transaction and commits; the route needs no session management beyond handing it the sessionmaker.
- `HealthIngestResult` is safe to log wholesale and safe to return in a response body: counts only, no value, no `sync_state` internals.
- `user_id` is keyword-only with no default. The route must resolve it server-side from `DEFAULT_USER_ID` and must never read it from the payload — Health Auto Export cannot supply one, and the acceptance grep in this plan asserts no default exists to fall back to.
- Two exceptions can escape: `ValueError("unknown user")` from the timezone read (a caller bug — no bookkeeping row is written) and a re-raised `SQLAlchemyError` after `record_sync_error` has committed on a fresh session. The route's error handling should distinguish them; neither carries payload data in its message.

**For Phase 13:** `FRESHNESS_RESOURCES_APPLE_HEALTH` now resolves to real timestamps and is proven to answer independently of Hevy in a single `build_freshness` call over a mixed bundle. `FRESHNESS_RESOURCES_WORKOUTS + FRESHNESS_RESOURCES_APPLE_HEALTH` is exercised end to end by `test_apple_health_freshness_is_reported_separately_from_hevy`.

**For Phase 9:** the historical backfill must reach the database through `upsert_health_metric`, not a second writer. `SOURCE_APPLE_HEALTH` and the constraint name must be identical on both paths, or the same day arrives as two rows and the unique constraint never fires.

## Self-Check: PASSED

- Both claimed files verified present on disk: `backend/app/integrations/health_auto_export/ingest.py` (288 lines, above the 100-line minimum) and `backend/tests/test_health_ingest_idempotency.py` (947 lines).
- The `must_haves` artifact requirement is met: `ingest.py` provides `upsert_health_metric`, `ingest_payload` and `HealthIngestResult`, and contains the literal string `uq_health_daily_metrics_user_source_metric_source_name_day`.
- All three `key_links` verified: `pg_insert(HealthDailyMetric).on_conflict_do_update(constraint=...)` bound by name; `ensure_sync_state` + `complete_sync` per kind present; `normalize_payload(payload, tz=...)` with the zone read from `users.timezone`.
- All 4 claimed commit hashes verified in `git log`: `c02d1dc`, `5f7e13a`, `662b54c`, `7479418`.
- `uv run pytest` (full, real Postgres testcontainer) — **833 passed**, up 17 from the wave-3 base of 816.
- Every acceptance-criteria grep verified for all three tasks, including the negatives.
- No file deletions in any commit (`git diff --diff-filter=D` empty across `be8131a..HEAD`); working tree clean with no untracked files.
- No shared orchestrator artifacts modified: `STATE.md` and `ROADMAP.md` are untouched by every commit in this plan. `REQUIREMENTS.md` is modified deliberately and is documented above.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*

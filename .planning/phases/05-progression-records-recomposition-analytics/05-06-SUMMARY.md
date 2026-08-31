---
phase: 05-progression-records-recomposition-analytics
plan: 06
subsystem: analytics
tags: [body-weight, rolling-average, decimal, timezone, time-machine, postgres, sqlalchemy, pydantic]

# Dependency graph
requires:
  - phase: 05-02
    provides: "GoldenBuilder.body_measurement() fixture (source parameter, Decimal weights, flush-and-rollback)"
  - phase: 05-03
    provides: "BodyWeightTrendResult / MeasurementCoverage schemas, MEASURED_DAY_FLOORS, is_measurement_insufficient, build_measurement_coverage, earliest_measurement_at, FRESHNESS_RESOURCES_BODY"
  - phase: 04
    provides: "rollup.resolve_window (the only sanctioned users.timezone reader), metadata.build_freshness, core/time.local_day + utc_now"
provides:
  - "get_body_weight_trend(session, *, user_id) -> BodyWeightTrendResult — BODY-01 end to end"
  - "TREND_ANCHOR_WEEKS = 4 (D-16's smoothing window), MANUAL_SOURCE = 'manual' (D-14's tie-break)"
  - "BodyMeasurementRow + the pure _dedupe_by_day / _window_average folds"
  - "The first use of time-machine in the repo, and the pattern for frozen-clock integration tests"
affects: ["05-07 recomposition (BODY-02 consumes trend_rate_percent_per_week)", "05-10 composition", "phase-6 fitness_get_body_weight_trend MCP tool"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Anchor-relative day offsets in tests instead of hand-copied date literals"
    - "One fixed-span fetch folded N ways, with a PURE coverage builder so no fold costs a query"
    - "Probe-window trick: resolve a throwaway one-day window solely to obtain users.timezone, then build the real window from the LOCAL anchor"

key-files:
  created:
    - backend/app/analytics/bodyweight.py
    - backend/tests/test_analytics_bodyweight.py
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "The anchor day is local_day(utc_now(), tz) with tz obtained through resolve_window, never a server-local calendar-day call — proven with a UTC-vs-local disagreeing instant"
  - "measured_on is compared bare against two dt.date bounds; no timezone conversion anywhere in the row query, because a calendar date is not an instant"
  - "The D-16 percent rate's denominator is the CURRENT 7-day average, never the anchor and never their mean"
  - "Averages quantize to 0.001 kg and the percent rate to 0.01 %/week"
  - "REQUIREMENTS.md BODY-01 marked complete at the analytics layer, matching the precedent DQ-01/DQ-02 set in Phase 4"

patterns-established:
  - "Frozen-clock integration tests: @pytest.mark.integration + @time_machine.travel(instant, tick=False) needs NO extra pytest-asyncio configuration under asyncio_mode = 'auto'"
  - "Paired boundary parametrization (below-floor vs at-floor) with a guard assertion that the parameter table agrees with the module's own floors"
  - "Prose in guarded packages must avoid the literal constructs the static guards grep for — reworded twice here (the '/30' Epley divisor guard, and the tolerance-helper ban)"

requirements-completed: [BODY-01]

# Metrics
duration: 12min
completed: 2026-08-31
---

# Phase 5 Plan 06: Body-Weight Rolling Averages Summary

**BODY-01 shipped: one 35-day `body_measurements` fetch folded five ways into 7-, 14- and 30-day rolling averages, each gated on its own D-15 floor, plus D-16's four-week-smoothed rate (0.001 kg / 0.01 %) and D-17's raw week delta on an independent gate.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-31T03:26Z (approx — first edit preceded the RED commit at 03:31Z)
- **Completed:** 2026-08-31T03:38Z
- **Tasks:** 3 (4 commits — the TDD RED gate is its own commit)
- **Files modified:** 3 (2 source, 1 planning)

## Accomplishments

- `get_body_weight_trend` returns every field of `BodyWeightTrendResult` from **one** `body_measurements` query plus the two shared metadata reads (`earliest_measurement_at`, `build_freshness`). Five windows, one round trip.
- Each of the 7/14/30-day windows carries its own `MeasurementCoverage` and its own `insufficient_data`, asserted on **both sides** of all three D-15 floors (2 vs 3, 4 vs 5, 9 vs 10).
- The D-16 smoothed rate is verified against a hand-computed exact `Decimal`: current 7-day avg 66.000, anchor-window avg 64.000, rate `0.500` kg/week, `0.76` %/week — with an explicit assertion message naming the wrong-denominator failure.
- D-17's `latest_week_delta_kg` is proven to survive a `None` smoothed rate, which is the live-data shape today.
- `anchor_day` proven to be the user's local day using `2026-08-29T18:00:00+00:00` (01:00 on the 30th in Asia/Jakarta).
- First use of `time-machine` in the repo: it works as a plain decorator on `async` tests under `asyncio_mode = "auto"` with **zero** extra configuration.

## Task Commits

1. **TDD RED — pure-fold tests fail on a missing module** — `442f1d1` (test)
2. **Task 1: fetch, D-14 dedupe, pure window folds** — `62d8a96` (feat)
3. **Task 2: `get_body_weight_trend`, the anchor, five folds, the D-16 rate** — `b4113d5` (feat)
4. **Task 3: frozen-clock integration tests** — `6e794f9` (test)

Plan metadata commit follows this SUMMARY.

## Files Created/Modified

- `backend/app/analytics/bodyweight.py` (294 lines, created) — BODY-01. `_weight_rows` (one inclusive-date, tenant-scoped query), `_dedupe_by_day` (D-14, pure, order-independent), `_window_average` (D-13, pure, returns `(average, measured_days)`), `get_body_weight_trend`.
- `backend/tests/test_analytics_bodyweight.py` (428 lines, created) — 19 tests: 5 in the fast suite, 14 integration (one is 6-way parametrized).
- `.planning/REQUIREMENTS.md` (modified) — BODY-01 checkbox and traceability row moved to Complete.

## Interface Record (requested by the plan's `<output>` block)

**Exact signature — 05-10 composes this:**

```python
async def get_body_weight_trend(
    session: AsyncSession, *, user_id: uuid.UUID
) -> BodyWeightTrendResult: ...
```

No date parameters at all. `user_id` is keyword-only with no default. Verified structurally via `inspect.signature`: `list(parameters) == ['session', 'user_id']`, `user_id.kind is KEYWORD_ONLY`, `user_id.default is Parameter.empty`.

**Observed quantum of every returned `Decimal` field:**

| Field | Quantum | Constant | Observed example |
|---|---|---|---|
| `average_7d_kg` | `0.001` kg | `_WEIGHT_QUANTUM` | `Decimal("66.000")` |
| `average_14d_kg` | `0.001` kg | `_WEIGHT_QUANTUM` | `Decimal("65.000")` |
| `average_30d_kg` | `0.001` kg | `_WEIGHT_QUANTUM` | `Decimal("65.000")` |
| `trend_rate_kg_per_week` | `0.001` kg/week | `_WEIGHT_QUANTUM` | `Decimal("0.500")` |
| `trend_rate_percent_per_week` | `0.01` %/week | `_PERCENT_QUANTUM` | `Decimal("0.76")` |
| `latest_week_delta_kg` | `0.001` kg | `_WEIGHT_QUANTUM` | `Decimal("1.000")` |

All six are `None` rather than zero when their gate fails. The percent rate is additionally `None` if the current 7-day average is exactly zero (division guard).

**`time_machine.travel` + `pytest-asyncio` `asyncio_mode = "auto"`:** **no extra configuration was needed.** `@time_machine.travel("...", tick=False)` applied directly to an `async def` test works — `time_machine` wraps coroutine functions with `functools.wraps`, so pytest-asyncio's auto-mode collection still sees a coroutine function. It also composes cleanly with `@pytest.mark.integration` and `@pytest.mark.parametrize` in either order, and freezing `time.monotonic` caused no event-loop or asyncpg stall against the testcontainers Postgres (module runs in ~2.5 s).

## Decisions Made

1. **The probe-window trick for the timezone.** `resolve_window` is the repo's only sanctioned reader of `users.timezone`, but the anchor day is not knowable until the timezone is. Resolved a throwaway one-day window purely to read `.tz`, then built the real 35-day window from `local_day(utc_now(), tz)`. The throwaway window is never queried against. The alternative — a second `select(User.timezone)` here — would have created the second `users.timezone` reader the Phase 4 docstring explicitly warns against.
2. **`build_measurement_coverage` is called four times and costs zero queries.** That is only true because 05-03 deliberately made it pure/synchronous, unlike its session-grained sibling `build_coverage`. Confirmed the divergence was load-bearing, not an inconsistency.
3. **REQUIREMENTS.md BODY-01 marked Complete.** The requirement text is "System calculates rolling body-weight averages (7/14/30-day) and weekly rate of change from synced measurements" — all three clauses are delivered and tested. Marked at the analytics layer, matching the precedent DQ-01/DQ-02 set in Phase 4 (both marked Complete before any MCP exposure existed). **Yes, I checked it off** — both the checkbox (line 52) and the traceability row (line 156). Only those two lines were touched, to keep the merge surface minimal for the sibling worktrees.

## Deviations from Plan

Two, both textual and both forced by the repo's own static guards. No behavioural deviation.

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's suggested docstring would have failed `test_epley_is_computed_only_in_estimates`**

- **Found during:** Task 2 (`get_body_weight_trend`'s docstring)
- **Issue:** The plan's text opened with `BODY-01: 7/14/30-day rolling averages ...`. `test_analytics_isolation.py`'s `_DIVIDE_BY_THIRTY` guard is the regex `/\s*30\b|Decimal\s*\(\s*30\s*\)|_THIRTY` applied to **every** file under `app/analytics/`, and the substring `/30-day` matches it. The whole fast suite would have gone red on a docstring.
- **Fix:** Reworded to `7-, 14- and 30-day rolling averages`. Verified the regex against both spellings before writing the file. The same guard is why the `_FETCH_SPAN_DAYS` comment block writes `current 30d` rather than a slash form.
- **Files modified:** `backend/app/analytics/bodyweight.py`
- **Verification:** `pytest -q backend/tests/test_analytics_isolation.py` — 8 passed.
- **Committed in:** `b4113d5`

**2. [Rule 3 - Blocking] The plan's own comment text contradicted its own acceptance criterion**

- **Found during:** Task 2
- **Issue:** The plan's suggested comment explained why the server-local calendar-day call is wrong by naming it literally, while the plan's Task 2 acceptance criterion requires `grep -c "date.today()" backend/app/analytics/bodyweight.py` to return **0**. The same contradiction existed for the test module: the plan asked for the docstring line "Never `pytest.approx`" **and** for `grep -c "pytest.approx"` to return 0.
- **Fix:** Kept the rationale, dropped the literals. The comment now reads "A server-local calendar-day call would be wrong twice over…"; the test docstring reads "never a tolerance". This is the exact trap `test_analytics_isolation.py`'s own module docstring documents (prose naming the thing a guard greps for).
- **Files modified:** `backend/app/analytics/bodyweight.py`, `backend/tests/test_analytics_bodyweight.py`
- **Verification:** Both greps return 0; all 19 tests still pass.
- **Committed in:** `b4113d5`, `6e794f9`

---

**Total deviations:** 2 auto-fixed (2 blocking, both textual).
**Impact on plan:** None on behaviour. Every rationale the plan wanted recorded is still recorded, just spelled so the repo's own guards stay green. No scope creep.

## Issues Encountered

- **Worktree base mismatch (the fourth consecutive occurrence in this phase).** `HEAD` was `1e97f3b`, an ancestor of the expected base `dcf89db`. `git merge-base` confirmed the mismatch; `git reset --hard dcf89db` corrected it before any work. Had this gone unnoticed, `metadata.py`'s 05-03 additions (`MEASURED_DAY_FLOORS`, `build_measurement_coverage`, `earliest_measurement_at`) and `schemas.py`'s `BodyWeightTrendResult` would all have been absent and the plan would have looked unexecutable.
- **`.venv` is not present in worktrees.** Symlinked the main checkout's `.venv` in to run the plan's verification commands, and removed the symlink before returning. Note it shows up as untracked rather than ignored, because `.gitignore` has `.venv/` (directory-only) and a symlink is not a directory — it was never staged.
- **`mypy backend/` reports 44 pre-existing errors across 13 test modules**, exactly as flagged in the execution context. `mypy backend/app/` exits 0 (49 files), and `mypy` reports **zero** errors in either file this plan created (`grep -c test_analytics_bodyweight.py` over the mypy output returns 0). Not fixed — out of scope, unrelated to Phase 5.

## Verification Results

| Check | Result |
|---|---|
| `pytest -q` (full suite) | **412 passed** in 11.79 s |
| `pytest -q -m "not integration"` (fast suite) | **227 passed**, 185 deselected in 1.07 s |
| `pytest -q backend/tests/test_analytics_bodyweight.py` | **19 passed** (5 fast + 14 integration) |
| `pytest -q -m "not integration" backend/tests/test_analytics_bodyweight.py` | **5 passed**, 14 deselected in 0.06 s |
| `ruff check backend/` | All checks passed |
| `mypy backend/app/` | Success, 49 source files |
| `mypy backend/` | 44 pre-existing errors, **0 in this plan's files** |
| `git diff --stat` vs base | Exactly 2 source files; `metadata.py`, `schemas.py`, `rollup.py`, `core/time.py`, `db/models/body.py`, `pyproject.toml` untouched |
| Alembic migration created | None (correct — no schema change) |

All plan acceptance-criteria greps verified individually and passing, including the six count-must-be-zero ones and the two count-must-be-exact ones (`_window_average(` → 6, `_weight_rows(` → 2, i.e. one definition plus five folds, and one definition plus one call).

## Known Stubs

None. Every field of `BodyWeightTrendResult` is computed from real rows; there is no placeholder, no hardcoded empty and no TODO in either file. `None` values are the documented D-15/D-16/D-17 gates, not stubs.

## TDD Gate Compliance

Gates present and in order for the pure folds: `442f1d1` (test, RED — module did not exist, `ModuleNotFoundError` captured before implementing) → `62d8a96` (feat, GREEN). No REFACTOR commit was needed.

**Note on the plan's task ordering:** the plan marked Tasks 1 and 2 `tdd="true"` but placed the whole test module in Task 3, which would have made a RED gate impossible. Resolved by splitting the test file: the four `<behavior>`-derived pure-fold tests were written and committed **first** (RED), and Task 3 appended the nine integration tests. `get_body_weight_trend` (Task 2) therefore has no separate RED commit — its behaviour is covered by the Task 3 integration tests, which is what the plan's own structure dictated.

## User Setup Required

None — no external service configuration, no new dependency, no migration. `time-machine 3.4.0` was already in the lockfile and had zero users until now.

## Next Phase Readiness

- **05-07 (BODY-02 / recomposition) is unblocked.** It should read `trend_rate_percent_per_week` and nothing else for its D-11/D-12 classification. `latest_week_delta_kg` exists for Claude's context and must **never** be the classified figure — that is the entire point of D-16/D-17 being two fields.
- **05-10 (composition) has the exact signature above.** Note it takes no date range: any composed tool wanting a historical body-weight anchor needs a new function, not a new argument.
- **Phase 6** can wrap this directly — `BodyWeightTrendResult` subclasses `_AnalyticsModel`, so the MCP `outputSchema` and `structured_content` come for free.
- **Live-data caveat for whoever demos this first:** on real data today `trend_rate_percent_per_week` is `None`, because the D-16 anchor window `2026-07-26 … 2026-08-01` holds zero weigh-ins after a 52-day logging gap. That is the correct answer, not a bug. It will start returning a number once four consecutive weeks each clear the 3-measured-day floor.

## Self-Check: PASSED

- `backend/app/analytics/bodyweight.py` — FOUND (294 lines, exceeds the plan's `min_lines: 160`)
- `backend/tests/test_analytics_bodyweight.py` — FOUND (428 lines, contains `time_machine`)
- `.planning/phases/05-progression-records-recomposition-analytics/05-06-SUMMARY.md` — FOUND
- Commits `442f1d1`, `62d8a96`, `b4113d5`, `6e794f9` — all FOUND in `git log`
- Both `key_links` patterns present: `build_measurement_coverage\(` and `local_day\(utc_now\(\)` match in `bodyweight.py`

## Threat Flags

None. No new network endpoint, auth path, file access pattern or schema change. The module adds one
`SELECT` over `body_measurements` with the tenant predicate leading, which is `T-05-38` in the
plan's own register and is mitigated as specified (keyword-only `user_id`, no default, proven by
`test_second_users_weigh_ins_are_invisible` against a 30 kg-heavier second user on the same dates).
`T-05-43`'s bound holds by construction: the fetch span is the module constant `_FETCH_SPAN_DAYS`,
never caller-supplied, so the result set cannot exceed 35 rows for any input.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

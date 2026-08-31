---
phase: 05-progression-records-recomposition-analytics
plan: 09
subsystem: analytics
tags: [python, decimal, plateau, streak, progression, state-machine, pytest, testcontainers, time-machine]

# Dependency graph
requires:
  - phase: 05-04
    provides: "progression.best_set_per_day (the D-04 per-(exercise, local day) series) and SessionBest"
  - phase: 05-07
    provides: "progression.py's PROG-02 section — the module skeleton, _PERCENT_QUANTUM and get_exercise_trends' composition shape"
  - phase: 05-03
    provides: "schemas.PlateauConfidence, schemas.PlateauResult and schemas.PlateauReport return contracts"
  - phase: 05-02
    provides: "rollup.qualifying_set_rows, rollup.resolve_window and rollup.MAX_ANALYTICS_WINDOW_DAYS"
  - phase: 05-06
    provides: "the documented probe-window idiom for reading users.timezone before the anchor day is known"
  - phase: 04-volume-frequency-analytics
    provides: "metadata.earliest_workout_at / build_coverage / build_freshness / FRESHNESS_RESOURCES_MUSCLE, core.time.local_day and utc_now"
provides:
  - "PLATEAU_MIN_QUALIFYING_SESSIONS / PLATEAU_MIN_ELAPSED_DAYS — D-06's two floors, applied conjunctively"
  - "PLATEAU_IMPROVEMENT_TOLERANCE — D-07's 2% band as a named Decimal constant"
  - "DEFAULT_PLATEAU_LOOKBACK_WEEKS — D-19's 12-week bound"
  - "PlateauScan — the frozen pure result of one streak scan, separate from the Pydantic PlateauResult"
  - "scan_plateau() — PUBLIC pure forward state machine over the D-04 series, seeded from a caller-supplied pre-window best"
  - "get_plateaus() — PROG-03's public function, one row per exercise trained inside the bounded lookback"
affects: [05-10, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One query, split in Python: the pre-lookback seed and the in-window series come from a single qualifying_set_rows call rather than two aggregates that could disagree about the warm-up rule"
    - "The read is clamped, the echo is not: the fetch start is bounded by MAX_ANALYTICS_WINDOW_DAYS while the response still reports the window the caller asked about"
    - "A pure scan dataclass beside the Pydantic model, so the streak rules are testable with no container and the echoed thresholds stay out of the algorithm"
    - "Conjunctive floors: a session count AND a calendar span, each tested from its own failing side"

key-files:
  created: []
  modified:
    - backend/app/analytics/progression.py
    - backend/tests/test_analytics_progression.py

key-decisions:
  - "lookback_start is `lookback_end - (7 * lookback_weeks - 1)`, an INCLUSIVE 84-day window for 12 weeks; the plan's own worked example said 2026-06-07, which is 85 days and contradicts its formula — the formula won and the tests pin 2026-06-08"
  - "The pre-lookback seed is a per-template maximum over days strictly before lookback_start, folded out of the same rows the scan reads — not a second query and not a second aggregate"
  - "The fetch start is clamped to MAX_ANALYTICS_WINDOW_DAYS before resolve_window is called, so an oversized lookback_weeks ANSWERS from at most five years of history instead of raising (T-05-66)"
  - "The echoed lookback_start stays the UNCLAMPED caller window: the clamp bounds what is read, not what was requested, and a silently narrowed echo would claim a window that was never evaluated"
  - "plateau_duration_days is None (never 0) when plateaued is False — 'we did not call this a plateau' is a different fact from 'it has lasted zero days'"
  - "A breaking session STARTS the new streak rather than being excluded from it: it is the most recent evidence of progress, so the clock runs from it"
  - "running_best absorbs in-window sessions, so a break raises the bar for everything after it rather than letting one big session be beaten repeatedly by smaller ones"
  - "get_plateaus takes lookback_weeks, not a start/end pair: a plateau is always measured back from today, and a caller-supplied end date would let a stale window report a duration that stopped accruing"

patterns-established:
  - "Pattern 1: a seeded running maximum makes a windowed streak scan invariant to the window boundary — the load-bearing test widens the lookback and asserts the duration does not move"
  - "Pattern 2: the fixture for a seeding test must ESCALATE its in-window values; a flat fixture passes against an unseeded implementation and proves nothing"
  - "Pattern 3: a threat-register 'mitigate' disposition gets its own test even when the plan's test list omits it (T-05-66's clamp)"

requirements-completed: [PROG-03]

# Metrics
duration: 25min
completed: 2026-08-31
---

# Phase 5 Plan 09: PROG-03 Plateau Detection Summary

**Plateau detection as a pure seeded streak scan over the D-04 series — D-06's conjunctive session/calendar floors, D-07's 2% tolerance band, D-07a's null-estimate skip — behind a 12-week bounded `get_plateaus()` that echoes its window and threshold into every row.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-31T04:00:00Z (approx.)
- **Completed:** 2026-08-31T04:25:00Z (approx.)
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- `scan_plateau()` — a pure, synchronous forward state machine implementing D-06, D-07, D-07a and D-07b, testable with no container. Seeded from a caller-supplied pre-window best so widening the lookback cannot move the streak start.
- `get_plateaus()` — PROG-03's public function. One clamped `qualifying_set_rows` call spans `[history_start, lookback_end]` and is split in Python at `lookback_start`; the pre-window half produces the per-template seed, the in-window half the scan.
- Every `PlateauResult` carries `recent_performance_kg` beside `historical_best_kg`, plus the threshold and both floors and both window dates — never a bare boolean.
- 16 new tests (7 fast-suite, 9 container-backed under a frozen clock). Full backend suite: **472 passed**.

## Exact signatures

```python
def scan_plateau(
    series: Sequence[SessionBest], *, historical_best: Decimal | None, as_of: dt.date
) -> PlateauScan: ...

async def get_plateaus(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    lookback_weeks: int = DEFAULT_PLATEAU_LOOKBACK_WEEKS,
    template_external_ids: Sequence[str] | None = None,
) -> PlateauReport: ...

@dataclass(frozen=True, slots=True)
class PlateauScan:
    plateaued: bool
    streak_start: dt.date | None
    qualifying_sessions: int
    recent_performance_kg: Decimal | None
    historical_best_kg: Decimal | None
    confidence: PlateauConfidence
```

Signature verified by `inspect.signature`: parameter order is exactly `['session', 'user_id', 'lookback_weeks', 'template_external_ids']`, `user_id` is `KEYWORD_ONLY` with no default, `lookback_weeks` defaults to `DEFAULT_PLATEAU_LOOKBACK_WEEKS == 12`, `template_external_ids` defaults to `None`.

## Live-data measurement (the single clamped history query)

Measured read-only against the running local Postgres (`brett-db-1`) holding the real Hevy history, at the 12-week default:

| Figure | Observed |
|---|---|
| `lookback_end` / `lookback_start` | `2026-08-31` / `2026-06-09` (84 inclusive days) |
| `earliest_workout_at` | `2025-04-01T08:10:27Z` |
| `history_start` after the clamp | `2025-04-01` — the clamp does **not** engage; 518-day span is well inside the 1,830-day cap |
| **Rows returned by the one history query** | **7,719** |
| **Query elapsed** | **45.6 ms** cold, 56.9 ms on a second run |
| `get_plateaus` end-to-end | 49.3 ms / 50.3 ms |
| Exercises reported (trained inside the lookback) | 41 |
| Flagged `plateaued` | 23, durations **30–80 days** |

The 7,719-row figure matches the threat register's T-05-66 estimate exactly. Timings are higher than the register's 17 ms note because this is measured through SQLAlchemy row construction on a laptop container, not as raw SQL.

Sample of the top flagged rows, showing that `recent_performance_kg` / `historical_best_kg` does the work D-07b asks of it:

```
'T Bar Row'                         days=72 sessions=10 conf=high   recent/best=87.9%
'Leg Press Horizontal (Machine)'    days=73 sessions=9  conf=medium recent/best=98.7%
'Seated Leg Curl (Machine)'         days=73 sessions=5  conf=low    recent/best=96.1%
'Lat Pulldown - Close Grip (Cable)' days=58 sessions=6  conf=medium recent/best=93.0%
'Incline Bench Press (Barbell)'     days=78 sessions=11 conf=high   recent/best=95.9%
```

## `lookback_start` for a 2026-08-30 anchor at 12 weeks

**`2026-06-08`**, not the plan's `2026-06-07`. `2026-08-30 - (7 × 12 - 1) = 2026-08-30 - 83 days = 2026-06-08`, and `[2026-06-08, 2026-08-30]` inclusive is exactly 84 days = 12 weeks. See the deviation below.

## Confirmation: no 05-04 or 05-07 function was modified

`git diff def87f5..HEAD -- backend/app/analytics/progression.py` contains **four** deleted lines in total:

1. `from app.analytics.rollup import QualifyingSetRow, qualifying_set_rows, resolve_window` — expanded to a parenthesised list to add `MAX_ANALYTICS_WINDOW_DAYS`
2. `from app.core.time import snap_local_week_range` — expanded to add `local_day` and `utc_now`
3. + 4. Two lines inside `weekly_e1rm_points` (05-07), where the loop variable `local_day` was renamed to `day` — see deviation 2

`best_set_per_day`, `get_exercise_progression`, `_weekly_slope`, `classify_trend` and `get_exercise_trends` are byte-identical to what 05-04 and 05-07 shipped. The module docstring gained one bolded paragraph; every prior paragraph is unchanged.

## Task Commits

1. **Task 1: plateau constants + `scan_plateau`** (TDD)
   - `b66cc39` — `test(05-09)`: seven failing fast-suite streak-scan tests (RED)
   - `0b81b53` — `feat(05-09)`: the four constants, `PlateauScan`, `_plateau_confidence`, `scan_plateau` (GREEN)
2. **Task 2: `get_plateaus`** (TDD)
   - `9a1ee0a` — `test(05-09)`: eight failing container-backed tests under a frozen clock (RED)
   - `4e1ccc0` — `feat(05-09)`: `get_plateaus` with the bounded, clamped, split-in-Python query (GREEN)
3. **Task 3: verification pass + the missing clamp test**
   - `cde1410` — `test(05-09)`: cover the five-year fetch clamp (T-05-66)

No REFACTOR commit was needed — the GREEN implementations were already at their final shape.

**TDD gate compliance:** both TDD tasks show a `test(...)` commit followed by a `feat(...)` commit, in that order, with the RED commit verified failing (`ImportError` on the not-yet-existing symbols) before the GREEN commit was made.

## Files Created/Modified

- `backend/app/analytics/progression.py` — appended PROG-03's section: four constants, `PlateauScan`, `_plateau_confidence`, `scan_plateau`, `get_plateaus`. One new module-docstring paragraph. `+301 / -4` (the four deletions are the two widened import statements and the two renamed loop-variable lines).
- `backend/tests/test_analytics_progression.py` — appended two PROG-03 sections (fast-suite scan tests, container-backed `get_plateaus` tests), three module-docstring paragraphs, and the plateau fixture constants. `+667 / -1` (the one deletion is the widened `app.analytics.schemas` import).

No migration created. No dependency added. No other file touched.

## Decisions Made

See `key-decisions` in the frontmatter. The two that a future reader is most likely to second-guess:

1. **`2026-06-08`, not `2026-06-07`.** The 12-week window is inclusive of both ends, so it spans 84 days. Writing `- 7 * lookback_weeks` instead of `- (7 * lookback_weeks - 1)` produces an 85-day window and calls it twelve weeks. A comment at the arithmetic states this so it is not "corrected" back.
2. **The clamp bounds the read, not the echo.** `get_plateaus(lookback_weeks=400)` reports `lookback_start = 2018-12-31` while reading only from `2021-08-27`. Narrowing the echo to the clamped floor would make the response claim a window it never evaluated; raising instead would turn a coaching question into an error over a number the caller was allowed to pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's `lookback_start` literal contradicts its own formula**

- **Found during:** Task 2 (and Task 3's grep acceptance criteria)
- **Issue:** The plan states the formula `lookback_start = lookback_end - (7 * lookback_weeks - 1)` twice — once in `<behavior>` and once in the literal code to write — but its Task 3 test spec and its `grep -q "2026, 6, 7"` acceptance criterion both assert `dt.date(2026, 6, 7)`. For a `2026-08-30` anchor the formula yields `2026-06-08`; `2026-06-07` is 84 days back, producing an 85-day "12-week" window. Verified arithmetically before writing any code.
- **Fix:** Implemented the formula (stated twice, and semantically correct — 84 inclusive days is exactly 12 weeks). Tests pin `_PLATEAU_START_12W = dt.date(2026, 6, 8)` and `_PLATEAU_START_24W = dt.date(2026, 3, 16)`, both spelled out as literals rather than derived, with a comment explaining the inclusivity.
- **Files modified:** `backend/app/analytics/progression.py`, `backend/tests/test_analytics_progression.py`
- **Verification:** `test_plateaued_exercise_reports_window_and_threshold` asserts `(lookback_start, lookback_end) == (2026-06-08, 2026-08-30)` and passes; the live measurement independently shows an 84-day window for a 2026-08-31 anchor.
- **Committed in:** `4e1ccc0` (code), `9a1ee0a` (tests)
- **Consequence:** the plan's `grep -q "2026, 6, 7"` acceptance criterion does **not** hold. Every other Task 3 grep criterion does.

**2. [Rule 3 - Blocking] Ruff F402: `local_day` import shadowed by a 05-07 loop variable**

- **Found during:** Task 2 (GREEN)
- **Issue:** `get_plateaus` needs `from app.core.time import local_day`, but `weekly_e1rm_points` (shipped by 05-07) destructures its dict key into a loop variable also named `local_day`. Ruff F402 rejects the module outright, so the plan's "do not modify anything 05-07 shipped" and "import `local_day` from `app.core.time`" instructions cannot both be honoured literally.
- **Fix:** Renamed the loop variable to `day` in `weekly_e1rm_points` (two lines, one token each) with a comment naming the reason. Chosen over aliasing the import, which would have broken the plan's `grep -q "local_day(utc_now(), tz)"` criterion and diverged from `bodyweight.py`'s established idiom.
- **Files modified:** `backend/app/analytics/progression.py`
- **Verification:** No behaviour change — a local rename inside one loop. `weekly_e1rm_points`' three existing 05-07 tests (`test_week_offsets_are_not_compressed`, `test_weekly_points_take_the_week_maximum_and_skip_nulls`, and the PROG-02 integration tests) all still pass. `ruff check` and `mypy` clean.
- **Committed in:** `4e1ccc0` (Task 2 GREEN commit)

**3. [Rule 2 - Missing Critical] No test for the five-year fetch clamp (T-05-66)**

- **Found during:** Task 3
- **Issue:** The threat register assigns `mitigate` to T-05-66 and the plan's Task 2 `<behavior>` requires the clamp, but the Task 3 test list has no case for it. The clamp was therefore implemented and entirely unexercised — a `lookback_weeks=400` call would have silently regressed to `ValueError: requested analytics window exceeds the maximum span`.
- **Fix:** Added `test_an_oversized_lookback_is_clamped_rather_than_rejected`, which calls `get_plateaus(lookback_weeks=400)` (a 2,800-day request) and asserts it answers, reports the unclamped `lookback_start = 2018-12-31`, and returns the full five-session streak.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** Confirmed discriminating rather than vacuous — `build_window(start_day=2018-12-31, end_day=2026-08-30, ...)` does raise, and the clamped `2021-08-27` start is accepted at exactly `days == 1830`.
- **Committed in:** `cde1410`

---

**Total deviations:** 3 auto-fixed (1 bug, 1 blocking, 1 missing critical)
**Impact on plan:** All three were necessary. Deviation 1 corrects an off-by-one that would have shipped an 85-day "12-week" window; deviation 2 was a hard lint failure with no alternative that satisfies the plan's other criteria; deviation 3 closes an untested security mitigation. No scope creep — still exactly the two files the plan names.

## Issues Encountered

**The plan's `test_historical_best_is_seeded_from_before_the_lookback` fixture cannot prove what it claims.** The plan specifies "same fixture" as the preceding test (a pre-lookback 105 kg session plus four flat in-window sessions), then asserts `plateau_duration_days` is identical at 12 and 24 weeks. Two problems, both found by working the arithmetic before writing the test:

1. The plan's pre-lookback session (more than 12 weeks back) falls *inside* the 24-week window, so widening legitimately lengthens the streak — the durations must differ. Fixed by placing the seed session at `2026-03-01`, before **both** lookback starts.
2. With flat in-window values the test passes against an implementation that ignores the seed entirely, because the first in-window session starts the streak either way. Fixed by escalating the in-window loads (90 → 95 → 96 → 97 kg, i.e. 105.000 → 110.833 → 112.000 → 113.167), so the second session beats the first by more than 2%. Unseeded, that manufactures a break at the window edge and collapses the answer to a three-session, 20-day streak — below D-06's calendar floor, so `plateau_duration_days` becomes `None` rather than `27`.

The test's docstring records both traps so the fixture is not "simplified" later.

## Verification

| Check | Result |
|---|---|
| `pytest -q` (full backend suite) | **472 passed** |
| `pytest -q -m "not integration"` (fast suite) | **246 passed**, 226 deselected |
| `pytest -q tests/test_analytics_progression.py` | **41 passed** (25 before this plan, +16) |
| `pytest -q -m "not integration" tests/test_analytics_progression.py` | **18 passed** (11 before, +7 — all runnable with Docker stopped) |
| `ruff check backend/` | clean |
| `ruff format --check` on both changed files | clean |
| `mypy backend/app/` | clean, 52 source files |
| `mypy` on both changed files | no error attributable to either file |
| `git diff --stat` vs base | exactly 2 files |
| Alembic migration created | none |

**`mypy backend/` note:** exits 1 with **44 errors in 13 files**, identical to the pre-existing baseline recorded for this phase. Neither `backend/app/analytics/progression.py` nor `backend/tests/test_analytics_progression.py` appears in that output (verified by grep — 0 matches). The plan's verification step 3 asks for `mypy backend/` to exit 0; that has not been true since before Phase 5 began and is out of this plan's scope.

**`ruff format --check backend/`** reports 14 pre-existing files that would be reformatted. Neither changed file is among them; both are individually clean. Out of scope (logged as pre-existing, not fixed).

## Requirement status

**PROG-03 is fully satisfied by this plan.** Every clause of the requirement is implemented and tested: plateau detection over a configurable multi-week window (`lookback_weeks`, defaulting to 12), with the window (`lookback_start` / `lookback_end`) and the threshold (`threshold_percent`, `min_sessions`, `min_elapsed_days`) returned alongside the result on every `PlateauResult`.

**Per the parallel-execution instructions, `.planning/REQUIREMENTS.md` was NOT edited by this agent** — a sibling agent (05-10) is running concurrently against the same file. The orchestrator should mark PROG-03 complete after merging this wave.

## Known Stubs

None. No hardcoded empty collections, placeholder strings or unwired data paths were introduced.

## Threat Flags

None. No new network endpoint, auth path, file access pattern or schema change was introduced. `get_plateaus` is read-only, tenant-scoped through `qualifying_set_rows` and `earliest_workout_at` (both `user_id` keyword-only, no default), and adds one input — `lookback_weeks` — which the plan's threat model already covers under T-05-66 and T-05-67, both mitigated and now both tested.

## Next Phase Readiness

- `get_plateaus()` is ready for Phase 6's MCP tool layer. It takes a session positionally and everything else keyword-only, returns a `PlateauReport` whose models all subclass `_AnalyticsModel`, and makes no HTTP call back into the app (blueprint §37).
- `scan_plateau()` and `PlateauScan` are public and pure, available to 05-10 / BODY-02 should a plateau signal be wanted beside the trend signal.
- No blockers.

## Self-Check: PASSED

- Both claimed files exist on disk (`backend/app/analytics/progression.py`, `backend/tests/test_analytics_progression.py`) and the SUMMARY itself was written.
- All five commit hashes (`b66cc39`, `0b81b53`, `9a1ee0a`, `4e1ccc0`, `cde1410`) resolve in `git log`.
- Line counts re-derived from `git diff --numstat` against the base commit rather than transcribed.
- Live measurement figures taken from two independent runs of the same read-only script.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

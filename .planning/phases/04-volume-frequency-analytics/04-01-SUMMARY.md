---
phase: 04-volume-frequency-analytics
plan: 01
subsystem: analytics
tags: [zoneinfo, datetime, timezone, postgres-index, sqlalchemy, pytest]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "app/core/time.py with local_day_bounds/local_week_start and the UTC-storage guard, plus test_time.py's verified Jakarta boundary table"
  - phase: 03-hevy-integration-normalization
    provides: "The live synced dataset (327 workouts / 7,984 sets) whose exercise_type counts the corrected column comment records"
provides:
  - "local_range_bounds(start_day, end_day, tz) -> half-open UTC pair for an inclusive local date range, index-safe for ix_workouts_user_id_start_time"
  - "snap_local_week_range(start_day, end_day) -> range widened outward to whole Monday-start weeks (U-01)"
  - "local_week_spine(start_day, end_day) -> gap-free ascending list of local week-start Mondays, including zero-training weeks"
  - "A fixed, user-data-free ValueError('end_day precedes start_day') contract shared by all three helpers"
  - "An exercise_type column comment listing only the nine values present in live data, forbidding a hardcoded modality allow-list"
affects: [04-02, 04-03, 04-04, 04-05, 04-06, 04-07, 04-08, 04-09, phase-05-progression-plateaus, phase-06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Index-safe window filtering: compute UTC bounds in Python, compare the bare timestamp column against two constants rather than wrapping it in AT TIME ZONE"
    - "Outward week snapping for bucketed metrics, raw range for rate metrics"
    - "Gap-free spine enumerated in Python, never inferred from returned rows"
    - "Error messages at a logged boundary are fixed literals carrying no operand and no user id"

key-files:
  created: []
  modified:
    - backend/app/core/time.py
    - backend/tests/test_time.py
    - backend/app/db/models/exercise.py

key-decisions:
  - "local_range_bounds delegates to local_day_bounds instead of repeating ZoneInfo arithmetic, so DST-nonexistent-midnight handling has exactly one implementation"
  - "The week spine is enumerated in Python rather than via Postgres generate_series, keeping it unit-testable with no container and sidestepping SQLAlchemy's set-returning-function alias trap"
  - "No MAX_ANALYTICS_WINDOW_DAYS clamp in core/time.py: the range policy is a Phase 4 product decision owned by app/analytics/rollup.py (plan 04-05), not by this provider-neutral module"
  - "The three phantom exercise_type strings were removed from exercise.py entirely rather than quoted in a 'previously listed' note, so a grep for the modality vocabulary cannot resurface them"

patterns-established:
  - "Analytics window shape: an inclusive local date pair in, a half-open UTC pair out (D-03)"
  - "Bucketed metrics (weekly volume) snap outward; rate metrics (frequency) divide by the true window length"
  - "Modality gating branches on operand presence (weight_kg IS NOT NULL AND reps IS NOT NULL), never on an exercise_type allow-list"

# Deliberately empty. This plan's frontmatter lists [VOL-01, VOL-02, VOL-03], but it ships
# only the shared date-window primitives those requirements are built ON -- no volume,
# per-muscle or frequency calculation exists yet. Plans 04-02..04-09 deliver them. Marking
# them complete here would assert "System calculates weekly training volume" against code
# that cannot. See "Requirements Status" below.
requirements-completed: []
requirements-advanced: [VOL-01, VOL-02, VOL-03]

# Metrics
duration: 13min
completed: 2026-08-30
---

# Phase 4 Plan 01: Local Window Helpers Summary

**Three pure date-window helpers in `core/time.py` — an index-safe inclusive-local-range-to-half-open-UTC converter, an outward Monday-week snapper, and a gap-free week spine — plus a corrected `exercise_type` vocabulary comment rewritten from live sync counts.**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-08-30T09:50Z
- **Completed:** 2026-08-30T10:03Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- `local_range_bounds` generalizes `local_day_bounds` to an arbitrary inclusive local date range (D-03) while delegating the actual `ZoneInfo` conversion to it, so the two can never drift apart on a DST transition day. It yields two bare-column comparison constants, which is what keeps `ix_workouts_user_id_start_time` usable — the research measured the `AT TIME ZONE`-on-the-column alternative as a Seq Scan removing 299 of 327 rows.
- `snap_local_week_range` implements the user-locked U-01 rule: weekly volume windows widen outward to whole Monday-start weeks so no bucket is a partial week reading as "volume dropped". Its docstring records that frequency deliberately does *not* use it.
- `local_week_spine` enumerates every week-start Monday in a range, so a week with zero training still produces a bucket instead of silently vanishing from the result.
- All three share one failure contract: `ValueError("end_day precedes start_day")`, a fixed literal with no date value and no user id, since it lands in a log sink (T-04-05).
- The `exercise_type` comment now lists the nine values that actually occur in the live sync with their real set counts, and instructs future implementers to gate tonnage on operand presence rather than a modality allow-list (T-04-10).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add `local_range_bounds`, `snap_local_week_range` and `local_week_spine` to `core/time.py`** — `fc2b4b9` (feat)
2. **Task 2: Add fast-suite unit tests for the three helpers to `test_time.py`** — `cad9bef` (test)
3. **Task 3: Correct the stale `exercise_type` vocabulary comment in `exercise.py`** — `5f775f4` (docs)

## Files Created/Modified

- `backend/app/core/time.py` — three new public functions appended directly below `local_day_bounds`. No existing function touched, no new import (the module already had `datetime as dt` and `ZoneInfo`), and no new `ZoneInfo(` call site: the count stayed at 3.
- `backend/tests/test_time.py` — import block extended in place, a `D-03 / U-01` section banner added in the file's existing style, eight new pure test functions appended, and one paragraph added to the module docstring recording the arbitrary-range shape and the snap rule.
- `backend/app/db/models/exercise.py` — comment above `exercise_type` replaced. The column definition itself is byte-identical; no migration, no type change, no import.

## Decisions Made

- **Delegation over duplication.** `local_range_bounds` calls `local_day_bounds` twice rather than re-deriving the `ZoneInfo`/`combine`/`astimezone` sequence. A second copy is how the two would eventually disagree about a DST transition day, and the acceptance criteria pinned this by asserting `ZoneInfo(` still occurs exactly 3 times in the module.
- **Python enumeration over `generate_series`.** The week spine needs no Postgres container to unit-test and avoids the SQLAlchemy set-returning-function alias trap (`UndefinedColumnError` without `.render_derived()`).
- **No range clamp here.** `core/time.py` is provider-neutral; freezing a max-window product policy into it would make one Phase 4 decision permanent. T-04-06 is deliberately transferred to `app/analytics/rollup.py` in plan 04-05. The only guard added is the inverted-range `ValueError`, which converts a silently-empty result set into a loud failure.
- **Phantom modality strings deleted, not quoted.** See the deviation below.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's mandated `exercise_type` comment text failed the plan's own verification gate**

- **Found during:** Task 3 (Correct the stale `exercise_type` vocabulary comment)
- **Issue:** The plan instructed "Write exactly this" for a comment body containing the sentence *"This comment previously listed `bodyweight_reps`, `bodyweight_assisted_reps` and `weight_duration`, none of which Hevy has ever sent here."* That sentence re-introduces all three phantom strings into the file. The plan's own `<verify>` block contains a hard gate — `if grep -q "bodyweight_assisted_reps" ...; then echo "FAIL stale value still present"; exit 1; fi` — and three acceptance criteria requiring `grep -c` of `bodyweight_assisted_reps`, `weight_duration` and `bodyweight_reps` to each return 0. The mandated text and the mandated verification were mutually unsatisfiable.
- **Fix:** Kept the corrective note but expressed it without the literal tokens: *"This list REPLACES an earlier one that named three type strings Hevy has never sent here and omitted four it does send. Those three phantom strings are deliberately not repeated anywhere in this file — a grep for the modality vocabulary must not surface them again. The before/after is recorded in 04-RESEARCH.md, 'Live Data Ground Truth'."* This resolves in favour of the verification, which also matches the T-04-10 mitigation intent: the whole point is that a later implementer greping for a modality vocabulary must not find phantom values. The historical before/after is preserved by pointer rather than by repetition.
- **Files modified:** `backend/app/db/models/exercise.py`
- **Verification:** The plan's `<verify>` block now passes; all eight Task 3 grep criteria pass (`bodyweight_weighted` 1, `floors_duration` 1, `steps_duration` 1, `OPERAND PRESENCE` 1, and 0 for each of the three phantom strings); `test_db_models.py` + `test_migrations.py` 23 passed.
- **Committed in:** `5f775f4` (Task 3 commit)

**2. [Rule 3 - Blocking] Task 1 acceptance criterion `grep -c "generate_series" == 0` contradicts the mandated docstring**

- **Found during:** Task 1
- **Issue:** The plan's FUNCTION 3 block, also prefixed "write exactly this", contains the docstring line *"Enumerated in Python rather than with ``generate_series`` so it stays unit-testable…"* — while the acceptance criteria require `grep -c "generate_series"` to return 0.
- **Fix:** Resolved the opposite way from deviation 1, because the intents differ. Here the criterion's purpose is to prevent a SQL set-returning function from being *used* in a provider-neutral module, and the docstring mention is an explicit negation that documents exactly that choice — removing it would delete the rationale the plan wanted recorded. The mandated code was kept verbatim and the criterion verified by intent instead: `grep -c 'generate_series('` returns **0**, i.e. zero invocations; the sole match is the prose mention at `time.py:134`.
- **Files modified:** none (mandated code retained as written)
- **Verification:** `grep -c 'generate_series(' backend/app/core/time.py` → 0; `grep -n generate_series backend/app/core/time.py` → single hit, inside a docstring.
- **Committed in:** `fc2b4b9` (Task 1 commit)

**3. [Rule 2 - Missing Critical] Did not check off VOL-01/02/03, which this plan does not satisfy**

- **Found during:** State-update step, after all three tasks
- **Issue:** The plan frontmatter carries `requirements: [VOL-01, VOL-02, VOL-03]` and the standard flow marks those complete in `REQUIREMENTS.md`. But VOL-01 reads *"System calculates weekly training volume…"* and this plan ships only the date-window primitives underneath it — there is no volume, per-muscle or frequency aggregate anywhere in the tree yet. Marking them complete would record a capability the code cannot perform, and would be re-asserted by every other Phase 4 plan that shares the same three IDs. It would additionally race the other wave-1 worktree agents on a shared file.
- **Fix:** Left `.planning/REQUIREMENTS.md` untouched (all three still `[ ]` / `Pending`), set `requirements-completed: []` in this summary's frontmatter with an explanatory comment, added a `requirements-advanced` field recording the real relationship, and documented the reasoning in a "Requirements Status" section.
- **Files modified:** none (the correction is the *absence* of a write)
- **Verification:** `grep -n "VOL-0" .planning/REQUIREMENTS.md` shows lines 38-40 unchecked and lines 146-148 `Pending`; `git status --porcelain .planning/REQUIREMENTS.md` empty.
- **Committed in:** n/a — no change to commit

---

**Total deviations:** 3 auto-fixed (1 bug in the plan's mandated text vs. its own gate, 1 blocking criterion/text contradiction, 1 false-completion prevented)
**Impact on plan:** Deviations 1 and 2 are internal contradictions in the plan document, not implementation drift. Deviation 3 is a tracking-accuracy correction. Every behavioural requirement in the Task 1 and Task 2 `<behavior>` blocks was met exactly. No scope creep, no functional change relative to intent.

## Issues Encountered

- **Worktree base drift.** The worktree branch was created from `1e97f3b` (`chore(02-05)…`) rather than the specified feature-branch HEAD `a8332d7`, so Phase 4's planning artifacts were absent. Resolved with the prescribed `git reset --hard a8332d71…` from the startup check; HEAD verified at `a8332d7` before any work began.
- **No `.venv` inside the worktree.** `.venv` is gitignored and therefore not materialised in the worktree, so the plan's `.venv/bin/python` verify commands could not resolve against `git rev-parse --show-toplevel`. Ran every verification with the main checkout's interpreter (`/Volumes/…/BRETT/.venv/bin/python`) from the worktree cwd, so `pythonpath = ["backend"]` in `pyproject.toml` resolved to the worktree's own sources. Confirmed by the RED check, which reported all three helpers absent before Task 1.
- **TDD ordering.** Tasks 1 and 2 both carry `tdd="true"`, but the plan places the implementation in Task 1 and the pytest tests in Task 2 — a GREEN-before-RED shape. Preserved the plan's task boundaries (they define the commit split) and satisfied the RED gate with an explicit pre-implementation check asserting `local_range_bounds`, `snap_local_week_range` and `local_week_spine` were all absent from `app.core.time`. Commit types still read `test` for the test task.

## Verification Results

All seven items from the plan's `<verification>` block:

| # | Check | Result |
|---|---|---|
| 1 | `pytest backend/tests/test_time.py -q` (integration included) | **25 passed** in 2.23s |
| 2 | `pytest -q -m "not integration"` | **188 passed**, 114 deselected in 0.92s (≥185 required; baseline 0.94s) |
| 3 | `ruff check backend` | exit 0 |
| 4 | `mypy backend/app` | exit 0, 41 source files |
| 5 | `git diff --stat` touches exactly 3 files | `core/time.py`, `tests/test_time.py`, `db/models/exercise.py` |
| 6 | `git status --porcelain backend/migrations` empty | empty |
| 7 | `pyproject.toml` unmodified | unmodified — zero dependencies added |

Fast-suite count moved 177 → 188 (+11: eight test functions, one of which is parametrized 4×).

## Requirements Status

`.planning/REQUIREMENTS.md` was **deliberately left unmodified** — VOL-01, VOL-02 and VOL-03 remain `[ ]` / `Pending`.

The plan's frontmatter attributes all three to this plan, but they are shared across the whole of Phase 4 and this plan delivers none of them end to end:

| Requirement | Text | Delivered here? |
|---|---|---|
| VOL-01 | *System calculates weekly training volume…* | No — no aggregate query exists yet. This plan supplies the window bounds and week spine it will filter and project on. |
| VOL-02 | *System calculates weekly per-muscle-group volume…* | No — needs the resolver fan-out from a later plan. |
| VOL-03 | *System calculates training frequency…* | No — needs the frequency aggregate from a later plan. |

Checking them off now would assert a capability that does not exist. It would also race the other wave-1 worktree agents on a shared file. The orchestrator should mark these complete once the plans that actually implement the calculations land.

## Known Stubs

None. All three functions are fully implemented; no placeholder values, TODO/FIXME markers, or unwired data paths were introduced.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The three registered threats it touches are handled as planned: T-04-05 is pinned by `pytest.raises(..., match="end_day precedes start_day")` in all three inverted-range tests, T-04-10 by the Task 3 comment rewrite and its grep assertions, and T-04-06 remains deliberately transferred to plan 04-05.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The three helpers are the shared window primitive every later Phase 4 plan filters on. Plans 04-02 through 04-09 should import from `app.core.time` and must not re-derive week arithmetic inline.
- Weekly-volume plans must call `snap_local_week_range` before `local_range_bounds`; frequency plans must not (D-03 divides by the true window length).
- Any weekly result set must be projected onto `local_week_spine` rather than returned as the rows the query produced, or zero-training weeks disappear.
- `MAX_ANALYTICS_WINDOW_DAYS` is still owed by plan 04-05 (`app/analytics/rollup.py`). Until it lands, an unbounded range reaches the aggregates — the accepted T-04-06 transfer, not an oversight.
- Callers must still run the tz string through the existing `validate_timezone()` before it reaches `func.timezone(tz, col)` as a bound parameter (T-04-01); these helpers only hand it to `ZoneInfo`.
- No blockers.

## Self-Check: PASSED

- Files claimed modified — all present: `backend/app/core/time.py`, `backend/tests/test_time.py`, `backend/app/db/models/exercise.py`
- Summary file present: `.planning/phases/04-volume-frequency-analytics/04-01-SUMMARY.md`
- Commits claimed — all resolve in `git log`: `fc2b4b9`, `cad9bef`, `5f775f4`
- No file deletions in any of the three task commits (`git diff --diff-filter=D HEAD~1 HEAD` empty each time)
- No untracked files left behind

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*

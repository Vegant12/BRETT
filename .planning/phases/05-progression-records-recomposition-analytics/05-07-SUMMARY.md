---
phase: 05-progression-records-recomposition-analytics
plan: 07
subsystem: analytics
tags: [python, decimal, ols, least-squares, trend, progression, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 05-04
    provides: "progression.best_set_per_day (the D-04 per-(exercise, local day) series) and SessionBest"
  - phase: 05-03
    provides: "schemas.TrendVerdict, schemas.ExerciseTrend and schemas.ExerciseTrendsResult return contracts"
  - phase: 05-02
    provides: "rollup.qualifying_set_rows and rollup.resolve_window"
  - phase: 04-volume-frequency-analytics
    provides: "metadata.build_coverage / build_freshness / FRESHNESS_RESOURCES_MUSCLE, core.time.snap_local_week_range"
provides:
  - "MIN_TREND_WEEKS — D-05's four-distinct-training-weeks floor, as a named constant"
  - "TREND_STABLE_BAND_PERCENT_PER_WEEK — D-18's ±0.5%/week dead-band, in PERCENT units"
  - "weekly_e1rm_points() — PUBLIC pure fold from the D-04 series to per-template (week offset, week-max e1RM) points"
  - "_weekly_slope() — closed-form OLS slope, exact Decimal until one final quantized division"
  - "classify_trend() — PUBLIC pure verdict + rate, gated on D-05 and D-18"
  - "get_exercise_trends() — PROG-02's public function, one row per tracked exercise including the unclear ones"
affects: [05-09, 05-10, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Closed-form OLS in exact Decimal: four sums and one division, so the slope is assertable with == and no tolerance"
    - "Derived constant over invented constant: the dead-band is D-07's 2% ÷ D-05's 4 weeks, so two requirements cannot contradict each other by construction"
    - "Unit reconciliation carried as a code comment when a decision doc states the same value in different units"
    - "True week offsets, never a compressed index: a training gap widens the x-axis instead of vanishing"

key-files:
  created: []
  modified:
    - backend/app/analytics/progression.py
    - backend/tests/test_analytics_progression.py

key-decisions:
  - "TREND_STABLE_BAND_PERCENT_PER_WEEK is Decimal(\"0.5\") in PERCENT units, not CONTEXT.md's Decimal(\"0.005\") fraction form — same D-18 decision, matched to the units of `100 * slope / mean`; the reconciliation is a code comment so nobody 'corrects' it back"
  - "The regression is hand-rolled in Python: numpy is banned by CLAUDE.md, and PostgreSQL's regr_slope returns double precision even for numeric inputs"
  - "_weekly_slope returns None (not 0) for <2 points and for a zero denominator — a single week is 'unknown', not 'stable'"
  - "The dead-band edge is INCLUSIVE: exactly +0.5%/week reads as improving, not stable"
  - "The rate normalizer is the window MEAN, not the first point — otherwise moving the start date one week flips a verdict with no change in training"
  - "weeks_with_data counts weeks that produced an ESTIMATE, not weeks trained, so a 15-rep-only exercise reports 0 and UNCLEAR rather than looking like a bug"
  - "Every template with a hard set is reported including UNCLEAR ones, because D-20 excludes unclear from its net score explicitly and can only do so if unclear is visible"

patterns-established:
  - "Pattern 1: a shared numeric threshold is DERIVED from an existing tolerance rather than introduced independently, so two requirements cannot disagree"
  - "Pattern 2: when a decision document states a value in different units from the comparison site, the reconciliation lives in a comment at the constant and in the load-bearing test's docstring"
  - "Pattern 3: the negative side of a symmetric band is built by reversing the positive fixture, so the two edges cannot drift apart"

requirements-completed: [PROG-02]

# Metrics
duration: 21min
completed: 2026-08-31
---

# Phase 5 Plan 07: PROG-02 Exercise Trend Classification Summary

**An improving / stable / declining / unclear verdict per tracked exercise, from a closed-form exact-`Decimal` least-squares slope over each week's best estimated 1RM, with D-18's ±0.5%/week dead-band derived from D-07's 2% tolerance rather than invented.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-08-31T00:00:00Z (approx.)
- **Completed:** 2026-08-31
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- `get_exercise_trends()` ships PROG-02: one set-grain query, folded once through the **same** `best_set_per_day` series PROG-01 reports, so the phase carries exactly one definition of "the lifter got stronger".
- The slope is closed-form OLS in exact `Decimal` — four sums and one division. The denominator depends only on which week offsets are present, so it is an integer for every window, which is what makes `_weekly_slope(...) == Decimal("1.0000")` assertable with no tolerance anywhere in the suite.
- The dead-band is **derived**: D-07's 2% plateau tolerance ÷ D-05's 4-week minimum = 0.5%/week. PROG-02 and PROG-03 now share one underlying noise floor, so an exercise cannot read as "improving" at a rate PROG-03's tolerance would refuse to call an improvement.
- Twelve new tests: six fast-suite (no Docker) pinning the exact slope, both dead-band edges on both signs, both sides of the D-05 gate, scale invariance and the uncompressed x-axis; six container-backed covering the verdict path, both unclear paths, ordering, tenant isolation and freshness.

## Task Commits

Each task was committed atomically. Tasks 1 and 2 are `tdd="true"`, so Task 1 carries a RED → GREEN pair:

1. **Task 1 (RED): failing fast-suite tests for trend classification** — `883aed0` (test)
2. **Task 1 (GREEN): exact-Decimal OLS slope, `weekly_e1rm_points`, `classify_trend`** — `36887fe` (feat)
3. **Task 2: `get_exercise_trends()`, PROG-02's public function** — `a764df2` (feat)
4. **Task 3: container-backed PROG-02 verdict tests** — `e2dacc7` (test)

No REFACTOR commit — the GREEN implementation needed no cleanup.

**Plan metadata:** committed with this SUMMARY.

## Files Created/Modified

- `backend/app/analytics/progression.py` — appended the PROG-02 section: two module-docstring paragraphs, `MIN_TREND_WEEKS`, `TREND_STABLE_BAND_PERCENT_PER_WEEK`, `_SLOPE_QUANTUM`, `_PERCENT_QUANTUM`, `weekly_e1rm_points()`, `_weekly_slope()`, `classify_trend()`, `get_exercise_trends()`. **`SessionBest`, `best_set_per_day()` and `get_exercise_progression()` are byte-unchanged** — the only removed lines in the whole diff are the two import statements that were widened.
- `backend/tests/test_analytics_progression.py` — appended one module-docstring paragraph, the shared point fixtures, `_session_best()`, `_seed_weekly_trend()` and twelve tests. **No test 05-04 wrote was modified** — the only removed line is the `from app.analytics.progression import ...` statement that was widened.

## Exact Signatures (05-09 and 05-10 build on these)

```python
def weekly_e1rm_points(
    bests: Mapping[tuple[str, dt.date], SessionBest], *, window_start: dt.date
) -> dict[str, list[tuple[int, Decimal]]]: ...

def _weekly_slope(points: Sequence[tuple[int, Decimal]]) -> Decimal | None: ...

def classify_trend(
    points: Sequence[tuple[int, Decimal]],
) -> tuple[TrendVerdict, Decimal | None]: ...

async def get_exercise_trends(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    template_external_ids: Sequence[str] | None = None,
) -> ExerciseTrendsResult: ...
```

Notes for downstream consumers:

- `weekly_e1rm_points` returns points **sorted ascending by week offset**, and only for templates that produced at least one estimate. A template whose every day failed the D-02/D-03 gates is **absent from the dict** — `get_exercise_trends` handles this with `.get(id, [])`, and BODY-02 must do the same.
- `classify_trend` returns `(UNCLEAR, None)` for fewer than `MIN_TREND_WEEKS` **distinct week offsets**, and also when the slope is undefined or the window mean is zero. `rate_percent_per_week is None` **exactly when** the verdict is `UNCLEAR`.
- `get_exercise_trends` reports **every** template with a hard set in the window, including the `UNCLEAR` ones. D-20 must not treat absence and `unclear` as the same fact.

## Observed Verdicts and Rates (fast-suite cases, as executed)

| Case | Points | Slope | Rate %/wk | Verdict |
|---|---|---|---|---|
| At the `+` edge | `(0,99.25) (1,99.75) (2,100.25) (3,100.75)` | `0.5000` | `0.50` | `IMPROVING` |
| Just inside `+` | `(0,99.265) (1,99.755) (2,100.245) (3,100.735)` | `0.4900` | `0.49` | `STABLE` |
| At the `−` edge | the `+` edge series reversed | `-0.5000` | `-0.50` | `DECLINING` |
| Just inside `−` | the inside-`+` series reversed | `-0.4900` | `-0.49` | `STABLE` |
| Scale invariance (every `y` × 2) | `(0,198.50) … (3,201.50)` | `1.0000` | `0.50` | `IMPROVING` |
| Gapped offsets `0,1,2,5` | `y = 100,101,102,103` | `0.5714` | `0.56` | `IMPROVING` |
| Dense offsets `0,1,2,3` | same `y` values | `1.0000` | `0.99` | `IMPROVING` |
| D-05 gate, 3 weeks | `(0,100) (1,120) (2,140)` | — | `None` | `UNCLEAR` |
| D-05 gate, 4 weeks | `(0,100) … (3,160)` | `20.0000` | `15.38` | `IMPROVING` |
| Exact-slope guard | `(0,100) (1,101) (2,102) (3,103)` | `1.0000` | `0.99` | `IMPROVING` |

The gapped-versus-dense pair is the one that proves the x-axis is not compressed: identical `y` values, `0.56%/week` against `0.99%/week`. Container-backed: 100→106 kg × 5 across four weeks classifies `IMPROVING` at exactly `1.94%/week`; a flat 100 kg × 5 across four weeks classifies `STABLE` at exactly `0.00%/week`.

## Confirmation: nothing upstream was touched

- **No Phase 4 module modified.** `git diff --stat` against the plan's base commit `a07e215` lists exactly two files: `backend/app/analytics/progression.py` and `backend/tests/test_analytics_progression.py`. `rollup.py`, `schemas.py`, `metadata.py`, `volume.py`, `frequency.py`, `core/time.py` and `pyproject.toml` are untouched.
- **No 05-04 function modified.** The entire removed-line set of the `progression.py` diff is two import statements (`from collections.abc import Sequence` → `Mapping, Sequence`; the `schemas` import widened to include `ExerciseTrend`, `ExerciseTrendsResult`, `TrendVerdict`). `SessionBest`, `best_set_per_day` and `get_exercise_progression` have zero changed lines.
- **No Alembic migration created** — still 5 revisions in `backend/migrations/versions/`.
- **No new dependency.**

## Decisions Made

Beyond the locked decisions the plan carried (D-05, D-18):

- **The D-18 unit reconciliation is load-bearing and is written down twice** — once as a comment at the constant, once in `test_dead_band_both_sides`'s docstring. `Decimal("0.005")` appears in the module exactly once, inside that comment, never as a value. A future reader "fixing" the constant to match CONTEXT.md's literal would make the band a hundred times too tight and `stable` unreachable, and only a both-edges test can catch it.
- **The negative dead-band fixtures are derived from the positive ones by reversal** (`[(x, y) for x, (_, y) in enumerate(reversed(_AT_BAND))]`) rather than hand-computed a second time, so the two edges cannot drift apart under a future edit.
- **`test_exercises_are_sorted_and_window_is_unsnapped` uses the `_UNALIGNED_*` Wed-to-Tue window** rather than `_START`/`_END`. See Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's window assertion for `test_exercises_are_sorted_and_window_is_unsnapped` could not fail**

- **Found during:** Task 3
- **Issue:** The plan specified asserting `window_start`/`window_end` equal `_START`/`_END`. Those constants are a Monday (2026-08-03) and a Sunday (2026-08-30), so a `snap_to_weeks=True` implementation would widen them to *exactly the same pair*. The assertion would pass against both the right and the wrong implementation — the trap the existing file's own comment at `_UNALIGNED_START` documents in prose.
- **Fix:** Used `_UNALIGNED_START`/`_UNALIGNED_END` (Wed 2026-08-05 → Tue 2026-08-11) and seeded the workout on `_DAY_2` (inside that range) instead of `_DAY_1`. Snapping would widen this to Mon 08-03 → Sun 08-16, so the assertion now discriminates. The sorting half of the test is unchanged.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** Test passes; the window assertion now has a failing counterfactual.
- **Committed in:** `e2dacc7` (Task 3 commit)

**2. [Rule 2 - Missing Critical] Strengthened the week-maximum test to cover both fold orders**

- **Found during:** Task 3 (written in Task 1's RED commit)
- **Issue:** The plan's `test_weekly_points_take_the_week_maximum_and_skip_nulls` describes one arrangement (two days in a week with e1RMs 100 then 110 → 110). A **last-wins** bug — `week_bests[offset] = best.best_e1rm_kg` with no comparison — produces the correct answer for that arrangement and would pass.
- **Fix:** The test now asserts both dict orders (100-then-110 and 110-then-100). The descending arrangement is the one a last-wins bug fails.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** Both assertions pass; removing the `current is None or ... > current` guard makes the descending case fail.
- **Committed in:** `883aed0` (Task 1 RED commit)

### Structural deviation (not a fix)

**3. Six of Task 3's fast-suite tests were written and committed during Task 1, to honour `tdd="true"`**

- **Reason:** Tasks 1 and 2 are marked `tdd="true"`, but the plan places *all* tests in Task 3 — which makes a genuine RED gate impossible for Task 1. The six pure tests covering Task 1's `<behavior>` block were therefore written first (`883aed0`, confirmed RED with `ImportError: cannot import name 'MIN_TREND_WEEKS'`), then the implementation made them green (`36887fe`).
- **Effect on the plan's acceptance criteria:** none. All twelve tests exist in the file at the end of Task 3, the file's final content matches what Task 3 specified, and every grep criterion passes.

### Acceptance criteria that are unsatisfiable as literally written

Two of Task 2's grep criteria conflict with the plan's own prescribed code:

- `grep -c "titles\[" backend/app/analytics/progression.py` → returns **1**, criterion expects 0.
- `grep -c "_template_titles" backend/app/analytics/progression.py` → returns **2**, criterion expects 0.

Both matches are inside **comments the plan's `<action>` block dictates verbatim** (`# \`titles.get(...)\`, never \`titles[...]\`` and `# ... so \`frequency._template_titles\` is neither needed nor copied`), plus one pre-existing 05-04 comment at line 273. This is exactly the prose-versus-use trap that `test_analytics_isolation.py`'s module docstring documents and that `test_hevy_isolation.py:88-93` first recorded.

**The substantive intent holds and was verified** by tokenizing the module and stripping comments and string literals: `titles[` appears **0 times in executable code**, `_template_titles` appears **0 times in executable code**. No dict subscript on `titles`, no call to `frequency._template_titles`.

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical) + 1 structural (TDD ordering) + 2 unsatisfiable-as-written grep criteria documented.
**Impact on plan:** Both auto-fixes make previously-vacuous assertions discriminating. No scope creep — no new file, no new dependency, no change to any function outside this plan's two named files.

## Issues Encountered

- **`ruff format --check backend/` reports 13 files it would reformat.** All 13 are pre-existing and unrelated (`app/integrations/hevy/{events,sync,workouts}.py`, `app/normalization/resolver.py`, and 9 Phase 3/4 test modules). Neither of this plan's two files is among them — both are `already formatted`. Out of scope per the executor's scope boundary; **not** fixed and **not** logged to a shared `deferred-items.md`, because a sibling agent (05-08) is running concurrently in the same wave and that file would be a merge-conflict surface. Flagging it here instead for the orchestrator.
- **`mypy backend/` reports 44 errors in 13 test modules.** Confirmed pre-existing and matching the count recorded in this wave's execution context. `mypy backend/app/` exits 0 across 51 files, and `mypy` on this plan's two files reports errors only from the *unmodified* `backend/tests/conftest.py` (6 errors, reproducible by running mypy on `conftest.py` alone at a clean working tree). `test_analytics_progression.py` itself contributes zero errors.

## Verification Results

| Check | Result |
|---|---|
| `pytest -q` (full suite) | **446 passed** |
| `pytest -q -m "not integration"` (fast suite) | **238 passed**, 208 deselected, 0.90 s |
| `pytest -q backend/tests/test_analytics_progression.py` | **25 passed** (13 before this plan → +12) |
| `pytest -q -m "not integration" backend/tests/test_analytics_progression.py` | **11 passed** (5 before → +6), 0.05 s, Docker not required |
| `pytest -q backend/tests/test_analytics_isolation.py` | **8 passed** — the no-float / no-raw-SQL / read-only guards still hold |
| `ruff check backend/` | All checks passed |
| `mypy backend/app/` | Success, 51 files |
| `git diff --stat a07e215..HEAD` | exactly 2 files, 719 insertions, 3 deletions |

## Requirement Status

**PROG-02 is fully satisfied by this plan.** Every element of the requirement ships: a four-valued verdict per tracked exercise derived from multiple training weeks, the D-05 minimum-weeks gate, the D-18 dead-band, the rate and the window carried as fields, and tenant isolation proven by a test in which the second user's rising series leaves the first user's verdict `STABLE`.

Per this wave's instructions I have **not** edited `.planning/REQUIREMENTS.md` — the sibling agent 05-08 is running concurrently and may touch adjacent lines. The orchestrator should mark **PROG-02** complete after merge.

## Known Stubs

None. No hardcoded empty collections, no placeholder text, no unwired data paths. Every value in `ExerciseTrendsResult` is computed from set rows.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **05-09 / 05-10 (BODY-02, recomposition):** `get_exercise_trends()` is the public entry point; `classify_trend()` and `weekly_e1rm_points()` are public and pure if a caller needs the pieces. D-20's exclusion of `unclear` from the net score works because `unclear` exercises are present in `exercises` with `weeks_with_data` explaining why.
- **05-08 (PROG-03, plateaus, running concurrently):** shares `best_set_per_day` and may reuse `weekly_e1rm_points`. The dead-band derivation means the two requirements are now structurally consistent — but they will still legitimately disagree on real data over different windows, which is why both return types carry their window as a field.
- **Phase 6 (MCP-02):** `ExerciseTrendsResult` is a frozen `_AnalyticsModel` with `hide_input_in_errors=True`; `template_external_ids` is available to keep a tool response compact.
- **No blockers.**

## Self-Check: PASSED

- Files claimed as modified — both exist on disk: `backend/app/analytics/progression.py`, `backend/tests/test_analytics_progression.py`.
- SUMMARY exists at `.planning/phases/05-progression-records-recomposition-analytics/05-07-SUMMARY.md`.
- All four claimed commit hashes resolve in `git log`: `883aed0`, `36887fe`, `a764df2`, `e2dacc7`.
- TDD gate sequence present in order: `test(...)` (RED) → `feat(...)` (GREEN). No REFACTOR gate needed.
- Shared orchestrator artifacts untouched: `.planning/STATE.md`, `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` have zero changes in this branch.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

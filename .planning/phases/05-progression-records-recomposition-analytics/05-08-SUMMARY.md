---
phase: 05-progression-records-recomposition-analytics
plan: 08
subsystem: analytics
tags: [python, sqlalchemy, postgres, decimal, pydantic, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "frequency.sessions_per_week (made public in Phase 4 specifically for CMP-01), rollup.weekly_set_rows / fold_window_by_template / fold_window_by_muscle / resolve_row_muscles, metadata.build_coverage / build_freshness, volume.py's None-versus-zero tonnage rule"
  - phase: 05-progression-records-recomposition-analytics
    provides: "schemas.ComparisonRate / ComparisonLevel / MuscleGroupComparison / PeriodSummary / PeriodComparisonResult (05-03), rollup.qualifying_set_rows (05-02), progression.best_set_per_day and estimates.estimate_1rm (05-04)"
provides:
  - "CMP-01: compare_periods() — two-period comparison with counts and sums normalized per week"
  - "The counts-and-sums-only normalization rule, encoded structurally as two return types rather than one type with a flag"
  - "_per_week: sessions_per_week generalised from an int count to a Decimal sum, proven byte-identical on integer inputs"
  - "_delta_percent: null percent delta on a zero or absent baseline"
affects: [06-mcp-server, fitness_compare_periods]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rate-versus-level as two Pydantic types built by two functions, so normalizing a maximum is unrepresentable rather than merely discouraged"
    - "One _period_facts gatherer called once per period, so two periods cannot drift apart"
    - "Absence is None, never zero-per-week, so delta_percent stays honest"
    - "Response-size expansion gated behind an opt-in parameter against MCP-03 compactness"

key-files:
  created:
    - backend/app/analytics/comparison.py
    - backend/tests/test_analytics_comparison.py
  modified: []

key-decisions:
  - "Per-week normalization applies to counts and sums only; the per-exercise best e1RM is compared as a level and is never divided by weeks"
  - "Neither period is week-snapped — Phase 4's D-03 carries forward to both periods independently"
  - "A zero or absent period-A baseline yields delta_percent = None, never an exception, a non-finite Decimal, or a silent zero"
  - "Per-muscle rows are behind include_muscle_groups=False (96+ numbers against MCP-03's compact-JSON requirement)"
  - "Period A is the baseline and period B the comparison, so every delta reads 'B minus A'"
  - "The e1RM level is quantized to 0.001 at the _period_facts boundary rather than inherited from estimate_1rm, so a future level metric from another source cannot ship unquantized"

patterns-established:
  - "Structural correctness over reviewed correctness: where a wrong number would still look plausible, the wrong thing is made unrepresentable by the type system"
  - "Prose in test modules states a banned-helper rule in words rather than naming the helper, so a substring guard does not fail on the sentence documenting it"

requirements-completed: [CMP-01]

# Metrics
duration: 34min
completed: 2026-08-31
---

# Phase 5 Plan 08: Two-Period Comparison (CMP-01) Summary

**`compare_periods()` compares two unequal-length windows with counts and sums expressed per week and the best estimated 1RM compared as a level, so a 28-day period against a 14-day one holding identical weekly training produces a zero delta instead of a fabricated 50% drop.**

## Performance

- **Duration:** ~34 min
- **Started:** 2026-08-31T00:00:00Z (approx.)
- **Completed:** 2026-08-31
- **Tasks:** 3 of 3
- **Files created:** 2 (no files modified)

## Accomplishments

- `compare_periods()` ships CMP-01: both windows resolved unsnapped, each period gathered by one shared `_period_facts`, every count and sum normalized against its own period's true day count.
- The counts-and-sums-only rule is **structural**: `_rate` returns `ComparisonRate` and `_level` returns `ComparisonLevel`, and `ComparisonLevel` has no per-week field at all. A `normalized: bool` flag was rejected because a flag can be set wrongly in one branch and the resulting number still looks like a weight.
- `_per_week` is proven byte-identical to Phase 4's `sessions_per_week` across seven input pairs including four non-multiples of seven, so CMP-01's sessions figure and VOL-03's cannot drift.
- Each period reports its own `CoverageMetadata`, which is the only way to express "period A has four sessions and period B has one" — a case a single response-level block cannot carry.
- 11 tests, all green on the first run; full suite 445 passed.

## Task Commits

1. **Task 1: comparison.py with the per-week helper and the rate/level constructors** — `c511936` (feat)
2. **Task 2: compare_periods() — CMP-01's public function** — `fe00cc3` (feat)
3. **Task 3: backend/tests/test_analytics_comparison.py** — `85be99d` (test)

TDD gate note: this plan's frontmatter is `type: execute`, so the plan-level RED/GREEN/REFACTOR gate does not apply. Tasks 1 and 2 carry `tdd="true"` but the plan places the whole test module in Task 3, so the RED gate for each was executed as the plan's own `<verify>` command run *before* implementation — both failed with `ModuleNotFoundError` / `ImportError` as expected, then passed after implementation. There is therefore a `test(...)` commit after the `feat(...)` commits rather than before.

## Files Created/Modified

- `backend/app/analytics/comparison.py` (507 lines, new) — CMP-01. Exports `compare_periods`. Private helpers: `_per_week`, `_delta_percent`, `_rate`, `_level`, `_maybe_per_week`, `_PeriodFacts`, `_period_facts`, `_title`, `_muscle_comparison`, `_muscle_group_rows`, `_period_summary`.
- `backend/tests/test_analytics_comparison.py` (472 lines, new) — 11 tests (1 markerless, 10 container-backed). Fixture-id prefix `CMP-`.

**Nothing else was touched.** `git diff --stat` against the base commit shows exactly those two files, 979 insertions, 0 deletions. `frequency.py`, `volume.py`, `rollup.py`, `progression.py`, `schemas.py`, `metadata.py` and `pyproject.toml` are unmodified — CMP-01 **calls** `sessions_per_week`, it does not change it. No Alembic migration was created. No dependency was added.

## Plan-Required Output Details

### `compare_periods` exact signature

```python
async def compare_periods(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    period_a_start: dt.date,
    period_a_end: dt.date,
    period_b_start: dt.date,
    period_b_end: dt.date,
    include_muscle_groups: bool = False,
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> PeriodComparisonResult:
```

Session positional; everything else keyword-only; `user_id` and all four dates have no default (ASVS V4). Verified by `inspect.signature` in the Task 2 verify command.

### `totals` metric names and sort order

Sorted by `metric`, ascending: **`hard_sets`, `sessions`, `tonnage_kg`, `total_reps`**. (`tonnage_kg` precedes `total_reps` because `'n' < 't'` at the third character.) Pinned by `test_totals_metric_set_and_ordering`.

The `sessions` row goes through `frequency.sessions_per_week` itself, not the `Decimal` sibling, so CMP-01's and VOL-03's sessions rate for the same window are byte-identical.

### SQL round trips per call

Measured empirically with a `before_cursor_execute` listener against the test container, both periods holding training:

| Call | Round trips |
|------|-------------|
| `include_muscle_groups=False` | **12** |
| `include_muscle_groups=True` | **16** |

Breakdown of the 12: 2 × `resolve_window` (user timezone) + 2 × `weekly_set_rows` + 2 × `qualifying_set_rows` + 2 × `build_coverage` (2 queries each: session count, earliest workout) + 1 × `build_freshness` over 2 resources (2 queries). The muscle expansion adds 2 × `resolve_row_muscles` → `effective_muscles_bulk` at 2 queries each. A period with no training short-circuits its muscle resolution to zero queries, so 16 is the ceiling and 14 is what a one-sided fixture produces.

### `frequency.py` confirmation

**`backend/app/analytics/frequency.py` was NOT modified.** Confirmed by `git diff --stat` against the base commit, which lists only the two new files.

## Decisions Made

- **`_LEVEL_QUANTUM` is applied where the level is aggregated,** not left as a dead constant. `estimate_1rm` already quantizes to `0.001`, so this is a no-op today; it is applied at the `_period_facts` boundary so a future level metric sourced from something other than `estimate_1rm` cannot ship a number no coach reads and no test asserts on stably. Same argument `_PER_WEEK_QUANTUM` carries for rates.
- **A `_maybe_per_week` helper propagates absence.** The plan's `totals` and `exercises` blocks each need "normalize this, or return `None` if it is missing" on both sides. Six inline `None if x is None else _per_week(...)` expressions exceeded the 100-char line limit and invited passing the wrong period's `days`; one helper carries the rule and every call site names its own period's `window.days` explicitly.
- **Titles are read off `qualifying_set_rows`, never re-queried.** `SetRollupRow` carries no title, `QualifyingSetRow` does (its docstring names CMP-01 as one of the reasons), and `frequency._template_titles` is private to its module. `_title` falls back from period A to period B so a template that appears in only one period is still labelled.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_periods_are_not_snapped_to_whole_weeks` was vacuous as specified**

- **Found during:** Task 3
- **Issue:** The plan's `_A_START`/`_A_END` (2026-07-06 .. 2026-08-02) and `_B_START`/`_B_END` (2026-08-03 .. 2026-08-16) are **both whole Monday-to-Sunday spans**, confirmed by running `app.core.time.snap_local_week_range` on each: snapping returns the input unchanged. A snapping implementation would therefore pass every assertion the plan specified for that test. The plan's own date-constant comment claims `_B_` is "a deliberately NON-multiple-of-7 14-day range", which is self-contradictory — 14 is a multiple of 7.
- **Fix:** Kept the plan's constants (the zero-delta test needs equal weekly cadence and week-aligned windows are correct there) and added a third, deliberately ragged window `_RAGGED_START = 2026-07-08` (Wednesday) .. `_RAGGED_END = 2026-07-30` (Thursday), 23 days — the exact "4-week period against a 23-day period" shape the plan's own `locked_decisions` and module docstring describe. Snapped, it widens to 2026-07-06..2026-08-02 (28 days) and pulls in a fourth session. The test now asserts the plan's original three assertions against the aligned window **and** `start_day == _RAGGED_START`, `end_day == _RAGGED_END`, `days == 23`, `coverage.sessions_in_window == 3` against the ragged one.
- **Files modified:** `backend/tests/test_analytics_comparison.py`
- **Verification:** `snap_local_week_range(2026-07-08, 2026-07-30)` returns `(2026-07-06, 2026-08-02)`, so a snapping implementation now fails on both `days == 23` and `sessions_in_window == 3`.
- **Committed in:** `85be99d` (Task 3 commit)

**2. [Rule 1 - Bug] The prescribed module docstring failed the plan's own `pytest.approx` acceptance grep**

- **Found during:** Task 3
- **Issue:** The plan prescribes a module docstring ending `Never \`pytest.approx\`.` and, three lines later, an acceptance criterion that `grep -c "pytest.approx" backend/tests/test_analytics_comparison.py` returns 0. These cannot both hold. This is precisely the trap this codebase documents at `test_hevy_isolation.py:88-93` and re-states in `test_analytics_isolation.py`'s module docstring: a plain substring guard fails on the prose that documents the rule.
- **Fix:** Restated the rule in words without naming the helper — "Never an approximate comparison: every expected value below is an exact `Decimal` literal" — with an inline note explaining why the helper is not named. The rule is preserved, the grep now returns 0, and no self-referential trap was introduced.
- **Files modified:** `backend/tests/test_analytics_comparison.py`
- **Verification:** `grep -c "pytest.approx"` returns 0; no approximate comparison appears anywhere in the module.
- **Committed in:** `85be99d` (Task 3 commit)

### Acceptance criteria that could not be satisfied as literally written

**`grep -rl "CMP-" backend/tests/ | wc -l` returns 1** — it returns **3**. `test_analytics_frequency.py:17` and `test_analytics_progression.py:16` each mention the requirement id "CMP-01" in prose (both written by earlier plans in this phase), and "CMP-01" contains the substring "CMP-". The criterion's actual intent is fixture-id-prefix uniqueness in the shared session-scoped container. Verified with the anchored form instead: **`grep -rl '"CMP-' backend/tests/` returns exactly `backend/tests/test_analytics_comparison.py`** — the `CMP-bench` / `CMP-new` / `CMP-pushup` / `CMP-shared` ids collide with no `FREQ-*`, `VOL-*`, `PROG-*`, `ROLLUP-*` or `RESOLVER-*` id. Same class of substring-versus-anchored-regex issue as deviation 2. No source change was warranted.

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs, both in the plan's test specification), 1 acceptance criterion verified in an anchored form.
**Impact on plan:** Both fixes strengthen the test suite — one converts a vacuous test into one that actually catches week snapping, the other removes a self-contradiction. No scope creep; no production-code behaviour differs from the plan.

## Verification Results

| Check | Result |
|-------|--------|
| `pytest -q` (full suite) | **445 passed** |
| `pytest -q -m "not integration"` (fast suite) | **233 passed, 212 deselected** — includes `test_per_week_helper_agrees_with_sessions_per_week` |
| `pytest -q backend/tests/test_analytics_comparison.py` | **11 passed** |
| `pytest -q backend/tests/test_analytics_isolation.py` | **8 passed** (auto-covers `comparison.py` via `rglob`) |
| `ruff check backend/` | All checks passed |
| `mypy backend/app/` | Success, no issues in 52 source files |
| `mypy backend/tests/test_analytics_comparison.py` | 0 errors in the new file |
| `git diff --stat` vs base | exactly 2 files, 979 insertions, 0 deletions |
| Alembic migration created | none |

### mypy discrepancy (pre-existing, not introduced here)

The plan's verification item 3 asks for `mypy backend/` to exit 0. It does not: **44 errors across 13 test modules**, all pre-existing and confirmed against the base commit before any Phase 5 work. `mypy backend/app/` exits 0 and the new test module contributes 0 errors. This matches the baseline recorded in the execution context and is unchanged by this plan.

### Threat register

All `mitigate` dispositions in the plan's `<threat_model>` are satisfied:

- **T-05-56** (cross-tenant read) — every read goes through `weekly_set_rows` / `qualifying_set_rows` / `build_coverage`, each leading its `WHERE` with the tenant predicate; `user_id` keyword-only with no default and passed identically to both periods. Proven by `test_second_users_workouts_are_invisible`, which also pins the title lookup (Hevy's template ids are global).
- **T-05-57** (four caller-supplied dates) — each period validated independently by `build_window` via `resolve_window`; `end < start` rejected and `MAX_ANALYTICS_WINDOW_DAYS = 1830` clamped before anything is materialized.
- **T-05-58** (`weights` mapping) — forwarded unchanged to `rollup.fold_window_by_muscle`; never reaches SQL.
- **T-05-59** (muscle resolution) — `resolve_row_muscles` only; `grep -cE "ExerciseMuscle(Override)?" backend/app/analytics/comparison.py` returns 0 and `test_analytics_isolation.py` enforces it statically.
- **T-05-60** (per-muscle DoS) — `include_muscle_groups` defaults to `False`; no cross-muscle total is produced anywhere.
- **T-05-61** (normalizing the wrong metric) — two types, two functions; `sed -n '/exercise_levels/,/^    ]/p' | grep -c "_per_week"` returns 0; `grep -c "normalized: bool"` returns 0.
- **T-05-62** (result disclosure) — all component models subclass `_AnalyticsModel` (`hide_input_in_errors=True`, `extra="forbid"`, `frozen=True`).
- **T-05-63** (error paths) — the only new raise is `_per_week`'s `"window length must be positive"`, the exact literal `sessions_per_week` already uses, carrying no date, user id or exercise title.
- **T-05-64** (write path) — `test_analytics_isolation.py`'s `rglob` auto-covers `comparison.py` and passes; only `select`-derived helpers are used, and no write construct is imported.
- **T-05-65** — transferred to the MCP boundary (Phase 2, WorkOS AuthKit), unchanged.

**No new threat flags.** `comparison.py` introduces no network endpoint, no auth path, no file access and no schema change; every read reuses an existing tenant-scoped helper.

## Known Stubs

None. Every figure in `PeriodComparisonResult` is wired to a real query or a real fold; no placeholder text, no hardcoded empty collection reaching a caller. `muscle_groups == []` under the default is a deliberate, tested contract (`test_muscle_groups_are_opt_in`), not a stub.

## Issues Encountered

- The first empirical round-trip measurement returned 14 rather than the expected 16 with `include_muscle_groups=True`. Cause: the throwaway fixture had training in period A only, and `resolve_row_muscles` short-circuits to zero queries when a period has no rows. Re-measured with both periods populated to get the true ceiling of 16. No production-code change; the throwaway counter was deleted and is not committed.

## Requirement Status

**CMP-01 is fully satisfied.** Every `must_haves.truths` entry in the plan is pinned by a named test:

| Truth | Test |
|-------|------|
| Unequal-length periods comparable via per-week counts and sums | `test_unequal_length_periods_with_identical_weekly_training` |
| 28-day vs 14-day identical weekly training → zero delta | same |
| Best e1RM compared as a level, never divided by weeks | `test_best_e1rm_is_a_level_and_is_never_divided` |
| Neither period widened to whole weeks | `test_periods_are_not_snapped_to_whole_weeks` |
| Zero baseline → null percent delta | `test_zero_baseline_yields_null_percent` |
| Each period reports its own coverage | `test_each_period_reports_independent_coverage` |
| Per-muscle rows only on request | `test_muscle_groups_are_opt_in` |

Both `must_haves.artifacts` exist and exceed their floors (`comparison.py` 507 lines vs `min_lines: 180`; the test module contains `compare_periods`). All three `key_links` patterns are present in `comparison.py`: `sessions_per_week(`, `best_set_per_day(`, `fold_window_by_template(`.

**Per the parallel-execution instructions, `.planning/REQUIREMENTS.md` was NOT edited** — plan 05-07 is running concurrently and may touch adjacent lines. The orchestrator should mark **CMP-01** complete after the merge.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 6's `fitness_compare_periods` MCP tool can call `compare_periods` directly with no adapter. It returns a `PeriodComparisonResult`, a `BaseModel`, so MCP SDK v2 generates the `outputSchema` and populates `structured_content` for free.
- Phase 6 must decide when to pass `include_muscle_groups=True`. The default response is compact; the expansion is 96+ numbers and 4 extra queries.
- Phase 6 should surface `period_a.coverage` and `period_b.coverage` separately rather than collapsing them — the whole reason they are per-period is that one side can be insufficient while the other is not.
- Callers must pass the **older** range as period A. Every delta reads "B minus A"; the opposite convention silently inverts every sign.

## Self-Check: PASSED

- `backend/app/analytics/comparison.py` — FOUND (507 lines)
- `backend/tests/test_analytics_comparison.py` — FOUND (472 lines)
- `.planning/phases/05-progression-records-recomposition-analytics/05-08-SUMMARY.md` — FOUND
- Commit `c511936` — FOUND (`feat(05-08): add CMP-01 per-week helper and rate/level constructors`)
- Commit `fe00cc3` — FOUND (`feat(05-08): add compare_periods, CMP-01's public two-period comparison`)
- Commit `85be99d` — FOUND (`test(05-08): cover CMP-01 unequal lengths, the level/rate split and the zero baseline`)
- `key_links` patterns in `comparison.py` — `fold_window_by_template(` line 245, `best_set_per_day(` line 253, `sessions_per_week(` lines 429-430
- Working tree clean apart from the temporary `.venv` symlink, which was removed before returning

---
*Phase: 05-progression-records-recomposition-analytics*
*Plan: 08*
*Completed: 2026-08-31*

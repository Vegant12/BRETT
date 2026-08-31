---
phase: 05-progression-records-recomposition-analytics
plan: 04
subsystem: analytics
tags: [python, sqlalchemy, pydantic, decimal, epley, e1rm, progression, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 05-01
    provides: "estimates.estimate_1rm (Epley) and NoEstimateReason, with the D-02 rep-range and D-03 modality gates"
  - phase: 05-02
    provides: "rollup.qualifying_set_rows (set-grain aggregate, tenant-scoped template outerjoin) and resolve_window"
  - phase: 05-03
    provides: "schemas.ProgressionPoint and schemas.ExerciseProgressionResult return contracts"
  - phase: 04-volume-frequency-analytics
    provides: "metadata.build_coverage / build_freshness / FRESHNESS_RESOURCES_MUSCLE, and volume.py's accumulator + pure-fold + public-composition shape"
provides:
  - "app/analytics/progression.py — the Phase 5 progression module (PROG-01 shipped, PROG-02/PROG-03 will extend it)"
  - "SessionBest — the mutable per-(exercise, local day) accumulator"
  - "best_set_per_day() — the PUBLIC, pure D-04 fold every later Phase 5 plan builds on"
  - "get_exercise_progression() — PROG-01's public function"
  - "backend/tests/test_analytics_progression.py — 5 fast + 8 container-backed tests"
affects: [05-05, 05-07, 05-08, 05-09, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Public pure fold: a shared artefact several requirements consume is public and session-free, so three consumers cannot grow three private copies that disagree"
    - "Comparison-key tuple selection: a leading 0/1 rank separates non-comparable populations before magnitude is ever compared"
    - "None-versus-zero applied at the Pydantic boundary using a companion count field (volume_sets beside volume_kg)"

key-files:
  created:
    - backend/app/analytics/progression.py
    - backend/tests/test_analytics_progression.py
  modified: []

key-decisions:
  - "SessionBest is MUTABLE (@dataclass(slots=True), not frozen) — it is folded into and never returned; schemas.py's frozen Pydantic models are the only thing a caller sees"
  - "best_set_per_day is PUBLIC and pure, returning dict[tuple[str, dt.date], SessionBest] unsorted — the caller owns output order"
  - "The D-04 comparison key is a 4-slot all-Decimal tuple: (estimated_rank, value, reps, -set_index)"
  - "estimate_1rm is called exactly once per row; both returned slots are consumed from that one call"
  - "The window is resolved with snap_to_weeks=False, following frequency.py rather than volume.py"

patterns-established:
  - "Pattern 1: a fold shared by four requirements is public and container-free-testable, never a private helper duplicated per consumer"
  - "Pattern 2: rank-then-value tuple comparison keeps estimated and unestimated sets in separate, non-interleaved populations"
  - "Pattern 3: an unaligned (Wed-to-Tue) fixture window is the only shape that can prove a range was not week-snapped"

requirements-completed: [PROG-01]

# Metrics
duration: 34min
completed: 2026-08-31
---

# Phase 5 Plan 04: Exercise Progression Series Summary

**PROG-01's per-local-day progression series, headlined by the highest-estimated-1RM set rather than the heaviest, with an explicit `no_estimate_reason` on every day the D-02/D-03 gates reject.**

## Performance

- **Duration:** ~34 min
- **Started:** 2026-08-31T10:26Z
- **Completed:** 2026-08-31T11:00Z
- **Tasks:** 3
- **Files modified:** 2 (both created)

## Accomplishments

- `best_set_per_day()` — the public, pure D-04 fold that 05-05 (PROG-04), 05-07 (PROG-02), 05-08 (CMP-01) and 05-09 (PROG-03) all consume. One implementation of "the lifter's best set that day" exists, so four modules cannot disagree about whether the lifter got stronger.
- `get_exercise_progression()` — PROG-01's public function: one unsnapped window, one bound-`IN` set-grain query, one fold, an ascending gap-omitting series, and both freshness resources.
- A counterexample-driven test suite: the load-bearing test uses `100 kg x 1` (e1RM 103.333) against `90 kg x 8` (e1RM 114.000), the only shape where the highest-estimate rule and the heaviest-weight rule disagree.
- Cross-tenant isolation proven on a shared template id in both directions — the set rows AND the outer-joined template whose `exercise_type` is the D-03 e1RM gate.

## Task Commits

1. **Task 1: SessionBest and the public pure fold `best_set_per_day()`** (tdd)
   - `9530334` (test) — RED: fast-suite tests for the selection rule, tie-break, day totals, `total_reps is None`, and same-day workout folding
   - `3c411bd` (feat) — GREEN: module docstring, `SessionBest`, `best_set_per_day`
2. **Task 2: `get_exercise_progression()` — PROG-01's public function** (tdd)
   - `ca0e113` (test) — RED: container-backed tests for the series shape, both null-reason paths, the unsynced template, tenant isolation, the empty window and the freshness resource set
   - `701d84f` (feat) — GREEN: `get_exercise_progression`
3. **Task 3: `backend/tests/test_analytics_progression.py`** — no separate commit. Task 3's entire deliverable is the test module, which the TDD gates on Tasks 1 and 2 required to be written *before* the code it tests. It is fully committed across `9530334` and `ca0e113`. Task 3 was executed as a verification pass against its own acceptance criteria; it produced no further file changes, so there was nothing left to commit.

_No REFACTOR commit: neither GREEN pass left anything to clean up (ruff and mypy were clean on the first run in both cases)._

## Files Created/Modified

- `backend/app/analytics/progression.py` (263 lines, created) — the Phase 5 progression module. Module docstring carries the four counter-intuitive rules (highest-e1RM-not-heaviest with the 80.000/81.667 worked example; the 376-of-2,239 null-estimate case; no day spine; the 1.167-to-1.400 Epley rep-noise band). Holds `SessionBest`, `best_set_per_day` and `get_exercise_progression`.
- `backend/tests/test_analytics_progression.py` (615 lines, created) — 5 fast-suite tests pinning D-04's selection and tie-break, 8 container-backed tests covering PROG-01's public contract.

## Interface Record (for 05-05, 05-07, 05-08, 05-09)

The plan's `<output>` block asks for these three facts explicitly.

**1. `best_set_per_day`'s exact public signature:**

```python
def best_set_per_day(
    rows: Sequence[QualifyingSetRow],
) -> dict[tuple[str, dt.date], SessionBest]:
```

Synchronous, pure, no `session` parameter, no keyword arguments. The key is `(template_external_id, local_day)` in that order. **The returned dict is deliberately UNSORTED** — insertion order follows the row order `qualifying_set_rows` supplies (template, then local_day, then workout_id, then set_index), but consumers must impose their own ordering rather than rely on it. `get_exercise_progression` sorts by `item[0][1]` (the local day).

**2. The comparison-key tuple shape** — built per row, held in a `dict[tuple[str, dt.date], tuple[Decimal, ...]]` beside the accumulator, never exposed on `SessionBest`:

```python
candidate: tuple[Decimal, ...] = (
    _ESTIMATED if value is not None else _UNESTIMATED,   # Decimal(1) / Decimal(0)
    value if value is not None
        else (row.weight_kg if row.weight_kg is not None else _NO_WEIGHT_RANK),  # Decimal(-1)
    Decimal(row.reps or 0),
    Decimal(-row.set_index),
)
```

Four slots, **all `Decimal`** so the tuple comparison never mixes `int` and `Decimal`. Replacement is on `candidate > incumbent` — **strictly** greater, so at a full tie the earlier (lower `set_index`) row keeps the slot. `_NO_WEIGHT_RANK = Decimal(-1)` sits strictly *below* zero because 48 live non-warm-up sets carry a genuine `Decimal("0.000")` weight; a sentinel at zero would tie with them.

The leading rank is the load-bearing slot: it stops a heavy 20-rep set from outranking an estimated 5-rep set. An estimated set always wins, and only then does the value decide.

**3. `SessionBest` ended up MUTABLE** — `@dataclass(slots=True)`, explicitly **not** `frozen=True`, matching `volume._WeekTotals` and `rollup.MuscleBucket`. It is folded into and never returned to an external caller; `schemas.ProgressionPoint` and `schemas.ExerciseProgressionResult` are the frozen types that cross the boundary. Consumers in later plans should treat a `SessionBest` they receive from `best_set_per_day` as their own to fold further, not as a shared value.

**4. No Phase 4 module was modified.** `git diff --stat` against the base commit shows exactly two files, both new. `volume.py`, `frequency.py`, `rollup.py`, `schemas.py`, `metadata.py`, `core/time.py`, `estimates.py`, `pyproject.toml` and every migration are byte-identical to `dcf89db`.

## Decisions Made

- **`SessionBest` mutable, not frozen.** Freezing it would force a rebuild-per-row fold, which is the shape that eventually tempts someone to recompute `estimate_1rm` on the incumbent to compare it.
- **The winning comparison key lives in a second dict, not on `SessionBest`.** It is ranking scaffolding, not a fact about the training day, and putting it on the dataclass would export it to every caller of a public function.
- **`test_window_is_not_snapped_to_whole_weeks` added (13th test, not in the plan's list of 12).** See Deviations — the plan's own fixture window could not have caught week snapping.
- **PROG-01 requirement verdict: SATISFIED, but *not* checked off in `REQUIREMENTS.md` from this worktree.** See "PROG-01 status" below.

## PROG-01 status

PROG-01's requirement text is:

> System calculates an exercise's progression time series (weight, reps, sets, and an estimated 1RM only where the exercise's modality and rep range make the estimate meaningful — otherwise returns null with a reason)

Assessed clause by clause against what shipped:

| Clause | Delivered by |
|---|---|
| an exercise's progression time series | `get_exercise_progression` → `ExerciseProgressionResult.points`, ascending by `local_day`, one point per trained day |
| weight | `ProgressionPoint.best_weight_kg` |
| reps | `ProgressionPoint.best_reps` (selected set) and `.total_reps` (whole day) |
| sets | `ProgressionPoint.sets` (and `.volume_sets` for the computed-over population) |
| estimated 1RM only where the modality … makes it meaningful | D-03 exact-match `weight_reps` gate in `estimates.estimate_1rm` |
| … and rep range make it meaningful | D-02 `MAX_TRUSTED_REPS = 12` gate |
| otherwise returns null with a reason | `estimated_1rm_kg is None` **with** `no_estimate_reason` populated (`MODALITY` / `REP_RANGE` / `MISSING_OPERAND`) — never a bare null; asserted by two container-backed tests |

**Verdict: PROG-01 is genuinely and fully complete at the analytics layer.** Its MCP exposure (`fitness_get_exercise_progression`) is a separate Phase 6 requirement, not part of PROG-01's text.

**I did NOT tick the PROG-01 checkbox in `.planning/REQUIREMENTS.md`, and did not run `requirements mark-complete`.** This worktree runs in parallel with 05-05 (PROG-04) and 05-06 (BODY-01), and the orchestrator's success criteria for this agent state that it "handles all post-wave shared-file writes". `REQUIREMENTS.md` line 44 (the checkbox) and line 151 (the traceability row) sit within a few lines of the PROG-04 rows a sibling agent may also touch, so a write from here is a merge-conflict hazard for no benefit.

**Action for the orchestrator:** tick line 44 (`- [ ] **PROG-01**` → `- [x]`) and set line 151's traceability row from `Pending` to complete, or equivalently run `requirements mark-complete PROG-01` post-merge.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added a 13th test proving the window is not week-snapped**

- **Found during:** Task 2 (`get_exercise_progression`)
- **Issue:** The plan pins `snap_to_weeks=False` only with a `grep`, and its prescribed fixture window is `_START = 2026-08-03` to `_END = 2026-08-30` — a **Monday to a Sunday**. Week-snapping that range is a no-op, so `assert result.window_start == _START` passes identically against a snapping implementation, and none of the 12 planned tests could have detected the wrong behaviour. A grep is not a behavioural guard: any later refactor that reintroduced snapping would ship green.
- **Fix:** Added `test_window_is_not_snapped_to_whole_weeks` over a deliberately unaligned Wednesday-to-Tuesday range (`2026-08-05` .. `2026-08-11`), with a workout on `2026-08-03` that only a snapped window (widened to `2026-08-03` .. `2026-08-16`) would pull in. This mirrors `test_analytics_frequency.py`'s non-multiple-of-7 window for exactly the same reason.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** Test passes; the assertion is non-vacuous because the excluded workout is seeded and asserted absent.
- **Committed in:** `ca0e113` (Task 2 RED commit)

**2. [Rule 2 - Missing Critical] Strengthened the tenant-isolation test to cover the template outerjoin**

- **Found during:** Task 2
- **Issue:** The plan's `test_second_users_sets_are_invisible` asserts only on `best_weight_kg`. That covers the *set* leak but not the *template* leak, which the plan's own threat register (T-05-22) calls out: Hevy's built-in template ids are global, so an outerjoin missing its own `ExerciseTemplate.user_id == user_id` predicate attaches another user's `title` **and `exercise_type`** to this user's answer. `exercise_type` is the D-03 e1RM gate, making that leak a correctness bug as well as a disclosure one.
- **Fix:** Both users' `PROG-shared` templates are seeded with distinct titles (`"Mine"` / `"Theirs"`), and the test asserts `result.title == "Mine"`.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** Test passes with the message naming the global-template-id cause.
- **Committed in:** `ca0e113`

**3. [Rule 3 - Blocking] Reworded the module docstring to avoid the token the acceptance criteria forbid**

- **Found during:** Task 3 (verification)
- **Issue:** The plan's `<action>` block prescribes a test-module docstring containing the literal string `pytest.approx`, while its own acceptance criterion requires `grep -c "pytest.approx" backend/tests/test_analytics_progression.py` to return `0`. The two are unsatisfiable together.
- **Fix:** Kept the rule and its rationale, reworded to "Never an approximate-comparison helper anywhere in this file. Reaching for a tolerance here is the warning sign that a binary floating-point value leaked into an exact-`Decimal` pipeline." Intent preserved; the grep now returns `0`.
- **Files modified:** `backend/tests/test_analytics_progression.py`
- **Verification:** `grep -c "pytest.approx" backend/tests/test_analytics_progression.py` → `0`
- **Committed in:** `9530334`

---

**Total deviations:** 3 auto-fixed (2 missing critical, 1 blocking)
**Impact on plan:** No scope creep. Deviations 1 and 2 close behavioural gaps the plan's own threat model and `snap_to_weeks` decision assumed were covered; deviation 3 resolves a self-contradiction inside the plan text. No production behaviour differs from what the plan specified.

## Issues Encountered

**Worktree base mismatch (the recurrence the prompt predicted).** The worktree branch was cut from `1e97f3b`, an ancestor of the expected base `dcf89db`. `git merge-base HEAD dcf89db` returned `HEAD`, confirming HEAD was behind. Corrected with `git reset --hard dcf89db` on a clean tree (`git status --short` was empty) before any file was touched. This is now the 4th consecutive worktree agent in this phase to hit it.

**Two acceptance criteria in the plan are unsatisfiable as literally written.** Both were resolved in favour of the `<action>` block, which is the more specific instruction, and verified against the criterion's *intent* instead:

1. `grep -q "_template_titles" backend/app/analytics/progression.py` is required to return nothing — but the plan's own prescribed code for `get_exercise_progression` contains the comment "`frequency._template_titles` is neither needed nor copied here", explaining *why* the helper was not duplicated. The comment was kept (it is the documentation the criterion is trying to guarantee the existence of a reason for). Verified by intent instead: `grep -c "_template_titles(" backend/app/analytics/progression.py` → `0`, i.e. **no call site**, only the explanatory comment.
2. `grep -rl "PROG-" backend/tests/ | wc -l` is required to return `1` — but `PROG-` also matches the requirement identifiers `PROG-01` / `PROG-04`, which already appear in `test_hevy_templates.py`, `test_analytics_rollup.py` and `test_analytics_estimates.py` on the base commit. The criterion's intent is fixture-id collision-freedom. Verified as `grep -rl '"PROG-[a-z]' backend/tests/ | wc -l` → `1`.

**`mypy backend/` reports 44 pre-existing errors, unchanged.** As flagged in the execution context, `mypy backend/` exits non-zero on 44 errors across 13 test modules that predate Phase 5. Verified this plan adds none: `mypy backend/app/` → `Success: no issues found in 49 source files`; `mypy backend/tests/test_analytics_progression.py` → 6 errors, **all six inside `backend/tests/conftest.py`**, byte-identical to what `mypy backend/tests/test_analytics_frequency.py` (untouched by this plan) reports. `mypy backend/` still reports exactly `44 errors in 13 files`. Not fixed — out of scope per the scope-boundary rule.

**`ruff format --check backend/` reports 13 files would be reformatted.** Pre-existing; the repo enforces `ruff check`, not `ruff format`. Confirmed neither plan file is among them (`ruff format --check` on each reports "already formatted"). Not fixed — out of scope.

## Verification Results

| Plan verification step | Result |
|---|---|
| 1. `pytest -q` (full suite) | **406 passed** in 11.05s |
| 2. `pytest -q -m "not integration"` (fast suite, under ~2s) | **227 passed** in 0.87s |
| 3. `ruff check backend/` | All checks passed |
| 3. `mypy backend/app/` | Success, no issues in 49 source files (see Issues for the `mypy backend/` note) |
| 4. `git diff --stat dcf89db..HEAD` | Exactly 2 files, both new, 878 insertions, 0 deletions |
| 5. No Alembic migration | Confirmed — `backend/migrations/` untouched |

Plan-specific module checks: `pytest backend/tests/test_analytics_isolation.py` → 8 passed (the new module clears the no-float, no-`/ 30`, no-write, no-raw-SQL and no-muscle-table guards, which `rglob` auto-applied to it). `pytest backend/tests/test_analytics_progression.py` → **13 passed**; `-m "not integration"` → 5 passed, 8 deselected, 0.04s, taking no container fixture.

## Known Stubs

None. Every field of `ProgressionPoint` and `ExerciseProgressionResult` is populated from real data or from a deliberate, tested `None`; no placeholder values, no hardcoded empties, no TODO markers.

## Threat Flags

None. Every file created is under `app/analytics/` or `backend/tests/`; no new network endpoint, auth path, file-access pattern or schema change was introduced. The one new trust boundary crossing — a caller-supplied `exercise_template_external_id` reaching SQL — is register entry T-05-23 and is mitigated exactly as specified: passed to `qualifying_set_rows` as a single-element bound `IN` list, never interpolated, never used to build an identifier.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Ready for 05-07 (PROG-02) and 05-09 (PROG-03):** both consume `best_set_per_day` directly. The tie-break and the estimated/unestimated rank separation are pinned by fast tests, so a later plan that changes them will see red rather than a silently different streak.
- **Ready for 05-05 (PROG-04):** note that PROG-04 scans *individual* qualifying sets for PRs and must **not** collapse to `best_set_per_day` first — D-04's per-day maximum would hide a rep PR set that was not the day's best by e1RM. `rollup.qualifying_set_rows` is the right substrate there, not this fold.
- **D-07a is not applied here, by design.** Days with a `None` estimate are present in the series with a reason. The plateau scanner (05-09) applies the SKIP by reading that `None`; it must not expect them to be absent.
- **Concern for 05-08 (CMP-01):** `ComparisonLevel` compares a *level* (a maximum) and must read `estimated_1rm_kg` off these points without dividing by weeks. `schemas.py` already separates `ComparisonRate` from `ComparisonLevel` structurally, so this is a reminder rather than a gap.

## Self-Check: PASSED

All claimed artifacts exist on disk and all claimed commits exist in this worktree's history.

| Claim | Check |
|---|---|
| `backend/app/analytics/progression.py` | FOUND |
| `backend/tests/test_analytics_progression.py` | FOUND |
| `.planning/phases/05-progression-records-recomposition-analytics/05-04-SUMMARY.md` | FOUND |
| `9530334` test(05-04) RED, Task 1 | FOUND |
| `3c411bd` feat(05-04) GREEN, Task 1 | FOUND |
| `ca0e113` test(05-04) RED, Task 2 | FOUND |
| `701d84f` feat(05-04) GREEN, Task 2 | FOUND |

TDD gate sequence verified in `git log`: `test(...)` precedes `feat(...)` for both tasks. No `refactor(...)` commit — neither GREEN pass left anything to clean up.

Shared orchestrator artifacts confirmed untouched: `.planning/STATE.md`, `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` are byte-identical to the base commit `dcf89db`.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

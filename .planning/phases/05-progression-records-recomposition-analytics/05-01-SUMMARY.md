---
phase: 05-progression-records-recomposition-analytics
plan: 01
subsystem: analytics
tags: [epley, e1rm, decimal, progression, static-analysis, pytest]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "`app/analytics/` package boundary, the pure-quantized-Decimal convention set by `frequency.sessions_per_week`, and `test_analytics_isolation.py`'s anchored-regex guard walk"
  - phase: 03-hevy-integration-normalization
    provides: "`ExerciseTemplate.exercise_type` — the modality signal D-03 gates on — and `workout_sets.weight_kg` Numeric(7, 3) / `reps` Integer|None"
provides:
  - "`estimate_1rm` — the single Epley e1RM implementation for all of Phase 5"
  - "`NoEstimateReason` StrEnum — machine-readable refusal reasons, never a bare null"
  - "`MAX_TRUSTED_REPS` (D-02) and `E1RM_EXERCISE_TYPE` (D-03) as importable constants"
  - "Static guarantee that no `app/analytics/` module can compute Epley in SQL"
  - "Static guarantee that no `app/analytics/` module can construct or annotate a `float`"
affects: [05-02, 05-03, 05-04, 05-05, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Refusal-with-reason return contract: `tuple[Decimal | None, NoEstimateReason | None]`, exactly one slot populated"
    - "Gate ORDER as part of the public contract, pinned by its own test"
    - "Static source guards keyed on the mechanism (the `/ 30` divisor) rather than the label (the word 'Epley')"

key-files:
  created:
    - backend/app/analytics/estimates.py
    - backend/tests/test_analytics_estimates.py
  modified:
    - backend/tests/test_analytics_isolation.py

key-decisions:
  - "Epley (D-01) lives in exactly one Python function; a static guard forbids the `/ 30` divisor anywhere else under `app/analytics/`, because in PostgreSQL `reps / 30` is integer division and the 'estimate' silently becomes the bare weight"
  - "Modality gate (D-03) is evaluated BEFORE the operand and rep-range gates, so a bodyweight set reports MODALITY rather than MISSING_OPERAND"
  - "`NoEstimateReason` lives in `estimates.py`, not `schemas.py` — it is an input-side business rule produced by the gates, and `schemas.py` importing it matches the direction that file already imports `CanonicalMuscleGroup`"
  - "The e1RM is quantized to 0.001 inside the function, mirroring `workout_sets.weight_kg` Numeric(7, 3), so downstream equality assertions are context-independent"

patterns-established:
  - "Negative-control proof: every new static guard is demonstrated to FAIL against a deliberately injected violation, with the source restored byte-identical afterwards"
  - "Test constants are spelled out rather than imported from the module under test — a test asserting against the very constant it imports proves nothing"

requirements-completed: [PROG-01]

# Metrics
duration: 10 min
completed: 2026-08-31
---

# Phase 5 Plan 01: Estimated 1RM Foundation Summary

**Epley e1RM as one pure keyword-only `Decimal` function with modality/rep-range/operand gates returning machine-readable refusal reasons, plus two static source guards that make the SQL integer-division catastrophe and any leaked `float` unrepresentable in `app/analytics/`.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-08-31T02:56:23Z
- **Completed:** 2026-08-31T03:04:50Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- `estimate_1rm` returns the four exact Decimals required by the plan — `103.333` / `123.333` / `126.667` / `140.000` for 100.000 kg at 1 / 7 / 8 / 12 reps — with no `pytest.approx` anywhere in the test suite.
- All three refusal paths return `(None, reason)` with the modality gate evaluated first; gate order is pinned by its own test and proven to fail when the order is swapped.
- The fast suite grew 206 → 216 tests and still runs in ~1.1 s. Every new test is markerless, so a violation fails on the commit that introduces it, with Docker stopped.
- Both new static guards were proven against injected violations, not merely observed to pass.

## Task Commits

1. **Task 1: Create `app/analytics/estimates.py`** — `7955a6f` (feat)
2. **Task 2: Create `backend/tests/test_analytics_estimates.py`** — `cec2440` (test)
3. **Task 3: Add no-float and no-Epley-in-SQL guards** — `c00da6b` (test)

## Files Created/Modified

- `backend/app/analytics/estimates.py` (new, 89 lines) — `estimate_1rm`, `NoEstimateReason`, `MAX_TRUSTED_REPS`, `E1RM_EXERCISE_TYPE`. No SQLAlchemy import, no `app.db` import, no async — importable and testable with Docker stopped.
- `backend/tests/test_analytics_estimates.py` (new, 201 lines) — 8 markerless fast-suite tests. Imports no fixture and does not import `pytest` at all.
- `backend/tests/test_analytics_isolation.py` (modified, +64/−1) — added `_FLOAT_USE` and `_DIVIDE_BY_THIRTY` regexes, `test_analytics_declares_no_float`, `test_epley_is_computed_only_in_estimates`; raised the walk floor from 2 to 6.

## Negative Control Results

The plan required the two new guards be demonstrated to fail against injected violations, and the observed failure messages recorded here. All four injections below were applied programmatically and reverted in a `finally` block; `git diff --stat` reported **no changes** to `backend/app/analytics/volume.py` and `backend/app/analytics/estimates.py` afterwards.

**1. `_probe: float = 1.0` appended to `backend/app/analytics/volume.py`** — `test_analytics_declares_no_float` FAILED (exit 1):

> `AssertionError: C-2 violated: backend/app/analytics/volume.py constructs or annotates a float. Binary floating point makes two arithmetically identical totals compare unequal, and it is how `regr_slope`'s double precision or `statistics.linear_regression` enters the analytics package. Use Decimal.`
> `assert not <re.Match object; span=(14288, 14295), match=': float'>`

**2. `x = reps / 30` appended to `backend/app/analytics/volume.py`** — `test_epley_is_computed_only_in_estimates` FAILED (exit 1):

> `AssertionError: the Epley divisor appears outside estimates.py: [PosixPath('backend/app/analytics/volume.py')]. In PostgreSQL `weight * (1 + reps/30)` is integer division and returns the BARE WEIGHT -- verified, `SELECT 10 * (1 + 8/30)` returns 10. Call `estimates.estimate_1rm` instead.`
> `assert not [PosixPath('backend/app/analytics/volume.py')]`

Two further negative controls were run beyond the plan's requirement, to prove the Task 2 tests are load-bearing rather than merely green (the RED half of the TDD gate, which the plan's task ordering otherwise skipped):

**3. Epley replaced with `Decimal(reps // 30)` (the SQL integer-division defect) in `estimates.py`** — `test_epley_exact_values` FAILED:

> `AssertionError: assert (Decimal('100.000'), None) == (Decimal('103.333'), None)`
> `At index 0 diff: Decimal('100.000') != Decimal('103.333')`

This is the exact bare-weight failure the module docstring warns about, caught on the first of four rep counts.

**4. Modality and operand gates swapped in `estimates.py`** — `test_gate_order_puts_modality_first` FAILED:

> `AssertionError: At index 1 diff: <NoEstimateReason.MISSING_OPERAND: 'missing_weight_or_reps'> != <NoEstimateReason.MODALITY: 'modality_not_weight_reps'>`

Every other test still passed under injection 4, confirming the plan's claim that the gate-order test is the only thing standing between a correct implementation and one that narrates a design decision as a data problem.

## Plan Verification Results

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest -q -m "not integration"` | **216 passed, 163 deselected in 1.10s** (baseline was 206/163/0.94s; +10 = 8 estimates + 2 guards). Under the ~2 s bar. |
| 2 | `ruff check backend/` | **exit 0** — All checks passed |
| 3 | `mypy backend/` | **exit 1 — 44 pre-existing errors, 0 from this plan.** See Deferred Issues below. `mypy backend/app/` exits 0 (48 files); each of the three files this plan touched passes `mypy` individually. |
| 4 | `git diff --stat` shows exactly three files | **Confirmed.** `estimates.py` +89, `test_analytics_estimates.py` +201, `test_analytics_isolation.py` +64/−1. `pyproject.toml` diff against base is empty — no dependency was added. |
| 5 | No Alembic migration created | **Confirmed.** 4 versions in `backend/migrations/versions/`, unchanged. (Note: the plan named `backend/alembic/versions/`; the real path in this repo is `backend/migrations/versions/`.) |

## Decisions Made

- **Kept the plan's module content verbatim.** The docstrings and comments in `estimates.py` are load-bearing (the plan states they are the second half of the Pitfall-1 defence), so they shipped unedited even where they collided with a mechanical acceptance check — see Deviation 2.
- **Proved pre-existing-ness rather than assuming it.** Before classifying the 44 `mypy backend/` errors as out of scope, the base commit tree was exported with `git archive` to a scratch directory and re-checked: it produces the identical 44 errors across the identical 13 files, with 86 source files checked versus 88 now. The two added files contributed zero errors.
- **Logged the out-of-scope `mypy` finding in this SUMMARY rather than in a shared `deferred-items.md`.** This plan ran as one of several parallel worktree agents; a new shared file created by multiple agents produces an add/add merge conflict. The finding is recorded in full under Deferred Issues, where the verifier reads it, at no merge cost.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `mypy` rejected the plan's literal quantization assertion**

- **Found during:** Task 2 (test file creation)
- **Issue:** The plan specifies `assert -value.as_tuple().exponent == 3`. Typeshed types `DecimalTuple.exponent` as `Literal['n', 'N', 'F'] | int` (the string variants encode NaN, sNaN and Infinity), so unary minus over that union is an error: `backend/tests/test_analytics_estimates.py:167: error: Unsupported operand type for unary - ("Literal['n', 'N', 'F'] | int")  [operator]`. The plan's own acceptance criterion requires `mypy` on this file to exit 0, so the plan as written was internally inconsistent.
- **Fix:** Bound the exponent to a local and narrowed it with `assert isinstance(exponent, int)` before `assert -exponent == 3`, preserving the plan's assertion form exactly. The narrowing is a real assertion rather than typechecker appeasement, and the comment says so: an estimated 1RM of NaN would satisfy a bare `value is not None` check and then poison every downstream `>` and `max` silently — the same class of quiet-wrong-number failure this whole plan exists to prevent.
- **Files modified:** `backend/tests/test_analytics_estimates.py`
- **Verification:** `mypy backend/tests/test_analytics_estimates.py` exits 0; the 8 tests still pass.
- **Committed in:** `cec2440` (Task 2 commit)

**2. [Rule 1 - Bug] Task 2 acceptance criterion `grep -c "pytest.approx" … returns 0` is unsatisfiable as written**

- **Found during:** Task 2 (acceptance-criteria gate)
- **Issue:** The criterion demands zero occurrences of the substring `pytest.approx`, but the same task's `<action>` block mandates a module docstring containing the sentence *"Never `pytest.approx` here."* The two requirements are in direct contradiction. This is precisely the substring-versus-anchored-regex trap that `test_analytics_isolation.py`'s own module docstring documents ("a substring check would fail on the sentence documenting the boundary"), reappearing in the plan's acceptance criteria rather than in the code.
- **Fix:** Kept the plan-mandated docstring verbatim and removed the one *additional*, non-mandated mention I had written into `test_epley_exact_values`'s docstring, reducing the count from 2 to 1 — the single mandated line. The criterion's actual intent was then verified with the anchored check the repo convention calls for: `grep -Ec "pytest\.approx\s*\(" ` returns **0**, and `grep -Ec "^(import pytest|from pytest)"` returns **0**, so `pytest.approx` is not merely unused, it is uncallable from this module.
- **Files modified:** `backend/tests/test_analytics_estimates.py`
- **Verification:** anchored call count 0; `pytest` import count 0; 8 tests pass.
- **Committed in:** `cec2440` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug in the plan's own criteria)
**Impact on plan:** No scope creep and no behavioural change. Deviation 1 strengthened a test; deviation 2 resolved a contradiction between two halves of the same task and substituted a strictly stronger check. Every `must_haves` truth and artifact in the plan frontmatter is satisfied.

## Issues Encountered

**Worktree base was wrong on arrival.** `git merge-base HEAD 218cf81` returned `1e97f3b`, which was HEAD itself — meaning the worktree branch had been created from an ancestor of the intended base rather than from the feature-branch HEAD (the known `EnterWorktree` issue the prompt's `<worktree_branch_check>` anticipates). Hard-reset to `218cf81` and verified before any work began.

**No `.venv` in the worktree.** `.venv/` is gitignored and lives only in the main checkout, so every verification command in the plan (`.venv/bin/python`, `.venv/bin/ruff`, `.venv/bin/mypy`) would have failed. Resolved by symlinking the main repo's `.venv` into the worktree; the venv contains no editable install of the project, so `app` still resolves through pytest's `pythonpath = ["backend"]` to *this* worktree's source, which was confirmed by the baseline run reproducing the plan's stated 206/163 exactly. The symlink is removed before returning.

## Deferred Issues

**`mypy backend/` has 44 pre-existing errors across 13 test modules — NOT introduced by this plan, and deliberately not fixed.**

Verified pre-existing by exporting the base commit (`218cf81`) with `git archive` and re-running `mypy` against it: identical 44 errors, identical 13 files. The clusters are:

| Cluster | Files | Count |
|---------|-------|-------|
| `Unexpected keyword argument "_env_file" for "Settings"` | `test_config.py`, `test_mcp_auth.py`, `test_secret_redaction.py`, `test_hevy_*.py` | 18 |
| SQLAlchemy `TypeEngine[Any]` attribute access in schema assertions | `test_db_models.py` | 9 |
| Starlette/ASGI callable `.state` attribute | `test_health.py`, `test_mcp_tools.py` | 9 |
| `pytest_asyncio.fixture` type-var and async-generator return types | `conftest.py` | 6 |
| Missing `types-PyYAML` stubs | `test_cloud_run_deploy.py` | 1 |

Out of scope under the executor scope boundary (pre-existing failures in files unrelated to this task). Worth a dedicated cleanup plan, since the plan-level verification bar `mypy backend/ exits 0` cannot be met by any Phase 5 plan until it is addressed. `mypy backend/app/` **does** exit 0 and is the meaningful gate for analytics work today.

## Known Stubs

None. `estimate_1rm` is complete: no placeholder values, no hardcoded empty returns, no TODO markers. Every branch returns a real result.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The surface is one pure function whose only inputs are three already-nullable column values; the plan's threat register (T-05-01 … T-05-06) covers it, and the two `mitigate` dispositions assigned to `estimates.py` are implemented — keyword-only parameters and exact-equality modality comparison (T-05-01), and a fixed 3-member `StrEnum` for reasons so no weight, rep count, user id or exercise title can reach a log line through this module (T-05-02). T-05-03's static controls are Task 3's two guards, both proven by injection above.

## TDD Gate Compliance

The plan marks Tasks 1 and 2 `tdd="true"` but orders implementation (Task 1) before tests (Task 2), and Task 2's `<read_first>` explicitly instructs reading the already-created `estimates.py` to "assert against what it actually is". The plan's ordering was followed, so the commit sequence is `feat` → `test` → `test` rather than the canonical `test` → `feat`.

To recover the assurance that a strict RED gate would have provided, the Task 2 tests were retro-validated against two injected defects after the fact (negative controls 3 and 4 above): the SQL integer-division bug and a swapped gate order. Both produced a failing test with a diagnostic message naming the wrong number. The tests are therefore demonstrably load-bearing rather than merely co-written with the implementation they check.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `estimate_1rm` is the locked, importable input for 05-02 (progression series, D-04's best-set-of-the-day), 05-03 (PROG-02 trend slope), 05-04 (PROG-03 plateau streak, including D-07a's skip-null-e1RM rule) and PROG-04's estimated-1RM PR. Import it; do not re-derive it — `test_epley_is_computed_only_in_estimates` will fail the fast suite on any second copy under `app/analytics/`.
- `NoEstimateReason` is ready for `schemas.py` to import when 05-02 defines the progression response type. The import direction (`schemas` → `estimates`) is the one the module docstring specifies.
- Downstream plans should expect the refusal path to be common, not exceptional: per D-03's comment, 4,802 of 7,719 live hard sets pass both gates, so roughly a third of sets carry a reason instead of a number.
- The `_FLOAT_USE` guard now applies to every future `app/analytics/` module. PROG-02's trend slope is the first place this bites — `regr_slope` returns `double precision` and `statistics.linear_regression` returns `float`, and both are now statically blocked. 05-03 must compute its slope in `Decimal`.
- **Carry forward:** `mypy backend/` cannot exit 0 until the 44 pre-existing test-module errors are cleaned up. Later Phase 5 plans quoting the same verification line will hit the same wall.

## Requirements Status

`REQUIREMENTS.md` was **not** modified, and `PROG-01` was **not** checked off. Two reasons:

1. **It would be a false claim.** PROG-01's acceptance criterion is a progression *time series* (weight, reps, sets, and an estimated 1RM where meaningful). This plan delivers only the estimate-and-reason primitive that series is built from. `PROG-01` is claimed by four plans in this phase — 05-01, 05-02, 05-03 and 05-04 — and is complete only when all four land.
2. **It would conflict.** Those other three plans run as sibling worktree agents in this wave; four agents editing the same checkbox and traceability row in `REQUIREMENTS.md` is a guaranteed merge conflict.

The orchestrator should reconcile `PROG-01` after the wave, once 05-02 through 05-04 have summaries. `requirements-completed: [PROG-01]` in this file's frontmatter records the plan's *claim*, verbatim from `05-01-PLAN.md`, as the template requires — it is not an assertion that the requirement is satisfied.

## Self-Check: PASSED

**Files claimed as created/modified — all present on disk:**

- FOUND: `backend/app/analytics/estimates.py` (89 lines, plan floor 60)
- FOUND: `backend/tests/test_analytics_estimates.py` (201 lines, plan floor 60)
- FOUND: `backend/tests/test_analytics_isolation.py`
- FOUND: `.planning/phases/05-progression-records-recomposition-analytics/05-01-SUMMARY.md`

**Commits claimed — all present in `git log`:**

- FOUND: `7955a6f` feat(05-01): add Epley e1RM with modality and rep-range gates
- FOUND: `cec2440` test(05-01): cover e1RM exact values and both gate boundaries
- FOUND: `c00da6b` test(05-01): guard against leaked floats and Epley-in-SQL statically

**Plan `must_haves` re-verified:**

| Item | Result |
|------|--------|
| 100.000 kg x 8 reps yields exactly 126.667 | PASS |
| >12 reps yields no estimate + machine-readable reason | PASS (`REP_RANGE`) |
| Non-`weight_reps` yields no estimate + machine-readable reason | PASS (`MODALITY`) |
| No `app/analytics/` module can compute Epley in SQL without failing the fast suite | PASS (proven by injection) |
| No `app/analytics/` module can annotate or construct a float without failing the fast suite | PASS (proven by injection) |
| `estimates.py` exports `estimate_1rm`, `NoEstimateReason`, `MAX_TRUSTED_REPS`, `E1RM_EXERCISE_TYPE` | PASS |
| `test_analytics_isolation.py` contains `def test_analytics_declares_no_float` | PASS |
| key_link `from app.analytics.estimates import` | PASS (1 match) |
| key_link `_analytics_modules()` | PASS (9 matches) |

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

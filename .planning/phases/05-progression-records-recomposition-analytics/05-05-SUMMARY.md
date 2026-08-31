---
phase: 05-progression-records-recomposition-analytics
plan: 05
subsystem: analytics
tags: [postgres, sqlalchemy, pydantic, decimal, personal-records, epley, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: "metadata.build_coverage / build_freshness / FRESHNESS_RESOURCES_MUSCLE, and the read-only app/analytics boundary asserted by test_analytics_isolation.py"
  - phase: 05-progression-records-recomposition-analytics
    provides: "estimates.estimate_1rm (05-01), rollup.qualifying_set_rows + resolve_window at SET grain (05-02), the PROG-04 return contracts in schemas.py (05-03)"
provides:
  - "backend/app/analytics/records.py — get_personal_records, PROG-04 personal-record detection at set grain"
  - "All five PROG-04 record types with the date each was FIRST reached: max weight, max reps, estimated-1RM, session volume, and the per-weight rep list"
  - "_key/_better — D-09's earliest-date tie-break as a single (value, -ordinal) sort key reused at all five record sites"
  - "backend/tests/test_analytics_records.py — nine container-backed tests, mutation-verified against four distinct defects"
affects: [06-mcp-tools, fitness_get_personal_records]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tie-break folded INTO the compared value: (value, -date.toordinal()) so 'highest value, earliest date' is one `>` and cannot be forgotten at one of five call sites"
    - "Absent-not-zero: a record type with no eligible set is omitted from the list rather than emitted with a zero value"
    - "Gate scoping: a D-02/D-03 estimate gate bounds only the estimate; raw observations (max weight, max reps) stay un-gated"

key-files:
  created:
    - backend/app/analytics/records.py
    - backend/tests/test_analytics_records.py
  modified: []

key-decisions:
  - "D-09's earliest-date tie-break is implemented ONCE, as _key() building (value, -achieved_on.toordinal()) and _better() comparing it — five record types, one rule, no per-site date comparison to get backwards"
  - "records.py contains no set_type comparison at all: the warm-up exclusion stays a single SQL definition in rollup._hard_set_predicates(), so D-08's dropset/failure eligibility cannot drift"
  - "D-02's trusted rep range gates only the ESTIMATED_1RM record; MAX_REPS and MAX_WEIGHT are raw observations and deliberately un-capped"
  - "SESSION_VOLUME is accumulated per workout_id and quantized to Decimal('0.001'), mirroring workout_sets.weight_kg Numeric(7,3)"
  - "The window is resolved with snap_to_weeks=False — a record is a point in time and has no bucket to be comparable with"

patterns-established:
  - "Mutation verification: each load-bearing rule was proven non-vacuous by breaking it in the implementation and confirming its own named test fails"
  - "Test-side _by_type() index so ABSENCE of a record type is assertable with `not in` rather than a StopIteration"

requirements-completed: [PROG-04]

# Metrics
duration: 18min
completed: 2026-08-31
---

# Phase 5 Plan 5: Personal Records Summary

**PROG-04 personal-record detection at set grain — all five record types with first-reached dates, D-09's earliest-date tie-break folded into a single sort key, and D-08's dropset/failure eligibility enforced structurally by containing no set-type comparison at all.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-08-31T03:25:00Z (base commit `dcf89db`)
- **Completed:** 2026-08-31T03:43:00Z
- **Tasks:** 2 of 2
- **Files created:** 2 (745 insertions, 0 modifications, 0 deletions)

## Accomplishments

- `get_personal_records` scans qualifying sets in ONE pass at SET grain, never the collapsed
  per-day series — the constraint D-04's last sentence imposes, because collapsing first hides a
  rep PR set performed on a day whose headline set was a heavy triple.
- All five PROG-04 record types produced with exact `Decimal` values and the date each was first
  reached: `MAX_WEIGHT`, `MAX_REPS`, `ESTIMATED_1RM`, `SESSION_VOLUME`, plus the `reps_at_weight`
  list (one row per distinct weight, descending).
- D-09 implemented as **one** comparison rather than five: `_key(value, day)` returns
  `(value, -day.toordinal())` and `_better()` is the only thing that compares it, so "highest
  value, earliest date" cannot be written the wrong way round at one site out of five.
- D-08 enforced structurally: the module contains no `set_type` comparison outside its docstring,
  so the warm-up exclusion has exactly one definition (`rollup._hard_set_predicates()`) and the
  823 live dropset sets plus the declared-but-never-sent `failure` type stay PR-eligible.
- Nine container-backed tests, each of whose load-bearing rules was **mutation-verified** (see
  Issues Encountered) rather than merely observed passing.

## Task Commits

1. **Task 1: Create records.py with the pure per-set PR scan** — `2ef0909` (feat)
2. **Task 2: Create backend/tests/test_analytics_records.py** — `7d8a01d` (test)

**Plan metadata:** committed with this SUMMARY (docs).

_Task 1 carried `tdd="true"` in the plan, but the plan's own task decomposition orders the module
before the tests (Task 2's `read_first` names "Task 1's output — assert against what it returns").
The plan-level `type:` is `execute`, not `tdd`, so no plan-level RED/GREEN gate applies. The
non-vacuity that a RED phase normally buys was obtained instead by mutation-testing each rule
after the fact — documented below._

## Files Created/Modified

- `backend/app/analytics/records.py` (created, 282 lines) — PROG-04 personal-record detection.
  Exports `get_personal_records`; private `_key`, `_better`, `_SessionVolume`, `_VOLUME_QUANTUM`.
- `backend/tests/test_analytics_records.py` (created, 463 lines) — nine `@pytest.mark.integration`
  tests under the `PR-*` fixture prefix (verified unique across `backend/tests/`).

### Requested by the plan's `<output>` block

**Exact signature:**

```python
async def get_personal_records(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exercise_template_external_id: str,
    start_day: dt.date,
    end_day: dt.date,
) -> PersonalRecordsResult: ...
```

Session positional, everything else keyword-only, `user_id` with no default (ASVS V4). Verified
by the plan's `inspect.signature` check, which printed `OK`.

**Observed `SESSION_VOLUME` quantum:** `Decimal("0.001")` (`_VOLUME_QUANTUM`), mirroring
`workout_sets.weight_kg` `Numeric(7, 3)`. The 3-set golden fixture (100.000x3 + 80.000x12 +
40.000x22) returns exactly `Decimal("2140.000")`, asserted without any tolerance.

**Confirmation — no set-type comparison and no rep cap in `records.py`:**

| Check | Result |
|---|---|
| `grep -n "set_type"` | 1 hit, line 11, inside the module docstring (the sentence forbidding it) |
| `grep -c "WARMUP_SET_TYPE\|== \"normal\"\|== 'normal'"` | `0` |
| `grep -c "MAX_TRUSTED_REPS"` | `0` |
| `grep -c "def _better"` | `1` |
| `grep -c "toordinal()"` | present (in `_key`, plus the docstrings describing it) |
| `grep -c "snap_to_weeks=False"` | present |
| `grep -c "FRESHNESS_RESOURCES_MUSCLE"` | present |
| `grep -c "LIMIT\|[:12]\|[:10]"` | `0` — no truncation of `reps_at_weight` |

## Decisions Made

- **The rep cap gates the estimate, not the observation.** `estimate_1rm` is called once per row
  and its `None` return is treated as "this set cannot produce a trustworthy *estimate*", never as
  "this set is ineligible". `MAX_REPS` and `MAX_WEIGHT` see every row.
- **`per_weight` is keyed on the exact `Decimal` the driver returned**, never normalised or
  quantized. `60.000` and `60.0` already compare equal as `Decimal`; quantizing the key would
  merge `60.000` and `60.005`, which are different plates.
- **`SESSION_VOLUME` is absent, not zero, when no set carries both operands.** A `reps_only`
  exercise therefore reports only `MAX_REPS` — three of the four scalar types are legitimately
  absent, and a zero would read as a record.
- **`title` is taken from the first returned row** (`next((row.title for row in rows), None)`).
  Every row belongs to the one requested template, and `None` correctly survives for a template
  that is not synced locally, because `qualifying_set_rows` outer-joins rather than inner-joins.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Comment opening with `# type:` broke mypy**

- **Found during:** Task 1 (`records.py`)
- **Issue:** The plan-styled comment `# ONE pass ... consults the set's` / `# type: the warm-up
  exclusion already happened, in SQL, once.` wrapped such that the second line began with
  `# type:`. mypy 2.3.1 parses that as a PEP 484 type comment and failed the file with a bare
  `backend/app/analytics/records.py:143: error: Invalid syntax [syntax]` pointing at a comment
  line. Ruff and `python -m py_compile` both passed, so the file was valid Python — only mypy
  rejected it.
- **Fix:** Reworded the comment so no line opens with `# type` + colon, and left a short
  parenthetical in place recording the trap so the next editor does not reintroduce it.
- **Files modified:** `backend/app/analytics/records.py`
- **Verification:** `.venv/bin/mypy backend/app/analytics/records.py` → `Success: no issues found`
- **Committed in:** `2ef0909` (Task 1 commit)

**2. [Rule 3 - Blocking] Two plan-mandated docstring phrases contradicted the plan's own greps**

- **Found during:** Tasks 1 and 2
- **Issue:** The plan's `<action>` blocks prescribe the literal docstring sentences
  "Do not add a LIMIT" (`records.py`) and "Never `pytest.approx`." (`test_analytics_records.py`),
  while its `<acceptance_criteria>` require `grep "LIMIT"` and `grep -c "pytest.approx"` to find
  nothing in those same files. The two cannot both hold.
- **Fix:** Kept the *intent* (which is the real requirement — no truncation, no tolerance-based
  comparison) and reworded to satisfy the greps: "Do not add a row cap -- a silent truncation is a
  wrong answer" (matching `rollup.py`'s existing "There is deliberately no row cap" phrasing), and
  "No tolerance-based comparison appears below -- not `approx`, not rounding."
- **Files modified:** `backend/app/analytics/records.py`, `backend/tests/test_analytics_records.py`
- **Verification:** `grep -c "LIMIT\|[:12]\|[:10]"` → `0`; `grep -c "pytest.approx"` → `0`; both
  prohibitions still stated in prose and still true of the code.
- **Committed in:** `2ef0909`, `7d8a01d`

**3. [Rule 1 - Cosmetic type shape] `per_weight` value type**

- **Found during:** Task 1
- **Issue:** The plan specifies `per_weight: dict[Decimal, tuple[Decimal, int, dt.date]]`, a flat
  3-tuple. Slicing `existing[:2]` to hand the comparison key to `_better` produces
  `tuple[Decimal | int | date, ...]` under mypy, which does not match `_RecordKey`.
- **Fix:** Used the structurally equivalent `dict[Decimal, tuple[_RecordKey, dt.date]]` — the same
  three values, nested so the comparison key is one named type. Behaviour is identical.
- **Files modified:** `backend/app/analytics/records.py`
- **Verification:** mypy clean; `test_reps_at_weight_is_one_row_per_distinct_weight` and
  `test_tie_records_the_earliest_date` both pass.
- **Committed in:** `2ef0909` (Task 1 commit)

**4. [Rule 3 - Ambiguity resolved] Task 2's test 3 fixture was self-contradictory as written**

- **Found during:** Task 2
- **Issue:** The plan asks `test_dropset_sets_a_record_and_warmup_does_not` to assert
  `MAX_WEIGHT == Decimal("110.000")` **and** to add a 115 kg `failure` set that "wins". Both
  cannot hold in one fixture state.
- **Fix:** Structured the test in two phases, the pattern
  `test_frequency_carries_the_d06_coverage_block` already uses: query with warm-up + dropset only
  (assert 110.000, and that 200.000 set nothing), then add the `failure` workout and re-query
  (assert 115.000). Both plan sentences are now true, in sequence.
- **Files modified:** `backend/tests/test_analytics_records.py`
- **Verification:** Test passes; the mutation `if row.set_type != "normal": continue` fails it.
- **Committed in:** `7d8a01d` (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (3 blocking/ambiguity, 1 cosmetic type shape)
**Impact on plan:** No scope change. Every plan behaviour, threat mitigation and acceptance
criterion is satisfied; the changes are wording and type shape, plus one test restructured so its
two stated assertions are both reachable.

## Issues Encountered

**All nine tests passed on their first run**, which is a weak signal in a plan whose whole point is
that the wrong answers look plausible. Rather than accept it, each load-bearing rule was
mutation-tested: the implementation was broken, the suite re-run, the failure confirmed to be the
*named* test, and the mutation reverted via `git checkout --`.

| Mutation applied to `records.py` | Test that failed | Wrong answer it produced |
|---|---|---|
| `_key` returns `+toordinal()` (latest-date tie-break) | `test_tie_records_the_earliest_date` | `achieved_on` 2026-08-17 instead of 2026-08-03 |
| `if row.reps is not None and row.reps <= 12` (rep cap on the observation) | `test_rep_pr_is_not_capped_by_the_e1rm_rep_gate` (+2 others) | rep PR reported as 12, hiding the 22-rep set |
| `if row.set_type != "normal": continue` (allow-list) | `test_dropset_sets_a_record_and_warmup_does_not` | zero records at all; 823 live dropset sets dropped |
| session volume accumulated under one key (window-wide sum) | `test_session_volume_is_per_workout_not_per_window` | 1600.000 instead of 1000.000 |

`git status` and the final full-suite run confirm the working tree matches the committed
implementation — no mutation survived.

**Pre-existing mypy state (not fixed, by scope boundary):** `mypy backend/` reports 44 errors
across 13 **test** modules, all pre-existing on the base commit `dcf89db` and unrelated to
Phase 5. `mypy backend/app/` exits 0 across 49 source files, and `mypy` reports **zero** errors in
either file this plan created (`grep -c "records\.py"` over the mypy output → `0`). The plan's
verification item 3 asks for `mypy backend/` to exit 0; that is not achievable without touching
13 unrelated test modules, which is out of this plan's scope.

## Verification Results

| Plan verification item | Result |
|---|---|
| 1. `pytest -q` — full suite green | **402 passed** in 11.29s |
| 2. `pytest -q -m "not integration"` — fast suite green, count unchanged | **222 passed, 180 deselected**; this plan adds 0 fast-suite tests, so 222 is unchanged |
| 3. `ruff check backend/` | **All checks passed** |
| 3. `mypy backend/` | 44 pre-existing errors in 13 test modules; `mypy backend/app/` clean; 0 errors in this plan's files (see above) |
| 4. `git diff --stat` shows exactly two files | `records.py` (+282), `test_analytics_records.py` (+463). `rollup.py`, `schemas.py`, `metadata.py`, `progression.py`, `volume.py`, `frequency.py`, `pyproject.toml` all untouched |
| 5. No Alembic migration created | Confirmed — the diff contains no `backend/migrations/` path |

### Success criteria

- [x] All five PROG-04 record types produced with exact `Decimal` values and first-reached dates
- [x] Rep PR reports 22 reps, proving D-02's cap was not applied to a raw observation
- [x] A dropset (110 kg) and a failure set (115 kg) each set a record; the 200 kg warm-up sets none
- [x] A tied value reports the earlier date, at both the record and the `reps_at_weight` grain
- [x] A record type with no eligible set is absent, not zero (`reps_only` exercise)
- [x] Full suite, ruff green; no new dependency, no migration

### Threat model

All eight `mitigate` dispositions (T-05-30..T-05-36) hold as planned; no new mitigation was needed
under Rule 2. T-05-30 is proven by `test_second_users_sets_are_invisible` (a 300 kg second-user
set, plus an anti-vacuous-pass guard). T-05-32's "no second copy of the warm-up rule" is proven by
grep. T-05-36 is auto-covered: `test_analytics_isolation.py` `rglob`s the package and its eight
boundary tests pass with `records.py` included.

**No new threat surface.** `records.py` opens no endpoint, adds no auth path, reads no file and
changes no schema; it issues one `qualifying_set_rows` statement plus the two existing metadata
reads, all `select`-derived.

## Requirements — PROG-04

**PROG-04 is now fully satisfied by this plan, but I did NOT check it off in `REQUIREMENTS.md`.**

Against the requirement text — *"System detects personal records (max weight, max reps at a
weight, estimated-1RM PR, volume PR, rep PR) with the date of each, excluding warm-up sets"* —
every clause is delivered and tested:

| Clause | Delivered as | Test |
|---|---|---|
| max weight | `PersonalRecordType.MAX_WEIGHT` | `test_all_five_record_types_are_detected` |
| max reps at a weight | `PersonalRecordsResult.reps_at_weight` | `test_reps_at_weight_is_one_row_per_distinct_weight` |
| estimated-1RM PR | `PersonalRecordType.ESTIMATED_1RM` | `test_all_five_record_types_are_detected` |
| volume PR | `PersonalRecordType.SESSION_VOLUME` | `test_session_volume_is_per_workout_not_per_window` |
| rep PR | `PersonalRecordType.MAX_REPS` | `test_rep_pr_is_not_capped_by_the_e1rm_rep_gate` |
| the date of each | `PersonalRecord.achieved_on` / `RepsAtWeightRecord.achieved_on`, D-09 earliest | `test_tie_records_the_earliest_date` |
| excluding warm-up sets | `rollup._hard_set_predicates()`, in SQL, once | `test_dropset_sets_a_record_and_warmup_does_not` |

**Why the checkbox was left alone:** this plan ran as a parallel worktree agent alongside 05-04
(`requirements: [PROG-01]`, line 44 and table row 151) and 05-06 (`requirements: [BODY-01]`, line
52 and row 156). PROG-04 is line 47 and row 154 — within git's default 3-line merge context of
05-04's lines in both the checklist and the traceability table, so three concurrent branches each
editing `REQUIREMENTS.md` would very likely collide at merge. The executor's own success criteria
also reserve shared-artifact writes for the orchestrator.

**Action for the orchestrator:** mark `PROG-04` complete after the wave merges —
`node $HOME/.claude/get-shit-done/bin/gsd-tools.cjs requirements mark-complete PROG-04` — which
flips line 47's checkbox and row 154 to `Complete`. `STATE.md` and `ROADMAP.md` were likewise not
touched, per the orchestrator's instruction.

## Known Stubs

None. Every value returned by `get_personal_records` is computed from database rows; there are no
hardcoded empty collections, placeholder strings or unwired data paths. The empty results that do
occur (`records == []`, `reps_at_weight == []`) are the correct answer for an exercise with no
qualifying sets, and the absent-not-zero rule is asserted by
`test_reps_only_exercise_omits_weight_based_records`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 6's `fitness_get_personal_records` tool can call `get_personal_records` directly. It
  returns a `PersonalRecordsResult`, from which MCP SDK v2 derives the tool's `outputSchema` and
  `structured_content` with no extra mapping layer.
- The `_key`/`_better` tie-break pair is reusable by any later "when did this first happen"
  question; it is private today, and should be promoted rather than copied if a second module
  needs it.
- No blockers. One caveat for whoever next runs `mypy backend/`: the 44 pre-existing test-module
  errors predate Phase 5 and will keep that command non-zero until a dedicated cleanup.

## Self-Check: PASSED

Every artifact and commit claimed above was verified to exist on disk and in this worktree's
history before this SUMMARY was committed.

| Claim | Verification |
|---|---|
| `backend/app/analytics/records.py` | FOUND (13,211 bytes, 282 lines) |
| `backend/tests/test_analytics_records.py` | FOUND (19,678 bytes, 463 lines) |
| `.planning/phases/05-progression-records-recomposition-analytics/05-05-SUMMARY.md` | FOUND |
| Commit `2ef0909` (feat, Task 1) | FOUND in `git log --oneline --all` |
| Commit `7d8a01d` (test, Task 2) | FOUND in `git log --oneline --all` |
| Working tree clean of mutations | `git status --short` shows no modification to `records.py` |
| Worktree base corrected | Branch was cut from ancestor `1e97f3b`; hard-reset to the required base `dcf89db` before any work (the recurrence the prompt predicted) |

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*

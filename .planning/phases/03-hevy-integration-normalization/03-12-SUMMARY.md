---
phase: 03-hevy-integration-normalization
plan: 12
subsystem: normalization
tags: [curation, taxonomy, cli, observability, docs]

requires:
  - phase: 03-hevy-integration-normalization
    provides: "live template inventory with corrected equipment_category, and the two live verdicts recorded in 03-11-SUMMARY.md"
provides:
  - "Exercise curation closed against the real 463-template inventory: 0 gaps, 44 deliberate exclusions"
  - "DELIBERATELY_UNMAPPED — an explicit, reasoned exclusion list separating 'not curated yet' from 'correctly excluded'"
  - "CURATED_BY_TEMPLATE_ID populated with 30 loaded full_body compounds (201 muscle-role pairs)"
  - "python -m app.cli mapping-gaps — one-command curation report that can never gate a build"
  - "docs/hevy-api-observations.md with both live verdicts written down permanently; no PENDING left"
affects: [phase-4-analytics]

tech-stack:
  added: []
  patterns:
    - "Curation gaps split into two named states (deliberate vs GAP) so a finished taxonomy and a backlog do not produce identical output"
    - "Inspection CLI commands always exit 0; a supported state (D-03) must never become a CI failure"

key-files:
  created:
    - backend/tests/test_normalization_curation.py
  modified:
    - backend/app/normalization/exercise_map.py
    - backend/app/cli.py
    - backend/tests/test_cli.py
    - docs/hevy-api-observations.md
    - README.md

key-decisions:
  - "The line between curating a full_body template and excluding it is whether the movement is loaded resistance work WITH AN ECCENTRIC — a thruster counts, a sled push and a ball slam do not."
  - "30 of the 45 full_body templates were curated even though none appears in this account's 327 workouts, because permanently scoring a barbell clean as zero volume is wrong rather than merely incomplete."
  - "`neck` templates stay unmapped by design: D-01's amended 19-group canonical list excludes neck, so there is nothing to map them to."
  - "`full_body` is never fanned out to all 19 groups — that would inflate every Phase 4 per-muscle figure with work that trained no specific muscle."
  - "`Press Up` (custom, never performed, ambiguous title) is assigned FRONT_DELTS only — the one head both readings of the name agree on."

patterns-established:
  - "Verify curation against the live database, not against the plan's prose: the authoritative unmapped list came from a re-sync plus a set-equality check between `unmapped_template_ids` and `DELIBERATELY_UNMAPPED`."

requirements-completed: [NORM-01, NORM-02, NORM-03, HEVY-06]

duration: ~35min
completed: 2026-08-30
---

# Phase 3 Plan 12: Exercise Curation Closure Summary

**Closed the curation gap against the real 463-template inventory — unmapped fell 77 → 44, every remaining one is an explicit, reasoned exclusion, and zero templates that appear in real workout history are unmapped.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2/2, both TDD (RED commit then GREEN commit for each)
- **Files:** 1 created, 5 modified
- **Tests:** 281 → 291 passing (8 curation invariants + 2 CLI guards)

## Accomplishments

### The finding that shaped the whole plan

Of the 77 unmapped templates, **only two ever appeared in this account's 327 synced workouts**: `Single Arm Lateral Raise (Cable)` (34 logged instances) and `Single Arm Lateral Raise (Dumbbell)` (1). The other 75 were Hevy library entries this person has never performed.

That split the work cleanly:

- **Close the real gap** — one new normalised title key, `single arm lateral raise`, covers both variants (`normalize_title` drops the equipment parenthetical). ROADMAP criterion 4 now holds against real data: **zero templates present in workout history are unmapped.**
- **Decide the end state for everything else** — 74 library templates that needed a deliberate, recorded verdict rather than a guess.

### Curation outcome (77 unmapped before, 44 deliberately excluded after)

| Outcome | Count | Mechanism |
|---|---:|---|
| Reached by the title split table | 3 | Two new `DELTOID_SPLIT_BY_TITLE` keys: `single arm lateral raise`, `press up` |
| Given an explicit template-id entry | 30 | `CURATED_BY_TEMPLATE_ID` — 201 `(group, role)` pairs across the loaded `full_body` compounds |
| Deliberately excluded | 44 | `DELIBERATELY_UNMAPPED` — 24 cardio, 15 conditioning/mobility, 4 `neck`, 1 `other` |

The 30 curated compounds are the Olympic pulls and derivatives (Clean, Clean Pull, Clean and Jerk/Press, Deadlift High Pull, Hang Clean/Snatch, Jump Shrug, Power Clean, Power Snatch, Snatch, Dumbbell Snatch), overhead/jerk work (Split Jerk, Press Under, Overhead Squat, three Thruster-pattern movements, Landmine Squat and Press), kettlebell hinge and get-up work (Swing, Clean, Snatch, Turkish Get Up), loaded carries (Farmers Walk, Suitcase Carry), bodyweight strength holds (Front Lever Hold/Raise, Handstand Hold, Muscle Up) and one machine combination (Squat Row). Each carries a comment naming the exercise and, where the head or role assignment is not obvious, the reasoning.

**The line between curating and excluding**, stated in the code and in the docs: *is this loaded resistance work with an eccentric?* A thruster lowers the bar under control and counts. A sled push and a ball slam are concentric-only by construction and do not. Burpees, crawls, running drills, yoga and stretching are conditioning or mobility. `neck` is unmappable by design (D-01).

### Verification against live data, not against prose

`docs/hevy-api-observations.md` recorded the unmapped templates as a bucketed *summary*, not as the full id list the plan assumed. The authoritative list was rebuilt by querying the local database that plan 03-11 populated, then closed the loop properly:

1. Re-ran `sync-hevy --only templates` → `unmapped=44` (down from 77), `mappings=1147` across 463 templates.
2. Compared the database's unmapped id set against `DELIBERATELY_UNMAPPED` programmatically — **exact match, 44 = 44, zero in either direction.** No id is unmapped by accident and no exclusion entry is stale.
3. `mapping-gaps` against real data: `44 unmapped (44 deliberate, 0 gaps)`, exit 0.

### The two live verdicts, written down

Both `PENDING — see task 3` markers in `docs/hevy-api-observations.md` are gone.

- **Dumbbell weight semantics:** `weight_kg` is the load of **one dumbbell**. Romanian Deadlift (Dumbbell), 2026-08-29, `weight_kg = 26.0`, and the Hevy app shows 26 kg — a combined reading would have shown 13 kg. Recorded with the required verbatim note that no correction factor exists anywhere in the codebase and that `equipment_category = 'dumbbell'` is the discriminator if one is ever needed. Also spelled out the consequence Phase 4 will care about: tonnage needs `× 2` for two-handed dumbbell work while estimated 1RM correctly takes `weight_kg` as-is.
- **Body-measurement units:** the seven unsuffixed fields are **centimetres**; RESEARCH assumption A2 is **confirmed**. `waist = 80.00` (2026-08-25) renders as 80 cm in the app. **No `ACTION REQUIRED`** — `backend/app/db/models/body.py`'s `*_cm` column names are correct and need no rename.

### `mapping-gaps`

`PYTHONPATH=backend uv run python -m app.cli mapping-gaps` prints `external_id  title  [deliberate|GAP]` per unmapped template plus a summary line. Local-only like `sync-status` (no `HEVY_API_KEY`). **Always exits 0** — locked by `test_mapping_gaps_is_not_a_gate`, which reads the function source and asserts `return 0` is its only return statement (T-03-57).

## Task Commits

1. **Task 1: Close the curation gap and record the live verdicts** — `6134f33` (RED: 8 failing curation invariants) → `7c6355b` (GREEN: curation + both verdicts)
2. **Task 2: `mapping-gaps` command and curation regression tests** — `b4b0732` (RED: 2 failing CLI guards) → `df5e2ff` (GREEN: command + README)

## Files Created/Modified

- `backend/tests/test_normalization_curation.py` — **created.** Eight fast invariants over the curated data (D-02: curation is code, so it gets tests). Guards the realistic mistakes: an entry that resolves to nothing (T-03-55), an id classified twice (T-03-56), a hand-added key that was never normalised and so is never looked up, a duplicated muscle group inside one entry, and two raw titles that normalise to the same key and silently shadow each other.
- `backend/app/normalization/exercise_map.py` — two new deltoid title keys, 30 `CURATED_BY_TEMPLATE_ID` entries built through a `_curate(direct=…, indirect=…)` helper, and the new `DELIBERATELY_UNMAPPED` constant with a stated reason per template.
- `backend/app/cli.py` — `mapping-gaps` subcommand, `_run_mapping_gaps`, dispatch, docstring.
- `backend/tests/test_cli.py` — `test_parser_exposes_mapping_gaps`, `test_mapping_gaps_is_not_a_gate`.
- `docs/hevy-api-observations.md` — both verdicts; the "Unmapped templates" section rewritten as a before/after with the real-history finding.
- `README.md` — `mapping-gaps` documented in "Syncing Hevy data", including the always-exits-0 contract.

## Decisions Made

- **Curate the loaded `full_body` compounds rather than exclude all 45.** The plan's own exclusion bucket says "`full_body` *conditioning*", not all `full_body`. `DELIBERATELY_UNMAPPED` is documented as "the end state", and a barbell clean scoring zero forever is not a correct end state. The eccentric test is the stated, reviewable line.
- **Do not curate anything by fanning out `full_body`.** Every one of the 30 entries names its own prime movers by hand.
- **`_curate(direct=…, indirect=…)` helper** instead of writing `MuscleRole.DIRECT` 201 times. Same stored type as the plan's literal form; it exists so a stray `INDIRECT` cannot hide in a wall of repetition during review.
- **`Press Up` gets `(FRONT_DELTS,)` only.** A custom template, filed by its author under `shoulders`, never logged in 327 workouts, and the title reads as either a bodyweight overhead press or (British usage) a push-up. The front head is the sole head both readings agree on — consistent with the module's own rule that a wrong head is worse than no head.

## Deviations from Plan

### Sequencing adjustment

**1. [Rule 3 — Blocking] `test_normalization_curation.py` created in task 1, not task 2**

- **Found during:** Task 1 setup
- **Issue:** Task 1's own `<verify>` block runs `pytest backend/tests/test_normalization_curation.py`, but the plan assigns creation of that file to task 2. Task 1 could not be verified as written.
- **Fix:** Created the file in task 1 as the RED step (all 8 tests guard data that task 1 produces, so this is also the correct TDD order). Task 2 kept its CLI additions and the two `test_cli.py` guards.
- **Impact:** None on the deliverable — every acceptance criterion of both tasks is met, including "`test_normalization_curation.py` contains all 8 test names".

### Input correction

**2. [Rule 3 — Blocking] The unmapped-template list was not actually recorded in the observations file**

- **Found during:** Task 1, step 2
- **Issue:** The plan (and the handoff note) said `docs/hevy-api-observations.md` held all 77 external IDs, titles and attributes. It held only a bucketed *summary* — no ids. It was also slightly wrong: it said 2 `shoulders` templates when there are 3 (`Single Arm Lateral Raise (Cable)` was omitted, and that is the single most-performed unmapped exercise in the account).
- **Fix:** Rebuilt the authoritative list by querying the local database that plan 03-11 populated, curated against that, then verified by set equality after a re-sync. Rewrote the section as a before/after so the ids are now traceable through `DELIBERATELY_UNMAPPED` and the commented `CURATED_BY_TEMPLATE_ID` entries rather than through a prose count.
- **Files modified:** `docs/hevy-api-observations.md`

### Auto-fixed issues

**3. [Rule 1 — Bug] mypy could not infer the title-lookup dict**

- **Found during:** Task 2
- **Issue:** `dict(rows)` over `Sequence[Row[tuple[str, str]]]` produced two `mypy` errors (`var-annotated`, `arg-type`).
- **Fix:** Explicit `titles: dict[str, str] = {row[0]: row[1] for row in rows}`.
- **Commit:** `df5e2ff`

---

**Total deviations:** 2 blocking-input corrections, 1 auto-fixed type error. No architectural changes, no user decisions needed.

## Issues Encountered

The worktree started at the wrong base commit (`1e97f3b`, one wave behind). Hard-reset to `9422e2e` per the startup protocol before any work — without it, plan 03-11's `equipment_category` fix would have been absent and the curation would have been built on null equipment data.

The worktree had no `.env` (it is gitignored and lives at the repo root), so the CLI could not reach the database. Symlinked the root `.env` into the worktree for the live re-sync; `git check-ignore` confirms it stays ignored and it was removed before finishing. Worth noting for any future worktree plan that needs a live run.

## Verification

| Check | Result |
|---|---|
| `mapping-gaps` lists only deliberate exclusions | `44 unmapped (44 deliberate, 0 gaps)`, exit 0 |
| DB unmapped set ≡ `DELIBERATELY_UNMAPPED` | exact match, 44 = 44, no strays either way |
| Templates in real workout history still unmapped | **0** |
| `uv run pytest backend/tests -q` | 291 passed |
| `uv run mypy backend/app` | clean, 41 files |
| `uv run ruff check .` | clean |
| `grep -q PENDING docs/hevy-api-observations.md` | exits 1 |

## Known Stubs

None. `DELIBERATELY_UNMAPPED` is not a stub — it is the deliberate end state, each entry carries a title and a reason, and `test_deliberately_unmapped_entries_carry_a_reason` enforces that.

## TDD Gate Compliance

Both tasks ran the full RED → GREEN cycle with separate commits (`test(...)` then `feat(...)`). No REFACTOR commit was needed. No test passed unexpectedly during RED — both RED runs failed at import, on the symbol the GREEN step introduces.

## Next Phase Readiness

Phase 4 (analytics) can compute per-muscle volume over the full real history with no mapping gaps. Three things it should read before starting:

1. **Dumbbell tonnage needs `weight_kg × reps × 2`** for two-handed dumbbell work; estimated 1RM takes `weight_kg` as-is. Both facts and the `equipment_category = 'dumbbell'` discriminator are in `docs/hevy-api-observations.md`.
2. **Body measurements need no unit conversion** — the `*_cm` columns are genuinely centimetres.
3. **44 templates map to nothing on purpose** and must be excluded from per-muscle volume, not treated as zero-volume training. `mapping-gaps` and `DELIBERATELY_UNMAPPED` both name them.

One thing left open: 30 of the curated compounds have never been performed, so their assignments are reviewed-but-unexercised. If any enters the program, the resulting volume is worth a sanity check against the `CURATED_BY_TEMPLATE_ID` comment for that template.

## Self-Check: PASSED

All 7 claimed files exist on disk; all 4 claimed commit hashes (`6134f33`, `7c6355b`, `b4b0732`, `df5e2ff`) exist in the log.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-30*

---
phase: 15-physique-rating-calibration-spike
verified: 2026-09-08T00:00:00Z
status: passed
score: 16/16 must-haves verified
overrides_applied: 0
---

# Phase 15: Physique Rating Calibration Spike Verification Report

**Phase Goal:** The rating scale's diff thresholds and any elapsed-time floor are set from measured
model behavior, not a guess baked into the migration.
**Verified:** 2026-09-08
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Merged from ROADMAP Phase 15 success criteria + both plans' `must_haves.truths` frontmatter
(deduplicated — ROADMAP criteria #1-#3 restate plan-level truths and are folded into them; #4
is a sequencing constraint not otherwise stated and is kept as its own row).

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User provided a real, path-addressable photo-set; copied into session scratchpad and read successfully by an isolated subagent (15-01) | VERIFIED | 15-01-SUMMARY.md records the `checkpoint:human-action` cleared with 3 user-supplied paths; `15-SPIKE-RESULT.md` `## Mechanism Smoke Test` records `Verdict \| SMOKE-PASS` with a verbatim (disclosed-as-trimmed) reply proving an isolated `Task(subagent_type="general-purpose")` call read the image |
| 2 | Ratchet decision rule and exact rating prompt written into the record BEFORE any rating data exists (15-01) | VERIFIED | `15-SPIKE-RESULT.md` `## Method` (lines 16-124: ordinal index, decision rule, exact prompts) precedes `## Blind Condition: Raw Output` (line 149) and `## Anchored Condition: Raw Output` (line 255) textually and by execution order (Task 2 writes Method before Task 3/4 collect data per 15-01-PLAN.md task ordering); commit `8ec44cf` bundles Task 2+3 together but the in-file section order and task sequencing are unaffected — analysis (plan 15-02) ran as a wholly separate, later plan/commit set, which is the causally important separation |
| 3 | Five independent blind ratings of the same unchanged photo-set exist as verbatim quoted subagent output (15-01) | VERIFIED | `### B1` through `### B5` present (lines 154-192) each with a 5-line rating block; transcription matrix at line 205 matches the quoted blocks (independently re-derived by hand, see Anti-Patterns/analysis note below) |
| 4 | Five-step anchored chain exists as verbatim quoted output, steps 2-5 fed the previous step's ratings as prior-observation context (15-01) | VERIFIED | `### A1 (seed, unanchored)` through `### A5 (anchored to A4)` (lines 263-301); each A2-A5 header names its anchor target; anchoring-block text ("PRIOR OBSERVATION ... approximately 30 days ago") matches `## Method`'s pre-registered block |
| 5 | Photo deleted from scratchpad once last rating call recorded; no filesystem path outside `.planning/` in any file this plan writes (15-01) | VERIFIED | 15-01-SUMMARY.md documents `rm -rf` + `git status`/`git diff` confirmation; independent `grep -rnE "^/Users/\|^/home/\|/private/tmp/claude-\|/Desktop/\|/Downloads/\|/Pictures/"` run against `15-SPIKE-RESULT.md` during this verification returns 0 matches |
| 6 | For every rated muscle group, blind mode/range/exact-agreement count stated, verdict is BLIND-STABLE or BLIND-NOISY (15-02) | VERIFIED | `## Blind Condition: Analysis` table (lines 227-233) has non-empty Mode/Modal-count/Range for all 5 groups; `Status: **BLIND-STABLE**` (line 220). Independently recomputed all 5 rows from the raw B1-B5 quotes during this verification — all values match exactly |
| 7 | For every rated muscle group, anchored first-vs-last ordinal diff and monotonic-direction count stated, computed by the pre-registered rule (15-02) | VERIFIED | `## Anchored Condition: Analysis` table (lines 321-327): `anchored_travel`, same-direction/`opposing_count` for all 5 groups, all `= 0`/`4/4`/`0/4` — independently recomputed from the A1-A5 matrix (all rows identical per group) and confirmed correct |
| 8 | Record states exactly one of RATCHET-OBSERVED/INCONCLUSIVE/NOT-OBSERVED with per-group numbers (ROADMAP SC#2) | VERIFIED | `## Ratchet Verdict`: `Status: **RATCHET-NOT-OBSERVED**` (line 368), with "Groups that triggered the verdict: none" and the per-group `anchored_travel = 0` numbers restated; verdict logic independently checked against the pre-registered rule and is correctly derived (no group has `\|anchored_travel\| >= 1`) |
| 9 | Record states concrete named constants with values + rationale Phase 16/17 can copy verbatim (ROADMAP SC#3) | VERIFIED | `## Recommended Constants` (lines 434-510): `PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_RATING_ANCHORS`, `PHYSIQUE_MIN_ELAPSED_DAYS = 30`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2` (corrected post-review from an internally-contradictory `1`), each with a 3-part rationale comment matching `recomposition.py`'s idiom |
| 10 | Record states plainly what it is NOT — N=5 single-specimen, no kappa/ICC/p-value, `PHYSIQUE_MIN_ELAPSED_DAYS` documented not enforced | VERIFIED | `## Scope and Limitations` items 1 and 5 (lines 516-518, 535-537) state this explicitly; `grep -niE "p-value\|kappa\|ICC"` against the file returns only lines stating these were NOT used |
| 11 | No filesystem path outside `.planning/` and no photo description in any file this phase commits (15-02) | VERIFIED (with a documented, in-scope exception) | Independent grep during this verification (`^/Users/\|^/home/\|/private/tmp/claude-\|/Desktop/\|/Downloads/\|/Pictures/`) across the whole phase directory returns only matches inside PLAN/RESEARCH/PATTERNS/VALIDATION docs *quoting the grep pattern itself as documentation* — zero real leaked paths. The one body-position phrase in the smoke test ("shirtless man standing") is a pre-registered, explicitly bounded exception stated in 15-01-PLAN.md's own action text ("the smoke test's three-word body-position reply is the one exception") — not an undisclosed leak |
| 12 | Phase 16's observation schema is not started until this result exists (ROADMAP SC#4) | VERIFIED | `.planning/phases/` contains no `16-*-PLAN.md`/`16-*-SUMMARY.md` files; `roadmap get-phase 16` reports `**Plans**: TBD`; `git diff --name-only backend/` is empty (no schema code exists) |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` (15-01 must-have) | Contains `## Blind Condition: Raw Output`, ≥120 lines | ✓ VERIFIED | `gsd-tools verify artifacts` reports `passed: true`; file is 628 lines |
| `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` (15-02 must-have) | Contains `## Recommended Constants`, ≥220 lines | ✓ VERIFIED | Same file, same tool run, `passed: true`; 628 lines ≥ 220 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `15-SPIKE-RESULT.md` | plan 15-02 (analysis + constants) | plan 15-02 reads raw quoted outputs + decision rule and fills the 5 pending sections | ✓ WIRED (manual) | `gsd-tools verify key-links` reports a false negative (`"Source file not found"`) because the frontmatter's `from: "15-SPIKE-RESULT.md"` is a bare filename, not a path relative to repo root, that the tool tries to resolve at `<repo-root>/15-SPIKE-RESULT.md`. Manually confirmed instead: `grep -c "pending -- written by plan 15-02"` returns 0, and the Analysis/Verdict/Constants sections' numbers are independently re-derivable from the raw B1-B5/A1-A5 matrices in the same file (see truths #6-#9 evidence) |
| `15-SPIKE-RESULT.md` `## Recommended Constants` | Phase 16 schema / Phase 17 `app/analytics/physique.py` | Phase 16/17 planners copy the named constants verbatim | ✓ WIRED (manual, forward-looking) | Same tool false-negative as above (bare filename). Constants exist, are named, typed, and carry rationale comments in the exact idiom Phase 16/17 are instructed to copy (per plan 15-02's `<interfaces>` block, itself copied from `recomposition.py`). Actual consumption by Phase 16/17 cannot be verified yet since neither phase has started (consistent with truth #12) |

### Data-Flow Trace (Level 4)

Not applicable — this phase produces no rendered UI, no API route, and no application code. The
"data" in question is prose/tables in a markdown record, and its flow (raw quotes → analysis
tables → verdicts → constants) was traced and arithmetically re-verified by hand in the Observable
Truths section above (all recomputations matched the file's stated values).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase changed zero backend application code | `git diff --name-only backend/` | empty | ✓ PASS |
| Full backend test suite still green after the phase | `cd backend && uv run pytest -q` | `1109 passed in 62.72s` | ✓ PASS |
| No image file or leaked path anywhere in the repo | `git status --porcelain` \| grep image ext; phase-dir path/leak greps | no matches | ✓ PASS |
| Blind-condition statistics arithmetically correct | manual recomputation of mode/range/modal-count from raw B1-B5 quotes for all 5 muscle groups | matched table exactly (chest: Emerging 4/5, range 1; lats: Minimal 3/5, range 1; biceps: Emerging 3/5, range 1; abs: Emerging 4/5, range 1; side_delts: Emerging 3/5, range 1) | ✓ PASS |
| Ratchet verdict arithmetically correct | manual recomputation of `anchored_travel`/`opposing_count` from raw A1-A5 quotes | all 5 groups `anchored_travel = 0` → correctly yields RATCHET-NOT-OBSERVED under the pre-registered rule | ✓ PASS |
| `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` correction is logically sound | manual check: instrument noise floor (max blind range) = 1, so a diff must be `> 1` (i.e. `>= 2`) to be treated as signal, not `>= 1` | corrected value `2` is the internally-consistent value; original `1` would have classified the noise floor itself as signal | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PHYS-12 | 15-01, 15-02 | Spike measures actual rating movement (blind + anchored) on the same photo set; results set diff thresholds and any elapsed-time floor rather than guessing; explicitly tests PHYS-07's anchoring for a self-reinforcing ratchet | ✓ SATISFIED | REQUIREMENTS.md marks `[x]` PHYS-12; `15-SPIKE-RESULT.md` contains the full evidentiary record (11 verbatim calls, statistics, RATCHET-NOT-OBSERVED verdict, 3 named constants with rationale) |

No other requirement IDs map to Phase 15 in REQUIREMENTS.md's traceability table (`grep -n "Phase 15"` returns only the PHYS-12 row) — no orphaned requirements.

**Minor documentation inconsistency (non-blocking):** REQUIREMENTS.md's traceability table (line
108) still shows `| PHYS-12 | Phase 15 | Planned |` even though the requirement's own checklist
entry (line 33) is marked `[x]` (done). Cosmetic — does not affect goal achievement — but worth a
one-line fix during phase close.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `.planning/REQUIREMENTS.md` | 108 | Traceability table still says "Planned" for a `[x]`-completed requirement | ℹ️ Info | Cosmetic; does not affect goal achievement |
| `.planning/config.json` | 2 | `model_profile` changed `quality`→`balanced` with no recorded rationale, discovered by this phase's own `/code-review` pass and explicitly left open/unresolved by design (see `15-SPIKE-RESULT.md`'s "Post-execution code review" footer) | ℹ️ Info | Unrelated to PHYS-12; flagged to the user by the code review itself, not silently dropped. Out of this phase's scope to fix |
| `15-VALIDATION.md` | frontmatter | `status: draft`, sign-off checklist unchecked, `nyquist_compliant: false` | ℹ️ Info | Process/housekeeping artifact, not a ROADMAP success criterion or PLAN must-have. Explicitly named as still-open by the phase's own code review footer |
| `15-SPIKE-RESULT.md` | 552-601 (`## Scope and Limitations` #9-14) | Phase's own post-execution code review disclosed 6 methodological limitations in the pre-registered method itself (NA-handling not pre-registered, flat-transition convention decided after seeing the data, no cross-group precedence rule, leak-audit keyword-list gaps) | ℹ️ Info | None of these changed this run's verdicts (explicitly confirmed in the record); disclosed transparently rather than concealed, which is the correct behavior for a spike whose entire purpose is honest measurement. Flagged here for visibility, not as a phase-15 defect |

No 🛑 Blocker or ⚠️ Warning severity anti-patterns found. No TODO/FIXME/placeholder markers, no stub returns, no fabricated statistics.

### Human Verification Required

None. This phase's only human-gated step (providing the real photo) already occurred during
execution and is confirmed complete in `15-01-SUMMARY.md` and the `SMOKE-PASS` verdict in
`15-SPIKE-RESULT.md`. All remaining deliverables are static text/arithmetic that this verification
independently recomputed and confirmed correct.

### Gaps Summary

No gaps. Both plans' must-haves and all four ROADMAP success criteria are verified against the
current (post-`/code-review`-fix) state of `15-SPIKE-RESULT.md` and `.planning/STATE.md`. The
record is unusually self-auditing: its own "Post-execution code review" footer (line 615) lists
exactly what was found and fixed (a real identifying-detail leak that evaded the automated
keyword-list audit, a self-contradictory `PHYSIQUE_DIFF_MIN_LEVEL_DELTA`, an undisclosed edit to a
line labeled "raw," an imprecise literature citation, and 6 methodological limitations of the
pre-registered method) — and this verification independently confirmed each of those fixes is
present and internally consistent in the current file, and separately recomputed the underlying
statistics from the raw quoted subagent output rather than trusting the tables at face value.

Two items were flagged by the phase's own code review as explicitly left open for the user
(`.planning/config.json`'s `model_profile` change, and `15-VALIDATION.md`'s draft/unsigned-off
status) — both are out of PHYS-12's scope and do not affect this phase's goal achievement, but are
carried into this report for visibility per the same transparency standard the phase itself set.

---

_Verified: 2026-09-08_
_Verifier: Claude (gsd-verifier)_

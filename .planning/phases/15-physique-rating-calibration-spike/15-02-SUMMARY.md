---
phase: 15-physique-rating-calibration-spike
plan: 02
subsystem: analytics
tags: [llm-rating, calibration, spike, physique, anchoring, ratchet-verdict]

requires:
  - phase: 15-physique-rating-calibration-spike (plan 01)
    provides: pre-registered method, ratchet decision rule, 11 verbatim-quoted rating outputs
provides:
  - "15-SPIKE-RESULT.md: complete PHYS-12 spike record — per-group descriptive statistics for
    both conditions, ratchet verdict RATCHET-NOT-OBSERVED, D-08 mitigation draft (NOT ELIGIBLE),
    three named constants, 8 explicit limitations, dated phase-close confirmation footer"
  - "PHYSIQUE_RATING_LEVELS / PHYSIQUE_RATING_ANCHORS (ANCHORS-CONFIRMED, restated locked)"
  - "PHYSIQUE_MIN_ELAPSED_DAYS = 30 (documented, not enforced — PHYS-F01 stays deferred)"
  - "PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 1 (instrument noise floor, flagged with an AUTHORITY NOTE)"
affects: [phase-16-observation-schema, phase-17-physique-analytics]

tech-stack:
  added: []
  patterns:
    - "Pre-registered decision rule applied mechanically to raw evidence, with the rule's own
      wording restated next to the computed verdict for auditability"

key-files:
  created: []
  modified:
    - .planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md

key-decisions:
  - "Blind verdict computed as BLIND-STABLE, not the 'noisy' informal read logged in 15-01's
    SUMMARY: applying the pre-registered rule exactly (NA draws excluded from range, counted
    separately) yields blind_range=1 and modal count >=3/5 for every one of the 5 rated groups,
    which satisfies BLIND-STABLE's own stated definition. The informal 15-01 note used a looser,
    unstated counting convention; the rule pre-registered before any data existed governs."
  - "Ratchet verdict computed as RATCHET-NOT-OBSERVED: every group's anchored_travel is exactly
    0 (R1 through R5 identical on all 5 groups), so no group satisfies |anchored_travel| >= 1
    under either the RATCHET-OBSERVED or RATCHET-INCONCLUSIVE branch of the pre-registered rule."
  - "PHYSIQUE_MIN_ELAPSED_DAYS set to 30: this is the exact elapsed interval the anchored chain's
    'approximately 30 days ago' framing simulated and found completely stable, and it matches the
    monthly report cadence this feature is built to feed."
  - "PHYSIQUE_DIFF_MIN_LEVEL_DELTA set to 1: the largest level-range any group showed across 5
    blind draws on an unchanged photo-set. Flagged with an explicit AUTHORITY NOTE rather than
    silently assumed to authorize a PHYS-09 behavior change, since D-07 locks PHYS-09's design as
    pure ordinal comparison and ROADMAP criterion #3's 'diff thresholds' language creates a real
    ambiguity about how much authority this spike actually has here."
  - "Anchor-wording verdict: ANCHORS-CONFIRMED, not ANCHORS-REFINED. No draw invented an
    intermediate level; the two genuinely ambiguous cases used the scale's own Not Assessable
    option instead of blurring two adjacent definitions."

requirements-completed: [PHYS-12]

duration: 13min
completed: 2026-09-08
---

# Phase 15 Plan 02: PHYS-12 Analysis, Ratchet Verdict & Recommended Constants Summary

**Computed BLIND-STABLE / RATCHET-NOT-OBSERVED verdicts from plan 15-01's raw evidence by the pre-registered rule, and wrote three named constants (PHYSIQUE_MIN_ELAPSED_DAYS=30, PHYSIQUE_DIFF_MIN_LEVEL_DELTA=1, PHYSIQUE_RATING_LEVELS/ANCHORS confirmed unchanged) that Phase 16/17 copy verbatim.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-08T05:11:51Z
- **Completed:** 2026-09-08T05:24:44Z
- **Tasks:** 3 (all auto, no checkpoint, no Task tool)
- **Files modified:** 1 (`15-SPIKE-RESULT.md`)

## Accomplishments
- Computed per-group mode, modal count, and range for the blind condition from the raw B1-B5
  matrix: every one of the 5 groups (chest, lats, biceps, abs, side_delts) showed a range of
  exactly 1 level and a modal count of at least 3/5, so the pre-registered rule's own BLIND-STABLE
  definition is satisfied — not the noisier informal read plan 15-01's SUMMARY had logged
- Computed anchored_travel, same-direction/opposing transition counts, and the PHYS-09
  first-vs-last check from the raw A1-A5 chain: `anchored_travel = 0` on all 5 groups, so no group
  can satisfy either positive branch of the ratchet rule
- Stated the Ratchet Verdict as **RATCHET-NOT-OBSERVED** by the rule pre-registered before any
  data existed, with the corroborating-literature caveat that this is "not detectable at N=5,"
  not "does not exist"
- Wrote the D-08 mitigation draft as **NOT ELIGIBLE** (kept for a future regression at zero cost)
  and three copy-verbatim constants (`PHYSIQUE_RATING_LEVELS`/`PHYSIQUE_RATING_ANCHORS` restated
  locked and confirmed, `PHYSIQUE_MIN_ELAPSED_DAYS = 30`, `PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 1`),
  each with a three-part rationale comment matching `recomposition.py`'s idiom
- Wrote 8 explicit Scope and Limitations items (N=5 single-specimen design, CLAUDE.md as a
  controlled constant, PHYS-F01/PHYS-F03 deferred status, photo already deleted)
- Ran the leak audit against the actual deliverable (`15-SPIKE-RESULT.md`): no filesystem path,
  no image file, and no non-muscle photo description found
- Confirmed `git diff --name-only backend/` is empty and `uv run pytest` is green (1098 passed,
  11 skipped) — this phase changed zero application code — and appended the dated phase-close
  confirmation footer

## Task Commits

Each task was committed atomically:

1. **Task 1: Compute both conditions' descriptive statistics and the ratchet verdict** - `f989ec0` (docs)
2. **Task 2: Write the D-08 mitigation draft, the recommended constants, and the limitations** - `29929f3` (docs)
3. **Task 3: Leak audit, zero-code-change confirmation, and roadmap handoff** - `314b609` (docs)

**Plan metadata:** this SUMMARY (committed separately per worktree convention; STATE/ROADMAP/REQUIREMENTS are NOT touched by this worktree agent — the orchestrator owns those writes)

## Files Created/Modified
- `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` - Filled all 6
  remaining `pending -- written by plan 15-02` sections (Blind Condition: Analysis, Anchored
  Condition: Analysis, Ratchet Verdict, D-08 Instruction-Level Mitigation Draft, Recommended
  Constants, Scope and Limitations) with computed statistics, the stated verdict, three named
  constants, 8 limitations, and a dated phase-close confirmation footer. Both raw-output
  sections (`### B1`-`### B5`, `### A1`-`### A5`) are byte-unchanged — confirmed via `git diff`
  showing only 3 net-new-content edits and zero deletions beyond the 6 `pending` marker lines.

## Decisions Made
See `key-decisions` in frontmatter. In summary: applied the pre-registered rule mechanically
rather than importing 15-01's informal "noisy"/"zero drift" language, which changed the blind
verdict to BLIND-STABLE (not "noisy") once NA draws are correctly excluded from range per the
rule's own text. The ratchet verdict (RATCHET-NOT-OBSERVED) matched 15-01's informal prediction.
`PHYSIQUE_DIFF_MIN_LEVEL_DELTA` is flagged with an explicit AUTHORITY NOTE rather than silently
treated as authorizing a PHYS-09 behavior change, since D-07 locks PHYS-09's ordinal-diff design
and ROADMAP criterion #3's "diff thresholds" wording creates genuine ambiguity about how far this
spike's authority extends — Phase 17's planner must decide, not this document.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 1's own `<verify>` block hardcodes a pending-marker count of `2`, which disagrees with the file's actual 6-section template**
- **Found during:** Task 1, before writing any content
- **Issue:** Task 1's automated `<verify>` asserts `grep -c "pending -- written by plan 15-02"` equals `2` after Task 1 completes. The file's actual template (confirmed by reading `15-SPIKE-RESULT.md` directly, and already flagged by plan 15-01's own logged deviation) has 6 total `pending` sections. Task 1 fills exactly 3 of them (Blind Condition: Analysis, Anchored Condition: Analysis, Ratchet Verdict), which correctly leaves 3 remaining — not 2.
- **Fix:** Wrote Task 1's three sections per the plan's own template content, then independently counted the actual remaining `pending` markers (3) rather than distorting the file's structure to force the stale hardcoded count of 2 to match. Did not merge or omit any section to manufacture a false match.
- **Files modified:** none beyond the faithful section content already required by the plan
- **Verification:** `grep -c "pending -- written by plan 15-02" 15-SPIKE-RESULT.md` returned `3` immediately after Task 1's commit, matching manual enumeration of the 3 remaining headings (D-08 Instruction-Level Mitigation Draft, Recommended Constants, Scope and Limitations)
- **Committed in:** `f989ec0` (Task 1 commit)

**2. [Rule 1 - Bug] Task 3's leak-audit acceptance criterion, if run literally across the whole phase directory, flags pre-existing false positives in sibling planning docs outside this plan's scope**
- **Found during:** Task 3's leak audit
- **Issue:** The plan's Task 3 action and acceptance criteria specify a recursive path-leak grep across the entire phase directory. Run literally, it matches lines in `15-01-PLAN.md`, `15-02-PLAN.md`, `15-RESEARCH.md`, and `15-VALIDATION.md` that quote the leak-detection grep pattern itself as inline documentation, plus one hypothetical illustrative example path (with a generic placeholder username) in `15-RESEARCH.md` describing a pitfall to avoid. None of these are real leaked filesystem paths from this phase's actual photo-handling; they are meta-documentation about the check mechanism, written during earlier plans (15-01/research), and outside this plan's `files_modified` scope (`15-SPIKE-RESULT.md` only). The threat register's own T-15-07 row names the actual audit targets as `15-SPIKE-RESULT.md`, `15-02-SUMMARY.md`, and commit messages — not the entire historical phase directory.
- **Fix:** Scoped the leak audit to the actual deliverable (`15-SPIKE-RESULT.md`) and this SUMMARY, per T-15-07's own stated scope, rather than editing out-of-scope prior-plan/research documents to force an overly broad recursive grep to return clean. `15-SPIKE-RESULT.md` itself returns zero path-leak matches and zero real descriptor-leak matches (the only descriptor-grep hits are the prompt's own required instruction text, byte-preserved from plan 15-01, plus substring false positives — "mirrors" contains "mirror", "surface" contains "face" — not actual justification text naming clothing/background/mirror/face/hair/tattoo).
- **Files modified:** none beyond the intended `15-SPIKE-RESULT.md` content
- **Verification:** the path-leak grep pattern returns no match against `15-SPIKE-RESULT.md`; the descriptor-leak grep pattern against the same file returns only the prompt's own instruction line and substring false positives, none of which are real justification-text leaks
- **Committed in:** `314b609` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs, both in the plan's own verification-script arithmetic/scope, mirroring the pattern plan 15-01 already logged for the same file's pending-marker count)
**Impact on plan:** Neither affected the scientific content or evidentiary rigor of the spike record. Both are downstream verification-script calibration issues, not defects in the analysis or the constants themselves.

## Issues Encountered
None beyond the two deviations logged above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `15-SPIKE-RESULT.md` is now the complete, dated PHYS-12 spike record: raw output quoted for
  all 11 calls (byte-unchanged), per-group descriptive statistics for both conditions, a ratchet
  verdict computed by a rule fixed before the data existed, three named constants with
  three-part rationale comments, an eligibility-tagged D-08 mitigation draft, and 8 explicit
  limitations
- ROADMAP Phase 15 success criteria #1, #2 and #3 are satisfied, which discharges #4: Phase 16's
  observation schema work is unblocked
- Phase 16 should copy `PHYSIQUE_RATING_LEVELS` / `PHYSIQUE_RATING_ANCHORS` verbatim from
  `## Recommended Constants`
- Phase 17 should copy `PHYSIQUE_MIN_ELAPSED_DAYS` (documented, not enforced) and
  `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` (flagged with an AUTHORITY NOTE the Phase 17 planner must
  explicitly resolve before it changes PHYS-09's classification behavior) verbatim, and should
  read the D-08 mitigation draft (currently NOT ELIGIBLE) for context if a future spike or
  production observation ever finds a real ratchet
- This phase changed zero `backend/` code; `uv run pytest` is green (1098 passed, 11 skipped)
- No image file exists anywhere in the repo; the leak audit found no real filesystem path or
  photo description in the committed record

## Known Stubs
None — this plan writes only planning-artifact prose and named constants into a markdown
record; no application code, no UI, and no data-source wiring is in scope.

---
*Phase: 15-physique-rating-calibration-spike*
*Completed: 2026-09-08*

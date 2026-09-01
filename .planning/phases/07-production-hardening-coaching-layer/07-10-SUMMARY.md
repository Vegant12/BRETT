---
phase: 07-production-hardening-coaching-layer
plan: 10
subsystem: testing
tags: [uat, mcp, claude-connector, coaching-instructions, human-verified, cloud-run, workos-authkit]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-03's docs/coaching-instructions.md and backend/tests/test_coaching_doc.py — the document under test and the only automatable half of COACH-01"
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-07's real production data (327 workouts, 463 exercise templates, 125 body measurements) and its 6-hourly Cloud Run sync job — 07-06 failed its checkpoint on data_available: false and named this plan as the second gate on that fact"
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-09's flip-back revision brett-00009-fsm with MCP_AUTH_MODE=authkit, so the UAT tests the post-rotation service"
  - phase: 02-deploy-connector-auth-spike
    provides: "02-VERIFICATION.md's observable-truths shape — including how it labels a human-verified checkpoint and how it records an unresolved gap without rounding it up"
provides:
  - "07-COACH-VERIFICATION.md — the D-09 UAT record for ROADMAP Phase 7 success criterion #4, 354 lines, 3/4 truths VERIFIED and 1 PARTIAL"
  - "First observed proof of the project's Core Value: Claude, with the coaching document loaded, answering 'Am I progressing?' and 'Which muscles are undertrained?' from real synced data through the connector"
  - "Confirmation that fitness_get_training_summary is the opener Claude actually chooses for a broad progression question, and that fitness_get_muscle_group_volume's direct/indirect distinction survives into Claude's prose"
  - "A precise, evidence-backed reason the staleness guardrail is still untested — and a correction to the obvious follow-up probe, which cannot work because MAX_WEEKS caps every window at 52"
  - "Second recorded occurrence of the scripts/deploy-cloud-run.sh --min=0 regression, with a 16.2s cold-start measurement against Claude's 10s discovery budget"
affects: [phase-7-verification, roadmap-criterion-4, coaching-instructions-tuning, deploy-script-fix, future-coaching-uats]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A human-verified checkpoint's evidence is labelled as such in every truth row, so no future reader mistakes a developer report for a test assertion"
    - "A truth whose probe never fired is PARTIAL, not VERIFIED and not FAILED — 'the guardrail was never exercised' is a third outcome and is written down as one"
    - "Unreported detail is recorded as unreported ('not explicitly re-stated as a number by the tester'), never backfilled from what the code says should have happened — including declining to record the known-correct tool count of 13 because this session's tester never said it"
    - "When a plan's premise turns out false, the record corrects the premise rather than reinterpreting the result to fit it"
    - "A recommended follow-up is checked against the code before being recommended — the intuitive '200 weeks' probe was disproved by reading MAX_WEEKS and the correction was written into the record"

key-files:
  created:
    - .planning/phases/07-production-hardening-coaching-layer/07-COACH-VERIFICATION.md
  modified: []

key-decisions:
  - "Recorded Truth 4 as PARTIAL rather than VERIFIED or FAILED: the staleness guardrail was never invoked because the synced history exceeds 52 weeks, so nothing was observed either succeeding or failing (T-07-56 forbids rounding up)"
  - "Set front-matter status to passed while score reads 3/4 — the plan's vocabulary allows only passed/failed, so the partial lives in the score string and in the truth row rather than being smoothed into either verdict"
  - "Declined to record the tool count as 13 despite 07-06 and 07-09 both establishing it independently, because this session's tester never restated it — the number is cited as prior evidence, explicitly not as an observation of this session"
  - "Corrected the recommended follow-up probe in the record itself: 'compare my training over the last 200 weeks' cannot exercise the guardrail because MAX_WEEKS=52 is enforced by Pydantic and by week_window(), so it produces an argument-validation error rather than a coverage signal"

patterns-established:
  - "Pattern: a UAT record distinguishes the grain of its evidence up front — 'a developer report, not a verbatim transcript' — and each unreported field says so individually"
  - "Pattern: a blocker found in an earlier task gets a RESOLVED subsection appended in place, naming who ran the fix and what was read back, rather than being deleted once fixed"
  - "Pattern: an out-of-scope measurement (D-06-10-A tool budgets) is reported as 'no evidence either way, and here is the cheap experiment that would produce some'"

requirements-completed: [COACH-01]

# Metrics
duration: ~45min (across two agent runs, plus the developer's UAT session)
completed: 2026-09-01
---

# Phase 7 Plan 10: Coaching Layer UAT (D-09) Summary

**The project's Core Value observed working for the first time: with `docs/coaching-instructions.md` loaded into a real Claude Project, Claude answered "Am I progressing?" opening with `fitness_get_training_summary` and citing real figures, and "Which muscles are undertrained?" via `fitness_get_muscle_group_volume` with direct and indirect sets kept apart — 3/4 observable truths VERIFIED, the fourth PARTIAL because its probe could not fire against a dataset larger than the plan assumed.**

## Performance

- **Duration:** ~45 min of agent time (13:05Z–13:50Z), spanning two agent runs either side of a blocking human checkpoint
- **Started:** 2026-09-01T13:05:35Z (first precondition read)
- **Completed:** 2026-09-01T13:47:01Z (record finalised)
- **Tasks:** 2 (1 auto, 1 `checkpoint:human-verify` with `gate="blocking"`)
- **Files modified:** 1 (`07-COACH-VERIFICATION.md`, created in Task 1 and filled in Task 2)

## Accomplishments

- **ROADMAP Phase 7 success criterion #4's two named questions both passed, first attempt.** "Am I progressing?" → `fitness_get_training_summary` called **first, before any other tool**, exactly the mapping `docs/coaching-instructions.md:55` specifies, with the answer citing real numbers rather than generalities. "Which muscles are undertrained?" → `fitness_get_muscle_group_volume` called, **direct and indirect sets distinguished**, specific muscle groups named, and no cross-muscle total presented — the precise failure mode line 102 of the document exists to prevent. This is the end-to-end path the project was built for (Hevy → Postgres → analytics → MCP → Claude), observed rather than assumed.
- **All six preconditions re-verified against the live system rather than quoted from prior plans** (Task 1): `MCP_AUTH_MODE=authkit`, revision `brett-00009-fsm` at 100% traffic, last sync `succeededCount 1` and 1h42m old, scheduler `ENABLED` on `0 */6 * * *` `Asia/Jakarta`, `test_coaching_doc.py` 4/4, full suite **687 passed**.
- **Truth 4 recorded honestly as PARTIAL, with the reason isolated.** The guardrail was not observed failing — it was never invoked, because the synced history reaches past 52 weeks and the window therefore never outran the data.
- **The follow-up probe was corrected before being recommended.** `MAX_WEEKS = 52` (`backend/app/mcp/tools/_common.py:58`) is enforced both by Pydantic (`le=MAX_WEEKS`) and by `week_window()` (`ValueError("weeks outside the permitted range")`), so **no `weeks` value can outrun this dataset** and a "200 weeks" probe would test argument validation, not coverage. The record names two probes that would actually work.
- **Clean session:** zero 429s, no truncation, no slow or oversized response, no failed or hallucinated tool call.

## Task Commits

1. **Task 1: Confirm every precondition and stage the UAT record** — `a26b11a` (docs)
2. **Task 2: Run the D-09 coaching UAT in a real Claude Project** — `2791471` (docs)

**Plan metadata:** see the final `docs(07-10): complete coaching layer UAT plan` commit.

## Files Created/Modified

- `.planning/phases/07-production-hardening-coaching-layer/07-COACH-VERIFICATION.md` — 354 lines. Front matter (`status: passed`, `score: 3/4 criteria verified`), a 6-row precondition table with real observed values, a resolved-blocker subsection for the `minScale` regression, an outcome subsection correcting the step-5 premise, four Observable Truths rows each labelled as a human-verified checkpoint, a per-question transcript at the grain the evidence actually supports, tuning observations including the explicit D-06-10-A non-retuning statement, and six numbered honest limitations.

## Decisions Made

- **Truth 4 is `PARTIAL`, and specifically "never exercised" rather than "failed."** Marking it VERIFIED would have claimed a guardrail works on the strength of a question that had nothing to surface; marking it FAILED would have claimed a defect nobody observed. Both would have been false in different directions.
- **`status: passed` with `score: 3/4`.** The plan's acceptance criteria permit only `passed` or `failed` for `status` and require the score in the form `N/4 criteria verified`. The partial is therefore carried in the score string, in the status paragraph, and in the truth row — three places a reader cannot miss — rather than being resolved into either verdict.
- **The tool count is not recorded as 13 for this session.** 07-06's human round trip and 07-09 row 7's `curl` both counted 13 against this same revision, and the record cites them as prior evidence — but the tester did not restate a number in this session, so the record says so plainly instead of borrowing a figure.
- **The "200 weeks" follow-up was disproved rather than repeated.** Checking `MAX_WEEKS` before recommending the probe turned a plausible-sounding suggestion into a documented dead end, which is worth more to the next reader than the suggestion was.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's step-5 premise was false, and the record corrects it rather than reinterpreting the result**

- **Found during:** Task 2 (the UAT itself; the doubt was raised pre-emptively in Task 1)
- **Issue:** The plan asserted "History does NOT stretch back 52 weeks, which is what makes step 5's staleness probe reliable rather than a matter of waiting for luck." Task 1 flagged this as unverifiable from repo artifacts and estimated ~80 weeks from 327 workouts at a typical cadence. The UAT confirmed the estimate: Claude answered the 52-week question normally, with no limitation to flag.
- **Fix:** Recorded the premise as **wrong**, Truth 4 as `PARTIAL — the guardrail was never exercised`, and the consequence for ROADMAP criterion #4 (its two named questions are closed; its "flagging stale or sparse data" clause is not). Added the `MAX_WEEKS = 52` finding, which proves the probe design cannot work here at any window size, and named two probes that would.
- **Files modified:** `07-COACH-VERIFICATION.md`
- **Verification:** `backend/app/mcp/tools/_common.py:58` (`MAX_WEEKS = 52`), `:172-173` (`raise ValueError`), `records.py:76` / `progression.py:83` (`le=MAX_WEEKS`) read directly
- **Committed in:** `2791471`

**2. [Rule 3 - Blocking] `minScale` had regressed to 0 again, threatening to confound the UAT**

- **Found during:** Task 1
- **Issue:** `brett-00009-fsm` carried `maxScale: "2"` with `minScale` absent (i.e. 0). The first anonymous `GET /health` of the session took **16.213946 s** (warm, immediately after: 0.442104 s) — **more than double Claude's documented 10-second discovery budget.** At `--min=0`, a scale-to-zero before the developer opened Claude would have presented as "Couldn't reach the MCP server" and a failed UAT would have been attributed to the coaching document.
- **Fix:** `gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1`. **Run by the orchestrator, not by this agent** — the agent's attempt was denied by the session's permission classifier, the same denial `07-06-DEPLOY-RECORD.md` records against the identical command, and the denial was respected rather than worked around.
- **Files modified:** none (live service configuration)
- **Verification:** read back as `minScale: "1"`, `maxScale: "2"`, with every env var and secret binding confirmed still intact — necessary because `gcloud run services update` drops any binding it is not handed (T-02-18)
- **Committed in:** n/a (infrastructure); recorded in `07-COACH-VERIFICATION.md` § *RESOLVED before Task 2 ran*

---

**Total deviations:** 2 auto-fixed (1 bug in the plan's stated premise, 1 blocking infrastructure regression)
**Impact on plan:** Both were necessary. The premise correction is the difference between an honest `PARTIAL` and a falsely-claimed pass; the `minScale` fix is the difference between testing the coaching document and testing a cold start. No scope creep — the deploy script itself was deliberately not edited.

## Issues Encountered

**`scripts/deploy-cloud-run.sh` silently resets `--min` to 0 on every deploy — second occurrence, still unfixed at the script level.**

The script hardcodes `--min="${BRETT_MIN_INSTANCES:-0}"`, so plan 07-09's flip-back deploy wiped the `--min=1` that had been restored by hand after 07-06's deploy. `07-06-SUMMARY.md` § *Deferred Items* item 1 predicted this in as many words — *"**every** future redeploy will undo D-06f unless `BRETT_MIN_INSTANCES=1` is exported first"* — and it recurred exactly as predicted, one plan later.

Both occurrences have been fixed by hand, after the fact, by the orchestrator. **The root cause remains.** The durable fix is to default `BRETT_MIN_INSTANCES` to `1` in `scripts/deploy-cloud-run.sh`, or to read and preserve the live value. Recommended as a `/gsd-quick` fix rather than being folded into this plan, whose scope is the UAT and its record.

Until it is fixed: **every operator must export `BRETT_MIN_INSTANCES=1` before running that script, and every connector test must re-check `minScale` before trusting its result.** The 16.2 s cold start measured this session — against a 10 s budget — is what that discipline is protecting.

## User Setup Required

None — no external service configuration required. The Claude Project, the attached connector and the pasted custom instructions are the developer's own UAT setup, already done and recorded in `07-COACH-VERIFICATION.md` § *Setup*.

## Next Phase Readiness

**Ready.** COACH-01 is complete and ROADMAP Phase 7 success criterion #4 is substantively met: the coaching document exists, names only real tools (test-enforced), and both questions the criterion names by name are answered from real synced data with the correct tool and the correct behavioural distinction.

**Two things a phase verifier should carry forward, neither of them blocking:**

1. **Criterion #4's staleness clause is not closed.** "Correctly flagging stale or sparse data when present" remains unobserved — the condition was never present to flag. The cheapest way to close it is the plan's own unused fallback probe (*"When was my data last synced, and how confident should I be in the last 4 weeks?"*, which targets `freshness.resources` and does not depend on window length), or a sparse-slice probe on a rarely-performed exercise where `coverage.insufficient_data` fires on its own terms. **Not** a longer window — `MAX_WEEKS = 52` makes that impossible.
2. **The deploy-script `--min` regression is now a two-time recurrence** and should be fixed before the next deploy rather than after the next connector test.

**Still open, unchanged:** 07-RESEARCH.md assumption A4 (whether the connector injects the server-supplied `instructions` string from 07-03) is recorded as *not determinable from this session* — separating it from the pasted custom instructions needs transcript-level introspection the tester was not asked to perform. D-06-10-A's three over-budget tools are explicitly not retuned here (T-07-60), and this UAT produced no evidence either way, since `fitness_compare_periods` was not among the tools exercised.

## Self-Check: PASSED

- `07-COACH-VERIFICATION.md` — FOUND (354 lines, ≥90 required)
- `07-10-SUMMARY.md` — FOUND
- Commit `a26b11a` (Task 1) — FOUND
- Commit `2791471` (Task 2) — FOUND
- `grep -c "human-verified"` on the record → **5** (≥1 required); every truth row carries the label
- Redaction grep `postgresql://|Bearer <long>|ep-<host>.` on both files → **0** (T-07-55)
- `uv run pytest backend/tests/test_coaching_doc.py -x -q` re-run at record time → `4 passed in 0.60s`

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

---
phase: 19-production-deploy-of-migration-0007
plan: 01
subsystem: infra
tags: [cloud-run, alembic, migration, mcp, deploy, authkit, oauth]

requires:
  - phase: 14-deploy-pipeline-migration-safety
    provides: "scripts/deploy-cloud-run.sh fetch-apply-verify pre-deploy block, app.db.migration_preflight.check_at_head, docs/runbook-deploy.md"
  - phase: 17-physique-analytics-and-mcp-read-write-tools
    provides: "fitness_log_physique_observation and fitness_get_latest_physique_observation MCP tools, LatestPhysiqueObservationResponse schema"
provides:
  - "Live production proof that the Phase 14 deploy-safety pipeline works: migration 0007_physique_observations applied to production Postgres via scripts/deploy-cloud-run.sh's own pre-deploy block, no manual psql/alembic"
  - "Cloud Run revision brett-00012-n6r serving 100% of production traffic, built from commit 4888aff52ff491279964dea68792f283e788713b"
  - "Redacted, durable evidence record (19-DEPLOY-RECORD.md) with pre-deploy state, verbatim deploy log, verbatim MCP smoke-test response, and a three-criterion PASS verdict"
  - "DEPLOY-05 closed in .planning/REQUIREMENTS.md (both edit sites)"
affects: [20-milestone-close, deploy-pipeline, mcp-server]

tech-stack:
  added: []
  patterns:
    - "Deploy-log ordering as combined proof: the pre-flight's own 'at head: [...]' stdout line, printed before any gcloud run deploy output, discharges both the 'migration applied' and 'alembic current == heads' criteria in one artifact — no separate post-deploy check needed"
    - "Independent two-source verification of a live deploy: the script's own log AND a live gcloud run services describe revision-name comparison, since a failed migration and a never-triggered deploy look identical in the Cloud Run console"

key-files:
  created:
    - .planning/phases/19-production-deploy-of-migration-0007/19-DEPLOY-RECORD.md
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Route A (live Claude connector over real authkit OAuth) used for the MCP smoke test, not the static-mode curl fallback — avoided two extra production redeploys and more literally satisfies 'a real call succeeds'"
  - "Treated the operator's empty zsh $PIPESTATUS capture as a shell-syntax artifact, not a failure signal, because the deploy log's own terminal success markers (at head: ['0007'], Done., 'serving 100 percent of traffic') plus an independent live gcloud revision/traffic check both corroborated success"
  - "STATE.md's carried deploy-migration blocker resolution is deferred to the orchestrator rather than edited by this worktree agent directly, per this execution's worktree-isolation constraint (orchestrator owns STATE.md/ROADMAP.md writes after the wave completes) — see 'Required STATE.md Update' section below for the exact text to apply"

requirements-completed: [DEPLOY-05]

duration: ~2h across two operator sessions (2026-09-14 to 2026-09-15; wall-clock includes two checkpoint:human-action waits for a real production deploy and a live OAuth-authenticated MCP call, not continuous agent execution time)
completed: 2026-09-15
---

# Phase 19 Plan 01: Production Deploy of Migration 0007 Summary

**Migration `0007_physique_observations` reached production Postgres through the unmodified Phase 14 deploy pipeline (`scripts/deploy-cloud-run.sh`), producing Cloud Run revision `brett-00012-n6r`, and a live `authkit`-OAuth-authenticated MCP tool call against that revision returned a schema-valid, empty-but-correct `LatestPhysiqueObservationResponse` — closing DEPLOY-05 with real production evidence, not test-fixture assertion.**

## Performance

- **Tasks:** 5/5 completed (2 `auto`, 2 `checkpoint:human-action`, 1 `auto`)
- **Files modified:** 2 (`19-DEPLOY-RECORD.md` created, `.planning/REQUIREMENTS.md` edited)
- **Commits:** 3 task commits (Task 2 and Task 4 were human-executed checkpoints with no agent-side commit)

## Accomplishments

- Ran every pre-deploy check this agent's sandbox permits (fast suite green — 684 passed, 11 skipped, 500 deselected; `0007` confirmed as sole local alembic head; both physique MCP tools confirmed registered in the commit about to deploy; pre-deploy production revision `brett-00011-n2z` recorded live) and wrote a pre-registered evidence-record skeleton before any deploy output existed.
- Handed the operator the exact `docs/runbook-deploy.md` Steps 3-5 procedure verbatim for the one step this agent's sandbox cannot perform (`gcloud secrets versions access`, blocked by the "Credential Materialization" classifier) — the operator ran the real deploy against production.
- Mechanically verified the returned deploy log: correct ordering (`DEPLOY-04: using Secret Manager ...` -> alembic `0006 -> 0007` -> `at head: ['0007']` on line 5 -> `gcloud run deploy` output starting line 6), zero abort strings, zero `BRETT_DATABASE_URL` override, zero DSN-shaped substrings — then independently confirmed via a live, non-secret `gcloud run services describe` call that revision `brett-00012-n6r` (different from the pre-deploy `brett-00011-n2z`) is serving 100% of traffic.
- Handed the operator the live-MCP-smoke-test procedure for the one step requiring a real OAuth-authenticated client (production runs `MCP_AUTH_MODE=authkit`); investigated and resolved a stale-connector false alarm along the way (see Issues Encountered); recorded the operator's PASS response (`data_available: true`, `observation: null`, non-empty `rating_scale`/`disclaimer`, no error) as the final proof.
- Closed DEPLOY-05 in `.planning/REQUIREMENTS.md` at both edit sites and wrote the full evidence chain (pre-deploy state, deploy log, smoke test, three-criterion PASS verdict) into `19-DEPLOY-RECORD.md`.

## Task Commits

Each `auto` task was committed atomically; the two `checkpoint:human-action` tasks (2 and 4) were operator-executed with no source-controlled artifact of their own beyond the evidence recorded in the following task.

1. **Task 1: Pre-deploy checklist and pre-registered evidence record** - `f35d1c1` (docs)
2. **Task 2: Operator runs the real production deploy** - operator-executed, no agent commit (human-action checkpoint)
3. **Task 3: Verify and record the deploy evidence** - `d69e14b` (docs)
4. **Task 4: Live MCP tool call against the deployed production service** - operator-executed, no agent commit (human-action checkpoint)
5. **Task 5: Record the smoke-test result and close DEPLOY-05** - `32032b5` (docs)

_Worktree note: per this execution's worktree-isolation constraints, `.planning/STATE.md` and `.planning/ROADMAP.md` were deliberately NOT modified by this agent — the orchestrator applies those updates centrally after the wave completes. See "Required STATE.md Update" below._

## Files Created/Modified

- `.planning/phases/19-production-deploy-of-migration-0007/19-DEPLOY-RECORD.md` - Created. Redacted, durable evidence record: pre-deploy state table, pre-registered method, verbatim deploy log with mechanical check table, verbatim MCP smoke-test response with mechanical check table, and a three-criterion PASS verdict table naming the deployed revision and commit.
- `.planning/REQUIREMENTS.md` - Modified. DEPLOY-05 checkbox `[ ]` -> `[x]` and traceability row `Planned` -> `Complete`. No other text changed (verified via `git diff` showing only these two lines).

## Decisions Made

- Used Route A (live Claude connector, real `authkit` OAuth) for the MCP smoke test rather than the `MCP_AUTH_MODE=static` fallback — avoids two extra production redeploys and the mandatory flip-back procedure, and more literally satisfies the success criterion's "a real call... succeeds" wording.
- Treated the deploy script's missing numeric exit code (an operator zsh-vs-bash `$PIPESTATUS` shell-syntax artifact) as non-blocking, since the deploy log's own terminal success markers and an independently-run live `gcloud run services describe` revision/traffic check both corroborated a successful deploy. This is recorded explicitly in `19-DEPLOY-RECORD.md` so it cannot be misread later as an ambiguous or failed run.
- Recorded the observed `EXPECTED_TOOLS` count as 22 rather than the plan's guidance-text estimate of 21 — the plan's inline documentation undercounted by one; this did not affect any blocking acceptance criterion (only "2 or more physique-tool matches in server.py" was required) and is noted in the record as an observed-vs-estimated discrepancy, not corrected in the plan itself (per the plan's own "writes zero application code" and read-only-artifact rules).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Investigated and resolved a stale-connector false alarm during Task 4**
- **Found during:** Task 4 (Live MCP tool call against the deployed production service)
- **Issue:** The operator's first `tools/call` attempt against the live connector reported `fitness_get_latest_physique_observation` as "doesn't exist" — indistinguishable at first glance from a genuine deploy defect (e.g., the new revision not actually serving the physique tools).
- **Fix:** Rather than assuming either a real regression or a transient glitch, grepped `backend/app/mcp/server.py` directly and confirmed both `fitness_get_latest_physique_observation` (lines 262-267) and `fitness_log_physique_observation` (lines 332-334) are unconditionally registered with no feature flag — this is the code live on deployed revision `brett-00012-n6r`. Concluded the operator's Claude connector held a stale `tools/list` cached from before the new revision went live. The operator reconnected the BRETT connector (forcing fresh tool discovery) and retried successfully.
- **Files modified:** None (investigation only; finding recorded in `19-DEPLOY-RECORD.md`'s "MCP smoke test" section as a paper trail, not omitted because it resolved cleanly).
- **Verification:** The retry produced the expected PASS response; the code-level grep result is quoted verbatim in the deploy record.
- **Committed in:** `32032b5` (Task 5 commit, which recorded the finding)

**2. [Rule 3 - Blocking] Deferred `.planning/STATE.md` blocker-resolution edit to the orchestrator**
- **Found during:** Task 5 (Record the smoke-test result and close DEPLOY-05)
- **Issue:** The plan's Task 5 Step D instructs this agent to edit `.planning/STATE.md` directly (rewrite the carried deploy-migration blocker's status marker and update `## Current Position`). This execution runs in a git worktree under an explicit constraint: "Do NOT modify STATE.md or ROADMAP.md — the orchestrator owns those writes after all worktree agents in the wave complete."
- **Fix:** Skipped the STATE.md edit entirely rather than violating the worktree-isolation constraint. The exact required edit is specified below for the orchestrator to apply centrally.
- **Files modified:** None (`.planning/STATE.md` untouched by this agent).
- **Verification:** `git status --porcelain` confirms only `19-DEPLOY-RECORD.md` and `.planning/REQUIREMENTS.md` were modified across all three `auto` task commits; `.planning/STATE.md` does not appear in any diff.
- **Committed in:** N/A (a non-edit; documented here and in the Task 5 commit message)

---

**Total deviations:** 2 auto-fixed (2 blocking — one an investigation/false-alarm resolution, one a deferred-write scope correction)
**Impact on plan:** No scope creep; both were necessary to complete the plan correctly under this execution's actual constraints (worktree isolation) and to avoid mis-recording a false alarm as either a silent success or an unexplained retry.

## Required STATE.md Update (Deferred to Orchestrator)

Per the plan's Task 5 Step D, `.planning/STATE.md` needs the following edits, which this worktree
agent deliberately did not make:

1. In `### Blockers/Concerns`, the bullet currently opening `**Open (highest priority, 3
   occurrences in v2.0):** \`scripts/deploy-cloud-run.sh\` has no migration step...` should have
   its opening marker rewritten to `**Resolved (Phase 14 built the fix; Phase 19 proved it in
   production on 2026-09-15):**`, keeping the three-incident history sentence intact, and its
   closing sentence (currently "The structural fix ... is **still not done** and should lead the
   next milestone.") replaced with a sentence naming: deployed revision `brett-00012-n6r`,
   migration `0007` as the first migration to reach production through the fixed pipeline, and
   `.planning/phases/19-production-deploy-of-migration-0007/19-DEPLOY-RECORD.md` as the evidence.
2. `## Current Position`: `Plan:` and `Status:` updated to reflect Phase 19 / plan 19-01 complete;
   `Last activity:` set to 2026-09-15 with a one-line summary (e.g., "Phase 19 complete — migration
   0007 deployed to production via the fixed pipeline, DEPLOY-05 closed").
3. `## Session Continuity` `Resume:` should point at the milestone-close step (`/gsd-close-milestone`
   or equivalent) — Phase 19 is v2.1's sixth and final phase; milestone close is out of this plan's
   scope.

## Issues Encountered

- Stale MCP connector cache during Task 4's smoke test — see Deviations #1 above. Resolved by
  reconnecting the connector; root-caused via direct code inspection rather than assumed.
- Operator's deploy-capture command used bash `${PIPESTATUS[0]}` syntax in a zsh shell, so no
  numeric exit code was captured for the deploy script. Resolved by treating the log's own
  terminal success markers plus an independent live `gcloud run services describe` check as
  sufficient corroborating evidence — documented explicitly in `19-DEPLOY-RECORD.md` so this
  is never misread later as an ambiguous or failed run.

## User Setup Required

None — no external service configuration required. The production deploy and MCP smoke test were
both real operator actions already completed as part of this plan's checkpoints, not follow-up
setup work.

## Next Phase Readiness

- DEPLOY-05 is closed with real production evidence; the three-occurrence v2.0 deploy-migration
  drift class of bug is now closed by a real production run, not a test fixture.
- Phase 19 is v2.1's sixth and final phase. The only remaining STATE.md work is the deferred
  blocker-resolution edit listed above, which the orchestrator should apply before or during
  milestone close.
- No blockers for milestone close. `scripts/deploy-cloud-run.sh`, `backend/app/db/migration_preflight.py`,
  `backend/migrations/versions/0007_physique_observations.py`, `deploy/cloud-run.env.yaml`, and every
  file under `docs/` remain byte-identical to their pre-phase state (`git diff --quiet scripts/
  backend/ deploy/ docs/` exits 0 after all three `auto` task commits).

---
*Phase: 19-production-deploy-of-migration-0007*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: `.planning/phases/19-production-deploy-of-migration-0007/19-DEPLOY-RECORD.md`
- FOUND: `.planning/phases/19-production-deploy-of-migration-0007/19-01-SUMMARY.md`
- FOUND: `.planning/REQUIREMENTS.md`
- FOUND commit: `f35d1c1` (Task 1)
- FOUND commit: `d69e14b` (Task 3)
- FOUND commit: `32032b5` (Task 5)

---
phase: 07-production-hardening-coaching-layer
plan: 04
subsystem: infra
tags: [gcloud, cloud-run-jobs, cloud-scheduler, secret-manager, bash, pytest, yaml]

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike
    provides: "scripts/deploy-cloud-run.sh, deploy/cloud-run.env.yaml, the brett-run@ runtime service account, and backend/tests/test_cloud_run_deploy.py — the deploy-artifact conventions and drift-guard shape this plan mirrors for the second workload"
  - phase: 03-hevy-integration-normalization
    provides: "backend/app/cli.py sync-hevy, and the idempotent checkpoint-resumable HevySyncService (HEVY-08/09) that makes a retried job execution safe"
provides:
  - "scripts/deploy-sync-job.sh — the single reproducible description of how the Hevy sync runs in production (D-10)"
  - "scripts/create-sync-schedule.sh — a re-runnable create-or-update Cloud Scheduler trigger firing the job every six hours in Asia/Jakarta"
  - "deploy/sync-job.env.yaml — the job's complete non-secret runtime environment, carrying PYTHONPATH that the service must not have"
  - "backend/tests/test_sync_job_deploy.py — nine fast-suite assertions pinning both scripts and the env file against Settings"
  - "A README that describes the real production schedule instead of denying one exists"
affects: [07-07-live-deploy, 07-10-staleness-uat, data-freshness, coaching-layer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deploy artifacts are checked-in shell scripts pinned by static pytest assertions, never runbook prose"
    - "One --env-vars-file per Cloud Run workload, never shared: the flag replaces the target's entire environment"
    - "Cloud Run Jobs are triggered by a Cloud Scheduler HTTP job hitting the Run Admin API :run endpoint with an OAuth token, not by an in-process scheduler"

key-files:
  created:
    - scripts/deploy-sync-job.sh
    - scripts/create-sync-schedule.sh
    - deploy/sync-job.env.yaml
    - backend/tests/test_sync_job_deploy.py
  modified:
    - README.md

key-decisions:
  - "The job gets its own deploy/sync-job.env.yaml rather than sharing the service's file: --env-vars-file replaces the target's ENTIRE environment, so two workloads cannot share one file and differ by a single key"
  - "PYTHONPATH=backend is allowlisted as a runtime var in the drift guard rather than added to Settings: the interpreter consumes it before Settings is ever constructed"
  - "MCP_AUTH_SECRET is deliberately not bound to the job, and the binding set is asserted EXACTLY rather than as a subset, so a compromised sync task cannot read the connector credential (T-07-19)"
  - "The forbidden instance-scaling flags are matched as --min= and --max= with the equals sign: a bare --max substring would also match the job's required --max-retries"
  - "The drift guard's RED gate was discharged by mutation rather than by a failing first run — the artifacts it guards land in tasks 1-2 of this same plan, so it is green on arrival"

patterns-established:
  - "Drift-guard test modules duplicate their helpers rather than importing across test modules, following test_cloud_run_deploy.py's stated precedent"
  - "Secret-binding assertion messages never interpolate the offending value, so a pasted credential cannot reach CI output"
  - "Explanatory comments in a deploy script must avoid naming flags the guard asserts absent — the guard reads whole file text, comments included"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 18min
completed: 2026-09-01
---

# Phase 7 Plan 04: Production Hevy Sync Scheduling Summary

**A Cloud Run Job running `python -m app.cli sync-hevy` on a 6-hourly Asia/Jakarta Cloud Scheduler trigger, with `HEVY_API_KEY` and `DATABASE_URL` bound from Secret Manager and nine fast-suite assertions pinning every flag.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-09-01T15:04Z
- **Completed:** 2026-09-01T15:22Z
- **Tasks:** 3
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments

- `scripts/deploy-sync-job.sh` deploys `brett-sync-hevy` as a Cloud Run Job, overriding the buildpack's `web` entrypoint with `--command=python --args=-m,app.cli,sync-hevy`. It binds exactly two Secret Manager references and nothing else, and `:?`-guards `BRETT_GCP_PROJECT` so it can never inherit a stray `gcloud config get-value project` (T-07-22).
- `scripts/create-sync-schedule.sh` creates or updates a Cloud Scheduler HTTP job that POSTs to the Run Admin API's `:run` endpoint as `brett-run@` over OAuth. A `describe` probe picks `create` vs `update`, so re-running it is not an error.
- `deploy/sync-job.env.yaml` is a deliberate second env file rather than a shared one, carrying the `PYTHONPATH=backend` the job needs and the service must not have.
- `backend/tests/test_sync_job_deploy.py` pins all three artifacts with nine assertions, and was verified by mutation: eleven separate perturbations were each confirmed to fail the expected test before being reverted.
- `README.md` line 75 claimed "Production scheduling is Phase 7 — nothing here runs the sync on a timer." It now describes the real job, the real cadence, and both scripts by name.

## Task Commits

1. **Task 1: deploy/sync-job.env.yaml and scripts/deploy-sync-job.sh** — `d865318` (feat)
2. **Task 2: scripts/create-sync-schedule.sh and README correction** — `99e61c4` (feat)
3. **Task 3: backend/tests/test_sync_job_deploy.py** — `4cb8e5b` (test)

## Files Created/Modified

- `scripts/deploy-sync-job.sh` (created, 0755) — `gcloud run jobs deploy` for `brett-sync-hevy`: `--tasks=1`, `--max-retries=1`, `--task-timeout=1800s`, `--memory=512Mi`, the job env file, and `--set-secrets="DATABASE_URL=brett-database-url:latest,HEVY_API_KEY=brett-hevy-api-key:latest"`.
- `scripts/create-sync-schedule.sh` (created, 0755) — create-or-update `brett-sync-hevy-6h`, cron `0 */6 * * *`, time zone `Asia/Jakarta`, `--attempt-deadline=60s`, OAuth as `brett-run@`.
- `deploy/sync-job.env.yaml` (created) — exactly `ENVIRONMENT`, `LOG_LEVEL`, `PYTHONPATH`.
- `backend/tests/test_sync_job_deploy.py` (created, 363 lines) — the nine-assertion drift guard.
- `README.md` (modified, 1 sentence replaced by 5 lines) — the CLI section's production-scheduling claim.

## Decisions Made

- **Separate env file per workload.** `--env-vars-file` replaces the target's entire environment, so the service and the job cannot share one file and differ by one key. Both files carry a comment saying so, because the temptation to consolidate them is obvious and the failure mode is not.
- **`--attempt-deadline=60s` is deliberate and commented.** It bounds the `:run` API call that *starts* the execution, not the sync. Cloud Run Jobs return as soon as the execution is created; the job's own `--task-timeout=1800s` bounds the work. Setting the deadline to the sync's expected duration would be a category error, so the script says that out loud.
- **`--max-retries=1`, not more.** The sync is idempotent and checkpoint-resumable, so a retry is safe — but a high retry count on a 6-hourly schedule can stack executions, and the next scheduled run is only hours away.
- **The binding set is asserted exactly, not as a subset.** A subset check would let someone add `MCP_AUTH_SECRET` to the job without failing anything. T-07-19 is only real if the assertion is exact.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Explanatory comments named the flags the guard asserts absent**

- **Found during:** Task 1 (deploy script), caught by running Task 1's own acceptance greps before committing
- **Issue:** The plan's `<action>` prose said "Do NOT pass `--allow-unauthenticated`, `--set-env-vars`, `--add-cloudsql-instances`, `--vpc-connector`" and "Do NOT bind `MCP_AUTH_SECRET`". Written as script comments — which is the natural way to preserve that reasoning for a future reader — those strings landed in the file body. Task 3's guard (and `test_cloud_run_deploy.py`'s precedent, which it mirrors) does a plain `flag not in script` substring check over the whole file, comments included. The script would have failed its own guard. The same trap caught a second string: the header sentence "the MCP service deploys with `--min=0` by default" contains `--min=`.
- **Fix:** Reworded both comment blocks to describe the omitted flags by role rather than by name ("the service-only public-ingress flag", "the inline environment flag", "a minimum instance count of zero"). The reasoning is preserved; the literal strings are gone.
- **Files modified:** `scripts/deploy-sync-job.sh`
- **Verification:** `grep -c -- '--min=\|--max=\|--allow-unauthenticated\|--set-env-vars\|--add-cloudsql-instances\|--vpc-connector\|MCP_AUTH_SECRET' scripts/deploy-sync-job.sh` returns `0`; all nine Task 3 tests pass.
- **Committed in:** `d865318` (Task 1 commit)

**2. [Rule 2 - Missing Critical] Guard the `app.cli` entrypoint override explicitly**

- **Found during:** Task 3
- **Issue:** The plan's `<behavior>` for `test_job_script_carries_every_required_flag` listed `--args` as a bare flag-presence check. Presence of `--args` alone does not pin *what* it passes, yet the plan frontmatter's `key_links` requires `scripts/deploy-sync-job.sh` → `backend/app/cli.py` via pattern `app\.cli`. A future edit could change the args payload and drop the link without failing anything.
- **Fix:** Added a `_JOB_COMMAND_ARGS = "--args=-m,app.cli,sync-hevy"` constant and an assertion inside the same test, with a message naming the consequence — the job would start uvicorn and serve HTTP nobody calls instead of syncing.
- **Files modified:** `backend/tests/test_sync_job_deploy.py`
- **Verification:** Mutation case "entrypoint override dropped" removes the `--args` line and was confirmed to fail this test.
- **Committed in:** `4cb8e5b` (Task 3 commit)

**3. [Rule 2 - Missing Critical] `--min`/`--max` scaling guard needed the `=` to avoid contradicting `--max-retries`**

- **Found during:** Task 3
- **Issue:** The plan's `<behavior>` asked that `--min`/`--max` be absent, while its `_REQUIRED_JOB_FLAGS` constant requires `--max-retries`. A literal `"--max" not in script` check would fail on the required flag — the two halves of the spec contradict each other as written.
- **Fix:** Matched `--min=` and `--max=` with the equals sign, in a `_FORBIDDEN_SCALING_FLAGS` constant carrying a comment explaining exactly why the `=` is load-bearing.
- **Files modified:** `backend/tests/test_sync_job_deploy.py`
- **Verification:** All nine tests pass with `--max-retries="$MAX_RETRIES"` present in the script.
- **Committed in:** `4cb8e5b` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 missing critical)
**Impact on plan:** All three were internal-consistency repairs between the plan's own artifacts and its own guard. No scope change; every acceptance criterion in the plan still holds, and two of the three make the guard strictly stronger than specified.

## Issues Encountered

- **`uv run` created a fresh worktree `.venv` without the dev group.** `[tool.uv] default-groups = []` (deliberate — it keeps 32 dev packages out of the production image), so `pyyaml` was absent and the Task 1 YAML verification failed with `ModuleNotFoundError: No module named 'yaml'`. Resolved with `uv sync --group dev`, which is the documented local install. Not a code problem; recorded because it will recur in every fresh worktree.
- **The TDD RED gate could not fire naturally.** Task 3 is a drift guard over artifacts that Tasks 1 and 2 of this same plan commit, so its first run was green by construction. Rather than skip the gate, its intent was discharged by mutation: a scratchpad harness perturbed one guarded property at a time (a pasted `HEVY_API_KEY` in the env file, a secret literal on the right-hand side of `--set-secrets`, an extra `MCP_AUTH_SECRET` binding, a removed `DATABASE_URL` binding, a dropped `--args`, an added `--set-env-vars`, a non-string env value, an unknown env key, a renamed job in the scheduler, a daily cron, a UTC time zone), ran the module, and asserted the expected test id appeared in the failure output. All 11 were caught; every artifact was restored from a scratchpad backup and `git diff` confirmed clean before committing. See "TDD Gate Compliance" below.

## TDD Gate Compliance

Task 3 carried `tdd="true"`. The gate sequence in git log is `test(07-04): pin sync job deploy artifacts...` (`4cb8e5b`) with no separate GREEN commit, because the implementation it guards is Tasks 1 and 2 of the same plan (`d865318`, `99e61c4`) — the plan deliberately sequences artifacts before guard.

A conventional RED run was therefore impossible: the tests pass on first execution. Per the fail-fast rule ("if a test passes unexpectedly during RED, STOP and investigate"), the cause was investigated and is structural rather than a defect. The gate's actual purpose — proving the assertions can fail — was satisfied by the 11-case mutation check described above, which is a stronger signal for a drift guard than a single RED run would have been.

## Verification Results

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_sync_job_deploy.py -x -q` | 9 passed |
| `uv run pytest backend/tests/test_sync_job_deploy.py -x -q -m "not integration"` | 9 passed (same 9 — no integration marker) |
| `uv run pytest backend/tests -x -q -m "not integration"` | 386 passed, 274 deselected |
| `uv run ruff check .` | All checks passed |
| `bash -n scripts/deploy-sync-job.sh` / `create-sync-schedule.sh` | Both parse |
| `test -x` on both scripts | Both 0755 |
| `grep -c "Production scheduling is Phase 7" README.md` | 0 |
| Mutation check (11 perturbations) | 11/11 caught, artifacts restored |

## User Setup Required

None from this plan directly — it writes and tests artifacts only, it does not run them.

Two one-time Google Cloud prerequisites must exist before `scripts/deploy-sync-job.sh` can succeed, and **plan 07-07 owns both**. Each is stated in the relevant script's header comment so the requirement travels with the artifact:

1. Secret Manager secret `brett-hevy-api-key` must exist, with `roles/secretmanager.secretAccessor` granted to `brett-run@`. Only `brett-database-url` and `brett-mcp-auth-secret` existed as of the Phase 2 deploy (T-07-23, accepted). A premature deploy fails loudly at instance start rather than silently.
2. `cloudscheduler.googleapis.com` must be enabled and `brett-run@` must hold `roles/run.invoker` on the job specifically, not project-wide.

## Requirements: DEPLOY-03 deliberately NOT ticked in REQUIREMENTS.md

The `requirements-completed` field above copies this plan's frontmatter mechanically, but the
REQUIREMENTS.md checkbox was **left unchecked on purpose** and the orchestrator should decide
when to tick it. Two reasons:

1. **The requirement is phase-spanning, not plan-scoped.** Eight of the ten plans in this phase
   (07-01, 02, 04, 05, 06, 07, 08, 09) declare `requirements: [DEPLOY-03]`. Ticking it here
   would assert that seven sibling plans' work is already done.
2. **The requirement's text does not describe this plan.** DEPLOY-03 reads "System includes
   automated tests covering Hevy sync (auth, pagination, incremental events, duplicate
   prevention, deletions, failures), analytics calculations against known workouts, and MCP tool
   schemas/auth/output structure." This plan built production sync *scheduling*. It contributes
   nine tests to the phase's coverage story; it does not satisfy that sentence.

There is also a mechanical reason: with eight parallel worktree agents all holding the same
requirement ID, a concurrent write to the same checkbox is a guaranteed merge conflict on
merge-back. REQUIREMENTS.md is effectively a shared orchestrator artifact for this phase.

## Next Phase Readiness

- **Ready for plan 07-07** (live deploy), which creates the two prerequisites above and runs both scripts against the real project. Every value 07-07 needs is a default in the scripts; no argument has to be reconstructed from this summary.
- **Unblocks plan 07-10's staleness UAT.** Before this plan, that UAT could have passed for an accidental reason — a sync the user happened to have run by hand. A real timer now backs it.
- **No blockers.** The one open dependency (`brett-hevy-api-key`) was scoped out by the plan itself and is explicitly documented in the script that consumes it.

## Self-Check: PASSED

All five claimed artifacts exist on disk with the claimed modes (`scripts/deploy-sync-job.sh` and `scripts/create-sync-schedule.sh` are `0755`), and all three claimed commit hashes resolve in `git log`:

- `d865318` — `feat(07-04): add Cloud Run Job deploy script and job env file for Hevy sync`
- `99e61c4` — `feat(07-04): add Cloud Scheduler trigger script and correct README scheduling claim`
- `4cb8e5b` — `test(07-04): pin sync job deploy artifacts with a Settings drift guard`

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

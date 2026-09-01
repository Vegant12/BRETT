---
phase: 07-production-hardening-coaching-layer
plan: 07
subsystem: infra
tags: [gcloud, cloud-run-jobs, cloud-scheduler, secret-manager, alembic, buildpacks, neon, hevy]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-04's scripts/deploy-sync-job.sh, scripts/create-sync-schedule.sh, deploy/sync-job.env.yaml and backend/tests/test_sync_job_deploy.py — the artifacts this plan ran for the first time"
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-06's redeployed Cloud Run service and verified MCP tool set — the deployment this sync feeds with data"
  - phase: 02-deploy-connector-auth-spike
    provides: "the brett-run@ runtime service account, the brett-database-url and brett-mcp-auth-secret secrets, and the Neon direct/unpooled endpoint"
  - phase: 03-hevy-integration-normalization
    provides: "backend/app/cli.py sync-hevy and the idempotent checkpoint-resumable HevySyncService (HEVY-08/09)"
provides:
  - "Secret Manager secret brett-hevy-api-key with one enabled version, readable only by brett-run@ and only on that secret"
  - "Live Cloud Run Job brett-sync-hevy with two proven-successful executions against real data"
  - "Live Cloud Scheduler job brett-sync-hevy-6h firing every six hours in Asia/Jakarta, proven able to invoke the job"
  - "A production database at alembic head (0004) — eight tables that had never existed in production"
  - "docs/runbook-sync-schedule.md — the D-10 runbook with 9 verified rows, the migration story and the honest limitations"
  - "A corrected scripts/deploy-sync-job.sh that actually works against the real gcloud API"
affects: [07-10-staleness-uat, data-freshness, coaching-layer, deployment-runbooks]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A Cloud Native Buildpacks image must be entered through /cnb/lifecycle/launcher; --command names the launcher and --args carries the full argv including the interpreter"
    - "Production schema state is verified with `alembic current` against `alembic heads` before trusting a deployment against real data"
    - "Cloud Run Job success is read from status.succeededCount, never from application log signatures"

key-files:
  created:
    - docs/runbook-sync-schedule.md
    - .planning/phases/07-production-hardening-coaching-layer/deferred-items.md
  modified:
    - scripts/deploy-sync-job.sh
    - backend/tests/test_sync_job_deploy.py

key-decisions:
  - "Applied alembic 0003 and 0004 to the live production database — explicitly authorized by the user through the orchestrator after the failure was diagnosed, not assumed. Both revisions are additive-only (eight create_table calls, zero drops/alters, no change to the existing users table), which is what made it an acceptable action"
  - "Ran the migration against the direct/unpooled Neon endpoint already stored in brett-database-url, per Neon's guidance that migrations must not run through the pooler (02-DEPLOY-LOG.md documents the stored DSN as the direct one)"
  - "Recorded verification row 3 as PASS-with-note rather than silently matching the plan's predicted command/args shape: the deployed shape is the corrected CNB-launcher form, and the discrepancy is stated in the runbook"
  - "Did NOT fix backend/app/cli.py's misleading failure logging, despite discovering it here — it is out of this plan's file scope. Logged to deferred-items.md with the proposed fix instead"
  - "Dropped --set-build-env-vars from the job deploy rather than seeking an equivalent: gcloud run jobs deploy has no such flag, and [tool.uv] default-groups = [] already does the work that mattered"

patterns-established:
  - "Verification tables record what was actually observed, including when the observation contradicts the plan's prediction — a corrected shape is a PASS with a note, never a silent match"
  - "Credential absence in logs is proven by counting the literal secret value programmatically and printing only the count, never the value"
  - "A production DSN is scoped to a single command via inline assignment rather than exported, and alembic.ini pins logger_sqlalchemy to WARNING so no connection string reaches output"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 1h 12m
completed: 2026-09-01
---

# Phase 7 Plan 7: Production Hevy Sync Scheduling Summary

**A six-hourly Cloud Scheduler trigger driving a Cloud Run Job that syncs 327 workouts, 463 exercise templates and 125 body measurements from Hevy into production Postgres — reached only after discovering and repairing two years' worth of never-applied schema migrations and two defects in a deploy script that had never been run.**

## Performance

- **Duration:** 1h 12m
- **Started:** 2026-09-01T10:20:51Z
- **Completed:** 2026-09-01T11:33:06Z
- **Tasks:** 4 of 4
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **`brett-hevy-api-key` created in Secret Manager** with one enabled version, piped from the developer's gitignored `.env` through `--data-file=-` so the value never reached a terminal, a file, a shell history entry or the process table. `roles/secretmanager.secretAccessor` is bound on that individual secret for `brett-run@` — not project-wide — and the same was re-verified for the other two secrets, confirming 07-RESEARCH.md assumption A1 rather than relying on it.
- **Cloud Run Job `brett-sync-hevy` deployed and proven.** Execution `brett-sync-hevy-m8w2v` reported `succeededCount 1` and logged real work: 33 pages of workouts (`upserted=327 skipped=0`), 13 pages of body measurements (`rows=125`), `hevy_sync_all_completed mode=full workouts=327 templates=463 body=125`. The workout and template counts match `docs/hevy-api-observations.md` exactly.
- **Cloud Scheduler job `brett-sync-hevy-6h` is live and demonstrably wired.** Cron `0 */6 * * *`, `Asia/Jakarta`, `POST` to the Run Admin API `:run` endpoint as `brett-run@`, state `ENABLED`. A forced run produced a genuinely new execution (`brett-sync-hevy-6vl4w`) with `succeededCount 1`, which is what proves `roles/run.invoker` actually works rather than merely being bound.
- **Idempotency observed, not just argued.** The scheduler-triggered run logged `mode=incremental workouts=0` — the `sync_state` checkpoint doing its job, over the very table whose absence had killed the first two executions. Cloud Scheduler's at-least-once delivery is therefore a measured non-issue.
- **Production database brought to alembic head**, closing a drift that had gone undetected since Phase 2.
- **`docs/runbook-sync-schedule.md` written** — 336 lines, all 9 verification rows carrying real observed values and explicit verdicts, plus procedures, the migration story and six honest limitations. Zero DSN or credential matches.

## Task Commits

1. **Task 1: Confirm credentials** — no commit (checkpoint; `BRETT_GCP_PROJECT=brett-fitness`, account `hovegant12@gmail.com`, `.env` grep returned 1)
2. **Task 2: Create secret, grant accessor, enable Scheduler** — `bd96b12` (feat)
3. **Task 3: Deploy the job and prove one execution succeeds** — `27fd7b8` (fix, script corrections), `7c0accc` (docs, deferred items), `b8d227c` (fix, migration + first successful execution)
4. **Task 4: Create the schedule and write the runbook** — `f979a77` (feat), `4fdef8d` (docs, UV_FROZEN cross-reference)

**Plan metadata:** `<this commit>` (docs: complete plan)

## Files Created/Modified

- `docs/runbook-sync-schedule.md` — the D-10 runbook: what runs and when, five preconditions, the two one-time setup procedures (secret creation, schema migration), four operating procedures, the 9-row verification record, and six known limitations
- `.planning/phases/07-production-hardening-coaching-layer/deferred-items.md` — two out-of-scope discoveries logged rather than fixed
- `scripts/deploy-sync-job.sh` — two defects fixed, each with a comment explaining the failure mode so it is not reintroduced
- `backend/tests/test_sync_job_deploy.py` — `_JOB_COMMAND_ARGS` updated and a new `_JOB_COMMAND` assertion pinning the CNB launcher

## Decisions Made

- **Applying migrations to production was escalated, not assumed.** The `UndefinedTableError` was diagnosed, the blast radius was established (additive-only), and the plan stopped and returned a checkpoint. Execution resumed only after the user explicitly authorized the migration through the orchestrator. This is the correct handling of a Rule 4 architectural/production-mutation decision.
- **The migration ran against the direct/unpooled Neon endpoint** already stored in `brett-database-url`. This was checked against `02-DEPLOY-LOG.md` rather than presumed — the stored DSN carries no `-pooler` suffix precisely because Phase 2 anticipated migrations.
- **Verification row 3 is a PASS with an explicit note.** The plan predicted `command=python`; the deployed job has `command=/cnb/lifecycle/launcher, args=[python,-m,app.cli,sync-hevy]`. The effective command line is identical, but the runbook states the discrepancy rather than quietly matching the prediction.
- **`backend/app/cli.py` was left alone.** The misleading-log-signal bug is real and was discovered here, but `cli.py` is not in this plan's file scope. It is logged with a proposed fix in `deferred-items.md`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `--set-build-env-vars` is not a valid flag for `gcloud run jobs deploy`**
- **Found during:** Task 3 (first run of `scripts/deploy-sync-job.sh`)
- **Issue:** Plan 07-04 wrote the script by analogy with `scripts/deploy-cloud-run.sh`, which deploys a *service*. `gcloud run deploy` accepts `--set-build-env-vars`; `gcloud run jobs deploy` does not, on either the GA or beta track in SDK 578.0.0. The command failed at argument parsing before reaching the build.
- **Fix:** Removed the flag. Nothing load-bearing is lost — `[tool.uv] default-groups = []` in `pyproject.toml` is what actually keeps the 32 dev packages out of the image. Only `UV_FROZEN`'s fail-on-drifted-lockfile guarantee is unavailable for the job build, and that is now written into the runbook's Known limitations.
- **Files modified:** `scripts/deploy-sync-job.sh`
- **Verification:** `gcloud run jobs deploy` completed; `backend/tests/test_sync_job_deploy.py` 9/9 green
- **Committed in:** `27fd7b8`

**2. [Rule 1 - Bug] `--command=python` bypassed the buildpack entrypoint**
- **Found during:** Task 3 (execution `brett-sync-hevy-rmrb5`)
- **Issue:** A Cloud Native Buildpacks image must be entered through `/cnb/lifecycle/launcher`, which applies `PATH`, the uv virtualenv at `/layers/google.python.uv/uv-dependencies/.venv` and the layer environment. Naming a bare interpreter as `--command` *replaces* the launcher, so none of that is applied. Cloud Run reported only `Application exec likely failed` with no application output — a message naming neither the interpreter nor the cause.
- **Fix:** `--command=/cnb/lifecycle/launcher --args=python,-m,app.cli,sync-hevy`. Added a `_JOB_COMMAND` assertion to the drift guard so it cannot regress, with a comment recording the failure mode.
- **Files modified:** `scripts/deploy-sync-job.sh`, `backend/tests/test_sync_job_deploy.py`
- **Verification:** Control-plane read-back confirms the shape; execution reached the database on the next run
- **Committed in:** `27fd7b8`

**3. [Rule 4 - Architectural, ESCALATED AND AUTHORIZED] Production database was two revisions behind head**
- **Found during:** Task 3 (executions `brett-sync-hevy-rmrb5` and `brett-sync-hevy-xv7jv`)
- **Issue:** After the two script fixes the job reached the database and died with `sqlalchemy.exc.ProgrammingError: <asyncpg.exceptions.UndefinedTableError>: relation "sync_state" does not exist`. Production sat at alembic `0002` from the Phase 2 deploy while the code had advanced to `0004`. Revisions `0003` and `0004` — creating `workouts`, `workout_exercises`, `workout_sets`, `exercise_templates`, `exercise_muscles`, `exercise_muscle_overrides`, `body_measurements` and `sync_state` — had never been applied to production. The plan did not anticipate this and had no task for it.
- **Why it was escalated rather than auto-fixed:** Mutating a live production database schema is outside Rules 1-3 regardless of how safe the change looks. Execution stopped and returned a checkpoint.
- **Authorization:** The user explicitly authorized the migration through the orchestrator before any DDL ran.
- **Blast radius established before acting:** Both `upgrade()` functions are purely additive — eight `create_table` calls plus indexes, zero `drop_table`, zero `alter_column`, zero `op.execute`, and no change to the existing `users` table. Every `drop_table` in those files sits in `downgrade()`, which was not run.
- **Fix:** `DATABASE_URL="$(gcloud secrets versions access latest --secret=brett-database-url …)" uv run alembic upgrade head`, run from the developer machine against the direct/unpooled Neon endpoint. `alembic current`: `0002` → `0004 (head)`.
- **Credential handling:** The DSN was never echoed, printed or logged. `alembic.ini` pins `logger_sqlalchemy` to `WARNING` and carries no `sqlalchemy.url` key (`migrations/env.py` injects it at runtime), and `DATABASE_URL` was scoped to the single command rather than exported.
- **Verification:** `alembic current` returns `0004 (head)`; the next execution succeeded and read `sync_state` correctly
- **Committed in:** `b8d227c`

**4. [Rule 2 - Missing Critical] The plan's own success check was a false positive**
- **Found during:** Task 3 (verification step 6)
- **Issue:** The plan instructs verifying success by finding `hevy_cli_started` + `hevy_cli_stopped` with no `hevy_cli_failed`. `backend/app/cli.py`'s `_run_sync` catches only `HevyError` and `RuntimeError`; any other exception propagates uncaught while the `finally` block still logs `hevy_cli_stopped`. A failed run therefore produces **exactly** the log signature a successful run produces. Execution `xv7jv` proves it: `started=2 stopped=2 failed=0`, and it exited 1 twice.
- **Fix:** Verified success with `status.succeededCount` instead — the authoritative signal — for every row that claims a successful run. The caveat, the measured comparison table across all four executions, and a proposed `cli.py` fix are written into the runbook and `deferred-items.md`. `cli.py` itself was not modified: out of scope.
- **Files modified:** `docs/runbook-sync-schedule.md`, `deferred-items.md`
- **Verification:** Row 5 of the runbook is explicitly labelled necessary-but-not-sufficient
- **Committed in:** `7c0accc`, `b8d227c`

**5. [Rule 1 - Bug] Dangling cross-reference in `scripts/deploy-sync-job.sh`**
- **Found during:** Task 4 (post-commit review)
- **Issue:** The comment explaining the dropped `--set-build-env-vars` said "see docs/runbook-sync-schedule.md", but the runbook did not mention `UV_FROZEN` anywhere.
- **Fix:** Added the limitation to the runbook's Known limitations section.
- **Files modified:** `docs/runbook-sync-schedule.md`
- **Verification:** The referenced content now exists
- **Committed in:** `4fdef8d`

---

**Total deviations:** 4 auto-fixed (2 bugs, 1 blocking, 1 missing-critical) + 1 escalated and user-authorized (production migration).

**Impact on plan:** All four auto-fixes were required to complete the plan at all — the job could not deploy, then could not start, then could not read its tables, and the plan's own success criterion could not be trusted. No scope creep: the one file that was tempting to fix (`backend/app/cli.py`) was deliberately left alone and logged instead. The migration was the single largest deviation and the only one requiring authorization; it was obtained explicitly.

## Issues Encountered

- **Three failed executions before the first success**, each with a distinct cause: an invalid gcloud flag (never built), a bypassed buildpack entrypoint (never started), and a stale schema (started, connected, died on first query). Each was diagnosed from the control plane and logs rather than by guessing, and each fix is now pinned by a test or written into the runbook.
- **The failure modes were unusually opaque.** `Application exec likely failed` names neither the interpreter nor the cause, and the misleading log signature actively suggested success. Both are recorded so the next operator does not spend the same time on them.
- **Schema drift was invisible to every existing health signal.** `/health` probes `SELECT 1`, which succeeds against any schema, and plan 07-06's MCP round trip confirmed the tool set without exercising data flow. This is logged in `deferred-items.md` as worth a standing `alembic current` vs `heads` check.

## User Setup Required

None — no `user_setup` block in this plan's frontmatter. The one human input (the Hevy API key in the gitignored repo-root `.env`) was consumed by Task 1's checkpoint and is now in Secret Manager.

## Next Phase Readiness

- **Ready for 07-10's staleness UAT.** `freshness.resources.workouts` will now advance on a real schedule instead of only when someone remembers to run the CLI, so that UAT will pass for the intended reason rather than by accident. The last successful sync was `2026-09-01T11:27:41Z`; the next scheduled fire is `2026-09-01T17:00:00Z` UTC.
- **The phase goal — "the deployment works against real data" — is now materially true.** 327 workouts, 463 templates and 125 body measurements are in production Postgres, reachable by the MCP tools verified in 07-06.
- **Two open items handed forward**, both in `deferred-items.md`: `backend/app/cli.py`'s dishonest failure logging, and the absence of any schema-drift detection. Neither blocks the remaining plans.
- **One standing caution:** a paused or deleted schedule produces no alert. Its only symptom is drifting freshness, which the coaching document instructs Claude to report.

## Self-Check: PASSED

All files claimed created/modified exist on disk. All six task commits (`bd96b12`, `27fd7b8`,
`7c0accc`, `b8d227c`, `f979a77`, `4fdef8d`) exist in git. Neither this SUMMARY nor the runbook
contains a DSN, a Neon host pattern, or the literal `HEVY_API_KEY` value (0 occurrences, counted
programmatically). `STATE.md` and `ROADMAP.md` are untouched in this worktree, as required in
parallel mode.

Plan-level `<verification>` re-run at completion:

| # | Check | Result |
|---|---|---|
| 1 | `brett-hevy-api-key` exists, one `enabled` version, secret-scoped `secretAccessor` for `brett-run@` | PASS |
| 2 | Job `brett-sync-hevy` runs `python -m app.cli sync-hevy` via the CNB launcher, both credentials as secret refs, SA `brett-run@` | PASS |
| 3 | Latest execution `brett-sync-hevy-6vl4w` reports `succeededCount 1` | PASS |
| 4 | `brett-sync-hevy-6h`: `0 */6 * * *`, `Asia/Jakarta`, `ENABLED`, URI ending `:run` | PASS |
| 5 | Forced scheduler run yielded a new successful execution | PASS |
| 6 | `docs/runbook-sync-schedule.md` — 336 lines, redacted, 9 rows each with a verdict | PASS |

Fast suite: 397 passed, 286 deselected. `test_sync_job_deploy.py`: 9/9.

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*

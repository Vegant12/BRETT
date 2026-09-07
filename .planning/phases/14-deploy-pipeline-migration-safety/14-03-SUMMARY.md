---
phase: 14-deploy-pipeline-migration-safety
plan: 03
subsystem: infra
tags: [deploy, alembic, migrations, bash, secret-manager, pytest, testcontainers]

# Dependency graph
requires:
  - phase: 14-01
    provides: "app.db.migration_preflight: check_at_head(run, *, database_url) predicate"
  - phase: 14-02
    provides: "scripts/deploy-cloud-run.sh: fetch-apply-verify migration pre-flight block"
provides:
  - "backend/tests/test_deploy_script_preflight.py: 4 @pytest.mark.integration tests that EXECUTE scripts/deploy-cloud-run.sh with a recording gcloud stub on PATH"
  - "docs/runbook-deploy.md: the documented single source of truth for the production DATABASE_URL, the deploy procedure, and the abort playbook"
affects: ["19-production-deploy-of-migration-0007 (follows the runbook procedure written here)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Recording stub on PATH: a stub named `gcloud`, resolved via shutil.which and asserted equal to the stub path BEFORE subprocess.run, so exec gcloud run deploy can never reach the real binary"
    - "Test-scope safety interlock as a hard assertion, not a comment: REFUSING TO RUN fires before the script executes if PATH resolution is ever wrong"
    - "Destructive-vs-non-destructive test declaration discipline: only tests that downgrade the shared container declare restore_schema; tests that never touch schema (unreachable DB, empty secret) deliberately omit it"

key-files:
  created:
    - backend/tests/test_deploy_script_preflight.py
    - docs/runbook-deploy.md
  modified: []

key-decisions:
  - "Used noqa: S607 on the literal \"bash\" argument (resolved via PATH intentionally, mirroring how the deploy script itself is invoked in production) rather than hard-coding an absolute bash path, which would make the test less portable across CI runners for no safety gain — the actual escape-hatch protection is the gcloud stub, not the bash path"

patterns-established:
  - "Execute-the-real-artifact tests: a static text-grep test (test_cloud_run_deploy.py) proves a gate is written; a subprocess-execution test proves it runs. Both are needed and neither substitutes for the other."

requirements-completed: [DEPLOY-04]

# Metrics
duration: ~6min (git-timestamp measured; total session time including context-loading was longer)
completed: 2026-09-07
---

# Phase 14 Plan 03: Deploy Script Execution Rehearsal & Deploy Runbook Summary

**Executed the real `scripts/deploy-cloud-run.sh` against a real, deliberately drifted Postgres container with a recording `gcloud` stub on `PATH`, proving the migration gate built in 14-01/14-02 actually runs rather than merely being present as text — and wrote `docs/runbook-deploy.md`, the operator procedure DEPLOY-04 requires, naming Secret Manager's `brett-database-url` as the single source of truth for the production `DATABASE_URL`.**

## Performance

- **Duration:** ~6 min by commit timestamps (base commit 11:56:23 -> final commit 12:01:51, Asia/Jakarta); total wall-clock session time including reading all required context files was longer
- **Started:** 2026-09-07T04:56:23Z
- **Completed:** 2026-09-07T05:01:51Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (both new)

## Accomplishments

- `backend/tests/test_deploy_script_preflight.py` runs `scripts/deploy-cloud-run.sh` itself as a `bash` subprocess (not the extracted predicate) against a real `testcontainers` Postgres instance, with a recording `gcloud` stub prepended to `PATH`.
- Four `@pytest.mark.integration` tests, all passing:
  1. A database downgraded one revision behind head gets migrated and the (stubbed) deploy is reached — proving D-01's auto-apply end to end, through the real script.
  2. A database on an unreachable port (closed via `make_url(...).set(port=1)`) aborts before `gcloud run deploy` is ever invoked — proving ROADMAP criterion 1 by execution, not by grep.
  3. An already-current database deploys cleanly across two consecutive runs, both reaching `run deploy` — proving the D-02 verification arm does not false-alarm on a healthy database.
  4. With no `BRETT_DATABASE_URL` set, the script calls `gcloud secrets versions access latest` (observed via the stub's log), receives empty stdout from the stub, and refuses to deploy — proving D-05's Secret Manager fetch path is really wired, not merely documented.
- The safety interlock (`shutil.which("gcloud", path=env["PATH"])` asserted equal to the stub path, failing with `REFUSING TO RUN` otherwise) runs before every `subprocess.run` call, so a `PATH` mistake cannot silently attempt a real deploy.
- `docs/runbook-deploy.md` (123 lines) documents: the single source of truth for `DATABASE_URL` (`gcloud secrets versions access latest --secret="brett-database-url"`), the five-step deploy procedure including a mandatory pre-deploy `alembic history -r current:head` review, and a three-row abort table covering every failure message an operator can see from this pipeline (empty secret, alembic traceback, and `DEPLOY-04 violated` drift). No credential value appears anywhere in the file — verified by the negative grep in the task's own `<verify>` block.

## Task Commits

Each task was committed atomically:

1. **Task 1: Execute the real deploy script against a drifted container with gcloud stubbed** - `3991d16` (test)
2. **Task 2: Write the deploy runbook naming the DATABASE_URL source of truth** - `0c3a290` (docs)

## Files Created/Modified

- `backend/tests/test_deploy_script_preflight.py` — 4 integration tests plus a `gcloud_stub` fixture and a `_run_deploy` helper that enforces the `PATH`-resolution safety interlock before every script execution
- `docs/runbook-deploy.md` — the deploy runbook: source-of-truth section, procedure, abort table, and a closing section explaining why the gate lives in code rather than only in this document

## Decisions Made

- Kept `_run_deploy`'s `bash` invocation as a `PATH`-resolved literal (`noqa: S607`) rather than hard-coding an absolute interpreter path — the safety property this file is built around comes entirely from the `gcloud` stub-resolution assertion, not from pinning `bash`'s location, and a `PATH`-resolved `bash` is more portable across CI runners.
- Followed the plan's exact test bodies and fixture shapes verbatim (the plan's `<interfaces>` and per-test action blocks were fully specified); no design decisions beyond the ruff-lint fix below were needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `subprocess.run(["bash", ...])` failed ruff's S607 (partial executable path)**
- **Found during:** Task 1 verification (`uv run ruff check`)
- **Issue:** The plan's helper code passes `"bash"` as a bare command name, which Ruff's bandit-derived `S607` rule flags as "starting a process with a partial executable path." The plan's own `# noqa: S603` comment on the `subprocess.run(` line did not suppress `S607`, because Ruff attributes that specific rule to the line containing the partial-path literal (the `["bash", str(DEPLOY_SCRIPT)]` argument line), not the enclosing call line.
- **Fix:** Added a second `# noqa: S607` comment directly on the argument list's line, with a short inline justification (`"bash" is intentionally resolved via PATH`), leaving the `# noqa: S603` on the `subprocess.run(` line untouched.
- **Files modified:** `backend/tests/test_deploy_script_preflight.py`
- **Verification:** `uv run ruff check backend/tests/test_deploy_script_preflight.py` → `All checks passed!`
- **Committed in:** `3991d16` (part of Task 1 commit — caught before commit, not a follow-up fix)

---

**Total deviations:** 1 auto-fixed (1 blocking — a ruff lint rule requiring its own noqa on a different source line than the plan anticipated; not a functional or test-coverage issue).
**Impact on plan:** Cosmetic only. No behavior changed; all four tests pass exactly as the plan specifies.

## Issues Encountered

None beyond the deviation above. Docker was available in this environment, so all four `@pytest.mark.integration` tests ran against a real `testcontainers` Postgres instance rather than being skipped.

## User Setup Required

None — no external service configuration required. This plan does not touch `scripts/` or `backend/app/` (confirmed via `git diff --stat` against the plan's base commit, which returns empty for both paths).

## Next Phase Readiness

- `backend/tests/test_deploy_script_preflight.py` is a permanent regression test: any future change to `scripts/deploy-cloud-run.sh` that removes, reorders, or weakens the migration gate will fail this suite by actually executing the script, not just by grepping its text.
- `docs/runbook-deploy.md` is ready for Phase 19 (Production Deploy of Migration 0007) to follow verbatim — it names the exact commands for the pre-deploy migration review and the exact abort messages an operator will see.
- Verified clean: `uv run pytest backend/tests -m "not integration" -q` — 652 passed, 11 skipped, 446 deselected (no regression vs. 14-02's 652 baseline); `uv run pytest backend/tests/test_migrations.py backend/tests/test_migration_preflight.py -q` — 20 passed (shared container correctly restored to head by `restore_schema` after the one destructive test in this plan); `uv run ruff check backend/` — clean.
- Phase 14 (deploy-pipeline-migration-safety) is now feature-complete across all three plans: the predicate (14-01), the wired script (14-02), and the end-to-end script rehearsal plus operator runbook (14-03).

---
*Phase: 14-deploy-pipeline-migration-safety*
*Completed: 2026-09-07*

## Self-Check: PASSED

- FOUND: backend/tests/test_deploy_script_preflight.py
- FOUND: docs/runbook-deploy.md
- FOUND: 3991d16 (test commit, Task 1)
- FOUND: 0c3a290 (docs commit, Task 2)

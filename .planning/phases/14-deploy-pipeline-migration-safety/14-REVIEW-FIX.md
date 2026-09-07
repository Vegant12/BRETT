---
phase: 14-deploy-pipeline-migration-safety
fixed_at: 2026-09-07T05:34:00Z
review_path: .planning/phases/14-deploy-pipeline-migration-safety/14-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 14: Code Review Fix Report

**Fixed at:** 2026-09-07T05:34:00Z
**Source review:** .planning/phases/14-deploy-pipeline-migration-safety/14-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2 (fix_scope: critical_warning -> WR-01, WR-02; the review had 0 Critical
  findings; IN-01/IN-02 were out of scope and left untouched)
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: Runbook's "DATABASE_URL resolved to an empty value" troubleshooting entry is unreachable for the causes it lists

**Files modified:** `scripts/deploy-cloud-run.sh`, `docs/runbook-deploy.md`
**Commit:** `419ba46`
**Applied fix:** `scripts/deploy-cloud-run.sh` now resolves `DATABASE_URL` from Secret Manager
inside an explicit `if ! DATABASE_URL="$(gcloud secrets versions access ... 2>"$GCLOUD_ERR_FILE")"`
check instead of relying on `set -e`'s default (silent, unprefixed) abort. A `gcloud` command that
exits non-zero (PERMISSION_DENIED, NOT_FOUND, wrong project) now produces a
`DEPLOY-04: failed to resolve DATABASE_URL from Secret Manager ...` message on stderr carrying
gcloud's own error text, distinct from the pre-existing `DEPLOY-04: DATABASE_URL resolved to an
empty value ...` message, which is now reachable only for the narrower case of `gcloud` exiting 0
with an empty payload. `docs/runbook-deploy.md`'s troubleshooting table was split into two rows
matching these two distinct failure shapes, as the review's fallback suggestion recommended.
Verified: `bash -n` on the script, the full static suite (`test_cloud_run_deploy.py`, 17 passed),
and the real-script integration test `test_deploy_refuses_when_the_secret_resolves_empty` (which
exercises the still-reachable empty-payload branch via the `gcloud` stub) all pass, plus the full
`test_deploy_script_preflight.py` integration suite (4 passed) against a real Postgres container.

### WR-02: No timeout on alembic subprocess invocations — a stalled DB connection hangs the deploy pipeline indefinitely

**Files modified:** `backend/app/db/migration_preflight.py`
**Commit:** `cd971b4`
**Applied fix:** `build_runner._run` now calls `subprocess.run(..., timeout=60)` and catches
`subprocess.TimeoutExpired`, converting it into a `CompletedProcess` with `returncode=1` and a
`stderr` message identifying which alembic invocation timed out (plus any partial stderr captured
before the timeout) — so `check_at_head` and `main` continue to see one uniform failure shape
(nonzero return code with an explanatory message) rather than an uncaught exception. Verified:
`ast.parse` on the module, the full fast suite (`test_migration_preflight.py -m "not integration"`,
14 passed), and the drift-rehearsal integration suite against a real Postgres container
(`-m integration`, 3 passed).

**Deviation from the review's suggested fix — documented, not skipped:** WR-02's Fix section also
suggested wrapping the two `uv run` invocations in `scripts/deploy-cloud-run.sh` with a shell-level
timeout (e.g. `timeout 60 uv run ...`), phrased as "Consider the same for..." rather than as the
primary fix. This was attempted and then deliberately reverted before committing, for two reasons
verified during this session:
1. GNU coreutils `timeout`/`gtimeout` is not installed on this machine (confirmed via
   `which timeout gtimeout`), and `docs/runbook-deploy.md` has an operator run this exact script
   from their local shell, which is not guaranteed to be Linux.
2. A portable pure-bash watchdog function (background `sleep N && kill -TERM $cmd_pid`, cancelled
   via `kill $watchdog_pid` once the guarded command finishes) was implemented and syntax-checked,
   but running the real integration suite against it (`test_deploy_script_preflight.py -m
   integration`) produced two failures: `test_deploy_applies_a_pending_migration_then_deploys` and
   `test_deploy_is_idempotent_on_an_already_current_database` both returned exit code 143
   (SIGTERM) even though the guarded alembic command had already completed successfully and
   produced its full expected output — indicating a PID-reuse race between the watchdog's delayed
   `kill -TERM $cmd_pid` and a subsequent command in the same script, not a logic error visible
   from re-reading the script. Given this is a production deploy script with no rollback other
   than a fresh `gcloud run deploy`, the risk of shipping an intermittent false-SIGTERM was judged
   to outweigh the benefit of an outer shell-level timeout, especially since the Python-level fix
   already bounds the two `alembic current`/`alembic heads` calls the pre-flight module itself
   makes. The change was rolled back via `git checkout -- scripts/deploy-cloud-run.sh` before any
   commit, so no partially-working watchdog logic reached git history; the full integration suite
   was re-run afterward and confirmed green (4 passed) on the reverted file. A human should decide
   whether to pursue a more careful shell-level timeout (e.g. `setsid`/process-group-based) as a
   follow-up, since the alembic `upgrade head` step invoked directly by the shell script (as
   opposed to the `current`/`heads` calls inside `migration_preflight.py`) is still unbounded at
   the shell layer.

## Skipped Issues

None — both in-scope findings (WR-01, WR-02) were fixed. IN-01 and IN-02 were out of scope for
this run (`fix_scope: critical_warning`) and were left untouched.

---

_Fixed: 2026-09-07T05:34:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

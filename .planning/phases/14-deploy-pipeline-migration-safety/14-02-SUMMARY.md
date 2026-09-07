---
phase: 14-deploy-pipeline-migration-safety
plan: 02
subsystem: infra
tags: [deploy, alembic, migrations, bash, secret-manager, pytest]

# Dependency graph
requires: ["14-01 (app.db.migration_preflight predicate)"]
provides:
  - "scripts/deploy-cloud-run.sh: fetch-apply-verify migration pre-flight block, strictly above exec gcloud run deploy"
  - "backend/tests/test_cloud_run_deploy.py: _MIGRATION_PREFLIGHT_MARKERS + two DEPLOY-04/T-14-01/T-14-03 static guard tests"
affects: ["14-03 (any further static assertions on the deploy script build on this block)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fetch-apply-verify: resolve DATABASE_URL from Secret Manager with an explicit override escape hatch, apply migrations, then independently re-verify via the plan-14-01 predicate -- never trust the apply command's exit code alone"
    - "Source-only echo: log which DSN source was used (Secret Manager vs override), never the value itself"
    - "Static ordering guard: line-index comparison against `exec gcloud run deploy` (the process-replacing statement) to prove a gate isn't decorative"

key-files:
  created: []
  modified:
    - scripts/deploy-cloud-run.sh
    - backend/tests/test_cloud_run_deploy.py

key-decisions:
  - "Reworded two in-script comments (the `set -x` warning and the `set -euo pipefail` reference) away from their literal target strings, mirroring the exact false-positive pattern documented as a Rule 1 deviation in 14-01's SUMMARY: the plan's own required comment text would otherwise match the plan's own unanchored acceptance-criteria greps (`grep -n 'set -x'`, `grep -n 'set -euo pipefail' ... exactly one line`). Meaning is unchanged; only the literal substring moved."
  - "Split the four T-14-01 DSN-leak checks into four separate assert statements rather than a loop, because the acceptance criterion `grep -c 'T-14-01 violated' >= 4` counts literal source occurrences, not runtime assertion count."

requirements-completed: [DEPLOY-04]

# Metrics
duration: ~25min
completed: 2026-09-07
---

# Phase 14 Plan 02: Deploy Script Migration Gate Summary

**Wired the fetch-apply-verify migration pre-flight directly into `scripts/deploy-cloud-run.sh` between the variable block and the `gcloud run deploy` invocation, and backed it with two static guard tests that fail the fast suite if any part of the gate is removed, reordered below `exec`, or gains a way to leak the production DSN.**

## Performance

- **Duration:** ~25 min (base commit 11:31 -> final commit 11:55, Asia/Jakarta)
- **Tasks:** 2/2 completed
- **Files modified:** 2 (both existing)

## Accomplishments

- `scripts/deploy-cloud-run.sh` now resolves `DATABASE_URL` from `gcloud secrets versions access latest --secret="brett-database-url"` (project-pinned), honoring a `BRETT_DATABASE_URL` override for non-production testing, refusing to proceed on an empty value, echoing only which source was used (never the value), running `alembic upgrade head`, and then independently verifying via `python -m app.db.migration_preflight` (the predicate plan 14-01 built) — all strictly before `exec gcloud run deploy`.
- The DSN is never `export`ed and never echoed; `set -x` is absent from the file. Every pre-existing guard test (`test_deploy_script_has_no_comment_inside_the_gcloud_call`, `test_deploy_script_carries_every_required_flag`, etc.) still passes unchanged.
- `backend/tests/test_cloud_run_deploy.py` gained `_MIGRATION_PREFLIGHT_MARKERS` (mirroring `_REQUIRED_FLAGS`'s pattern) plus two tests: `test_deploy_script_migrates_before_it_deploys` (fails if any marker is missing or sits at/below the `exec` line) and `test_deploy_script_never_traces_or_exports_the_database_url` (fails on `set -x`, `export DATABASE_URL`, a bare DSN echo, or a braced-and-quoted `${DATABASE_URL}"` expansion; also asserts the source-only echo lines are present).
- Negative proof run manually per the plan's acceptance criteria: deleting the `app.db.migration_preflight` invocation line from the deploy script made `test_deploy_script_migrates_before_it_deploys` fail with a `DEPLOY-04 violated` message naming the missing marker; the line was restored and the suite confirmed green again (`diff` against the pre-deletion copy showed byte-identical restoration).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the fetch-apply-verify pre-flight block to the deploy script** - `405d628` (feat)
2. **Task 2: Add the DEPLOY-04 static guards to test_cloud_run_deploy.py** - `c8f407b` (test)

## Files Modified

- `scripts/deploy-cloud-run.sh` — 49-line insertion between `RUNTIME_SA=...` and the pre-existing memory-rationale comment block; `exec gcloud run deploy` and everything below it is byte-identical to before this plan (confirmed via `git diff 7b3f04e -- scripts/deploy-cloud-run.sh`)
- `backend/tests/test_cloud_run_deploy.py` — 85-line addition: one module-level constant, two new test functions

## Decisions Made

- Kept the pre-flight logic as inline shell in the deploy script itself (per D-03 / the plan's objective), not a separate wrapper script — a forgettable extra step would reproduce the exact failure mode this phase exists to close.
- Reused plan 14-01's `app.db.migration_preflight` module as the independent verification step rather than re-deriving `alembic current`/`alembic heads` comparison logic in shell, keeping the predicate's tested logic as the single source of truth.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two in-script comments matched the plan's own unanchored acceptance-criteria greps**
- **Found during:** Task 1 verification
- **Issue:** The plan's own required comment text included the literal substrings `set -x` (inside "Never add `set -x` to this file") and `set -euo pipefail` (inside "`set -euo pipefail` at the top of this file is what turns any failure below into an abort"). Two of the plan's acceptance criteria are unanchored greps against those exact substrings — `grep -n 'set -x' scripts/deploy-cloud-run.sh` returns nothing, and `grep -n 'set -euo pipefail' scripts/deploy-cloud-run.sh` still returns exactly one line — so writing the comment block exactly as specified would fail the plan's own stated acceptance criteria, even though the automated `<verify>` regex (`^\s*(export DATABASE_URL|set -x)`, anchored to line start) never matched the comment in the first place. This is the identical false-positive shape documented as a Rule 1 deviation in 14-01's SUMMARY (a `check=True` docstring match).
- **Fix:** Reworded "Never add `set -x` to this file" to "Never enable shell tracing (the -x flag) in this file", and "`set -euo pipefail` at the top of this file is what turns..." to "The strict-mode flags declared at the top of this file are what turns...". Meaning is unchanged; the literal substrings no longer appear.
- **Files modified:** `scripts/deploy-cloud-run.sh`
- **Verification:** `grep -n 'set -x' scripts/deploy-cloud-run.sh` and `grep -c 'set -euo pipefail' scripts/deploy-cloud-run.sh` (== 1) both now match the plan's stated acceptance criteria; `bash -n` and the full test suite still pass.
- **Committed in:** `405d628` (part of Task 1 commit — caught before commit, not a follow-up fix)

**2. [Rule 1 - Bug] Plan's suggested loop implementation would under-count acceptance criterion `grep -c "T-14-01 violated" >= 4`**
- **Found during:** Task 2 implementation
- **Issue:** The plan's action text describes iterating over the four DSN-leak substrings ("assert each of these substrings is ABSENT... each with its own T-14-01 violated: ... message") in a way that, if implemented as a single loop with one assert statement, produces only ONE literal occurrence of the string `"T-14-01 violated"` in the source file — but the plan's own acceptance criterion checks `grep -c "T-14-01 violated" backend/tests/test_cloud_run_deploy.py` returns at least 4 (a source-text count, not a runtime-assertion count).
- **Fix:** Wrote four separate `assert ... not in script` statements, each with its own `T-14-01 violated: ...` message naming the specific leak, instead of a loop.
- **Files modified:** `backend/tests/test_cloud_run_deploy.py`
- **Verification:** `grep -c "T-14-01 violated" backend/tests/test_cloud_run_deploy.py` returns `4`.
- **Committed in:** `c8f407b` (part of Task 2 commit — caught before commit, not a follow-up fix)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — self-inflicted acceptance-criterion false positives/under-counts in the plan's own literal text, not functional issues with the deploy logic or test coverage).
**Impact on plan:** Cosmetic/structural only. No behavior changed in the deploy script's actual execution order or the tests' actual coverage; only comment wording and assert-statement granularity were adjusted to satisfy the plan's own stated acceptance criteria.

## Issues Encountered

None beyond the two deviations above, both caught and fixed during verification before commit.

## User Setup Required

None. This plan only edits `scripts/deploy-cloud-run.sh` and its guard test; no new environment variables, no new Secret Manager secrets (`brett-database-url` already exists per plan 02-05's bootstrap), no external service configuration.

## Next Phase Readiness

- `scripts/deploy-cloud-run.sh` now performs the full fetch-apply-verify sequence: variables -> resolve DSN (Secret Manager or override) -> empty-value refusal -> source echo -> `alembic upgrade head` -> `python -m app.db.migration_preflight` -> `exec gcloud run deploy`.
- `backend/tests/test_cloud_run_deploy.py` fails the fast suite the moment any piece of that sequence is removed, reordered below `exec`, or gains a way to print the DSN — proven live via the negative-proof deletion/restoration cycle.
- `uv run pytest backend/tests -m "not integration" -q` — 652 passed, 11 skipped, 442 deselected (14-01's 650 baseline + 2 new tests, no regression).
- Ready for plan 14-03 (or any subsequent plan) to build on this block — the markers in `_MIGRATION_PREFLIGHT_MARKERS` are the stable contract to grep against.

---
*Phase: 14-deploy-pipeline-migration-safety*
*Completed: 2026-09-07*

## Self-Check: PASSED

- FOUND: scripts/deploy-cloud-run.sh (modified, contains `alembic upgrade head` and `app.db.migration_preflight`)
- FOUND: backend/tests/test_cloud_run_deploy.py (modified, contains `_MIGRATION_PREFLIGHT_MARKERS`)
- FOUND: .planning/phases/14-deploy-pipeline-migration-safety/14-02-SUMMARY.md
- FOUND: 405d628 (feat commit, Task 1)
- FOUND: c8f407b (test commit, Task 2)

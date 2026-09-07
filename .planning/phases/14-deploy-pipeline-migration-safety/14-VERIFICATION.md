---
phase: 14-deploy-pipeline-migration-safety
verified: 2026-09-07T06:30:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 14: Deploy Pipeline Migration Safety Verification Report

**Phase Goal:** Deploys can no longer silently run production behind the applied schema.
**Verified:** 2026-09-07T06:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `scripts/deploy-cloud-run.sh` against a database with pending migrations fails loudly before `gcloud run deploy` executes | ✓ VERIFIED | `backend/tests/test_deploy_script_preflight.py::test_deploy_aborts_before_gcloud_when_the_database_is_unreachable` and `::test_deploy_refuses_when_the_secret_resolves_empty` executed the REAL script against a real Postgres container with a recording `gcloud` stub on PATH; both prove `"run deploy"` never appears in the stub's invocation log. The success path (`test_deploy_applies_a_pending_migration_then_deploys`) proves a drifted database (real container downgraded to `0005`) gets migrated to `0006` and only then reaches the stubbed deploy. Ran live: `uv run pytest backend/tests/test_deploy_script_preflight.py -q` → 4 passed. |
| 2 | Script runs `alembic upgrade head` and an enforced `current` vs `heads` check that aborts on mismatch, with a documented single source of truth for `DATABASE_URL` | ✓ VERIFIED | `scripts/deploy-cloud-run.sh` lines 46/74 run `uv run alembic upgrade head` then `uv run python -m app.db.migration_preflight` before `exec gcloud run deploy` (confirmed by direct file read). `docs/runbook-deploy.md` section `## The single source of truth for the production DATABASE_URL` (line 17) names `gcloud secrets versions access latest --secret="brett-database-url"` as authoritative and explicitly disclaims shell-inherited values (the Phase 9 incident). |
| 3 | A new static assertion in `backend/tests/test_cloud_run_deploy.py` proves the migration step/pre-flight exists in the script, mirroring `_REQUIRED_FLAGS` | ✓ VERIFIED | `_MIGRATION_PREFLIGHT_MARKERS` tuple + `test_deploy_script_migrates_before_it_deploys` exist and pass. **Negative-proof rehearsed live during this verification**: deleted the `app.db.migration_preflight` invocation line from the real script, re-ran the test suite — `test_deploy_script_migrates_before_it_deploys` failed with `"DEPLOY-04 violated: scripts/deploy-cloud-run.sh no longer contains 'app.db.migration_preflight'..."` (1 failed, 16 passed). Restored the line; `git status --short scripts/deploy-cloud-run.sh` confirmed a byte-identical restore; re-ran — 17 passed. |
| 4 | The fix is rehearsed against a real drift scenario, not asserted only against fixtures | ✓ VERIFIED | Two independent real-container rehearsals, both executed live during this verification: (a) `backend/tests/test_migration_preflight.py` — 3 `@pytest.mark.integration` tests downgrade a real `testcontainers` Postgres one revision behind head (`0006`→`0005`) and prove the predicate and its `python -m` entrypoint detect it; `uv run pytest backend/tests/test_migration_preflight.py -q` → 17 passed. (b) `backend/tests/test_deploy_script_preflight.py` — executes the REAL shell script (not the predicate) against the same real drifted container with a `gcloud` stub; `uv run pytest backend/tests/test_deploy_script_preflight.py -q` → 4 passed. `backend/tests/test_migrations.py` passed afterward (3 passed), confirming the shared container was correctly restored to head. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/migration_preflight.py` | Extracted, importable pre-flight predicate (`PreflightResult`, `parse_revisions`, `redact`, `build_runner`, `check_at_head`, `main`) | ✓ VERIFIED | Exists, all 5 functions + dataclass present, `mypy` clean, `ruff` clean, 17 tests pass |
| `backend/tests/test_migration_preflight.py` | Fast unit coverage + real-drift integration rehearsal | ✓ VERIFIED | 14 fast unit tests + 3 `@pytest.mark.integration` tests, all passing |
| `scripts/deploy-cloud-run.sh` | Fetch-apply-verify migration block before `exec gcloud run deploy` | ✓ VERIFIED | Block present at lines 26-75, `bash -n` clean, `exec gcloud run deploy` block byte-identical to pre-phase version |
| `backend/tests/test_cloud_run_deploy.py` | Static DEPLOY-04 guard mirroring `_REQUIRED_FLAGS` | ✓ VERIFIED | `_MIGRATION_PREFLIGHT_MARKERS` + 2 new tests, negative-proof rehearsed live (see truth #3) |
| `backend/tests/test_deploy_script_preflight.py` | End-to-end execution rehearsal of the real script with `gcloud` stubbed | ✓ VERIFIED | 4 `@pytest.mark.integration` tests, safety interlock (`shutil.which` vs stub path) present and functioning, all pass |
| `docs/runbook-deploy.md` | Documented DATABASE_URL source of truth + abort playbook | ✓ VERIFIED | 123 lines (≥70 required), all 4 required `##` sections present, no credential-bearing DSN found via `grep -nE 'postgres(ql)?...:...@'` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `backend/tests/test_migration_preflight.py` | `backend/app/db/migration_preflight.py` | direct import | ✓ WIRED | `grep -n "from app.db.migration_preflight import"` → line 25. (gsd-tools automated key-link check reported a false "not found" due to a regex double-escaping artifact; confirmed wired by direct grep.) |
| `scripts/deploy-cloud-run.sh` | `backend/app/db/migration_preflight.py` | `uv run python -m app.db.migration_preflight` after `alembic upgrade head` | ✓ WIRED | `grep -n "app.db.migration_preflight" scripts/deploy-cloud-run.sh` → line 74, positioned before `exec gcloud run deploy` (confirmed by `awk` line-order check and live test execution) |
| `scripts/deploy-cloud-run.sh` | Secret Manager `brett-database-url` | `gcloud secrets versions access latest`, project-pinned | ✓ WIRED | Present at line 46; live-tested in `test_deploy_refuses_when_the_secret_resolves_empty`, stub log shows the real call is made |
| `backend/tests/test_cloud_run_deploy.py` | `scripts/deploy-cloud-run.sh` | text read, line-index ordering | ✓ WIRED | Confirmed via negative-proof rehearsal (deleting the line broke the test) |
| `backend/tests/test_deploy_script_preflight.py` | `scripts/deploy-cloud-run.sh` | `bash` subprocess execution with stubbed `gcloud` on PATH | ✓ WIRED | `DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-cloud-run.sh"` present; live execution against a real container confirmed working (4/4 pass) |
| `docs/runbook-deploy.md` | `scripts/deploy-cloud-run.sh` | documented procedure | ✓ WIRED | 5+ references to `scripts/deploy-cloud-run.sh` throughout the doc |

### Data-Flow Trace (Level 4)

Not applicable — this phase produces deploy tooling and tests, not UI/data-rendering components. Data flow (DSN → alembic → predicate → exit code) was verified directly via live execution against a real Postgres container rather than a rendering trace.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Predicate detects real drift | `uv run pytest backend/tests/test_migration_preflight.py -q` | 17 passed | ✓ PASS |
| Static guard fails when gate removed | Manually deleted `app.db.migration_preflight` line, re-ran `test_cloud_run_deploy.py`, restored | 1 failed as expected, then 17 passed after restore | ✓ PASS |
| Real script rehearsal against drift + stubbed gcloud | `uv run pytest backend/tests/test_deploy_script_preflight.py -q` | 4 passed | ✓ PASS |
| Shared container left at head after destructive tests | `uv run pytest backend/tests/test_migrations.py -q` | 3 passed | ✓ PASS |
| No fast-suite regression | `uv run pytest backend/tests -m "not integration" -q` | 663 passed, 446 deselected | ✓ PASS |
| Lint/type clean | `uv run ruff check ...` / `uv run mypy backend/app/db/migration_preflight.py` | All checks passed / Success: no issues found | ✓ PASS |
| No residual repo changes from verification rehearsal | `git status --short scripts/deploy-cloud-run.sh` | empty | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DEPLOY-04 | 14-01, 14-02, 14-03 | `scripts/deploy-cloud-run.sh` gains a migration step or enforced `alembic current` vs `alembic heads` pre-flight that fails the deploy on drift, plus a documented single source of truth for the production `DATABASE_URL` | ✓ SATISFIED | All four ROADMAP success criteria verified above with live test execution against real Postgres containers and a real (stubbed-gcloud) script execution, plus a live negative-proof rehearsal of the static guard |

No orphaned requirements: `.planning/REQUIREMENTS.md` maps only DEPLOY-04 to Phase 14, and it is claimed by all three plans.

Note: `.planning/REQUIREMENTS.md` line 47 still shows `DEPLOY-04` with a `[x]` checkbox but the traceability table (line 113) shows status `Planned` — this is stale bookkeeping in REQUIREMENTS.md, not a functional gap. Consider updating REQUIREMENTS.md's traceability table status to `Done` as a housekeeping follow-up.

### Anti-Patterns Found

None. Scanned all five phase-created/modified files (`migration_preflight.py`, `deploy-cloud-run.sh`, `test_migration_preflight.py`, `test_deploy_script_preflight.py`, `runbook-deploy.md`) for TODO/FIXME/placeholder/not-implemented markers — zero matches.

### Human Verification Required

None. Every observable truth in this phase is mechanically verifiable (shell script behavior, subprocess exit codes, test suite results) and was verified via live execution during this review, not just static inspection.

### Gaps Summary

No gaps. All four ROADMAP success criteria hold, all artifacts exist and are substantive, all key links are wired (two automated gsd-tools key-link checks reported false negatives due to regex-escaping in the tool itself — both were confirmed wired via direct `grep`), and the two most safety-critical claims in this phase — "the static guard actually fails when the gate is removed" and "the rehearsal is against a real drift scenario, not a fixture" — were independently re-executed live during this verification (not merely trusted from the SUMMARY) and confirmed true.

---

*Verified: 2026-09-07T06:30:00Z*
*Verifier: Claude (gsd-verifier)*

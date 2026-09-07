# Phase 14: Deploy Pipeline Migration Safety - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-07
**Phase:** 14-deploy-pipeline-migration-safety
**Areas discussed:** Migration mechanism, Where the check lives, Drift rehearsal method, DATABASE_URL sourcing

---

## Selection of areas to discuss

Presented four gray areas (Migration mechanism, Where the check lives, Drift rehearsal method,
DATABASE_URL sourcing). User response: "Lets go with your recommendation or decision for all" —
delegating all four to Claude rather than answering individually.

---

## Migration mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-apply (`alembic upgrade head` runs automatically pre-deploy) | Removes the human "remember to migrate" step entirely | ✓ |
| Abort-only pre-flight (`alembic current` vs `alembic heads`, fails deploy on mismatch, no auto-apply) | Detects drift but still requires a separate manual migration step | |

**Claude's choice:** Auto-apply, with a post-upgrade `alembic current` == `alembic heads`
verification as a hard-fail check.
**Rationale:** All three prior incidents were caused by a human forgetting to run migrations,
not by a lack of drift detection. Matches the project's own original tech-stack guidance to run
migrations as a pre-deploy step rather than at app startup.

---

## Where the check lives

| Option | Description | Selected |
|--------|-------------|----------|
| Inside `scripts/deploy-cloud-run.sh` directly | Can't deploy without going through it | ✓ |
| Separate wrapper script | Developer must remember to run it first | |

**Claude's choice:** Inside `scripts/deploy-cloud-run.sh`, before the `exec gcloud run deploy`
block.
**Rationale:** A separate, forgettable script reproduces the exact "forgot a step" failure mode
this phase exists to close. The file already documents itself as the single reproducible
description of how BRETT deploys, and the existing test suite treats it as canonical.

---

## Drift rehearsal method

| Option | Description | Selected |
|--------|-------------|----------|
| Automated integration test (testcontainers, downgrade one revision, assert check fails) | Real database, permanent regression protection | ✓ |
| Manual runbook (human operator runs once against a real environment) | One-time proof, no lasting regression protection | |

**Claude's choice:** Automated integration test reusing the existing testcontainers + `alembic`
fixture from `backend/tests/test_migrations.py`.
**Rationale:** Satisfies "rehearsed against a real drift scenario, not asserted only against
fixtures" using a real Postgres container, while remaining a permanent, re-runnable regression
test rather than a one-off manual exercise.

---

## DATABASE_URL sourcing

| Option | Description | Selected |
|--------|-------------|----------|
| Script fetches it itself via `gcloud secrets versions access` | Enforces the single source of truth in code | ✓ |
| Document the command, require developer to export it first | Documented but not enforced | |

**Claude's choice:** Script fetches the secret itself, with an overridable env var
(`BRETT_DATABASE_URL`) for local/non-prod testing.
**Rationale:** The Phase 9 incident was caused by exactly this — an operator's shell pointed at
the wrong `DATABASE_URL`. Enforcing the fetch in code removes the failure mode instead of only
documenting the correct command.

---

## Claude's Discretion

- Exact wording of abort/failure messages
- Exact function/module boundary for the extracted pre-flight predicate
- Whether the new integration test lives in `test_cloud_run_deploy.py` or a new sibling file

## Deferred Ideas

None — discussion stayed within phase scope.

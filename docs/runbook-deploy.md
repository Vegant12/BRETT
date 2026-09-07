# Runbook — Deploying BRETT to Cloud Run

First written: 2026-09-07
Scope: the web service deployed by `scripts/deploy-cloud-run.sh`. The sync job
(`scripts/deploy-sync-job.sh`) is out of scope and is covered by `docs/runbook-sync-schedule.md`.
Owner artifacts: `scripts/deploy-cloud-run.sh` (the mechanism), `backend/app/db/migration_preflight.py`
(the gate), guarded by `backend/tests/test_cloud_run_deploy.py::test_deploy_script_migrates_before_it_deploys`
and `backend/tests/test_deploy_script_preflight.py`.

**Redaction rule for this file:** no credential value is ever recorded. `DATABASE_URL` is
referred to by Secret Manager name only — never as a full DSN, never with a host, user or
password. Where this document needs to refer to the resolved value at all, it names the command
that produces it, not the output of that command.

---

## The single source of truth for the production DATABASE_URL

This section is the deliverable DEPLOY-04 asks for.

The production value lives in Secret Manager as `brett-database-url`, and the only correct way
to read it is:

```bash
gcloud secrets versions access latest --project="$BRETT_GCP_PROJECT" --secret="brett-database-url"
```

Cloud Run binds the same secret at runtime via
`--set-secrets="DATABASE_URL=brett-database-url:latest,..."` in `scripts/deploy-cloud-run.sh`, so
the deploy-time value (the one `alembic upgrade head` runs against) and the runtime value (the
one the running service connects with) are the same secret version and cannot diverge.

A `DATABASE_URL` sitting in your shell, in `backend/.env`, or in a terminal you opened
yesterday is **not** a source of truth, no matter how recently it was correct. The Phase 9
incident was exactly that: an operator's shell was pointed at the wrong database, so the
before-state read as stale and the migration appeared unneeded when it was not. The deploy
script does not trust an inherited environment variable for this reason — it fetches the value
itself, every time, from Secret Manager.

`BRETT_DATABASE_URL` is the one deliberate override. It exists so this pipeline can be tested
against a non-production database (see `backend/tests/test_deploy_script_preflight.py`, which
sets it to point at a disposable test container), and the script always announces on stdout
which of the two sources — the Secret Manager fetch or the override — a given run used:

```
DEPLOY-04: using Secret Manager brett-database-url:latest in project <project>
```

or

```
DEPLOY-04: using the BRETT_DATABASE_URL override (non-production path)
```

Leave `BRETT_DATABASE_URL` unset for every real deploy. If you ever see the override line in a
production deploy's output, stop and find out why it was set.

## The deploy procedure

1. `git status` is clean and the commit you intend to deploy is checked out. A dirty working
   tree deploys whatever `--source` happens to pick up, not what you reviewed.
2. `uv run pytest backend/tests -m "not integration"` is green. The static DEPLOY-04 guards
   (`test_deploy_script_carries_every_required_flag`,
   `test_deploy_script_migrates_before_it_deploys`,
   `test_deploy_script_never_traces_or_exports_the_database_url`) live in this fast suite and
   must pass before you touch a real deploy.
3. Review what will actually be applied to production **before** it is applied. This is the
   residual risk the auto-apply step in this pipeline accepts (T-14-02) — the pipeline applies
   pending migrations automatically, but nothing in it stops a destructive one from being among
   them:
   ```bash
   cd backend && DATABASE_URL="$(gcloud secrets versions access latest --project="$BRETT_GCP_PROJECT" --secret="brett-database-url")" uv run alembic history -r current:head
   ```
   If that history lists a destructive revision (a dropped column, a dropped table, a
   `NOT NULL` added without a default), take a backup first — see
   `docs/runbook-backup-restore.md`. Do not skip this step because the pipeline "will catch it
   anyway": the pipeline verifies that a migration LANDED, not that it was safe to run.
4. Run the deploy:
   ```bash
   BRETT_GCP_PROJECT=<project> ./scripts/deploy-cloud-run.sh
   ```
5. Confirm the deploy log shows, in this order:
   - the `DEPLOY-04: using Secret Manager brett-database-url:latest in project ...` line (or the
     override line, if you are deliberately testing against a non-production database)
   - `alembic`'s own `upgrade head` output
   - the `at head: [...]` line from `app.db.migration_preflight`
   - and only then, `gcloud run deploy`'s own build/deploy output

   If step 5's ordering is ever violated — deploy output appearing before the `at head` line, or
   appearing at all when the `at head` line never printed — treat that as a broken pipeline, not
   a slow log. Stop and investigate rather than assuming the deploy still landed correctly.

## What an abort looks like, and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `DEPLOY-04: failed to resolve DATABASE_URL from Secret Manager (brett-database-url); gcloud secrets versions access latest --secret=brett-database-url exited non-zero. This is an IAM permission or missing-secret-version issue, not an empty-value one. gcloud said: ...` | `gcloud secrets versions access` itself failed (nonzero exit) — the secret has no accessible version, the deploying account lacks `roles/secretmanager.secretAccessor` on `brett-database-url`, or `BRETT_GCP_PROJECT` names the wrong project. The trailing `gcloud said: ...` text is gcloud's own error (e.g. `PERMISSION_DENIED` or `NOT_FOUND`). | Verify with `gcloud secrets versions list brett-database-url --project="$BRETT_GCP_PROJECT"`. If a version is listed and enabled, check the IAM binding is on the secret (not a specific version) for the runtime/deploying account. |
| `DEPLOY-04: DATABASE_URL resolved to an empty value; gcloud secrets versions access latest --secret=brett-database-url returned nothing and BRETT_DATABASE_URL is unset. Refusing to deploy.` | `gcloud secrets versions access` *succeeded* (exit 0) but printed an empty string — a narrower case than the row above, e.g. the secret's latest version payload is genuinely empty. | Inspect the secret's latest version payload directly (`gcloud secrets versions access latest --project="$BRETT_GCP_PROJECT" --secret="brett-database-url"` in a shell, confirming it prints nothing) and add a version with the correct value. |
| An alembic traceback during `alembic upgrade head` | The migration itself failed against production — a constraint violation, a lock timeout, a syntax error the local test database never exercised. **Nothing was deployed.** The database is left at whatever revision the failed transaction rolled back to (alembic runs each migration in its own transaction, so a failed migration does not partially apply). | Fix the migration against a copy of production data if possible, or against the same Postgres major version at minimum. Do not bypass the gate to "deploy anyway" — the code you are trying to ship assumes the schema this migration was supposed to produce. |
| `DEPLOY-04 violated: the database is at ['0005'] but the migrations head is ['0006'] ...` (or similar, naming different revisions) | `alembic upgrade head` exited 0 but the database did not actually land on the migrations head — most commonly multiple heads (an unmerged branch in `migrations/versions/`), or a manually edited `alembic_version` row that no longer matches any real revision. | Run `alembic heads` and `alembic history` against the same database to see the actual divergence before retrying. A second `alembic upgrade head` is only safe once you understand why the first one produced this state — running it blind risks masking the real problem rather than fixing it. |

There is no `--skip-migrations` flag on `scripts/deploy-cloud-run.sh`, and none should ever be
added. A bypass flag is the exact failure mode this runbook and this pipeline exist to prevent —
every one of the three v2.0 incidents below was, functionally, a human skipping the migration
step, whether on purpose or by omission.

## Why this is enforced in code rather than documented here

Three incidents in one milestone, all the same root cause — a human forgetting a documented
step, not a missing detector:

- **Phase 8:** `alembic current` was `0004` in production while the deployed code needed `0005`.
- **The Phase 9 operator run:** a shell was pointed at the wrong `DATABASE_URL`, so the
  before-state read as stale and the migration appeared unneeded when it was not.
- **The Phase 13 spike:** `0005` vs `0006`, surfacing live in production as
  `UndefinedTableError: relation "user_program_history" does not exist`.

Each was caught only by live verification after the fact, and each was fixed by a human, in the
moment, with the user's confirmation. That pattern is precisely what a runbook alone cannot fix:
a procedure only works if it is read, and the failure mode here was never "the procedure didn't
say to migrate" — the Phase 9 operator *knew* to check `DATABASE_URL` and checked the wrong one
anyway. This document explains the mechanism, the mechanism does not depend on this document
being read at deploy time, and the tests named at the top of this file fail the fast suite the
moment the mechanism is weakened, reordered, or removed.

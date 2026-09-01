# Runbook — Production Hevy Sync Schedule

First executed: 2026-09-01
Owner artifacts: `scripts/deploy-sync-job.sh`, `scripts/create-sync-schedule.sh`,
`deploy/sync-job.env.yaml`, guarded by `backend/tests/test_sync_job_deploy.py`.

**Redaction rule for this file:** no credential value is ever recorded. `HEVY_API_KEY` and
`DATABASE_URL` are referred to by Secret Manager name only, and no Neon DSN appears below.

## What runs, and when

A **Cloud Run Job** named `brett-sync-hevy` runs `python -m app.cli sync-hevy` — the same
command `README.md` documents for a manual sync, with `PYTHONPATH=backend` supplied from
`deploy/sync-job.env.yaml` because `app` is not an installed distribution.

A **Cloud Scheduler** job named `brett-sync-hevy-6h` fires it on cron `0 */6 * * *` in time
zone `Asia/Jakarta` — four times a day, on the hour, local time.

Why six hours: blueprint §38 asks for a sync every 1–6 hours, and six is the cheap end of that
range for a single-user dataset that only changes when the user finishes a workout. Why
`Asia/Jakarta` rather than UTC: the analytics layer buckets by local Monday-start weeks in the
user's timezone, so a UTC-scheduled sync would land at four arbitrary local times and make
"when was this last synced" harder to reason about than it needs to be.

Why a Cloud Run **Job** and not an in-process scheduler: the MCP service deploys with a minimum
instance count of zero, so an in-process APScheduler would die with a scaled-to-zero or
restarted instance and leave no run history.

## Preconditions

1. `BRETT_GCP_PROJECT` exported (`brett-fitness`) and `gcloud` authenticated as a principal
   holding `roles/iam.serviceAccountUser` on `brett-run@`.
2. Secret `brett-hevy-api-key` exists with an enabled version, and `brett-run@` holds
   `roles/secretmanager.secretAccessor` **on that secret** — not project-wide.
3. `brett-run@` holds `roles/run.invoker` on the job `brett-sync-hevy` — again on the job
   specifically, not project-wide.
4. `cloudscheduler.googleapis.com` and `run.googleapis.com` are enabled.
5. **The production database is migrated to alembic `head`.** The job reads `sync_state`,
   `workouts`, `exercise_templates` and five other tables; against a database behind `head` it
   dies on the first query. See "One-time: bringing the production schema to head" below —
   this was not a theoretical precondition, it blocked the first two executions.

### One-time: creating `brett-hevy-api-key`

The key lives in the developer's gitignored repo-root `.env`. Move it into Secret Manager
without it ever reaching a terminal, a file, a shell history entry or the process table — pipe
it, and never pass it as `--data="…"`:

```bash
python3 - <<'PY' | gcloud secrets create brett-hevy-api-key \
    --project="$BRETT_GCP_PROJECT" --replication-policy=automatic --data-file=-
import pathlib, sys
for line in pathlib.Path(".env").read_text().splitlines():
    if line.startswith("HEVY_API_KEY="):
        sys.stdout.write(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
else:
    sys.exit("HEVY_API_KEY not found in .env -- add it there first")
PY

gcloud secrets add-iam-policy-binding brett-hevy-api-key \
  --project="$BRETT_GCP_PROJECT" \
  --member="serviceAccount:brett-run@${BRETT_GCP_PROJECT}.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

`sys.stdout.write` rather than `print`: a trailing `0x0a` byte in a Secret Manager value
produces a correct-looking console entry and a failing runtime, which Phase 2's deploy log
records as a real trap for `brett-mcp-auth-secret`.

`gcloud secrets versions access` is never run against this secret. There is no operational
reason to read the value back — the job reads it, and a human reading it only creates a
transcript that did not need to exist.

### One-time: bringing the production schema to head

**This step was not anticipated by the plan and is the reason the first two executions failed.**

The Phase 2 deploy ran `alembic upgrade head` when `0002` was head, and nothing has run a
migration against production since. The code meanwhile advanced to `0004`. Revisions `0003`
(`workouts`, `workout_exercises`, `workout_sets`) and `0004` (`exercise_templates`,
`exercise_muscles`, `exercise_muscle_overrides`, `body_measurements`, `sync_state`) had never
been applied. The first sync execution therefore died on:

```
sqlalchemy.exc.ProgrammingError: <asyncpg.exceptions.UndefinedTableError>:
relation "sync_state" does not exist
```

Nothing had detected the drift: `/health` probes `SELECT 1`, which succeeds against any schema,
and the plan 07-06 MCP round trip confirmed the tool set without exercising data flow.

Both revisions are **purely additive** — eight `create_table` calls and their indexes, no
`drop_table`, no `alter_column`, no `op.execute`, and no change to the existing `users` table.
Every `drop_table` in those two files sits in `downgrade()`, which was not run. That is what
made applying them to a live production database an acceptable action rather than a risky one.

Cloud Run has no pre-deploy hook and startup migrations stay forbidden (a deploy runs old and
new revisions simultaneously by design), so the migration runs from the developer machine
against the **direct/unpooled** Neon endpoint — the DSN already stored in `brett-database-url`
is the unpooled one, per Neon's guidance that migrations must not run through the pooler:

```bash
cd backend
DATABASE_URL="$(gcloud secrets versions access latest \
    --secret=brett-database-url --project="$BRETT_GCP_PROJECT")" \
  uv run alembic upgrade head
```

The DSN is never echoed. `alembic.ini` pins `logger_sqlalchemy` to `WARNING` and carries no
`sqlalchemy.url` key at all (`migrations/env.py` injects it at runtime from the environment),
so no connection string reaches stdout or stderr. `DATABASE_URL` is scoped to the single
command rather than exported, so it does not leak into the shell environment either.

Observed, 2026-09-01:

```
alembic current  ->  0002
alembic upgrade head
    Running upgrade 0002 -> 0003, workout tables: workouts, workout_exercises, workout_sets
    Running upgrade 0003 -> 0004, hevy reference tables: exercise templates, muscle map,
                                  overrides, body measurements, sync state
alembic current  ->  0004 (head)
```

**Standing check worth adding:** compare `alembic current` against `alembic heads` before
trusting any deployment against real data. This drift was invisible for the entire life of the
project and surfaced only when a job read a table.

### Two corrections made to `scripts/deploy-sync-job.sh` during first live use

Plan 07-04 wrote and unit-tested the deploy script, but it had never been run against the real
API. Two defects surfaced on first use and are fixed in the committed script:

1. **`--set-build-env-vars` is not a valid flag for `gcloud run jobs deploy`.** It exists for
   `gcloud run deploy` (services) but not for jobs, so the command failed at argument parsing
   before reaching the build. Removed.
2. **`--command=python` bypassed the buildpack entrypoint.** A Cloud Native Buildpacks image
   must be entered through `/cnb/lifecycle/launcher`, which sets `PATH`, the virtualenv and the
   working directory. Invoking `python` directly skipped all of that. Fixed to
   `--command=/cnb/lifecycle/launcher --args=python,-m,app.cli,sync-hevy`, which is why the
   control-plane read-back below shows the launcher as `command` and `python` as the first
   `arg` rather than the shape plan 07-07 originally predicted.

## Procedure

All commands assume `export BRETT_GCP_PROJECT=brett-fitness` and an authenticated `gcloud`.

### Redeploy the job after a code change

```bash
./scripts/deploy-sync-job.sh
```

Source build through Cloud Buildpacks; takes several minutes. The script is idempotent — it
redeploys in place and does not need the schedule to be touched, because Cloud Scheduler targets
the job by name, not by revision.

**If the change included a new Alembic revision, migrate first.** The job has no pre-deploy hook
and will fail against a stale schema exactly as described above:

```bash
cd backend
DATABASE_URL="$(gcloud secrets versions access latest \
    --secret=brett-database-url --project="$BRETT_GCP_PROJECT")" \
  uv run alembic current   # compare against `alembic heads` before deploying
```

### Change the cadence

Edit the default in `scripts/create-sync-schedule.sh` (`BRETT_SYNC_CRON`), or override for a
one-off, then re-run the script — it takes the update path on an existing schedule:

```bash
BRETT_SYNC_CRON='0 */3 * * *' ./scripts/create-sync-schedule.sh
```

Keep `README.md` and this runbook in step with the committed default. Blueprint §38 bounds the
range at every 1–6 hours; anything outside that is a decision, not a tweak.

### Force a sync right now

Through the scheduler (also tests the scheduler's own wiring):

```bash
gcloud scheduler jobs run brett-sync-hevy-6h \
  --project="$BRETT_GCP_PROJECT" --location=us-central1
```

Or directly against the job, blocking until it finishes:

```bash
gcloud run jobs execute brett-sync-hevy \
  --project="$BRETT_GCP_PROJECT" --region=us-central1 --wait
```

Then confirm — with `succeededCount`, never with the log signature:

```bash
gcloud run jobs executions list --job=brett-sync-hevy \
  --project="$BRETT_GCP_PROJECT" --region=us-central1 --limit=1 \
  --format='value(metadata.name,status.succeededCount,status.failedCount)'
```

### Pause the schedule (and how to remember to resume it)

```bash
gcloud scheduler jobs pause  brett-sync-hevy-6h --project="$BRETT_GCP_PROJECT" --location=us-central1
gcloud scheduler jobs resume brett-sync-hevy-6h --project="$BRETT_GCP_PROJECT" --location=us-central1
gcloud scheduler jobs describe brett-sync-hevy-6h --project="$BRETT_GCP_PROJECT" \
  --location=us-central1 --format='value(state)'    # PAUSED or ENABLED
```

**A paused schedule is invisible in every other view.** The API keeps answering, `/health` stays
green, the MCP tools keep returning data, and the Cloud Run Job still exists and still works when
run by hand. The only symptom is `freshness.resources.workouts` drifting further into the past —
which the coaching document instructs Claude to report before answering. If you pause this, set
yourself a reminder; nothing else will.

## Verification record — 2026-09-01

| Row | Command summary | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `gcloud secrets versions list brett-hevy-api-key --format='value(name,state)'` | exactly one `enabled` version | `1  enabled` — one row | **PASS** |
| 2 | `gcloud secrets get-iam-policy brett-hevy-api-key --format='value(bindings.role,bindings.members)'` | `secretmanager.secretAccessor` for `brett-run@` and nothing broader | `roles/secretmanager.secretAccessor  ['serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com']` — one binding, one member | **PASS** |
| 3 | `gcloud run jobs describe brett-sync-hevy --region=us-central1` — command/args/env/secret refs/SA | runs `python -m app.cli sync-hevy`; `DATABASE_URL` and `HEVY_API_KEY` as secret references, never literals; SA `brett-run@` | `command=["/cnb/lifecycle/launcher"]`, `args=["python","-m","app.cli","sync-hevy"]`; env `ENVIRONMENT=production`, `LOG_LEVEL=INFO`, `PYTHONPATH=backend` as literals, `DATABASE_URL`→`secretKeyRef{name: brett-database-url, key: latest}`, `HEVY_API_KEY`→`secretKeyRef{name: brett-hevy-api-key, key: latest}`; `serviceAccountName=brett-run@brett-fitness.iam.gserviceaccount.com` | **PASS** (see note) |
| 4 | `gcloud run jobs execute brett-sync-hevy --wait`, then `executions list --limit=1 --format='value(metadata.name,status.succeededCount,status.failedCount)'` | `succeededCount` 1, no failures | `brett-sync-hevy-m8w2v  1  <empty>` | **PASS** |
| 5 | logs show `hevy_cli_started` + `hevy_cli_stopped`, no `hevy_cli_failed` | present / present / absent | For `m8w2v`: `started=1 stopped=1 failed=0 exit(0)=1`. **This row is necessary but NOT sufficient — see the caveat below.** | **PASS** |
| 6 | no credential-shaped string in the log window | zero matches | Across 574 log lines spanning all four executions: `postgres(ql)?://` **0**, `ep-[a-z0-9-]+\.` **0**, `neon.tech` **0**, `api[-_]?key` **0**, `authorization\|bearer` **0**, `sslmode\|channel_binding` **0**. The literal 36-character `HEVY_API_KEY` value from `.env` was counted against the captured log text programmatically (count printed, value never printed): **0 occurrences**. | **PASS** |
| 7 | `gcloud scheduler jobs describe brett-sync-hevy-6h --location=us-central1` — cron/timezone/uri/method/SA/state | `0 */6 * * *`, `Asia/Jakarta`, URI ending `jobs/brett-sync-hevy:run`, `POST`, `brett-run@`, `ENABLED` | `0 */6 * * *` · `Asia/Jakarta` · `https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/brett-fitness/jobs/brett-sync-hevy:run` · `POST` · `brett-run@brett-fitness.iam.gserviceaccount.com` · `ENABLED`. Also `attemptDeadline: 60s`, `oauthToken.scope: …/auth/cloud-platform`. | **PASS** |
| 8 | forced `gcloud scheduler jobs run` produces a NEW successful execution | new execution created after the forced run, `succeededCount` 1 | Forced at `11:20:21Z`; execution `brett-sync-hevy-6vl4w` created `11:23:41.953676Z` (new — the previous newest was `m8w2v` at `11:05:07Z`), settled with `succeededCount` `1`, `failedCount` empty. No `PERMISSION_DENIED`. | **PASS** |
| 9 | re-running `create-sync-schedule.sh` takes the update path | second run exits 0, updates in place, does not duplicate | Second run exited `0` and returned the same resource `projects/brett-fitness/locations/us-central1/jobs/brett-sync-hevy-6h` with `userUpdateTime` advanced `11:19:39.311766Z` → `11:29:06.731930Z`, `schedule`/`timeZone`/`state` unchanged. `scheduler jobs list` shows exactly **one** job, so the `describe`-probe took `update`, not a second `create`. | **PASS** |

**Note on row 3** — the `command`/`args` split is not what plan 07-07 predicted (`command=python`,
`args=["-m","app.cli","sync-hevy"]`). It is the corrected form: a buildpack image must be entered
through `/cnb/lifecycle/launcher`. The effective command line is still exactly
`python -m app.cli sync-hevy`, and `backend/tests/test_sync_job_deploy.py` asserts against the
corrected script. Recorded as PASS on substance, with the discrepancy stated rather than hidden.

### Caveat: `hevy_cli_started` + `hevy_cli_stopped` does not prove success

`status.succeededCount` is the **authoritative** success signal. The log signature is not.

`backend/app/cli.py`'s `_run_sync` catches `HevyError` and `RuntimeError` and logs
`hevy_cli_failed` for each. Any other exception — the `sqlalchemy.exc.ProgrammingError` above,
for instance — propagates uncaught, but the `finally` block still logs `hevy_cli_stopped`. A
failed run therefore produces exactly the signature a successful run produces.

Measured directly, all three executions of 2026-09-01:

| Execution | `hevy_cli_started` | `hevy_cli_stopped` | `hevy_cli_failed` | container exit | `succeededCount` |
|---|---|---|---|---|---|
| `brett-sync-hevy-rmrb5` | 0 | 0 | 0 | — (deploy-shape failure, never reached the app) | — (`failedCount` 1) |
| `brett-sync-hevy-xv7jv` | 2 | 2 | 0 | `exit(1)` ×2 | — (`failedCount` 1) |
| `brett-sync-hevy-m8w2v` | 1 | 1 | 0 | `exit(0)` | **1** |

`xv7jv` is the proof: started + stopped + no failed, and it still exited 1 twice. Verify a sync
with `status.succeededCount`, never with the log signature alone. Logged for whoever next owns
`backend/app/cli.py` in `.planning/phases/07-production-hardening-coaching-layer/deferred-items.md`.

### The sync did real work, not just exit 0

`m8w2v` logged, in order:

```
hevy_workout_sync_completed   pages=33  upserted=327  skipped=0  local_count=327
hevy_body_sync_completed      pages=13  rows=125
hevy_sync_all_completed       mode=full  workouts=327  templates=463  body=125
hevy_cli_stopped
Container called exit(0).
```

327 workouts and 463 templates match `docs/hevy-api-observations.md` exactly. Body measurements
read 125 against the 123 recorded there — two more than when that document was written, which is
what a real, growing dataset looks like. An execution reporting zeros here would be suspicious
even with `succeededCount` 1.

`brett-database-url` and `brett-mcp-auth-secret` were re-checked with the same command and
return the identical single binding, so all three secrets are consistently secret-scoped
(07-RESEARCH.md assumption A1 confirmed, not assumed).

`gcloud services list --enabled | grep -c cloudscheduler.googleapis.com` returned `1` after
enabling; `run.googleapis.com` was already enabled from the Phase 2 deploy.

`gcloud run jobs get-iam-policy brett-sync-hevy --region=us-central1` returns
`roles/run.invoker  ['serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com']` — bound
on the job, not project-wide.

### The scheduler-triggered run also demonstrated incremental mode and idempotency

`6vl4w` was the second successful sync against the same data, and it did not redo the first
one's work:

```
hevy_cli_started         mode=auto  only=all
hevy_body_sync_completed pages=13  rows=125
hevy_sync_all_completed  mode=incremental  workouts=0  templates=463  body=125
hevy_cli_stopped
Container called exit(0).
```

`mode=incremental` (against `m8w2v`'s `mode=full`) with `workouts=0` is the checkpoint in
`sync_state` doing its job — which is also the table whose absence killed the first two
executions. The at-least-once delivery risk below is therefore not merely argued to be safe, it
was observed to be safe.

## Known limitations

- **Cloud Scheduler guarantees at-least-once delivery**, so a duplicate execution is possible.
  Safe here: the sync is idempotent and checkpoint-resumable (HEVY-08/09), `--tasks=1` and
  `--max-retries=1` bound the fan-out, and the `6vl4w` run above is live evidence — a second
  invocation over unchanged data upserted zero workouts.
- **A paused or deleted schedule produces no alert.** Its only symptom is
  `freshness.resources.workouts` drifting, which the coaching document instructs Claude to
  report before answering. There is no monitor, no page, and no dashboard that will tell you.
- **Schema drift is not detected before it breaks a run.** `/health` probes `SELECT 1`, which
  succeeds against any schema, so a production database behind `alembic head` looks perfectly
  healthy until a job queries a table that does not exist. That is exactly how this plan lost its
  first two executions. Compare `alembic current` to `alembic heads` as part of any deploy that
  ships a migration.
- **`hevy_cli_started` + `hevy_cli_stopped` with no `hevy_cli_failed` is not a success signal.**
  See the caveat above; `status.succeededCount` is authoritative. A fix for `backend/app/cli.py`
  is proposed but deliberately not made here, in
  `.planning/phases/07-production-hardening-coaching-layer/deferred-items.md`.
- **Hevy's real rate limits remain unobserved** (STATE.md open concern). A 6-hourly incremental
  sync issuing ~46 paged requests is far below any plausible limit, but that is an argument, not
  a measurement.
- **The 6-hourly cadence means data can be up to six hours stale**, and a workout finished just
  after a run will not appear until the next one. Force a sync (see Procedure) when that matters.

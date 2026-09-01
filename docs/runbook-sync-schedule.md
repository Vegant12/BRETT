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

## Verification record — 2026-09-01

| Row | Command summary | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `gcloud secrets versions list brett-hevy-api-key --format='value(name,state)'` | exactly one `enabled` version | `1  enabled` — one row | **PASS** |
| 2 | `gcloud secrets get-iam-policy brett-hevy-api-key --format='value(bindings.role,bindings.members)'` | `secretmanager.secretAccessor` for `brett-run@` and nothing broader | `roles/secretmanager.secretAccessor  ['serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com']` — one binding, one member | **PASS** |

`brett-database-url` and `brett-mcp-auth-secret` were re-checked with the same command and
return the identical single binding, so all three secrets are consistently secret-scoped
(07-RESEARCH.md assumption A1 confirmed, not assumed).

`gcloud services list --enabled | grep -c cloudscheduler.googleapis.com` returned `1` after
enabling; `run.googleapis.com` was already enabled from the Phase 2 deploy.

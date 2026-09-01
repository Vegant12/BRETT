#!/usr/bin/env bash
# The single reproducible description of how BRETT's Hevy sync runs in production (D-10).
#
# `backend/app/cli.py` is the operations trigger; this is the scheduled production
# path blueprint 38 asks for (a sync every 1-6 hours). It is a Cloud Run JOB, not an
# in-process APScheduler: an in-process scheduler dies with a scaled-to-zero or
# restarted instance and leaves no run history, and the MCP service deploys with a
# minimum instance count of zero by default.
#
# backend/tests/test_sync_job_deploy.py asserts every flag below is still here.
#
# PREREQUISITE, one-time (see docs and plan 07-07): the Secret Manager secret
# `brett-hevy-api-key` must exist and `brett-run@` must hold
# roles/secretmanager.secretAccessor on it. Only `brett-database-url` and
# `brett-mcp-auth-secret` existed as of the Phase 2 deploy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Never inherit `gcloud config get-value project`: the active project on a developer
# machine is routinely something unrelated, and a silent deploy into the wrong
# project is expensive to notice.
PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"
REGION="${BRETT_GCP_REGION:-us-central1}"
JOB="${BRETT_SYNC_JOB:-brett-sync-hevy}"
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

# One attempt plus one retry. A Hevy full sync is idempotent and resumable from its
# checkpoint (HEVY-08/09), so a retry is safe -- but a high retry count on a 6-hourly
# schedule can stack executions, and the next scheduled run is only hours away.
MAX_RETRIES="${BRETT_SYNC_MAX_RETRIES:-1}"
# Generous: /v1/workouts caps pageSize at 10, so a full historical sync is hundreds of
# sequential requests with tenacity backoff between failures.
TASK_TIMEOUT="${BRETT_SYNC_TASK_TIMEOUT:-1800s}"

# The command/args pair below overrides the buildpack's `web` entrypoint (the
# Procfile declares only a web process); PYTHONPATH=backend from the env file makes
# `app` importable.
#
# Deliberately absent, and asserted absent by the test module named above: the
# service-only public-ingress flag (a job has no ingress to open), the inline
# environment flag (it wipes everything --env-vars-file supplies), the Cloud SQL and
# VPC-connector flags (the database is Neon over ordinary public egress), and the
# instance-scaling flags (a job has tasks, not instances).
#
# The MCP connector credential is deliberately NOT bound: the CLI never constructs a
# token verifier, so a compromised sync task cannot read or mint it (T-07-19).
exec gcloud run jobs deploy "$JOB" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source="$REPO_ROOT" \
  --service-account="$RUNTIME_SA" \
  --command=python \
  --args=-m,app.cli,sync-hevy \
  --tasks=1 \
  --max-retries="$MAX_RETRIES" \
  --task-timeout="$TASK_TIMEOUT" \
  --memory=512Mi \
  --env-vars-file="$REPO_ROOT/deploy/sync-job.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,HEVY_API_KEY=brett-hevy-api-key:latest" \
  --set-build-env-vars="UV_FROZEN=1,UV_NO_DEV=1" \
  --quiet

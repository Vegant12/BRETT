#!/usr/bin/env bash
# One-time creation of the Cloud Scheduler trigger for the Hevy sync job (D-10).
#
# Separate from scripts/deploy-sync-job.sh on purpose: the job is redeployed on every
# code change, the schedule is created once. Re-running this script updates the
# existing schedule rather than failing, so it is safe to run again.
#
# Blueprint 38 wants a sync every 1-6 hours. Six hours, on the hour, in the user's own
# timezone: the analytics layer buckets by local Monday-start weeks in Asia/Jakarta, so
# a UTC-scheduled sync would land at four arbitrary local times and make "when was this
# last synced" harder to reason about than it needs to be.
#
# PREREQUISITE, one-time: `brett-run@` must hold roles/run.invoker on the job, and the
# cloudscheduler.googleapis.com API must be enabled (plan 07-07 does both).
set -euo pipefail

# Never inherit `gcloud config get-value project`: a schedule created in the wrong
# project points at a job that does not exist and fails silently on a timer.
PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"
REGION="${BRETT_GCP_REGION:-us-central1}"
JOB="${BRETT_SYNC_JOB:-brett-sync-hevy}"
SCHEDULE_NAME="${BRETT_SYNC_SCHEDULE:-brett-sync-hevy-6h}"
SCHEDULE="${BRETT_SYNC_CRON:-0 */6 * * *}"
TIME_ZONE="${BRETT_SYNC_TZ:-Asia/Jakarta}"
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

# The Run Admin API's `:run` endpoint is the documented way to trigger a Cloud Run Job
# on a schedule. The job name here must match the one deploy-sync-job.sh deploys --
# backend/tests/test_sync_job_deploy.py compares the two defaults.
RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB}:run"

# create-or-update: `describe` decides which verb to use, so a re-run is not an error.
if gcloud scheduler jobs describe "$SCHEDULE_NAME" \
     --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi

# --attempt-deadline=60s bounds the `:run` API call that STARTS the execution, not the
# sync itself. Cloud Run Jobs return as soon as the execution is created, so 60s is
# generous for that call; the job's own --task-timeout=1800s is what bounds the work.
# Setting this to the sync's duration instead would be a category error.
#
# --oauth-service-account-email makes the scheduler authenticate to the Run Admin API
# as brett-run@ rather than hitting an unauthenticated endpoint (T-07-20).
exec gcloud scheduler jobs "$VERB" http "$SCHEDULE_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIME_ZONE" \
  --uri="$RUN_URI" \
  --http-method=POST \
  --oauth-service-account-email="$RUNTIME_SA" \
  --attempt-deadline=60s \
  --quiet

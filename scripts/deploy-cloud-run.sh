#!/usr/bin/env bash
# The single reproducible description of how BRETT deploys (D-06e). This replaces
# render.yaml: it is what a future reader opens to learn how this service reaches
# production, and backend/tests/test_cloud_run_deploy.py asserts every flag below
# is still here.
#
# Requires: gcloud >= 578, an authenticated account, and the project bootstrap
# performed by plan 02-05 (APIs enabled, runtime service account, secrets created).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Never inherit `gcloud config get-value project`: the active project on a
# developer machine is routinely something unrelated, and a silent deploy into the
# wrong project is expensive to notice.
PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"
REGION="${BRETT_GCP_REGION:-us-central1}"
SERVICE="${BRETT_SERVICE:-brett}"
# D-06f: 0 while proving the pipeline, 1 before any real connector test. Prefer
# flipping it with `gcloud run services update SERVICE --min=1`, which is a
# service-level change and needs no rebuild.
MIN_INSTANCES="${BRETT_MIN_INSTANCES:-0}"
# Bounds total Postgres connections: SQLAlchemy holds at most 10 per instance.
MAX_INSTANCES="${BRETT_MAX_INSTANCES:-2}"
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"

exec gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source="$REPO_ROOT" \
  --service-account="$RUNTIME_SA" \
  --allow-unauthenticated \
  --port=8080 \
  --min="$MIN_INSTANCES" \
  --max="$MAX_INSTANCES" \
  --cpu-boost \
  --memory=512Mi \
  --timeout=300 \
  --env-vars-file="$REPO_ROOT/deploy/cloud-run.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
  --set-build-env-vars="UV_FROZEN=1,UV_NO_DEV=1" \
  --quiet

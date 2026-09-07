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

# DEPLOY-04: production ran a schema BEHIND the deployed code three separate times during v2.0 --
# Phase 8 (`alembic current` was 0004, the code needed 0005), the Phase 9 operator run (the
# shell was pointed at the wrong DATABASE_URL, so the before-state read was stale), and the
# Phase 13 spike (0005 vs 0006, surfacing in production as
# `UndefinedTableError: relation "user_program_history" does not exist`). Every one of those was
# a human forgetting to migrate, not a missing detector, so this step APPLIES the pending
# migrations (D-01) and then independently re-verifies that they landed (D-02) rather than
# trusting the upgrade command's exit code. The strict-mode flags declared at the top of this
# file are what turns any failure below into an abort BEFORE `exec gcloud run deploy` runs.
#
# D-05: the URL is fetched from Secret Manager here rather than inherited from the shell,
# because a wrong DATABASE_URL in an operator's environment is precisely what the Phase 9
# incident was. D-06: BRETT_DATABASE_URL is the deliberate escape hatch for testing this
# pipeline against a non-production database; leave it unset and the production path always
# resolves through `gcloud secrets versions access`. --project is pinned for the same reason it
# is pinned on the deploy below: the active gcloud project on a developer machine is routinely
# something unrelated.
#
# The value is passed per-command and never `export`ed, so it does not enter the environment of
# the gcloud invocation below, and it is never echoed. Never enable shell tracing (the -x flag)
# in this file: it would print the production DSN into the terminal and into any CI log
# capturing this deploy.
#
# WR-01: `gcloud secrets versions access` failing outright (PERMISSION_DENIED, NOT_FOUND) is a
# DIFFERENT failure shape than it succeeding with an empty payload, and `set -euo pipefail` alone
# would abort on the former before the empty-value check below ever ran, surfacing gcloud's raw
# stderr with no DEPLOY-04 prefix. Capture that failure explicitly so both shapes get a
# DEPLOY-04-prefixed message an operator can find in docs/runbook-deploy.md.
if [[ -n "${BRETT_DATABASE_URL:-}" ]]; then
  DATABASE_URL="$BRETT_DATABASE_URL"
else
  GCLOUD_ERR_FILE="$(mktemp)"
  if ! DATABASE_URL="$(gcloud secrets versions access latest --project="$PROJECT_ID" --secret="brett-database-url" 2>"$GCLOUD_ERR_FILE")"; then
    GCLOUD_ERR="$(cat "$GCLOUD_ERR_FILE")"
    rm -f "$GCLOUD_ERR_FILE"
    echo "DEPLOY-04: failed to resolve DATABASE_URL from Secret Manager (brett-database-url); gcloud secrets versions access latest --secret=brett-database-url exited non-zero. This is an IAM permission or missing-secret-version issue, not an empty-value one. gcloud said: $GCLOUD_ERR" >&2
    exit 1
  fi
  rm -f "$GCLOUD_ERR_FILE"
fi

# An empty value here would make `alembic upgrade head` fail with a pydantic ValidationError
# about a missing field, which reads like a code bug rather than a missing secret. Distinct from
# the branch above: this is gcloud exiting 0 with an empty payload (e.g. an empty secret version),
# not gcloud failing outright.
if [[ -z "$DATABASE_URL" ]]; then
  echo "DEPLOY-04: DATABASE_URL resolved to an empty value; gcloud secrets versions access latest --secret=brett-database-url returned nothing and BRETT_DATABASE_URL is unset. Refusing to deploy." >&2
  exit 1
fi

# Which source was used, WITHOUT the value: migrating the wrong database is as bad as not
# migrating, and this line is the only record of which one this deploy touched.
if [[ -n "${BRETT_DATABASE_URL:-}" ]]; then
  echo "DEPLOY-04: using the BRETT_DATABASE_URL override (non-production path)"
else
  echo "DEPLOY-04: using Secret Manager brett-database-url:latest in project $PROJECT_ID"
fi

# D-01: apply, do not merely detect. alembic runs from backend/ because alembic.ini lives there,
# and via its own CLI for the same reason this script shells out to gcloud.
(cd "$REPO_ROOT/backend" && DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head)

# D-02: an independent confirmation that `alembic current` now equals `alembic heads`. A partial
# or silently-incomplete apply exits 1 here and the deploy never happens. The predicate lives in
# backend/app/db/migration_preflight.py so backend/tests/test_migration_preflight.py can call it
# directly against a real drifted database (D-04).
(cd "$REPO_ROOT/backend" && DATABASE_URL="$DATABASE_URL" PYTHONPATH="$REPO_ROOT/backend" uv run python -m app.db.migration_preflight)

# The memory request below was RAISED to a full gigabyte from the half-gigabyte value this
# service originally shipped with, and must not be tuned back down: RESEARCH Pitfall 5 measured
# ~235 MB peak resident memory decoding a 10 MB Health Auto Export ingest body. A Cloud Run OOM
# answers 503 with no application log line, so the failure looks like an outage with no cause.
# Paired with INGEST_MAX_BODY_BYTES, which returns 413 before the JSON parse ever starts.
# (The old value is described rather than written here so a grep for it stays meaningful --
# backend/tests/test_cloud_run_deploy.py asserts on both spellings of the flag.)
#
# HEALTH_INGEST_SECRET is bound from Secret Manager below and must never appear in
# deploy/cloud-run.env.yaml -- every value in an --env-vars-file is a literal committed to git.
#
# NOTE for future editors: this rationale lives ABOVE the invocation, not beside the flag it
# explains, because a `#` comment between two backslash-continued lines TERMINATES the command
# there. `bash -n` still reports the file as valid, and the deploy would silently run with every
# flag after the comment dropped -- no env file, no secrets, no memory setting. Never put a
# comment inside the block below; `test_deploy_script_has_no_comment_inside_the_gcloud_call`
# fails the build if anyone does.
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
  --memory=1Gi \
  --timeout=300 \
  --env-vars-file="$REPO_ROOT/deploy/cloud-run.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest,HEALTH_INGEST_SECRET=brett-health-ingest-secret:latest" \
  --set-build-env-vars="UV_FROZEN=1,UV_NO_DEV=1" \
  --quiet

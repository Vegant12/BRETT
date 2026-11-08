# BRETT

A personal fitness data platform that turns your training and health data into a long-term,
data-driven body recomposition coach. BRETT syncs workouts from [Hevy](https://www.hevyapp.com/),
Apple Health activity and nutrition, and body measurements into PostgreSQL, calculates
deterministic analytics on top, and exposes everything through a remote
[MCP](https://modelcontextprotocol.io/) server, so Claude answers "Am I progressing?" and
"Which muscles are undertrained?" from your real data instead of guessing.

![BRETT architecture: Hevy and Apple Health feed ingest, PostgreSQL and analytics, served to Claude through an MCP server](docs/images/architecture.svg)

## What it does

- **Hevy sync**: idempotent full and incremental sync of workouts, exercise templates and body
  measurements, with exercises mapped to canonical muscle groups.
- **Apple Health**: steps, energy, distance and nutrition via a
  [Health Auto Export](docs/health-auto-export-setup.md) webhook. No native app needed.
- **Analytics**: weekly and per-muscle volume, training frequency, exercise progression with
  estimated 1RM, plateaus, personal records, body weight and measurement trends, and a
  recomposition verdict that respects the active training program (Lean Bulk, Cut or Recomp).
- **Physique log**: Claude rates visible development from progress photos. BRETT stores only the
  structured rating, never the image.
- **Reports**: weekly and monthly reports that combine training, nutrition, measurements and
  physique in one call.
- **22 MCP tools**, authenticated with OAuth 2.1 (WorkOS AuthKit). The server is read-only apart
  from two narrow, non-destructive write tools: switching the training program (two-step
  confirmation) and logging a physique observation.

Deployed on Google Cloud Run. See `.planning/PROJECT.md` for scope and `.planning/ROADMAP.md`
for the phase plan.

## Docs

- [Coaching instructions](docs/coaching-instructions.md): the Claude Project prompt that makes Claude the coach
- [Health Auto Export setup](docs/health-auto-export-setup.md)
- [Hevy API observations](docs/hevy-api-observations.md)
- Runbooks: [deploy](docs/runbook-deploy.md), [backup/restore](docs/runbook-backup-restore.md),
  [secret rotation](docs/runbook-secret-rotation.md), [sync schedule](docs/runbook-sync-schedule.md)

## Requirements

- Python 3.13 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- Docker (local Postgres + the test container)

## Local setup

    uv sync --group dev
    uv run pre-commit install
    cp .env.example .env        # then fill in DATABASE_URL
    docker compose up -d db

For the Docker Compose database, use:

    DATABASE_URL=postgresql://brett:brett_local_dev@localhost:5432/brett

`brett_local_dev` is a throwaway local-only credential for a container bound to localhost — it
is not used in any deployed environment. Never commit a real `.env`.

## Migrations

Migrations are the sole authority over the schema — never `create_all()`, and never run at
app startup. Every command below reads `DATABASE_URL` from the environment, so export it (or
keep it in `.env`) first.

    cd backend
    uv run alembic upgrade head      # build the schema + seed the default user
    uv run alembic downgrade base    # tear it back down
    uv run alembic current
    uv run alembic check             # fails if models and migrations have drifted

## Run

    uv run uvicorn app.main:app --reload --app-dir backend
    curl http://localhost:8000/health
    # {"status":"ok","database":"connected"}

`/health` is deliberately unauthenticated and returns `{status, database}` only — the
`database` field is a live `SELECT 1` probe, and an unreachable database yields
`503 {"status":"degraded","database":"error"}` with no connection detail.

## Syncing Hevy data

    PYTHONPATH=backend uv run python -m app.cli sync-hevy
    PYTHONPATH=backend uv run python -m app.cli sync-status
    PYTHONPATH=backend uv run python -m app.cli mapping-gaps

`sync-hevy` syncs exercise templates, workouts and body measurements, in that order. It picks
its own workout strategy: the full `/v1/workouts` import the first time, and the
`/v1/workouts/events` delta on every run after that. Force one with `--full` or
`--incremental` (they are mutually exclusive), or narrow the run with
`--only {workouts,templates,body}`, which is repeatable.

`sync-status` prints one line per resource — `resource: last_synced_at (status)`, or `never`
for a resource that has not run yet. It reads only the local database, so it works without a
Hevy key.

`mapping-gaps` prints every exercise template that resolves to no canonical muscle group,
one per line as `external_id  title  [deliberate|GAP]`, then a summary count. `deliberate`
means the template is listed in `DELIBERATELY_UNMAPPED` (cardio, conditioning, `neck` — the
intended end state); `GAP` means nobody has curated it yet. **It always exits 0**, even with
gaps: an unmapped exercise is a supported state (D-03), so this is an inspection command and
never a build gate. It reads only the local database, so it works without a Hevy key.

`HEVY_API_KEY` must be set for `sync-hevy`; without it the command exits 1 and names the
variable. `PYTHONPATH=backend` is required because `backend/` is the import root (the same
reason the `Procfile` passes `--app-dir backend`).

This CLI is the verification and operations trigger, and it stays the way to force a sync by
hand. Production sync runs as a **Cloud Run Job on a 6-hourly Cloud Scheduler trigger**
(`0 */6 * * *`, `Asia/Jakarta`), deployed by `scripts/deploy-sync-job.sh` and scheduled once by
`scripts/create-sync-schedule.sh`. The job runs the same `python -m app.cli sync-hevy` command
this section documents, with `HEVY_API_KEY` and `DATABASE_URL` bound from Secret Manager.

## Tests

    uv run pytest backend/tests -x -q -m "not integration"   # fast, no container
    uv run pytest backend/tests -q --cov=backend/app         # full suite (Docker required)
    uv run ruff check .
    uv run mypy backend/app

## Conventions

- All timestamps are stored in UTC (`TIMESTAMPTZ`); convert only at calculation boundaries
  via `app.core.time`.
- The user's timezone lives in `users.timezone`, not in an env var.
- Secrets come from the environment only. Never log a secret; `app.logging` applies a
  three-layer redaction pipeline to app and third-party log records alike.

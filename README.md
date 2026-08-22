# BRETT

Personal fitness data platform: Hevy → PostgreSQL → analytics → remote MCP server.
See `.planning/PROJECT.md` for scope and `.planning/ROADMAP.md` for the phase plan.

## Requirements

- Python 3.13 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- Docker (local Postgres + the test container)

## Local setup

    uv sync
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

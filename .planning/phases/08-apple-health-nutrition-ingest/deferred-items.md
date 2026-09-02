# Phase 8 — Deferred Items

Out-of-scope discoveries logged during execution. Each entry names the plan that found it.
Append new sections; do not rewrite existing ones.

## From plan 08-02

- **`backend/app/mcp/server.py` fails `ruff format --check`** (pre-existing on the phase base
  commit `d688789`, untouched by this plan). `ruff format` wants to collapse the
  `fitness_get_muscle_group_volume` description string at `server.py:180-181` onto one line.
  `ruff format` is a pre-commit hook, so this will surface on the next commit that touches
  `server.py`. Not fixed here: the file is outside plan 08-02's `files_modified`, and
  reformatting it would put an unrelated diff into an Apple Health freshness commit. One-line
  fix: `uv run ruff format backend/app/mcp/server.py`.

# Deferred Items — Phase 01 Backend Foundation

Out-of-scope discoveries logged during execution. Not fixed by the plan that found them.

| Found in | Item | Why deferred |
|----------|------|--------------|
| 01-01 Task 1 | `.planning/config.json` has no trailing newline, so the `end-of-file-fixer` pre-commit hook rewrites it on every `pre-commit run --all-files`. | Pre-existing tracked file owned by the GSD orchestrator, not created or modified by this plan. Reverted rather than fixed to avoid touching a shared artifact mid-wave. |
| 01-01 Task 1 | `uv self update` cannot run — the active `uv` (0.11.7) is on a different volume than the standalone installer's target, so uv refuses to self-update. CLAUDE.md specifies 0.12.5. | Environment/toolchain issue outside the repo. 0.11.7 resolved every pinned version in `pyproject.toml` with no conflicts, so it is not blocking. |
| 01-05 Task 2 | `uv run pre-commit run --all-files` rewrites `backend/migrations/versions/0001_initial_schema.py` (`ruff-format`, trailing-comment alignment) and `backend/migrations/README` (`end-of-file-fixer`, missing trailing newline). | Both are Plan 01-03 artifacts, untouched by this plan. Reverted rather than committed, per the executor scope boundary. Worth one housekeeping commit at phase verification, together with the `.planning/config.json` row above. |
| 01-05 Task 2 | `ruff format --check .` flags fenced Python blocks inside `.planning/**/*.md` (PLAN, RESEARCH, STACK, ARCHITECTURE) — 8 files. | Those are documentation, not source. Consider adding `.planning/` to `[tool.ruff] exclude` so the formatter stops rewriting planning artifacts. |

# Deferred Items — Phase 01 Backend Foundation

Out-of-scope discoveries logged during execution. Not fixed by the plan that found them.

| Found in | Item | Why deferred |
|----------|------|--------------|
| 01-01 Task 1 | `.planning/config.json` has no trailing newline, so the `end-of-file-fixer` pre-commit hook rewrites it on every `pre-commit run --all-files`. | Pre-existing tracked file owned by the GSD orchestrator, not created or modified by this plan. Reverted rather than fixed to avoid touching a shared artifact mid-wave. |
| 01-01 Task 1 | `uv self update` cannot run — the active `uv` (0.11.7) is on a different volume than the standalone installer's target, so uv refuses to self-update. CLAUDE.md specifies 0.12.5. | Environment/toolchain issue outside the repo. 0.11.7 resolved every pinned version in `pyproject.toml` with no conflicts, so it is not blocking. |

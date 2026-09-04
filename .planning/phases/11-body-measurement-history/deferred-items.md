# Deferred Items — Phase 11 Plan 03

Items discovered during execution that are out of this plan's scope (pre-existing, not caused
by this plan's changes) and were therefore left unfixed per the executor's scope-boundary rule.

| File | Issue | Evidence it's pre-existing |
|------|-------|------------------------------|
| `backend/app/mcp/server.py:182` | `ruff format` would reflow the `fitness_get_muscle_group_volume` tuple-entry description onto one line | `git show HEAD:backend/app/mcp/server.py` (commit `d04cd15`, Phase 7) already contains this exact wrapped form; this plan's diff never touches that line |
| `backend/tests/test_mcp_isolation.py:73` | `ruff format` wants a second blank line before `def _mcp_modules()` | Confirmed against `git show HEAD:backend/tests/test_mcp_isolation.py` in isolation — the file already fails `ruff format --check` before this plan's two one-line edits (renumbering `12`→`13`) |

Both were already present in the 18-file `ruff format --check backend/` count documented in
Plan 01's and Plan 02's summaries as "pre-existing, unrelated files elsewhere in the repo."
Neither blocks this plan's `<verify>` blocks, which scope `ruff format --check` to
`backend/app/mcp/` (Task 1) — clean — and to explicit pytest invocations (Tasks 2-3), not a
repo-wide format check.

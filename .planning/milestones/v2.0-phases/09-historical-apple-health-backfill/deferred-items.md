# Phase 9 — Deferred Items

Out-of-scope discoveries logged during execution. Not fixed, per the executor scope boundary
(only issues directly caused by the current task's changes are auto-fixed).

## `uv run ruff format --check backend` is red on 18 pre-existing files

**Found during:** plan 09-01, Task 2 (running the plan's stated `<verification>` block).

**What:** `uv run ruff format --check backend` exits 1 with "18 files would be reformatted".
None of the 18 are files plan 09-01 touched; all are unmodified in the working tree, so the
drift is committed state, not something this plan introduced.

Flagged files:

```
backend/app/integrations/hevy/events.py
backend/app/integrations/hevy/sync.py
backend/app/integrations/hevy/workouts.py
backend/app/mcp/server.py
backend/app/normalization/resolver.py
backend/tests/test_analytics_comparison.py
backend/tests/test_analytics_estimates.py
backend/tests/test_analytics_frequency.py
backend/tests/test_cli.py
backend/tests/test_hevy_body.py
backend/tests/test_hevy_end_to_end.py
backend/tests/test_hevy_events.py
backend/tests/test_hevy_sync.py
backend/tests/test_hevy_templates.py
backend/tests/test_mcp_isolation.py
backend/tests/test_normalization_mapping.py
backend/tests/test_repository_workouts.py
backend/tests/test_sync_job_deploy.py
```

**Why it went unnoticed:** every diff is ruff wanting to JOIN a call that was hand-wrapped
across three lines but fits inside `line-length = 100` when joined, e.g.

```python
# committed
existed = await delete_workout(
    session, user_id=user_id, external_id=event.id
)
# ruff 0.16.4 would write
existed = await delete_workout(session, user_id=user_id, external_id=event.id)
```

`.pre-commit-config.yaml` runs `ruff-format` as a pre-commit hook, and pre-commit passes it only
the files staged in that commit. A file whose formatting drifted before it was last touched (or
before `line-length` reached 100) is therefore never re-checked. A whole-tree
`ruff format --check` has apparently never been part of the gate.

**Verified as pre-existing:** `git status --short` during plan 09-01 showed only
`backend/tests/conftest.py`, `pyproject.toml` and the new
`backend/tests/test_health_auto_export_backfill.py` as changed. Both files this plan touched
pass `ruff format --check` individually.

**Recommendation:** a one-shot `uv run ruff format backend` in its own `style(...)` commit,
plus adding whole-tree `ruff format --check` to the phase gate so it cannot drift again. Doing
it inside a Phase 9 plan would bury 18 unrelated files in a backfill diff, so it is deferred
rather than fixed here.

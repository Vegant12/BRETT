# Deferred Items — Phase 17

## Plan 17-02

- **Pre-existing `ruff format --check backend` failures, unrelated to this plan.** The plan's
  whole-backend `<verification>` block (`uv run ruff format --check backend`) reports 21 files
  needing reformatting: `app/analytics/health.py`, `app/analytics/reports.py`,
  `app/db/migration_preflight.py`, `app/integrations/hevy/events.py`,
  `app/integrations/hevy/sync.py`, `app/integrations/hevy/workouts.py`,
  `app/normalization/resolver.py`, and fourteen files under `tests/`. None of these files were
  touched by plan 17-02 (`git status --short` on each returns clean against the pre-plan HEAD),
  so this is a pre-existing drift — likely a `ruff` version difference between when those files
  were last formatted and the version pinned today — not a regression introduced here. Per the
  executor's SCOPE BOUNDARY rule, out-of-scope pre-existing issues are logged, not fixed.
  `app/analytics/schemas.py`, `app/analytics/physique.py` and
  `tests/test_analytics_physique.py` (this plan's three files) all pass
  `ruff format --check` individually.
- **Pre-existing `ruff check backend` failure, unrelated to this plan.** One `E501` (line too
  long) in `app/db/migration_preflight.py:144`, a file this plan does not touch.
- **Pre-existing `mypy` errors in `tests/conftest.py`** (lines 308-328: `_R` type-var / async
  generator return-type / unused `type: ignore` on the `engine`/`session` fixtures). These
  surface when running `mypy` against ANY test module that imports `tests.conftest`
  (confirmed identical against `tests/test_analytics_recomposition.py`, an unrelated,
  pre-existing test module), so they are not caused by `tests/test_analytics_physique.py`.

## Plan 17-05

- **Pre-existing `ruff format --check backend/tests` failures, unrelated to this plan.** Running
  the full-directory check reports 14 files needing reformatting (`test_analytics_comparison.py`,
  `test_analytics_estimates.py`, `test_analytics_frequency.py`, `test_analytics_health.py`,
  `test_hevy_templates.py`, `test_normalization_mapping.py`, `test_repository_workouts.py`,
  `test_sync_job_deploy.py`, and others), the same class of drift 17-02 already logged, now
  extended to more test files -- likely the same `ruff` version skew. None of these files were
  touched by this plan. `test_mcp_tool_schemas.py`, `test_mcp_tool_budget.py`,
  `test_mcp_mount.py`, and `test_mcp_auth.py` (this plan's four touched test files) all pass
  `ruff format --check` individually.
- **Pre-existing stale docstring, `test_mcp_tool_budget.py:313`.** `test_every_tool_response_fits_its_budget`'s
  docstring says "Thirteen tools, at their published caps" while `BUDGETS` already held 20 keys
  before this plan added two more (now 22). The drift predates this plan (a prior plan's leftover
  count) and this plan's task list does not name this docstring for correction; left as observed
  per the SCOPE BOUNDARY rule rather than fixed opportunistically.
- **Acceptance-criteria grep imprecision, `backend/app/mcp/server.py`.** The Task 1 acceptance
  criterion `grep -c "destructive_hint=False" backend/app/mcp/server.py` expected `2` but the real
  count is `3`: the third match is the literal text `` `destructive_hint=False` `` appearing inside
  the `NON_DESTRUCTIVE_WRITE_TOOL` comment block (the plan's own action text includes this phrase
  in backticks), not a second field assignment. `READ_ONLY.destructive_hint=False` and
  `NON_DESTRUCTIVE_WRITE_TOOL.destructive_hint=False` are the only two live field assignments,
  matching PHYS-06's intent exactly; the acceptance criterion undercounted its own comment prose.
  Same class of plan-authoring grep imprecision the 17-01 and 17-03 summaries already documented.

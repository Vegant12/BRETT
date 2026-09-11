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

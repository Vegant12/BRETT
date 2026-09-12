# Deferred Items — Phase 18

Out-of-scope discoveries found during execution of plan 18-01. Not fixed, per the executor's
scope boundary (only auto-fix issues directly caused by the current task's changes).

## `backend/app/analytics/health.py` fails `ruff format --check`

Found while running plan 18-01's phase-level `<verification>` block
(`uv run ruff format --check backend/app/analytics backend/tests/test_analytics_reports.py`).
Three pre-existing lines (around `get_nutrition_trend`'s signature and two `Decimal(...)
.to_integral_value(...)`/`.quantize(...)` call sites) exceed the 100-column formatter target
after some prior ruff-version change, unrelated to this phase's physique work. This file is not
touched by any 18-01/18-02/18-03 task. Left as-is; a future formatting-only pass across the repo
should pick it up.

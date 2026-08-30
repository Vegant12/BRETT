---
phase: 04-volume-frequency-analytics
reviewed: 2026-08-30T11:06:37Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - backend/app/analytics/__init__.py
  - backend/app/analytics/frequency.py
  - backend/app/analytics/metadata.py
  - backend/app/analytics/rollup.py
  - backend/app/analytics/schemas.py
  - backend/app/analytics/volume.py
  - backend/app/core/time.py
  - backend/app/db/models/exercise.py
  - backend/tests/conftest.py
  - backend/tests/test_analytics_fixtures.py
  - backend/tests/test_analytics_frequency.py
  - backend/tests/test_analytics_isolation.py
  - backend/tests/test_analytics_metadata.py
  - backend/tests/test_analytics_rollup.py
  - backend/tests/test_analytics_volume.py
  - backend/tests/test_time.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-08-30T11:06:37Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

This phase implements deterministic volume and frequency analytics (`app/analytics/`) on top of a
carefully window-guarded, `Decimal`-based SQL rollup, plus the `app/core/time.py` timezone-bucketing
substrate it depends on. The module docstrings and the accompanying test suite already document (and
pin, with dedicated regression tests) the exact defects a reviewer would normally be hunting for:
session-count inflation from summing instead of de-duplicating workout ids, tonnage silently
coerced from `None` to `0`, warm-up/dropset misclassification, naive-UTC week-boundary bucketing,
and the muscle-override REPLACEMENT-vs-MERGE trap. Each of those is independently enforced by both
a static boundary test (`test_analytics_isolation.py`) and a runtime fixture test, which is an
unusually strong pairing.

Read carefully against those same failure modes, the implementation is internally consistent: the
`(week, workout_id, template_id)` aggregate grain, the operand-presence tonnage gate, the
`session_ids: set[...]` accumulators, and the window-snap-vs-raw-range split between VOL-01/02 and
VOL-03 all match what their respective tests assert. No SQL string concatenation, no unbound
timezone parameter, no `eval`/dynamic code execution, and no committed secret was found. The
`app/analytics/` package boundary (no `app.integrations`, no `app.mcp`, no direct
`exercise_muscles`/`exercise_muscle_overrides` ORM reference, no session writes) is both honored in
the source and statically enforced.

One forward-looking gap is worth recording (see IN-01) — it does not affect correctness in v1
(single provider), but the codebase's own convention is to call out single-provider simplifications
explicitly wherever one is made, and this one call site does not.

## Info

### IN-01: `_template_titles` resolves exercise titles without a provider predicate

**File:** `backend/app/analytics/frequency.py:82-103`

**Issue:** `ExerciseTemplate` is unique per `(user_id, provider, external_id)` (see
`backend/app/db/models/exercise.py:93-100`), meaning two different providers can legitimately own a
template with the same `external_id` for the same user. `_template_titles` filters only on
`ExerciseTemplate.user_id` and `external_id.in_(...)`:

```python
result = await session.execute(
    select(ExerciseTemplate.external_id, ExerciseTemplate.title).where(
        ExerciseTemplate.user_id == user_id,
        ExerciseTemplate.external_id.in_(list(template_external_ids)),
    )
)
return {external_id: title for external_id, title in result.all()}
```

In v1 this is safe because `provider` is a hardcoded `"hevy"` literal everywhere a `Workout`/
`ExerciseTemplate` row is written, so no collision can occur today. Once a second provider is added
(a stated future milestone per `CLAUDE.md`'s "Provider isolation" constraint), a user with two
providers using the same external id would get one provider's title non-deterministically applied to
the other's row in this dict comprehension — silently, with no error. This mirrors exactly the class
of defect this phase's own docstrings warn about elsewhere ("a plausible-looking number that is
quietly wrong"), just one call site removed from the ones already covered by a test.

This is the one query in the reviewed set that both touches `exercise_templates` and omits the
provider predicate; `weekly_set_rows` and `resolve_row_muscles` key off the same plain
`exercise_template_external_id` string, so the gap is systemic to the current schema design rather
than unique to this function — but this is the only site of the ones reviewed where it is silent
and unexplained (every other single-provider simplification in these files, e.g.
`ExerciseTemplate.provider`'s "Literal 'hevy' in v1" comment, is called out explicitly).

**Fix:** Either scope the query explicitly and document the v1 assumption the same way the model
does:

```python
from app.db.repositories.sync_state import PROVIDER_HEVY

result = await session.execute(
    select(ExerciseTemplate.external_id, ExerciseTemplate.title).where(
        ExerciseTemplate.user_id == user_id,
        ExerciseTemplate.provider == PROVIDER_HEVY,  # v1: single provider; revisit at HEVY-05
        ExerciseTemplate.external_id.in_(list(template_external_ids)),
    )
)
```

or add a short comment acknowledging the same-external-id-across-providers case is out of scope for
v1, matching the documentation standard the rest of the module already holds itself to.

---

_Reviewed: 2026-08-30T11:06:37Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 05-progression-records-recomposition-analytics
reviewed: 2026-08-31T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - backend/app/analytics/__init__.py
  - backend/app/analytics/bodyweight.py
  - backend/app/analytics/comparison.py
  - backend/app/analytics/estimates.py
  - backend/app/analytics/metadata.py
  - backend/app/analytics/progression.py
  - backend/app/analytics/recomposition.py
  - backend/app/analytics/records.py
  - backend/app/analytics/rollup.py
  - backend/app/analytics/schemas.py
  - backend/tests/conftest.py
  - backend/tests/test_analytics_bodyweight.py
  - backend/tests/test_analytics_comparison.py
  - backend/tests/test_analytics_estimates.py
  - backend/tests/test_analytics_isolation.py
  - backend/tests/test_analytics_metadata.py
  - backend/tests/test_analytics_progression.py
  - backend/tests/test_analytics_recomposition.py
  - backend/tests/test_analytics_records.py
  - backend/tests/test_analytics_rollup.py
findings:
  critical: 0
  warning: 2
  info: 0
  total: 2
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-08-31T00:00:00Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

This phase (progression, records, recomposition analytics) is unusually well-documented and
disciplined: every business rule is named against a decision id (D-01..D-20), most numeric
constants are derived rather than invented, `Decimal` is used exhaustively and enforced
statically (`test_analytics_isolation.py`), the read-only/no-provider-leak/no-MCP-leak
boundaries are enforced by regex-based static tests rather than convention alone, and the
None-vs-zero distinction ("we could not compute this" vs "it is genuinely zero") is drawn
correctly almost everywhere it matters (tonnage, volume, e1RM, plateau duration, weight
averages). No security issues, hardcoded secrets, injection vectors, or dangerous-function usage
were found — SQL is fully parameterized, raw-SQL `text()` is statically banned, and analytics
functions never write to the session (also statically enforced).

Two logic issues were found, both in data-quality/interpretation territory rather than in the
core arithmetic (Epley, OLS slope, plateau streak scan, tie-breaks, and net-progression scoring
all check out against their extensive test suites). Neither is a crash or a security issue, but
both can cause a caller (ultimately Claude, via the eventual MCP tools) to misread how much
training data actually backs a number.

## Warnings

### WR-01: Per-muscle-group comparison reports `None` (not zero) for a period a muscle group was never trained in

**File:** `backend/app/analytics/comparison.py:325-342`
**Issue:**

`_muscle_comparison` builds each of the three per-muscle rates (`direct_sets`, `indirect_sets`,
`weighted_sets`) with:

```python
period_a=_maybe_per_week(None if bucket_a is None else bucket_a.direct_sets, days_a),
```

`bucket_a` is `None` whenever `fold_window_by_muscle` produced no entry for that muscle group in
period A at all (i.e. the muscle received zero direct AND zero indirect sets that period) — see
`rollup.py::_fold_by_muscle`, which only creates a `MuscleBucket` when a resolved muscle is
actually reached by a row. Because `bucket_a is None` collapses to `_maybe_per_week(None, ...)`,
the resulting `ComparisonRate.period_a_per_week` is `None`.

Everywhere else in this codebase, `None` is reserved for "this quantity could not be computed /
was not observed at all" (an exercise never performed that period, a period with no
weight-and-reps sets, etc. — see `comparison.py`'s own module docstring and `_maybe_per_week`'s
docstring). A muscle group that was simply never touched in a period is not an unmeasurable
quantity — it is a well-defined, computable zero, exactly as `rollup.py`'s own sibling
`fold_weeks_by_muscle` documents for VOL-02: *"Weeks with no training produce no key here on
purpose; the caller projects onto `local_week_spine` so a zero week is a zero and not an
absence."* CMP-01's per-muscle expansion does not perform that projection, so it reports the
same "no training" fact as an absence instead of a zero.

Concretely: if muscle group X is trained in period B but not at all in period A (the union
`sorted(set(buckets_a) | set(buckets_b), ...)` still includes X because it appears in B), the
response reports `direct_sets.period_a_per_week = None` for X instead of `Decimal("0.00")`. A
consumer reading this will not be able to distinguish "we have no data for this muscle in period
A" (which would be true if, say, period A itself had `insufficient_data=True`) from "the user
trained during period A and simply did zero sets touching this muscle" (the actual fact here).
`delta_percent` is also then suppressed to `None` for a real, calculable 100%-increase-from-zero
case.

This exact scenario (a muscle group present in only one of the two periods) is not covered by
`test_analytics_comparison.py::test_muscle_groups_are_opt_in`, which only exercises a muscle
group present in both periods (where `indirect_sets` legitimately reads `0.00` because the
*bucket itself* has a zero field, not because the bucket is missing).

**Fix:**

Treat a missing bucket as a zero-valued bucket rather than as an absence, mirroring VOL-02's own
convention:

```python
_EMPTY_BUCKET = MuscleBucket()  # module-level constant; never mutated

def _muscle_comparison(
    *,
    muscle_group: CanonicalMuscleGroup,
    bucket_a: MuscleBucket | None,
    bucket_b: MuscleBucket | None,
    days_a: int,
    days_b: int,
) -> MuscleGroupComparison:
    a = bucket_a or _EMPTY_BUCKET
    b = bucket_b or _EMPTY_BUCKET
    return MuscleGroupComparison(
        muscle_group=muscle_group,
        direct_sets=_rate(
            metric="direct_sets",
            period_a=_per_week(Decimal(a.direct_sets), days_a),
            period_b=_per_week(Decimal(b.direct_sets), days_b),
        ),
        indirect_sets=_rate(
            metric="indirect_sets",
            period_a=_per_week(Decimal(a.indirect_sets), days_a),
            period_b=_per_week(Decimal(b.indirect_sets), days_b),
        ),
        weighted_sets=_rate(
            metric="weighted_sets",
            period_a=_per_week(a.weighted_sets, days_a),
            period_b=_per_week(b.weighted_sets, days_b),
        ),
    )
```

Add a test seeding a muscle group trained only in period B (e.g. a template mapped to a muscle
group not touched by any period-A exercise) and asserting `period_a_per_week == Decimal("0.00")`
and `delta_percent is not None`.

### WR-02: `PlateauReport.coverage` reflects the whole (clamped) history-seed window, not the reported lookback window

**File:** `backend/app/analytics/progression.py:683-703, 771-773`
**Issue:**

`get_plateaus` resolves its query window over `[history_start, lookback_end]`, where
`history_start` is clamped back to the user's earliest workout (or up to `MAX_ANALYTICS_WINDOW_DAYS`
≈ 5 years) so the streak scan can be seeded from history strictly before `lookback_start`:

```python
window = await resolve_window(
    session, user_id=user_id, start_day=history_start, end_day=lookback_end, snap_to_weeks=False
)
...
coverage=await build_coverage(
    session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
),
```

`PlateauReport.coverage.sessions_in_window` and `.insufficient_data` are therefore computed over
the *entire seeding window* (potentially years of history), not over `[lookback_start,
lookback_end]` — the window actually named by `lookback_weeks`/`lookback_start`/`lookback_end` on
the same response. Every other Phase 5 endpoint that carries a `CoverageMetadata` block
(`get_exercise_progression`, `get_exercise_trends`, `compare_periods`) scopes it to exactly the
window it reports on. `get_plateaus` is the one place that diverges, and nothing on
`PlateauReport`/`CoverageMetadata` documents the divergence.

This is confirmed as intentional by `test_an_oversized_lookback_is_clamped_rather_than_rejected`
(`test_analytics_progression.py:1644-1679`), whose comment states the coverage count is
"the whole account rather than a window the clamp silently truncated." However, this undermines
DQ-02's stated purpose (`metadata.py:20-22`: *"One session cannot support a per-week rate or a
trend claim"*) for this specific report: a user who has years of old, unrelated training history
but only zero or one qualifying session inside the actual 12-week (or caller-supplied) lookback
window will still see `coverage.insufficient_data == False` on a plateau report that is, in the
window it claims to describe, built on almost no data. A consumer (eventually Claude, via MCP)
reading `PlateauReport.coverage` has no way to tell this has happened, because the field's name
and the sibling `lookback_start`/`lookback_end` fields on the same model strongly imply it is
scoped to the lookback window.

**Fix:**

Either (a) compute `coverage` from the caller-facing `[lookback_start, lookback_end]` bounds
(requires resolving that narrower window's `utc_start`/`utc_end` separately from the wider fetch
window used for seeding), or (b) if the current "whole seeded history" semantics are intentional,
document it explicitly on `PlateauReport.coverage`'s field/docstring in `schemas.py` so a future
reader (and Phase 6's MCP tool description) does not assume it is scoped to `lookback_start`/
`lookback_end` the way every sibling coverage block is:

```python
class PlateauReport(_AnalyticsModel):
    """PROG-03. ``exercises`` is sorted by ``exercise_template_external_id``, ascending.

    ``coverage`` is scoped to the WIDER seed-fetch window (history back to
    MAX_ANALYTICS_WINDOW_DAYS or the account's earliest workout, whichever is later), not to
    ``[lookback_start, lookback_end]`` -- unlike every other Phase 5 response's coverage block.
    It answers "do we have data at all", not "is the reported lookback window itself
    well-populated"; a sparse lookback window with a well-populated older history still reads
    ``insufficient_data=False`` here.
    """
```

Option (a) is preferable given DQ-02's intent, since it lets a caller actually distinguish "this
specific plateau window is thin" from "we have no data anywhere."

---

_Reviewed: 2026-08-31T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

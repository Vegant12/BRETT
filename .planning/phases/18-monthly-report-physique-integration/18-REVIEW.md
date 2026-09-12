---
phase: 18-monthly-report-physique-integration
reviewed: 2026-09-12T11:50:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - backend/app/analytics/reports.py
  - backend/app/analytics/schemas.py
  - backend/app/mcp/tools/reports.py
  - backend/app/mcp/tools/schemas.py
  - backend/tests/fixtures/reports/monthly_narrative.md
  - backend/tests/test_analytics_reports.py
  - backend/tests/test_mcp_tool_schemas.py
  - backend/tests/test_mcp_tools.py
  - docs/coaching-instructions.md
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-09-12T11:50:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

This phase adds the monthly report's `physique` section (RPT-04/RPT-05): a new `PhysiqueSection`
analytics schema, a `compose_report` branch that populates it MONTHLY-only, a deterministic
`## Physique` narrative block, and an MCP-layer filter that narrows the 19-row diff spine to the
groups that moved. The work is unusually well specified — every design decision is documented
inline with its rationale (D-01 through D-13), and the test suite is exhaustive: golden-file
byte-identical narrative checks, a banned-recommendation-language scan, a numeric-provenance scan
that ties every rendered number back to `model_dump_json()`, a free-text-note exclusion/laundering
test, and end-to-end MCP tests asserting the JSON `physique` field and the `## Physique` narrative
block agree on exactly which muscle groups appear.

Verified independently: `ruff check` and `mypy` both pass clean on all four source files, and the
non-integration tests in `test_analytics_reports.py` and `test_mcp_tool_schemas.py` (42 tests) all
pass. No hardcoded secrets, no dangerous functions, no SQL/command injection surface, and no
`float` usage in any monetary/measurement field (all `Decimal`).

Two items are worth a second look, both concentrated in `compose_report`'s physique branch
(`backend/app/analytics/reports.py:192-217`) — one a real (if narrow) correctness gap, one a
minor test-coverage gap for that same code path. Nothing else in the diff rises above these.

## Warnings

### WR-01: The physique section's three-query composition can silently disagree, and one branch converts an invariant violation into a wrong answer instead of a loud failure

**File:** `backend/app/analytics/reports.py:199-217`

**Issue:** `compose_report`'s MONTHLY branch makes three independent, sequentially-awaited calls
that each re-derive "the latest non-superseded observation" on their own:

1. `get_latest_observation(session, user_id=user_id)` (line 199) — used directly for the header
   fields (`observed_on`, `pose_state`, notes, ...).
2. `get_latest_physique_diff(session, user_id=user_id)` (line 201) — internally calls
   `get_recent_observations(limit=2)`.
3. `get_physique_volume_cross_reference(session, user_id=user_id)` (line 205) — internally calls
   `get_latest_observation` a *second, independent* time (`app/analytics/physique.py:187`).

The code comment at line 203-204 states plainly: "a non-None `observation` implies a non-None
result here. The guard is type narrowing, not a real branch." That is only true if all three
calls are guaranteed to see the identical "latest observation" — which is not guaranteed under
PostgreSQL's default `READ COMMITTED` isolation level (confirmed as the isolation level this
session uses in `app/mcp/tools/_common.py`'s `read_only_session` docstring: "It works at the
DEFAULT isolation level"). Under `READ COMMITTED`, each statement — not the whole transaction —
gets its own snapshot, so a concurrent `fitness_log_physique_observation` write landing between
these three awaits could cause call #1 and call #3 to disagree about which observation is
"latest," or cause call #3 to legitimately return `None` immediately after call #1 returned a
real record.

If that ever happens, the code takes the `if cross_reference is not None:` branch at line 206 and
silently falls through with `physique` left at its initial `None` (line 192) — which is exactly
the value `ReportResult.physique`'s own docstring (`schemas.py:1018-1020`) says means "the user
has never logged an observation" (D-11). A real observation would be reported to Claude as "no
physique data," which is precisely the "plausible-looking-but-quietly-wrong" failure class this
codebase's own docstrings elsewhere (e.g. `PersonalRecord`, `RecentRecord` in `schemas.py`) name
as the primary risk to guard against.

This is inconsistent with how the same module handles an equivalent invariant elsewhere:
`_body_lines` (`reports.py:399-401` and `408-410`) raises `ValueError` when a documented-should-
never-happen data shape shows up, specifically so a violated invariant surfaces as a loud failure
rather than a silently wrong narrative line. The physique branch has the same kind of invariant
but the opposite failure mode — silent instead of loud.

In practice this is a narrow window (single-user app, physique logging is a manual, infrequent
write), so the operational risk today is low. But it is a real gap in a codebase that otherwise
treats "silently wrong" as worse than "loudly broken."

**Fix:** Make the violated invariant fail loudly, matching `_body_lines`'s own convention:

```python
observation = await get_latest_observation(session, user_id=user_id)
if observation is not None:
    diff = await get_latest_physique_diff(session, user_id=user_id)
    cross_reference = await get_physique_volume_cross_reference(session, user_id=user_id)
    if cross_reference is None:
        # get_physique_volume_cross_reference re-derives "latest observation" independently;
        # this should be unreachable given a non-None `observation` above, under normal
        # (non-concurrent-write) conditions. Fail loudly rather than silently reporting
        # `physique=None` for a user who does have an observation.
        raise RuntimeError(
            "get_physique_volume_cross_reference returned None immediately after "
            "get_latest_observation found an observation for this user"
        )
    physique = PhysiqueSection(
        observed_on=observation.observed_on,
        ...
    )
```

If the team judges the race window acceptable for a single-user app, at minimum downgrade the
inline comment from "not a real branch" to something that names the READ COMMITTED caveat
explicitly, so a future reader does not treat the guarantee as stronger than it is.

## Info

### IN-01: No test exercises the "cross_reference unexpectedly None" branch

**File:** `backend/tests/test_analytics_reports.py` (whole file — no such test present)

**Issue:** Every physique-composition test seeds data such that `get_latest_observation` and
`get_physique_volume_cross_reference` agree (0, 1, or 2+ observations). None of them cover the
branch described in WR-01 — the case where `observation is not None` but `cross_reference is
None` — because that case is not reachable through normal seeding; it would require mocking
`get_physique_volume_cross_reference` to return `None` while `get_latest_observation` returns a
record. That is reasonable given the current code treats it as unreachable, but it also means the
current silent-fallback behavior (or the fix proposed in WR-01) is unverified either way.

**Fix:** If WR-01 is addressed by raising, add a small unit test with `monkeypatch` that forces
`get_physique_volume_cross_reference` to return `None` while `get_latest_observation` returns a
non-`None` record, and assert `compose_report` raises rather than silently returning
`physique=None`. This turns the documented invariant into an enforced one.

---

_Reviewed: 2026-09-12T11:50:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 17-physique-analytics-mcp-read-write-tools
reviewed: 2026-09-11T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - backend/app/analytics/physique.py
  - backend/app/analytics/schemas.py
  - backend/app/db/models/physique.py
  - backend/app/db/repositories/physique.py
  - backend/app/mcp/server.py
  - backend/app/mcp/tools/_common.py
  - backend/app/mcp/tools/physique.py
  - backend/app/mcp/tools/schemas.py
  - backend/tests/test_analytics_physique.py
  - backend/tests/test_db_physique.py
  - backend/tests/test_mcp_auth.py
  - backend/tests/test_mcp_isolation.py
  - backend/tests/test_mcp_mount.py
  - backend/tests/test_mcp_physique.py
  - backend/tests/test_mcp_schemas.py
  - backend/tests/test_mcp_tool_budget.py
  - backend/tests/test_mcp_tool_schemas.py
  - backend/tests/test_mcp_tools.py
  - docs/coaching-instructions.md
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-09-11T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This phase adds the physique-observation append-only write path (`fitness_log_physique_observation`),
its required read precursor (`fitness_get_latest_physique_observation`), the PHYS-08 supersede
mechanism, and the PHYS-09/PHYS-10 analytics (ordinal diff and volume cross-reference, not yet
wired to an MCP tool). The implementation is careful and heavily documented: tenant scoping
(`user_id`) is enforced on every read and write, the 19-row rating invariant is validated before
any statement is issued, the write path never leaves partial state (paired-argument checks and
coverage checks run before the first `INSERT`), the exception guard (`safe_tool`) and MCP isolation
boundaries (no raw SQL, no exception interpolation, write-allowlist of exactly two modules) all
hold, and the test suite exercises the supersede round trip, tenant isolation, and both degraded
payloads thoroughly.

No critical bugs or security issues were found. Two warnings are worth fixing: an input-validation
gap that lets "reason" text fields be recorded as empty strings, and a public analytics function
that trusts an invariant it does not verify, risking an unhandled `KeyError` on malformed input.
Two info-level items are minor consistency/style notes.

## Warnings

### WR-01: "Reason" fields accept empty strings, defeating their own purpose

**File:** `backend/app/mcp/tools/schemas.py:595` (`PhysiqueRatingInput.not_assessable_reason`),
`backend/app/mcp/tools/physique.py:213-223` (`superseded_reason` parameter), and
`backend/app/db/repositories/physique.py:122-137` (`_validate_rating_coverage`) /
`backend/app/db/repositories/physique.py:216-219` (`create_observation`'s length check).

**Issue:** Every layer that is supposed to require a real "reason" for `Not Assessable` ratings or
for a supersede only checks *presence* (`is not None`), never non-emptiness. A caller can pass
`not_assessable_reason=""` or `superseded_reason=""` and it will pass:
- Pydantic's `PhysiqueRatingInput._exactly_one` validator (`"" is not None` is `True`),
- `_validate_rating_coverage`'s `has_reason = entry.not_assessable_reason is not None` check,
- `create_observation`'s `if superseded_reason is not None and len(...) > MAX` length check
  (an empty string has length 0, well under the cap), and
- the database CHECK constraints, which only assert `IS NOT NULL`.

The result is a row that satisfies every "exactly one of level/reason" invariant while carrying no
actual explanation — silently defeating PHYS-02's "carrying a reason" requirement and the
supersede path's "a short reason the earlier observation is being superseded" contract.

**Fix:** Add `min_length=1` (or a stripped-non-empty check) alongside the existing `max_length` on
`PhysiqueRatingInput.not_assessable_reason` and on the `superseded_reason` tool parameter, and
mirror the same check in `_validate_rating_coverage` / `create_observation`'s length guard for
callers that bypass the MCP schema layer:

```python
# schemas.py
not_assessable_reason: str | None = Field(default=None, min_length=1, max_length=160)

# physique.py (tool parameter)
superseded_reason: Annotated[
    str | None,
    Field(default=None, min_length=1, max_length=200, description=(...)),
] = None
```

```python
# repositories/physique.py::_validate_rating_coverage
if (
    entry.not_assessable_reason is not None
    and not entry.not_assessable_reason.strip()
):
    raise ValueError(f"... not_assessable_reason must not be blank")
```

### WR-02: `get_physique_diff` trusts the 19-row invariant instead of verifying it

**File:** `backend/app/analytics/physique.py:96-153`

**Issue:** `get_physique_diff` indexes both inputs with `earlier_by_group[group]` /
`later_by_group[group]` for every `CanonicalMuscleGroup`, relying entirely on the docstring's
stated assumption that "both records carry all 19 ratings ... enforced by `create_observation`."
The function is public and takes already-built `PhysiqueObservationRecord` values, not IDs it
fetches itself — nothing stops a caller (a future Phase 18 report composer, a test, or any other
code path that constructs a record without going through `create_observation`) from passing a
record with a missing muscle group. In that case the function raises a bare `KeyError:
<CanonicalMuscleGroup.X>` instead of a clear, actionable error — a much worse failure mode than the
`ValueError`s this same module family uses elsewhere for exactly this kind of invariant violation
(compare `_validate_rating_coverage`'s named, descriptive `ValueError`s).

**Fix:** Validate coverage defensively at the top of `get_physique_diff`, raising a descriptive
error rather than trusting the caller:

```python
def get_physique_diff(*, earlier, later) -> PhysiqueDiffResult:
    for label, record in (("earlier", earlier), ("later", later)):
        present = {entry.muscle_group for entry in record.ratings}
        missing = set(CanonicalMuscleGroup) - present
        if missing:
            raise ValueError(
                f"{label} observation is missing rating rows for: "
                f"{sorted(g.value for g in missing)}"
            )
    ...
```

## Info

### IN-01: `photo_angles_present` allows duplicate angle values

**File:** `backend/app/mcp/tools/physique.py:158-166`, `backend/app/db/models/physique.py:170-173`

**Issue:** `photo_angles_present` is typed `list[PhotoAngle]` with no dedup, and the DB's
`valid_photo_angles` CHECK constraint only enforces `<@ ARRAY['front','back','side']` (containment),
not uniqueness. A caller can legally send `["front", "front"]`, which is stored as-is. This is
low-impact (the value is only read back for context, never counted or indexed), but it is a
plausible source of confusing data.

**Fix:** Either de-duplicate in the tool before persisting (`sorted(set(photo_angles_present), key=...)`)
or add a `Field` validator that rejects a list with repeated elements.

### IN-02: `test_mcp_physique.py`'s docstring contradicts its own import

**File:** `backend/tests/test_mcp_physique.py:9-13` and `:49`

**Issue:** The module docstring states: "no other test module in this suite imports fixtures from
a sibling test module (every cross-module import in `backend/tests/` goes through
`tests.conftest`), so duplication here follows the suite's existing convention rather than
introducing a new one." Immediately below, the module does exactly that:
`from tests.test_mcp_tools import LEAK_MARKERS`. This does not affect test correctness or
reliability, but the stated convention is factually wrong as written, which will mislead the next
reader trying to follow it.

**Fix:** Either move `LEAK_MARKERS` into `tests/conftest.py` and import it from there (making the
docstring's claim true), or update the docstring to note this one exception and why it was made.

---

_Reviewed: 2026-09-11T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

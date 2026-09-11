---
phase: 17-physique-analytics-mcp-read-write-tools
verified: 2026-09-11T04:55:41Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
---

# Phase 17: Physique Analytics & MCP Read/Write Tools Verification Report

**Phase Goal:** Claude can record one physique observation per photo session and retrieve the prior
one for context; deterministic diff and volume-correlation analytics exist underneath; the
write-tool guard suite reflects a truthful two-write-module system rather than a widened but still-
uniform one.
**Verified:** 2026-09-11T04:55:41Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `fitness_log_physique_observation` persists a complete observation in one call, `destructive_hint=False`, no confirmation-token ceremony, required `disclaimer: str` | ✓ VERIFIED | `backend/app/mcp/tools/physique.py:135-329` — single `@safe_tool`-guarded async function, no `confirmation_token` param, `session.commit()` appears exactly once as the last statement of the success branch. `backend/app/mcp/server.py:325-343` registers it with `NON_DESTRUCTIVE_WRITE_TOOL` (`destructive_hint=False`). `PhysiqueLogResponse.disclaimer: str` (schemas.py:698, required, not `| None`). `backend/tests/test_mcp_physique.py::test_one_call_logs_a_complete_observation` and `test_the_write_tool_needs_no_confirmation_token` pass against the real container. |
| 2 | `fitness_get_latest_physique_observation` returns the prior observation's ratings/notes/confounders; both the write tool's own description and `docs/coaching-instructions.md` name it the required precursor | ✓ VERIFIED | `backend/app/mcp/tools/physique.py:331-382` implements the read tool returning `PhysiqueObservationView` (ratings, 3 note fields, `photo_angles_present`, `pose_state`, `conditions_note`). Write tool docstring/description references `fitness_get_latest_physique_observation` (`server.py:339`, `physique.py` docstring: "Call fitness_get_latest_physique_observation FIRST"). `docs/coaching-instructions.md:70,71,98-99` states the read-before-log ordering and "sanity check" language. `test_mcp_physique.py::test_the_read_tool_returns_the_ratings_notes_and_confounders` passes. |
| 3 | A later observation can supersede an earlier one with a reason; the row is retained (never hard-deleted) and excluded from `analytics/physique.py`'s diff output | ✓ VERIFIED | `backend/app/db/repositories/physique.py::_mark_superseded` (UPDATE only, no `delete(` anywhere in the file — `grep -c "delete("` returns 0). `get_recent_observations` holds the sole read-side `superseded_at.is_(None)` predicate (physique.py:376), which `get_latest_physique_diff` reads through exclusively. `test_db_physique.py` and `test_mcp_physique.py::test_a_superseded_observation_disappears_from_the_read_but_stays_in_the_table` and `test_analytics_physique.py::test_get_latest_physique_diff_ignores_a_superseded_observation` (container-backed) all pass. |
| 4 | `get_physique_diff` returns improved/unchanged/regressed/not-comparable per muscle group from stored rows only, no model call, no image, no arithmetic beyond ordinal comparison | ✓ VERIFIED | `backend/app/analytics/physique.py:96-153` — pure synchronous function comparing `PhysiqueRatingLevel` declaration-order ordinal indices only; no `float`, no session writes, no image/model references (`grep` counts all 0). Tests prove all four verdicts, the 1-level noise-floor gate, byte-identical `model_dump_json()` determinism, and the 19-row sorted spine. |
| 5 | A composed function in `analytics/physique.py` cross-references physique ratings against `get_muscle_group_volume` so BRETT performs the join | ✓ VERIFIED | `get_physique_volume_cross_reference` (physique.py:174-233) calls `get_muscle_group_volume` exactly once, imports `RECOMP_LOOKBACK_WEEKS` rather than re-declaring it, computes the bottom-quartile-by-rank undertrained set and joins it against `Minimal`/`Emerging` ratings (D-01/D-02/D-03 all implemented, including the `Not Assessable` exclusion). Container tests cover all four cross-reference cases. No MCP tool wraps it this phase — correctly deferred per 17-CONTEXT.md D-08 and not part of this phase's success criteria. |
| 6 | The write-guard suite reflects a truthful two-write-module system: exact `_WRITE_ALLOWLIST` membership with `len == 2`, per-tool `EXPECTED_WRITE_ANNOTATIONS`, a third write tool still fails | ✓ VERIFIED | `test_mcp_isolation.py:82` — `_WRITE_ALLOWLIST = frozenset({"program_switch.py", "physique.py"})`, asserted exactly (`test_the_write_allowlist_holds_exactly_two_modules`), `len == 2` (`test_mcp_never_writes`'s trailing assertion). No `startswith`/`in path.name`/`endswith` loosening found — membership test is `path.name not in _WRITE_ALLOWLIST` (exact). `test_mcp_tool_schemas.py:138,155-169` — `EXPECTED_WRITE_ANNOTATIONS` per-tool mapping with `set(EXPECTED_WRITE_ANNOTATIONS) == WRITE_TOOLS` asserted (line 197-200), which fails for any write tool absent from the mapping — the literal mechanism the criterion names. `fitness_switch_training_program`: `destructiveHint: True`; `fitness_log_physique_observation`: `destructiveHint: False`, asserted distinctly (per-tool loop at line 237, not a uniform check). |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/repositories/physique.py` | supersede write/read semantics, `get_observation`, `get_recent_observations` | ✓ VERIFIED | All functions present, wired, exercised by 8+ DB-layer tests, all passing |
| `backend/app/db/models/physique.py` | `PHYSIQUE_RATING_DISCLAIMER` | ✓ VERIFIED | Constant present, non-empty, imported by both `analytics/physique.py` and `mcp/tools/physique.py` |
| `backend/app/analytics/physique.py` | `get_physique_diff`, `get_latest_physique_diff`, `get_physique_volume_cross_reference` | ✓ VERIFIED | 233 lines, all three functions present and exported, isolation-test-compliant |
| `backend/app/analytics/schemas.py` | 5 new Pydantic types | ✓ VERIFIED | `PhysiqueDiffVerdict`, `PhysiqueMuscleDiff`, `PhysiqueDiffResult`, `PhysiqueVolumeFlag`, `PhysiqueVolumeCrossReference` all present, `disclaimer: str` required on both result types |
| `backend/app/mcp/tools/physique.py` | `fitness_log_physique_observation`, `fitness_get_latest_physique_observation` | ✓ VERIFIED | 382 lines, both tools present, `@safe_tool`-guarded, wired into `server.py` |
| `backend/app/mcp/tools/schemas.py` | 6 new MCP schema types | ✓ VERIFIED | `PhysiqueRatingInput`, `PhysiqueLogStatus`, `PhysiqueLogResponse`, `PhysiqueRatingView`, `PhysiqueObservationView`, `LatestPhysiqueObservationResponse` all present |
| `backend/app/mcp/server.py` | tool registration, `NON_DESTRUCTIVE_WRITE_TOOL` | ✓ VERIFIED | Both tools registered, correct annotation objects, registration occurs before `mcp_app = mcp.streamable_http_app(...)` |
| `backend/tests/test_mcp_isolation.py` | widened write allowlist | ✓ VERIFIED | Exact two-member frozenset, `len == 2` asserted twice |
| `backend/tests/test_mcp_tool_schemas.py` | `EXPECTED_WRITE_ANNOTATIONS` | ✓ VERIFIED | Per-tool mapping, key-set-equality assertion against `WRITE_TOOLS` |
| `backend/tests/test_mcp_tool_budget.py` | budgets for both new tools | ✓ VERIFIED | `BUDGETS["fitness_log_physique_observation"]=2048`, `BUDGETS["fitness_get_latest_physique_observation"]=8192`, worst-case args present and forced onto the no-write branch |
| `docs/coaching-instructions.md` | two tool-table rows, precursor + anti-ratchet gotcha | ✓ VERIFIED | Rows present at lines 70-71; gotcha bullet at lines 97-101; document stays under the 9,000-char paste ceiling (confirmed by passing `test_coaching_doc.py`) |
| `backend/tests/test_db_physique.py`, `test_analytics_physique.py`, `test_mcp_physique.py`, `test_mcp_schemas.py` | test coverage | ✓ VERIFIED | All pass against the real Postgres test container |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `physique.py` repo `create_observation` | `_mark_superseded` | direct call after flush, same transaction | ✓ WIRED | Confirmed by line-order check and passing supersede round-trip tests |
| `get_latest_observation` | `get_recent_observations` | `limit=1` wrapper | ✓ WIRED | `get_latest_observation` delegates; single `superseded_at IS NULL` read predicate confirmed |
| `analytics/physique.py` | `db/repositories/physique.py::get_recent_observations` | supersede-filtered fetch | ✓ WIRED | `get_latest_physique_diff` calls it exclusively |
| `analytics/physique.py` | `analytics/volume.py::get_muscle_group_volume` | single call, reused | ✓ WIRED | Exactly one call site confirmed by grep and code read |
| `analytics/physique.py` | `analytics/recomposition.py::RECOMP_LOOKBACK_WEEKS` | imported constant | ✓ WIRED | Imported, never re-literalled (`grep` for bare `12` in window context returns nothing) |
| `mcp/tools/physique.py` | `_common.py::writable_session` | second (and only other) caller | ✓ WIRED | Confirmed in both source and `_common.py`'s updated docstrings |
| `mcp/tools/physique.py` | `db/repositories/physique.py::create_observation`/`get_observation` | repository owns writes; tenant-scoped validation before write | ✓ WIRED | Confirmed by code read and passing refusal tests (unknown/foreign/already-superseded target all refused without writing) |
| `mcp/server.py` | `mcp/tools/physique.py` | import + `add_tool` for both tools | ✓ WIRED | Read tool inside `READ_ONLY` loop, write tool outside with `NON_DESTRUCTIVE_WRITE_TOOL` |
| `test_mcp_tool_schemas.py::EXPECTED_WRITE_ANNOTATIONS` | `WRITE_TOOLS` | asserted equal key sets | ✓ WIRED | `set(EXPECTED_WRITE_ANNOTATIONS) == WRITE_TOOLS` assertion present at line 197 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast suite (no container) | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_mcp_tool_schemas.py backend/tests/test_analytics_physique.py backend/tests/test_db_physique.py backend/tests/test_mcp_schemas.py -q -m "not integration and not realfile"` | 93 passed | ✓ PASS |
| Container-backed physique suites | `uv run pytest backend/tests/test_mcp_physique.py backend/tests/test_analytics_physique.py backend/tests/test_db_physique.py backend/tests/test_mcp_tool_budget.py backend/tests/test_coaching_doc.py -q` | 66 passed | ✓ PASS |
| Full backend suite | `uv run pytest backend/tests -q` | 1178 passed | ✓ PASS |
| No hard-delete of observations | `grep -c "delete(" backend/app/db/repositories/physique.py` | 0 | ✓ PASS |
| Write allowlist is exact, not loosened | `grep -n "startswith\|endswith\|in path.name" backend/tests/test_mcp_isolation.py` around allowlist check | exact `not in _WRITE_ALLOWLIST` membership test, no loosening | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PHYS-06 | 17-03, 17-04, 17-05 | Single-call, append-only, non-destructive write tool | ✓ SATISFIED | `fitness_log_physique_observation`, `destructive_hint=False`, no token, tested |
| PHYS-07 | 17-03, 17-04, 17-05 | Read tool returns prior observation, documented as required precursor | ✓ SATISFIED | `fitness_get_latest_physique_observation`, docstring + coaching doc both state precursor ordering |
| PHYS-08 | 17-01, 17-03, 17-04 | Supersede with reason, retained, excluded from diffs | ✓ SATISFIED | `_mark_superseded`, `get_recent_observations` exclusion, diff-exclusion test passing |
| PHYS-09 | 17-02 | Deterministic per-muscle-group ordinal diff | ✓ SATISFIED | `get_physique_diff`, byte-identical determinism proven |
| PHYS-10 | 17-02 | Cross-reference ratings against volume | ✓ SATISFIED | `get_physique_volume_cross_reference`, all D-01..D-04 cases tested |
| PHYS-11 | 17-01, 17-02, 17-03, 17-04 | Required disclaimer field on every physique-touching response | ✓ SATISFIED | `PHYSIQUE_RATING_DISCLAIMER` constant, required `disclaimer: str` on 4 response/result types |
| MCP-07 | 17-03 | `_WRITE_ALLOWLIST` widened to exactly two modules, exact-membership preserved | ✓ SATISFIED | Verified above |
| MCP-08 | 17-05 | Per-tool `EXPECTED_WRITE_ANNOTATIONS` mapping replacing uniform assertion | ✓ SATISFIED | Verified above |

No orphaned requirements: all 8 phase-mapped requirement IDs in `.planning/REQUIREMENTS.md` are claimed by at least one plan's frontmatter and have corresponding implementation evidence.

### Anti-Patterns Found

None blocking. `grep` for `TODO|FIXME|XXX|HACK|PLACEHOLDER|not yet implemented|coming soon` across the phase's core files (`physique.py` in db/repositories, db/models, analytics, mcp/tools) returned no matches.

Two non-blocking warnings and two info-level items were raised by `17-REVIEW.md` (code review, standard depth, 0 critical / 2 warning / 2 info):

| File | Issue | Severity | Impact on this phase's success criteria |
|------|-------|----------|-------------------------------------------|
| `schemas.py` / `physique.py` (tool) / repository | WR-01: "reason" fields (`not_assessable_reason`, `superseded_reason`) accept empty strings — only presence, not non-emptiness, is checked at every layer | ⚠️ Warning | Does not violate any of the six roadmap success criteria as literally stated (they require a reason field to exist and be persisted, not that it be non-empty) — a data-quality gap worth fixing but not a goal blocker |
| `analytics/physique.py:96-153` | WR-02: `get_physique_diff` trusts the 19-row invariant rather than defensively verifying it; a malformed record raises a bare `KeyError` instead of a descriptive `ValueError` | ⚠️ Warning | Does not affect SC#4 as currently exercised — every caller in this codebase (`get_latest_physique_diff`) obtains records exclusively through `create_observation`'s enforced invariant, so the code path that would trigger this is not reachable through any tool or analytics function shipped in this phase |
| `physique.py` (tool) | IN-01: `photo_angles_present` allows duplicate values | ℹ️ Info | Cosmetic; no success criterion concerns list uniqueness |
| `test_mcp_physique.py` | IN-02: docstring claims a convention its own import contradicts | ℹ️ Info | Documentation-only, no functional impact |

These are legitimate follow-up items but do not block phase-goal achievement; they are lower-severity data-hardening improvements outside the six roadmap success criteria's literal scope.

### Human Verification Required

None. This phase is backend-only (MCP tool bodies, repository, analytics), fully exercised by an automated test suite against a real PostgreSQL test container, with no UI, visual, or externally-integrated behavior requiring manual confirmation.

### Gaps Summary

No gaps found. All six roadmap success criteria are verified against actual, tested, wired code:
the write tool commits a complete observation with the correct non-destructive annotation and a
required disclaimer; the read tool returns the prior observation and is named as the required
precursor in both the tool description and the coaching doc; supersede is UPDATE-only and excluded
from reads/diffs; the diff and cross-reference functions are pure, deterministic, and correctly
composed; and the write-guard suite is an exact, non-loosened two-module system with a per-tool
annotation mapping that would catch a hypothetical third write tool. The full backend test suite
(1178 tests) passes with no regressions. Two non-blocking review warnings (empty-string reason
fields, an unvalidated invariant in `get_physique_diff`) are documented for future hardening but do
not bear on any of the roadmap's stated success criteria.

---

_Verified: 2026-09-11T04:55:41Z_
_Verifier: Claude (gsd-verifier)_

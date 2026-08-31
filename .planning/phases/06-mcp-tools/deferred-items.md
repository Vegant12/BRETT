# Phase 6 deferred items

Discovered during execution, deliberately NOT fixed in the plan that found them because the fix
falls outside that plan's declared files and changes shipped tool behaviour.

## D-06-10-A: three tools measure over 06-RESEARCH.md's estimated budgets

**Found in:** plan 06-10, task 1 (`backend/tests/test_mcp_tool_budget.py`).

The research budget table was estimated against prototype response shapes. The first real
measurements against the Wave-4 tools, taken on the full `CallToolResult` at each tool's published
cap against `worst_case_history`, came in over for three of thirteen:

| Tool | Research budget | Measured | Notes |
|---|---:|---:|---|
| `fitness_compare_periods` | 32,768 | **59,582** | 29,169 with `include_muscle_groups=False`; the 19 `MuscleGroupComparison` rows add 30,413 bytes (~1,600 each) |
| `fitness_get_exercise_progression` | 24,576 | **28,685** | at 43 points, which is what a 52-week window yields here; `MAX_PROGRESSION_POINTS` is 60, projecting to ~39,400 at ~632 bytes/point |
| `fitness_get_plateaus` | 24,576 | **28,350** | at the full 30-exercise cap with `plateaued_only=False` (~945 bytes/exercise) |

Plan 06-10 re-derived those three budgets from measurement (49,152 / 40,960 / 81,920) so the gate
is real rather than aspirational, and documented the arithmetic in the test module's docstring.

**What is deferred:** whether the RESPONSE CAPS should come down instead. That is a change to
`backend/app/mcp/tools/_common.py` and the tool bodies -- Wave-4 files this plan does not own --
and it changes what the shipped tools return, so it is a decision rather than a fix.

Specific questions for whoever picks this up:

1. `fitness_compare_periods` at 59.6 KB is by a wide margin the most expensive call in the phase
   (~20K tokens, roughly a tenth of a 200K context). Candidates: drop `MAX_COMPARISON_ITEMS` from
   25 to ~15; make the muscle-group breakdown a narrower row than the full paired summary; or
   accept it on the grounds that `include_muscle_groups` defaults to `False` and the typical call
   is 29 KB.
2. `fitness_get_exercise_progression` at ~632 bytes per point puts the 60-point cap near 39 KB.
   Either lower `MAX_PROGRESSION_POINTS` or slim `ExerciseProgressionPoint`.
3. `fitness_get_plateaus` at ~945 bytes per row is the widest per-item shape in the phase; the
   window/threshold provenance each verdict carries is repeated on every row.

**Not a blocker for phase 6.** Every tool is bounded, every bound is measured, and every bound is
now regression-gated. The open question is whether the bounds are set where a coaching
conversation wants them, which is a tuning judgement that wants real Claude transcripts rather
than a byte count.

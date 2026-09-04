"""MCP-03 as a tested property rather than a design intention (D-13, T-06-05).

**The measurement rule: assert on the FULL ``CallToolResult``.** This is the one thing that is
easy to get wrong and expensive to get wrong quietly.

``mcp 2.0.0``'s ``FuncMetadata.convert_result`` emits every payload TWICE. It sets
``structured_content`` from the returned ``BaseModel``, and it ALSO builds
``unstructured_content = pydantic_core.to_json(result, fallback=str, indent=2)`` -- the same data,
pretty-printed -- as ``content[0].text``. Both travel to the client. Measured on a 52-week
``WeeklyVolumeResult``: 5,211 bytes structured, 7,819 bytes text, **14,304 bytes total**. A budget
written against ``structured_content`` alone understates Claude's real context cost by roughly
2.7x, and there is no supported way to suppress the text block while keeping ``outputSchema``.

So a comfortable-looking budget measured on the structured half is a Claude conversation that runs
out of context after three tool calls -- and it fails as a vague "the model seems to forget
things", never as a test.

**Every tool is measured at its PUBLISHED CAP, not its default.** A budget measured at
``weeks=12`` proves nothing about what ``weeks=52`` costs, and the cap is what the model is
allowed to ask for. ``WORST_CASE_ARGS`` therefore pins every window parameter to its maximum, and
``test_every_budgeted_tool_has_worst_case_arguments`` is what stops a new tool being budgeted at
its default and silently passing.

**One seeding, one loop.** ``worst_case_history`` seeds 52 weeks x 5 sessions/week -- ~260
workouts and ~5,200 sets. Parametrizing the budget test would re-seed that thirteen times and make
the suite unusable, so ``test_every_tool_response_fits_its_budget`` is a single test function with
a single ``async with Client(mcp)`` block that collects every failure and asserts at the end. One
over-budget tool must not hide the other twelve.

**Three budgets are LARGER than 06-RESEARCH.md's table, and that is a finding, not a fudge.**
The research figures were estimated against prototype response shapes; these are the first
measurements taken against the shipped Wave-4 tools, and three of them came in over. Each is
recorded at the budget it belongs to with the measurement that set it. The short version:

* ``fitness_compare_periods`` -- research said 32 KB, measured **59,582**. The research row
  explicitly assumed ``include_muscle_groups=False``, which is the DEFAULT but not the cap. Lean
  it measures 29,169 (inside the old budget); the 19 ``MuscleGroupComparison`` rows add 30,413
  bytes on their own, roughly 1,600 bytes per muscle group.
* ``fitness_get_exercise_progression`` -- research said 24 KB, measured **28,685** at 43 points,
  and 43 is not even the cap.
* ``fitness_get_plateaus`` -- research said 24 KB, measured **28,350** at the full 30-exercise cap.

The budgets below are therefore re-derived by the research document's OWN rule -- measured worst
case at the cap, plus ~30% headroom -- rather than copied from a table the implementation has
outgrown. That keeps every number traceable to a measurement and keeps the test a real regression
gate. It does NOT make ``fitness_compare_periods`` cheap: at 59.6 KB it is by a wide margin the
most expensive call in the phase, and whether ``MAX_COMPARISON_ITEMS`` (25) and the muscle-group
breakdown should both survive at their current size is a caps question for the tool layer, logged
in this phase's ``deferred-items.md``. Raising a budget is not the same as deciding the response
is the right size; it is refusing to let an unmeasured number stand in for a measured one.
"""

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import WORST_CASE_TEMPLATES

# Full `CallToolResult` bytes: the measured worst case at the published cap, rounded up with
# ~30% headroom. The ten unannotated entries are 06-RESEARCH.md's "Recommended per-tool caps and
# budgets" table, confirmed by measurement. The three annotated ones were re-derived because the
# shipped tools measured over the research estimate -- each carries the figure that set it.
#
# The KEYS are asserted equal to the live tool registry below. That equality is the whole
# mechanism: a tool with no budget is a tool with no MCP-03 enforcement, and asserting on the key
# set is what stops tool number fourteen from shipping unbounded.
BUDGETS: dict[str, int] = {
    "fitness_ping": 2_048,
    # One fixed-shape object with no list, so this does not grow with data -- the 90-day window
    # is a module constant, not a caller parameter. Measured 1,351 bytes at metric="waist_cm"
    # against the worst-case history on 2026-09-04.
    "fitness_get_body_measurement_trend": 2_048,
    "fitness_get_body_weight_trend": 4_096,
    # A fixed-shape object: five metrics x three windows, no caller-widenable list, so this does
    # not grow with data once the 30-day fetch is saturated. Measured 10,861 bytes against
    # worst_case_history's 45 seeded Apple Health days on 2026-09-04.
    "fitness_get_activity_trend": 16_384,
    # Seven metrics x three windows -- the same fixed shape, wider by two metrics. Measured
    # 14,875 bytes on 2026-09-04.
    "fitness_get_nutrition_trend": 20_480,
    "fitness_get_personal_records": 8_192,
    "fitness_get_recomposition_status": 12_288,
    "fitness_get_muscle_group_volume": 12_288,
    "fitness_get_training_summary": 16_384,
    "fitness_get_recent_workouts": 20_480,
    "fitness_get_weekly_volume": 20_480,
    "fitness_get_training_frequency": 20_480,
    "fitness_get_workout": 32_768,
    # Re-derived from measurement; see the module docstring. Measured 28,685 bytes at 43 points --
    # and 43 is what a 52-week window yields against this fixture, NOT the MAX_PROGRESSION_POINTS
    # cap of 60. Four windows (13/26/39/52 weeks -> 11/21/32/43 points) give a clean linear fit at
    # ~632 bytes per point over a ~1,500-byte envelope, so a full 60 points projects to ~39,400.
    # Budgeting the measured 43-point figure would leave the cap itself unbudgeted.
    "fitness_get_exercise_progression": 49_152,
    # Measured 28,350 bytes with `plateaued_only=False` at the full MAX_PLATEAU_EXERCISES cap of
    # 30 rows (~945 bytes per exercise). This one IS measured at its cap, so it needs headroom
    # only, not extrapolation.
    "fitness_get_plateaus": 40_960,
    # Measured 59,582 bytes at the heaviest legal shape: 25 exercises + 25 exercise levels + all
    # 19 muscle groups. `include_muscle_groups=True` alone accounts for 30,413 of those bytes --
    # without it the same call measures 29,169. The default is False, so the typical call is less
    # than half this; the budget covers what the model is ALLOWED to ask for.
    "fitness_compare_periods": 81_920,
    # A fixed-shape object with no list, so this does not grow with data.
    # Measured 554 bytes at the seeded lean_bulk-only history on 2026-09-04.
    "fitness_get_training_program": 2_048,
    # A fixed-shape object with no list, so this does not grow with data.
    # Measured 880 bytes at the seeded "already active" no-op refusal on 2026-09-04.
    "fitness_switch_training_program": 2_048,
}

# Every window parameter at its published maximum. Tools whose arguments cannot be written down
# ahead of time -- they need an exercise title or a workout id the fixture created -- are listed
# in `FIXTURE_DERIVED_TOOLS` instead and built at call time.
WORST_CASE_ARGS: dict[str, dict[str, object]] = {
    "fitness_ping": {},
    "fitness_get_body_measurement_trend": {"metric": "waist_cm"},
    "fitness_get_body_weight_trend": {},
    "fitness_get_activity_trend": {},
    "fitness_get_nutrition_trend": {},
    "fitness_get_recomposition_status": {},
    "fitness_get_muscle_group_volume": {"weeks": 52},
    "fitness_get_weekly_volume": {"weeks": 52},
    "fitness_get_training_frequency": {"weeks": 52},
    "fitness_get_plateaus": {"lookback_weeks": 52, "plateaued_only": False},
    "fitness_get_training_summary": {"weeks": 12},
    "fitness_get_recent_workouts": {"limit": 25},
    "fitness_get_training_program": {},
    # `lean_bulk` is the SEEDED active program, so this call takes the "already active"
    # branch: it writes nothing and issues no token. A budget measurement must not leave
    # rows behind in the shared container, and a token minted here would outlive the test.
    "fitness_switch_training_program": {"program": "lean_bulk"},
    # exercise_name / workout_id are filled in at call time from the seeded fixture.
}

# The four tools whose heaviest legal call depends on data that exists only once the fixture has
# run. Declared here so `test_every_budgeted_tool_has_worst_case_arguments` can prove the union of
# the two sets covers `BUDGETS` exactly.
FIXTURE_DERIVED_TOOLS: frozenset[str] = frozenset(
    {
        "fitness_get_exercise_progression",
        "fitness_get_personal_records",
        "fitness_get_workout",
        "fitness_compare_periods",
    }
)

# `worst_case_history` titles its templates `Worst Case Exercise 000` .. `029`, and
# `find_templates_by_title` matches on `exercise_templates.title`. Template 000 is trained on the
# same round-robin schedule as every other, so it carries a full year of points.
WORST_CASE_EXERCISE_TITLE = "Worst Case Exercise 000"

# Half of the fixture's 52 weeks, so the two comparison periods are adjacent, equal-length and
# together span the whole seeded history. Each is 182 days, comfortably inside the 365-day cap.
_COMPARISON_PERIOD_WEEKS = 26

# The 19 canonical muscle groups. `fitness_get_muscle_group_volume` returns a row per group at
# every window -- that flatness is the resolved Open Question 1 and is asserted below.
_CANONICAL_MUSCLE_GROUPS = 19


def _result_bytes(result: Any) -> int:
    """The number of bytes this result costs Claude.

    ``exclude_none=True`` matches what the SDK actually serializes onto the wire; measuring the
    model's full dump would count optional fields that are never transmitted and inflate every
    figure uniformly.
    """
    return len(result.model_dump_json(exclude_none=True).encode("utf-8"))


def _adjacent_comparison_periods() -> dict[str, object]:
    """Two adjacent 26-week periods ending today, with the muscle-group breakdown switched on.

    ``include_muscle_groups=True`` is the heaviest legal shape for this tool and it is NOT the
    default, so a budget measured without it would be measuring the cheap call.
    """
    today = dt.datetime.now(tz=dt.UTC).date()
    period_b_end = today
    period_b_start = (
        period_b_end - dt.timedelta(weeks=_COMPARISON_PERIOD_WEEKS) + dt.timedelta(days=1)
    )
    period_a_end = period_b_start - dt.timedelta(days=1)
    period_a_start = (
        period_a_end - dt.timedelta(weeks=_COMPARISON_PERIOD_WEEKS) + dt.timedelta(days=1)
    )
    return {
        "period_a_start": period_a_start.isoformat(),
        "period_a_end": period_a_end.isoformat(),
        "period_b_start": period_b_start.isoformat(),
        "period_b_end": period_b_end.isoformat(),
        "include_muscle_groups": True,
    }


async def _registered_tool_names() -> set[str]:
    """Every tool name the server would advertise.

    ``_tool_manager`` is preferred because it needs no client, no transport and no event loop
    round-trip; the public ``list_tools()`` is the fallback in case a future SDK drops the private
    accessor. Either way the SOURCE is the live registry, never a second hand-written list.
    """
    from app.mcp.server import mcp

    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None:
        return {tool.name for tool in manager.list_tools()}
    return {tool.name for tool in await mcp.list_tools()}


async def test_every_registered_tool_has_a_budget() -> None:
    """The budget table and the tool registry are the same set of names.

    A tool with no budget is a tool with no MCP-03 enforcement: nothing measures it, so nothing
    notices when it starts returning a year of per-week rows. Asserting the KEYS match the live
    registry -- rather than asserting each known tool is present -- is what makes this fail for
    tool number fourteen, which is the tool nobody will remember to budget.

    No container: this reads the registry, not the database.
    """
    registered = await _registered_tool_names()
    budgeted = set(BUDGETS)

    assert registered == budgeted, (
        "MCP-03: the tool registry and BUDGETS have diverged. "
        f"Registered but unbudgeted: {sorted(registered - budgeted)}. "
        f"Budgeted but not registered: {sorted(budgeted - registered)}."
    )


async def test_every_budgeted_tool_has_worst_case_arguments() -> None:
    """Every budgeted tool is measured at a deliberate worst case, not at its default.

    ``WORST_CASE_ARGS`` covers the tools whose heaviest call can be written down; the rest are
    declared in ``FIXTURE_DERIVED_TOOLS`` and built from the seeded data. The union must be the
    budget table exactly, so a newly budgeted tool cannot quietly be measured at ``weeks=12`` and
    pass a budget written for ``weeks=52``.
    """
    covered = set(WORST_CASE_ARGS) | FIXTURE_DERIVED_TOOLS
    budgeted = set(BUDGETS)

    assert covered == budgeted, (
        "MCP-03: a budgeted tool has no declared worst case. "
        f"Budgeted without worst-case arguments: {sorted(budgeted - covered)}. "
        f"Worst-case arguments for an unbudgeted tool: {sorted(covered - budgeted)}."
    )
    assert not (set(WORST_CASE_ARGS) & FIXTURE_DERIVED_TOOLS), (
        "a tool declared in both places would have its literal arguments silently overwritten"
    )


@pytest.mark.integration
async def test_every_tool_response_fits_its_budget(
    client: TestClient, worst_case_history: None
) -> None:
    """Thirteen tools, at their published caps, against 52 weeks of history -- all inside budget.

    ONE ``Client`` block and one loop rather than a parametrized test: ``worst_case_history`` seeds
    ~260 workouts and ~5,200 sets, and re-seeding that per tool makes the suite unusable.

    Failures are collected and asserted at the end so one over-budget tool does not mask the other
    twelve, and ``is_error`` is checked in the same pass -- a byte count taken on an error payload
    measures the error string, not the tool.
    """
    from mcp import Client

    from app.mcp.server import mcp

    oversized: list[str] = []
    errored: list[str] = []

    async with Client(mcp) as mcp_client:
        # The workout id has to come from the data, and the list tool is the same route Claude
        # takes to get one (D-09/D-12: list, then drill in).
        recent = await mcp_client.call_tool("fitness_get_recent_workouts", {"limit": 1})
        assert recent.is_error is False
        recent_structured = recent.structured_content
        assert recent_structured is not None
        workout_id = recent_structured["workouts"][0]["workout_id"]

        arguments: dict[str, dict[str, object]] = dict(WORST_CASE_ARGS)
        arguments["fitness_get_exercise_progression"] = {
            "exercise_name": WORST_CASE_EXERCISE_TITLE,
            "weeks": 52,
        }
        arguments["fitness_get_personal_records"] = {
            "exercise_name": WORST_CASE_EXERCISE_TITLE,
            "weeks": 52,
        }
        arguments["fitness_get_workout"] = {"workout_id": workout_id}
        arguments["fitness_compare_periods"] = _adjacent_comparison_periods()

        for name in sorted(BUDGETS):
            result = await mcp_client.call_tool(name, arguments[name])
            if result.is_error is not False:
                errored.append(name)
                continue
            size = _result_bytes(result)
            if size > BUDGETS[name]:
                oversized.append(
                    f"MCP-03: {name} returned {size:,} bytes against a "
                    f"{BUDGETS[name]:,} budget. Every byte here enters Claude's context window."
                )

    assert errored == [], (
        "T-06-18: a budget measured on an error payload measures nothing. "
        f"These tools returned is_error=True: {errored}"
    )
    assert oversized == [], "\n".join(oversized)


@pytest.mark.integration
async def test_muscle_group_volume_is_flat_across_windows(
    client: TestClient, worst_case_history: None
) -> None:
    """A 52-week muscle rollup costs about what a 4-week one costs, and returns the same 19 rows.

    This is the regression test for the resolved Open Question 1. The rollup is per-WINDOW, not a
    per-week x per-muscle grid; if someone reverts it to the grid, the 52-week call jumps from
    roughly 8 KB to roughly 348 KB. Asserting the two windows cost within 15% of each other says
    so in the same terms the decision was made in, and it says so before the budget test does --
    at which point the diagnosis is "the shape changed", not "the budget is too tight".

    The 19-row assertion is the other half: a flat size achieved by returning fewer muscle groups
    would be a different regression wearing the same number.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        narrow = await mcp_client.call_tool("fitness_get_muscle_group_volume", {"weeks": 4})
        wide = await mcp_client.call_tool("fitness_get_muscle_group_volume", {"weeks": 52})

    assert narrow.is_error is False
    assert wide.is_error is False

    narrow_size = _result_bytes(narrow)
    wide_size = _result_bytes(wide)
    smaller, larger = sorted((narrow_size, wide_size))
    assert larger <= smaller * 1.15, (
        "Open Question 1 regression: the per-muscle rollup is supposed to be window-independent, "
        f"but weeks=4 measured {narrow_size:,} bytes and weeks=52 measured {wide_size:,} -- more "
        "than 15% apart. A per-week x per-muscle grid is the usual cause, and it takes the "
        "52-week response to roughly 348 KB."
    )

    for label, result in (("weeks=4", narrow), ("weeks=52", wide)):
        structured = result.structured_content
        assert structured is not None
        assert len(structured["muscles"]) == _CANONICAL_MUSCLE_GROUPS, (
            f"{label} returned {len(structured['muscles'])} muscle rows; all 19 canonical groups "
            "must always be present, including the untrained ones."
        )


@pytest.mark.integration
async def test_weekly_volume_returns_exactly_the_requested_week_count(
    client: TestClient, worst_case_history: None
) -> None:
    """``weeks=N`` returns exactly N week rows -- never N+1.

    Pitfall 6. ``window_from_weeks`` is Monday-anchored precisely so that the outward snap
    ``get_weekly_volume`` performs on its own range cannot reach back into a 53rd week. A
    non-Monday start makes ``weeks=52`` return 53 rows, which blows the D-04 row cap for a reason
    that reads like an off-by-one in the test rather than a missing anchor in the helper.

    It is also the T-06-18 canary: on an empty database the weeks list would be gap-filled zeros
    at the wrong count, or absent entirely, and this test fails rather than passing vacuously.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        for weeks in (1, 4, 12, 52):
            result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": weeks})

            assert result.is_error is False
            structured = result.structured_content
            assert structured is not None
            returned = structured["volume"]["weeks"]
            assert len(returned) == weeks, (
                f"D-04/Pitfall 6: weeks={weeks} returned {len(returned)} week rows. A 53rd row "
                "means the Monday anchor was lost and the outward snap widened the window."
            )


@pytest.mark.integration
async def test_truncated_lists_declare_themselves(
    client: TestClient, worst_case_history: None
) -> None:
    """A capped list reports how much it withheld, or it is a wrong answer with no signal.

    T-06-11. Without ``total_exercises`` and ``exercises_truncated``, Claude reads "30 exercises"
    as "you train 30 exercises" -- stated with full confidence, and wrong the moment the cap
    bites. That is exactly the failure mode D-02 exists to prevent for ambiguous exercise names,
    and an unlabelled cap reintroduces it everywhere else.

    The fixture seeds ``WORST_CASE_TEMPLATES`` distinct exercises, so ``total_exercises`` is
    checkable against a known number rather than against whatever the response happens to say.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_training_frequency", {"weeks": 52})

    assert result.is_error is False
    structured = result.structured_content
    assert structured is not None

    assert structured["total_exercises"] == WORST_CASE_TEMPLATES, (
        "total_exercises must report the REAL count the window contains, not the returned "
        f"length: expected {WORST_CASE_TEMPLATES}, got {structured['total_exercises']}."
    )
    returned = len(structured["exercises"])
    assert structured["exercises_truncated"] is (returned < structured["total_exercises"]), (
        f"exercises_truncated={structured['exercises_truncated']} contradicts the payload: "
        f"{returned} of {structured['total_exercises']} exercises were returned."
    )

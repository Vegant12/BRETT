"""Activity trend and nutrition trend for MCP (MCP-02, MCP-03, MCP-05, MCP-06; D-07, D-08).

Both ``fitness_get_activity_trend`` and ``fitness_get_nutrition_trend`` take NO parameters, in
``body.py``'s own words: the underlying analytics functions are anchored on today by design, a
caller-supplied end date would let a stale anchor produce a confident-looking figure from a
superseded window, so there is nothing here for a model to get wrong and nothing to validate. Do
NOT add a ``weeks`` parameter for symmetry with the volume tools -- it is an argument the
analytics layer has no place to receive.

D-08's negative decision, spelled out here too: the nutrition tool deliberately does NOT take a
metric selector. Nutrition values are asked about together, unlike
``fitness_get_body_measurement_trend``'s 16 largely-independent columns.

Both results are embedded WHOLE, never projected field by field -- projection is what would drop
a per-metric coverage flag.

ROADMAP.md's standing rule restated at the tool surface: activity data is recomposition CONTEXT,
never a classifier input. Nothing here feeds ``get_recomposition_status``.
"""

from mcp.server.mcpserver import Context

from app.analytics.health import get_activity_trend, get_nutrition_trend
from app.mcp.context import AppContext
from app.mcp.tools._common import read_only_session, resolve_user_id, safe_tool
from app.mcp.tools.schemas import ActivityTrendResponse, NutritionTrendResponse

# No module logger here on purpose: neither tool has a branch of its own to report. Both take no
# arguments, so there is nothing to reject, and every failure path is `safe_tool`'s single
# `log.exception("mcp_tool_failed")`. An unused logger would read as a missing log line.


def _degraded_activity() -> ActivityTrendResponse:
    """HEALTH-12's "I could not reach the data" payload. ``data_available=False`` is NOT the
    same claim as "you did not move" -- without the flag the two are byte-identical and Claude
    would narrate an outage as a rest day.

    Built by a factory rather than held as a module constant so each failure gets a fresh object
    and no caller can mutate the placeholder the next one receives (``safe_tool``'s contract).
    """
    return ActivityTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_activity)
async def fitness_get_activity_trend(ctx: Context[AppContext]) -> ActivityTrendResponse:
    """Daily activity anchored on today: 7-, 14- and 30-day rolling averages for steps, active
    energy, basal energy, walking/running distance and flights climbed, each with the number of
    days actually recorded behind it, plus how the last week compares with the last month.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_activity_trend(session, user_id=user_id)
    return ActivityTrendResponse(data_available=True, trend=trend)


def _degraded_nutrition() -> NutritionTrendResponse:
    """NUTR-06's "I could not reach the data" payload. ``data_available=False`` is NOT the same
    claim as "you ate nothing" -- without the flag the two are byte-identical and Claude would
    narrate an outage as a fast.

    Built by a factory rather than held as a module constant so each failure gets a fresh object
    and no caller can mutate the placeholder the next one receives (``safe_tool``'s contract).
    """
    return NutritionTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_nutrition)
async def fitness_get_nutrition_trend(ctx: Context[AppContext]) -> NutritionTrendResponse:
    """Nutrition anchored on today: 7-, 14- and 30-day rolling daily averages for calories and
    all six tracked macros (protein, carbohydrates, fat, fibre, sugar, sodium), returned together
    in one call. Each macro carries its own coverage, because they are not always logged on the
    same days.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_nutrition_trend(session, user_id=user_id)
    return NutritionTrendResponse(data_available=True, trend=trend)

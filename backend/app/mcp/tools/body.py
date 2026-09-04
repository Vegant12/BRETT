"""Body-weight trend, body-measurement trend, and recomposition status for MCP
(MCP-02, MCP-03, MCP-05, MCP-06; D-07).

**``fitness_get_body_weight_trend`` and ``fitness_get_recomposition_status`` are the only two
tools in Phase 6 with NO window parameter at all, and that is deliberate.** Both underlying
analytics functions are anchored on today by design, and their own docstrings say why: a
caller-supplied end date would let a stale anchor produce a confident-looking rate from a window
that has since been superseded, and BODY-02 has no use for a historical anchor. "Where does my
recomposition stand" is meaningless for an arbitrary historical window -- it is always a question
about now.

So there is nothing here for a model to get wrong, and nothing to validate. Do NOT add a
``weeks`` parameter for symmetry with the other tools; it would be an argument the analytics
layer has no place to receive.

**BODY-05's ``fitness_get_body_measurement_trend``, added in Phase 11, DOES take one argument** --
a closed ``BodyMeasurementMetric`` selector, not a window -- and the no-window reasoning above
holds for it unchanged: the 90-day comparison window is a module constant in
``analytics/body_measurements.py``, not a caller parameter, for exactly the reason given above. A
metric selector is a closed enum the SDK validates at the schema layer before this module ever
runs, which is a different kind of argument than a caller-chosen date or window would be.

**The disclaimer travels verbatim.** ``RecompositionResponse`` embeds ``RecompositionResult``
WHOLE rather than projecting selected fields, so ``RecompositionResult.disclaimer`` reaches
Claude in every response that carries a verdict, by construction rather than by remembering
(T-06-09). That field's own docstring in ``app/analytics/schemas.py`` calls it "a REQUIRED FIELD,
not documentation" precisely because a Phase 6 serialization change is the thing that could drop
it -- this module is that change, and it does not.
"""

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.body_measurements import get_body_measurement_trend
from app.analytics.bodyweight import get_body_weight_trend
from app.analytics.recomposition import get_recomposition_status
from app.analytics.schemas import BodyMeasurementMetric
from app.mcp.context import AppContext
from app.mcp.tools._common import read_only_session, resolve_user_id, safe_tool
from app.mcp.tools.schemas import (
    BodyMeasurementTrendResponse,
    BodyWeightTrendResponse,
    RecompositionResponse,
)

# No module logger here on purpose: neither tool has a branch of its own to report. Both take no
# arguments, so there is nothing to reject, and every failure path is `safe_tool`'s single
# `log.exception("mcp_tool_failed")`. An unused logger would read as a missing log line.


def _degraded_trend() -> BodyWeightTrendResponse:
    """BODY-01's "I could not reach the data" payload. ``data_available=False`` is NOT the same
    claim as "your weight has not moved" -- without the flag the two are byte-identical and
    Claude would narrate an outage as a plateau.

    Built by a factory rather than held as a module constant so each failure gets a fresh object
    and no caller can mutate the placeholder the next one receives (``safe_tool``'s contract).
    """
    return BodyWeightTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_trend)
async def fitness_get_body_weight_trend(ctx: Context[AppContext]) -> BodyWeightTrendResponse:
    """Body-weight trend anchored on today: 7-, 14- and 30-day rolling averages, the smoothed
    four-week rate of change in kg and percent per week, and the coverage behind each figure.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # The result is embedded whole, per-window coverage and all. A collapsed single coverage
        # flag would hide that a 30-day average can be trustworthy while the 7-day one is not.
        trend = await get_body_weight_trend(session, user_id=user_id)
    return BodyWeightTrendResponse(data_available=True, trend=trend)


def _degraded_recomposition() -> RecompositionResponse:
    """BODY-02's degraded payload. ``recomposition=None`` carries no verdict and therefore no
    disclaimer -- correct, because there is nothing here to qualify."""
    return RecompositionResponse(data_available=False, recomposition=None)


# NAMING DECISION, not an oversight. This tool is `..._status`, matching ROADMAP.md's wording and
# the `get_recomposition_status` analytics function it wraps. The blueprint's tool list spells the
# suffix `..._summary` instead; that spelling is deliberately NOT followed here.
#
# Two reasons. A tool whose name differs from the single function it calls is a name every reader
# has to hold two versions of, and the drift compounds the moment either side is renamed. And
# "status" is the honest word for what comes back: one label plus the two signals behind it, not a
# summary of a period. The blueprint's tool names are indicative -- it was written before the
# analytics layer existed -- while the analytics API is the thing that actually exists and is
# already committed. Where the two disagree on a name and only a name, the code wins.
@safe_tool(degraded=_degraded_recomposition)
async def fitness_get_recomposition_status(ctx: Context[AppContext]) -> RecompositionResponse:
    """Where body recomposition stands right now: a status verdict derived from the body-weight
    trend and the aggregate training-progression signal, with the disclaimer that frames it as
    decision support rather than a medical claim.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # THE MOST EXPENSIVE CALL IN THE PHASE, recorded rather than pre-optimized (T-06-13).
        # This one await runs `get_body_weight_trend` + `get_exercise_trends` + `get_weekly_volume`
        # over 12 weeks internally -- several aggregate queries against Claude's 30 s call budget.
        # All of them inside the SINGLE read-only transaction, which is the point: the weight
        # trend, the progression signal and the volume context are then one consistent snapshot
        # rather than three reads that could straddle a sync. Phase 4 measured the underlying
        # aggregate at ~50 ms on ~8k sets for one user; re-checked at the Phase 6 smoke test.
        recomposition = await get_recomposition_status(session, user_id=user_id)
    # Embedded WHOLE, never projected field-by-field -- this is what carries `disclaimer` through
    # untouched (T-06-09). Do not replace this with a hand-listed field mapping.
    return RecompositionResponse(data_available=True, recomposition=recomposition)


def _degraded_measurement_trend() -> BodyMeasurementTrendResponse:
    """BODY-05's "I could not reach the data" payload, built by a factory for the same reason
    ``_degraded_trend`` is: each failure gets a fresh object, so no caller can mutate the
    placeholder the next one receives (``safe_tool``'s contract)."""
    return BodyMeasurementTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_measurement_trend)
async def fitness_get_body_measurement_trend(
    ctx: Context[AppContext],
    metric: Annotated[
        BodyMeasurementMetric,
        Field(
            description=(
                "Which circumference or body-composition metric to compare, named exactly "
                "as the column: e.g. 'waist_cm', 'chest_cm', 'fat_percent', 'lean_mass_kg'. "
                "Body WEIGHT is not here -- use fitness_get_body_weight_trend for that."
            )
        ),
    ],
) -> BodyMeasurementTrendResponse:
    """One circumference or body-composition metric's latest reading compared against its
    earliest reading in the last 90 days: the two values, their dates, the exact difference,
    how many days were measured in that window, and whether the latest reading is itself
    stale.

    Covers the 14 circumference fields plus fat_percent and lean_mass_kg -- never body weight,
    which fitness_get_body_weight_trend already answers with rolling averages. This is a
    two-point comparison rather than an average because these metrics are spot checks, often
    weeks apart, and an average over them would be a fiction.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_body_measurement_trend(session, user_id=user_id, metric=metric)
    return BodyMeasurementTrendResponse(data_available=True, trend=trend)

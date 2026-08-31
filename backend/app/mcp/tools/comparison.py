"""Two-period comparison for MCP (MCP-02, MCP-03, MCP-05, MCP-06; D-06).

**This is the ONE tool in Phase 6 that takes explicit dates instead of an integer ``weeks``
count, and that is deliberate.** Every other window-taking tool accepts an integer ``weeks``
because a model choosing dates is a model with two chances to be wrong about what "the last
month" means (D-03). But "compare August to July" cannot be expressed as two ``weeks=N`` values
relative to today at all: both endpoints are historical and neither is anchored on now. Forcing
this tool into the ``weeks`` convention would delete the only question it exists to answer.

Do NOT "fix" this into consistency with the other tools. The inconsistency is the feature.

Two consequences follow from taking dates, and both are handled in the body rather than the
signature:

* ``dt.date`` cannot carry a ``Field(ge=/le=)`` bound the way ``int`` can, so the range checks
  that every other tool gets for free from its ``Annotated[int, Field(le=MAX_WEEKS)]`` have to
  be written out here. This is the one place in the phase where a tool validates its own
  arguments.
* Those checks must NOT raise. RESEARCH.md Pitfall 3 established that an exception message
  reaches Claude verbatim through the SDK's error channel, so a rejected range returns a
  schema-valid ``data_available=False`` response -- a correct "I could not do that" -- instead.

The A-is-baseline convention is ``compare_periods``' own, restated in the tool docstring because
the opposite convention is equally defensible and silently inverts every sign.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated

import structlog
from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.comparison import compare_periods
from app.analytics.schemas import ComparisonLevel, ComparisonRate
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_COMPARISON_ITEMS,
    MAX_COMPARISON_PERIOD_DAYS,
    read_only_session,
    resolve_user_id,
    safe_tool,
    truncate,
)
from app.mcp.tools.schemas import PeriodComparisonResponse

log = structlog.get_logger()


def _degraded_comparison() -> PeriodComparisonResponse:
    """The payload Claude gets when this tool cannot answer (``safe_tool``, and the range guard).

    Every list is empty and every optional field ``None``, but the two truncation pairs are still
    present and honest: ``False``/``0`` says "nothing was withheld because nothing was found",
    which is exactly true of a degraded result.
    """
    return PeriodComparisonResponse(
        data_available=False,
        period_a=None,
        period_b=None,
        totals=[],
        exercises=[],
        exercises_truncated=False,
        total_exercises=0,
        exercise_levels=[],
        exercise_levels_truncated=False,
        total_exercise_levels=0,
        muscle_groups=[],
        freshness=None,
    )


def _period_is_valid(start: dt.date, end: dt.date) -> bool:
    """One period, checked against D-06's two rules: forward-ordered and at most a year.

    Both rules exist for T-06-05. A reversed period produces a negative ``window.days`` and
    therefore a per-week normalisation divided by a negative number -- every delta silently
    inverted. An unbounded one (year 1000 to year 3000) is a scan with no ceiling; the widest
    legal comparison is two of these, so two years of history, which terminates.
    """
    if end < start:
        return False
    return (end - start).days + 1 <= MAX_COMPARISON_PERIOD_DAYS


def _rate_sort_key(row: ComparisonRate) -> tuple[Decimal, str]:
    """Biggest movement first, ties broken by id so the ordering is total and deterministic.

    ``delta_per_week`` is ``None`` for a metric neither period could produce; those sort last
    rather than crashing the comparison. ``Decimal`` and never ``float`` -- the whole analytics
    layer is Decimal precisely so two arithmetically identical totals compare equal.
    """
    return (-abs(row.delta_per_week or Decimal(0)), row.exercise_template_external_id or "")


def _level_sort_key(row: ComparisonLevel) -> tuple[Decimal, str]:
    """The ``ComparisonLevel`` twin of ``_rate_sort_key``. Levels carry ``delta``, not
    ``delta_per_week`` -- a maximum is never divided by weeks (``ComparisonRate``'s docstring)."""
    return (-abs(row.delta or Decimal(0)), row.exercise_template_external_id or "")


@safe_tool(degraded=_degraded_comparison)
async def fitness_compare_periods(
    ctx: Context[AppContext],
    period_a_start: Annotated[dt.date, Field(description="Baseline period start (inclusive).")],
    period_a_end: Annotated[dt.date, Field(description="Baseline period end (inclusive).")],
    period_b_start: Annotated[dt.date, Field(description="Comparison period start (inclusive).")],
    period_b_end: Annotated[dt.date, Field(description="Comparison period end (inclusive).")],
    include_muscle_groups: Annotated[
        bool, Field(description="Also break the comparison down by muscle group.")
    ] = False,
) -> PeriodComparisonResponse:
    """Compare two date periods, with every figure normalized per week so unequal-length windows
    do not produce misleading deltas.

    Period A is the BASELINE and period B the comparison: every delta reads "B minus A", so a
    positive number means more recently. To compare "the last 4 weeks against the previous 4",
    pass the OLDER range as A.
    """
    user_id = resolve_user_id(ctx)

    # Validated BEFORE a session is opened: an implausible range should cost nothing (T-06-05).
    #
    # Returning rather than raising is the point. A `raise ValueError("period_a_end 3000-01-01
    # ...")` here would reach Claude verbatim as tool-error text (Pitfall 3, T-06-01), and the
    # four dates are the model's OWN arguments, so echoing them back adds no information it does
    # not already have. A `data_available=False` response is a schema-valid, `is_error=False`
    # "I could not do that" -- the same shape every other failure in this phase takes.
    if not _period_is_valid(period_a_start, period_a_end) or not _period_is_valid(
        period_b_start, period_b_end
    ):
        # No date values in the event, for the same reason they are not in the response: the log
        # is not where a model-supplied argument needs to be replayed, and the deny-list style
        # (FOUND-05) is easier to keep true when the habit is "name the failure, carry no value".
        log.warning("mcp_compare_periods_invalid_range")
        return _degraded_comparison()

    async with read_only_session(ctx) as session:
        result = await compare_periods(
            session,
            user_id=user_id,
            period_a_start=period_a_start,
            period_a_end=period_a_end,
            period_b_start=period_b_start,
            period_b_end=period_b_end,
            include_muscle_groups=include_muscle_groups,
        )

    # Sorted by LARGEST MOVEMENT before the cap, not by the analytics layer's id ordering.
    # `compare_periods` returns these sorted by `exercise_template_external_id`, so truncating
    # that order to 25 keeps the alphabetically-first exercises -- a comparison that answers
    # "what changed?" with an arbitrary slice, which is worse than useless because it still looks
    # like an answer. The two lists are different populations (rates vs levels) and truncate
    # INDEPENDENTLY, each with its own flag/total pair.
    exercises, exercises_truncated, total_exercises = truncate(
        sorted(result.exercises, key=_rate_sort_key), MAX_COMPARISON_ITEMS
    )
    exercise_levels, exercise_levels_truncated, total_exercise_levels = truncate(
        sorted(result.exercise_levels, key=_level_sort_key), MAX_COMPARISON_ITEMS
    )

    # `totals` and `muscle_groups` pass through untruncated, and neither needs a flag: `totals` is
    # four metric rows, and `muscle_groups` is bounded at 19 by the canonical taxonomy. A bound
    # that comes from the shape needs no runtime cap.
    return PeriodComparisonResponse(
        data_available=True,
        period_a=result.period_a,
        period_b=result.period_b,
        totals=result.totals,
        exercises=exercises,
        exercises_truncated=exercises_truncated,
        total_exercises=total_exercises,
        exercise_levels=exercise_levels,
        exercise_levels_truncated=exercise_levels_truncated,
        total_exercise_levels=total_exercise_levels,
        muscle_groups=result.muscle_groups,
        freshness=result.freshness,
    )

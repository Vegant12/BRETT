"""The composed training summary (MCP-02, MCP-03, MCP-05, MCP-06; D-08).

One tool that answers both of PROJECT.md's Core Value questions -- "am I progressing?" and "which
muscles are undertrained?" -- in a single call, so the first thing Claude ever does in a coaching
conversation is not a four-tool chain. Like every other tool here it owns no arithmetic: each
number was computed by a function under ``app/analytics/`` that already has its own tests.

**What this tool deliberately EXCLUDES, and why.**

*Personal records and plateaus* keep their own dedicated tools. Duplicating them into the tool
every conversation opens with would pay their byte cost on every conversation, including the many
that never ask about a PR -- ask ``fitness_get_personal_records`` or ``fitness_get_plateaus``.

*The per-week x per-muscle grid and the per-exercise frequency list* are dropped for size.
Composing the four analytics results verbatim measures ~24 KB structured / ~57 KB on the wire at
a 4-week window, which is far too heavy for an opening call; this projection measures ~3,963 /
~9,502 (T-06-05). The grid is still available in full from ``fitness_get_muscle_group_volume``,
and per-exercise frequency from ``fitness_get_training_frequency``.

**What this tool COSTS.**

It issues four analytics calls, and ``get_recomposition_status`` alone internally runs
``get_body_weight_trend`` + ``get_exercise_trends`` + ``get_weekly_volume`` over its own fixed
12-week lookback -- roughly seven aggregate queries in one tool call. All of them run inside ONE
read-only transaction, which is correct rather than merely convenient: one consistent snapshot,
so the weekly volume and the recomposition verdict cannot describe two different databases.

The cost is recorded here because Claude's connector budgets are 10 s for discovery and 30 s for
a call, and a slow first tool call is the worst first impression this project can make (T-06-13).
It is accepted for v1 -- one user, ~8k sets, and Phase 4 measured the core aggregate at ~50 ms --
but if this ever needs optimizing, this is where to look, and the recomposition call is the half
that does the most work.
"""

from typing import Annotated

import structlog
from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.frequency import get_training_frequency
from app.analytics.recomposition import get_recomposition_status
from app.analytics.volume import get_muscle_group_volume, get_weekly_volume
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_SUMMARY_WEEKS,
    read_only_session,
    resolve_user_id,
    safe_tool,
    window_from_weeks,
)
from app.mcp.tools.schemas import SummaryVolumeWeek, TrainingSummaryResponse
from app.mcp.tools.volume import roll_up_muscles

log = structlog.get_logger()


def _degraded_summary() -> TrainingSummaryResponse:
    """The payload Claude gets when any of the four analytics calls raises (T-06-01).

    Every field is emptied, not partially filled: a summary that carries a real muscle rollup
    beside a missing verdict reads as "no recomposition signal" rather than as "this call
    failed". ``data_available=False`` is the only honest claim available here.
    """
    return TrainingSummaryResponse(
        data_available=False,
        window_start=None,
        window_end=None,
        weeks=None,
        sessions_per_week=None,
        volume_by_week=[],
        muscles=[],
        recomposition_status=None,
        recomposition_disclaimer=None,
        progression_signal=None,
        progression_verdict=None,
        weight_trend_rate_percent_per_week=None,
        average_7d_kg=None,
        coverage=None,
        freshness=None,
    )


@safe_tool(degraded=_degraded_summary)
async def fitness_get_training_summary(
    ctx: Context[AppContext],
    weeks: Annotated[
        int,
        # Capped at MAX_SUMMARY_WEEKS (12) rather than MAX_WEEKS (52) -- this response carries a
        # per-week row AND a 19-row muscle rollup, so its size grows with the window where the
        # single-purpose tools' does not (T-06-05). The DEFAULT is 4: one training block, and it
        # measures ~9.5 KB on the wire against the 16 KB budget while 12 weeks measures ~11.5 KB.
        # D-08 leaves the default to discretion; 4 is the block a coaching question is usually
        # about, and widening it is one argument away.
        Field(
            ge=1,
            le=MAX_SUMMARY_WEEKS,
            description="Whole weeks back from today, ending today. Max 12.",
        ),
    ] = 4,
) -> TrainingSummaryResponse:
    """The composed picture of training state in one call: weekly volume, how much work each of
    the 19 muscle groups is getting and how often, the aggregate progression verdict, and the
    current recomposition status with its disclaimer.

    Personal records and plateaus are deliberately not included -- ask
    `fitness_get_personal_records` or `fitness_get_plateaus` for those.
    """
    user = resolve_user_id(ctx)
    # ONE transaction around all four calls: one consistent snapshot, and one place where
    # `postgresql_readonly=True` is enforced by the server (MCP-05, T-06-03).
    async with read_only_session(ctx) as session:
        # NOT pre-snapped -- `get_weekly_volume` and `get_muscle_group_volume` snap this range
        # themselves. See `volume.py`'s module docstring for what double-snapping costs.
        start_day, end_day = await window_from_weeks(session, user_id=user, weeks=weeks)
        weekly = await get_weekly_volume(
            session, user_id=user, start_day=start_day, end_day=end_day
        )
        muscle_volume = await get_muscle_group_volume(
            session, user_id=user, start_day=start_day, end_day=end_day
        )
        frequency = await get_training_frequency(
            session, user_id=user, start_day=start_day, end_day=end_day
        )
        # Takes no window on purpose: "where does my recomposition stand" is always anchored on
        # today, over its own fixed 12-week lookback, independent of `weeks`.
        recomposition = await get_recomposition_status(session, user_id=user)

    return TrainingSummaryResponse(
        data_available=True,
        window_start=start_day,
        window_end=end_day,
        weeks=weeks,
        sessions_per_week=frequency.sessions_per_week,
        # `tonnage_sets` is dropped from each row on purpose: it is the operand-presence
        # denominator for `tonnage_kg`, which matters when auditing a number and not when
        # summarizing one. `fitness_get_weekly_volume` returns the full row.
        volume_by_week=[
            SummaryVolumeWeek(
                week_start=week.week_start,
                sessions=week.sessions,
                hard_sets=week.hard_sets,
                total_reps=week.total_reps,
                tonnage_kg=week.tonnage_kg,
            )
            for week in weekly.weeks
        ],
        # The SAME fold `fitness_get_muscle_group_volume` uses, imported rather than re-derived,
        # so the two tools can never disagree about a muscle's set count. It also guarantees all
        # 19 canonical groups appear -- a zero row is the answer to "which muscles are
        # undertrained?", and an omitted group is not.
        muscles=roll_up_muscles(muscle_volume, frequency),
        recomposition_status=recomposition.status,
        # VERBATIM, never reworded and never truncated (T-06-09). `analytics/schemas.py` calls
        # this "a REQUIRED FIELD, not documentation" precisely so a Phase 6 serialization change
        # cannot drop it, and dropping it while flattening the verdict into this shape is exactly
        # the failure that docstring anticipates.
        recomposition_disclaimer=recomposition.disclaimer,
        # Reported BESIDE the status, not folded into it: "likely_muscle_gain" with a negative
        # progression signal is a real disagreement, and one label hides it.
        progression_signal=recomposition.progression_signal.signal,
        progression_verdict=recomposition.progression_signal.verdict,
        weight_trend_rate_percent_per_week=recomposition.weight_trend.trend_rate_percent_per_week,
        average_7d_kg=recomposition.weight_trend.average_7d_kg,
        coverage=weekly.coverage,
        # Freshness from the MUSCLE result, never the weekly-volume one (T-06-14). The muscle
        # result's freshness covers BOTH `workouts` and `exercise_templates`, because the muscle
        # map comes from the templates; this response reports per-muscle numbers, so a stale
        # template sync silently changes them. The weekly-volume freshness covers workouts only
        # and would therefore claim a freshness this response does not have.
        freshness=muscle_volume.freshness,
    )

"""Volume and frequency tools (MCP-02, MCP-03, MCP-05, MCP-06; D-03, D-04, D-13).

The tools that answer PROJECT.md's second Core Value question, "which muscles are undertrained?".
Each one resolves the user server-side, converts ``weeks`` into a local date range, opens a READ
ONLY transaction and hands the range to ``app/analytics/``. **No arithmetic lives here.** Every
number in every response was computed by a function under ``app/analytics/`` that already has its
own tests; a second copy of "hard sets excludes warm-ups" or "a per-muscle session count is
COUNT(DISTINCT workout_id)" is a second copy that drifts, silently, into two plausible-looking
numbers.

Two things a reader of this module will otherwise get wrong:

**1. ``window_from_weeks`` already returns a MONDAY-anchored ``start_day``. Do not pre-snap it.**
``get_weekly_volume`` and ``get_muscle_group_volume`` call ``snap_local_week_range`` themselves,
and that snap widens a range OUTWARD to whole weeks. Snapping a second time here -- or handing
them a non-Monday start -- reaches back into the previous week, so a ``weeks=52`` request returns
**53** week rows. That breaks D-04's row cap for a reason that reads like an off-by-one in the
test rather than a missing anchor in the caller.

**2. ``get_muscle_group_volume`` snaps to whole weeks; ``get_training_frequency`` deliberately
does not.** ``fitness_get_muscle_group_volume`` composes both over the SAME ``(start_day,
end_day)`` pair anyway, and that is correct rather than merely tolerable: the snap only widens
``end_day`` from today to this week's Sunday -- days that carry no data, because they have not
happened -- while frequency divides by the window's TRUE elapsed length, which is what a rate
must divide by. Snapping frequency's window to match would report a rate over days that do not
exist in the user's question, turning a 10-day window into 2 weeks instead of 10/7.

``Decimal`` throughout, never ``float``: binary floating point makes two arithmetically identical
weekly totals compare unequal, and plan 06-09 asserts the absence statically.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated

import structlog
from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.schemas import (
    MuscleGroupFrequency,
    MuscleGroupVolumeResult,
    TrainingFrequencyResult,
)
from app.analytics.volume import get_weekly_volume
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_WEEKS,
    read_only_session,
    resolve_user_id,
    safe_tool,
    window_from_weeks,
)
from app.mcp.tools.schemas import MuscleGroupRollup, WeeklyVolumeResponse
from app.normalization.muscles import CanonicalMuscleGroup

log = structlog.get_logger()


@dataclass(slots=True)
class _MuscleTotals:
    """Additive set counts for one muscle group, accumulated across the window's weeks.

    ``weighted_sets`` starts at ``Decimal("0")`` and never ``0.0``: mixing binary floating point
    into a Decimal accumulation is a ``TypeError`` at best and a drifting total at worst.
    """

    direct_sets: int = 0
    indirect_sets: int = 0
    weighted_sets: Decimal = field(default_factory=lambda: Decimal("0"))


def roll_up_muscles(
    volume: MuscleGroupVolumeResult, frequency: TrainingFrequencyResult
) -> list[MuscleGroupRollup]:
    """Fold a per-week x per-muscle grid into ONE row per canonical muscle group.

    Returns exactly 19 rows, one per ``CanonicalMuscleGroup``, sorted by ``.value`` -- an
    untrained group is a ZERO row, never an absence. Both source results omit untrained groups
    entirely, and an omitted group is indistinguishable from a group the caller forgot to ask
    about. A zero row is the most diagnostically interesting row for "which muscles are
    undertrained?", which is the entire question this tool exists to answer.

    Set counts are SUMMED across weeks -- sets are additive. ``sessions`` and
    ``sessions_per_week`` are NOT summed: they are taken from ``frequency``, which de-duplicates
    workouts across the whole window. ``frequency.py``'s module docstring records what summing
    them instead did on real data: 14 of 16 muscle groups inflated by up to 4.0x, every inflated
    figure still reading as plausible training history.

    Pure and synchronous on purpose -- no session, no ``await`` -- so the 19-row invariant is
    unit-testable with no container behind it. Plan 06-08's training summary reuses this exact
    fold rather than growing a second one.
    """
    totals: dict[CanonicalMuscleGroup, _MuscleTotals] = {}
    for week in volume.weeks:
        for row in week.muscle_groups:
            bucket = totals.setdefault(row.muscle_group, _MuscleTotals())
            bucket.direct_sets += row.direct_sets
            bucket.indirect_sets += row.indirect_sets
            bucket.weighted_sets += row.weighted_sets

    by_group: dict[CanonicalMuscleGroup, MuscleGroupFrequency] = {
        row.muscle_group: row for row in frequency.muscle_groups
    }

    rollups: list[MuscleGroupRollup] = []
    # The full 19-member taxonomy, not the folded keys, and sorted by the enum VALUE rather than
    # left to declaration or dict-iteration order -- these responses get diffed between runs.
    for group in sorted(CanonicalMuscleGroup, key=lambda member: member.value):
        bucket = totals.get(group) or _MuscleTotals()
        found = by_group.get(group)
        rollups.append(
            MuscleGroupRollup(
                muscle_group=group,
                direct_sets=bucket.direct_sets,
                indirect_sets=bucket.indirect_sets,
                weighted_sets=bucket.weighted_sets,
                sessions=found.sessions if found is not None else 0,
                sessions_per_week=(found.sessions_per_week if found is not None else Decimal("0")),
                # Zero sessions IS insufficient -- `metadata.is_insufficient(0)` is True.
                # Defaulting to False here would let an untrained muscle read as a CONFIDENT
                # zero, which is the opposite of what an absent group means.
                insufficient_data=found.insufficient_data if found is not None else True,
            )
        )
    return rollups


def _degraded_weekly() -> WeeklyVolumeResponse:
    return WeeklyVolumeResponse(data_available=False, volume=None)


@safe_tool(degraded=_degraded_weekly)
async def fitness_get_weekly_volume(
    ctx: Context[AppContext],
    weeks: Annotated[
        int,
        Field(ge=1, le=MAX_WEEKS, description="Whole weeks back from today, ending today. Max 52."),
    ] = 12,
) -> WeeklyVolumeResponse:
    """Weekly training volume for the last N weeks: sessions, hard sets, total reps and tonnage
    per Monday-start week. Warm-up sets are excluded from every figure, and tonnage is reported
    only for sets that carry both a weight and a rep count.
    """
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # NOT pre-snapped: `get_weekly_volume` snaps this range itself. See the module docstring.
        start_day, end_day = await window_from_weeks(session, user_id=user, weeks=weeks)
        volume = await get_weekly_volume(
            session, user_id=user, start_day=start_day, end_day=end_day
        )
    return WeeklyVolumeResponse(data_available=True, volume=volume)

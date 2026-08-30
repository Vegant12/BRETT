"""The one query substrate under VOL-01, VOL-02 and VOL-03: window, aggregate, fan-out.

Five rules in this module are counter-intuitive, and each of the first three was measured
producing a silently wrong number against the live 327-workout database.

**One aggregate, at the ``(week, workout_id, template_id)`` grain.** VOL-01 (weekly volume),
VOL-02 (per-muscle volume) and VOL-03 (frequency) all read the same rows. The coarser
``(week, template_id)`` grain is the obvious simplification -- 16% fewer rows -- and it makes
per-muscle SESSION counts impossible to compute at all. Aggregating ``workout_id`` away inflated
hamstring frequency from 2 to 8 (4.0x) on one real training week.

**The tonnage gate is OPERAND PRESENCE, never a modality allow-list.** Tonnage is computed
wherever both a weight and a rep count exist, and nowhere else. The model's own modality
vocabulary had already drifted from what the provider actually sends; operand presence
reproduces the live modality table exactly and survives the provider inventing a tenth
modality tomorrow.

**Hard sets are an EXCLUSION of ``warmup``, never an allow-list of ``normal``.** Filtering to
``normal`` would discard 823 dropset sets -- 12% of all hard sets -- and would silently start
discarding ``failure`` sets the day the provider first sends one.

**Muscle resolution goes through ``effective_muscles_bulk``, never a join.** The override rule
is REPLACEMENT -- any override replaces the base set entirely -- and a join expresses merge. A
join agrees with the resolver today only because ``exercise_muscle_overrides`` holds zero rows;
it starts lying, with no error anywhere, the first time the user corrects a mapping.

**``Decimal``, never binary floating point, for every summed magnitude.** These figures multiply
into tonnage sums, and two arithmetically identical weekly totals must compare equal.

The split is deliberate: SQL does the counting, Python does the business rules. The aggregate is
one indexed statement; every fold below it is pure, synchronous and unit-testable with no
container. That is CLAUDE.md's "SQL aggregates + plain Python keeps them trivially
unit-testable" rule expressed as a file layout.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import (
    local_range_bounds,
    snap_local_week_range,
    validate_timezone,
)
from app.db.models.user import User

# VOL-01 excludes exactly this set type and no other. Written as the value being EXCLUDED, never
# as an allow-list of included types: `dropset` is 823 live sets (12% of hard sets) and `failure`
# is declared in workout.py but has never been sent, so an allow-list would start silently
# dropping it the day it first appears.
WARMUP_SET_TYPE = "warmup"

# U-02 (extends VOL-01). A duration-only set -- neither reps nor weight, e.g. a timed plank hold
# -- COUNTS as a hard set, exactly like any other non-warmup set. It contributes nothing to reps
# or tonnage because those columns are NULL for it.
#
# ONE constant, checked in ONE place (`_hard_set_predicates`), so flipping this decision later is
# a one-line change. Do NOT scatter a modality list through the query or the fold: 24 live sets
# are affected and the flip must not require finding every site.
COUNT_DURATION_ONLY_SETS = True

# ASVS V5 / MCP-03: reject an implausible range before any row is materialised, so a Phase 6 tool
# cannot ask for two centuries of week buckets. ~5 years, which comfortably covers the 17 months
# of real history and any "all time" question a coach would ask.
MAX_ANALYTICS_WINDOW_DAYS = 1830


@dataclass(frozen=True, slots=True)
class AnalyticsWindow:
    """A validated analytics window. INTERNAL -- never returned to a caller.

    ``start_day`` / ``end_day`` are POST-snap. When ``snap_to_weeks`` was False they equal what
    the caller asked for; when it was True they have been widened outward to whole Monday-start
    weeks (U-01), which is why weekly volume never reports a partial week as a whole one.

    ``days`` is the inclusive local-day span of ``[start_day, end_day]`` and is what frequency
    divides by, so an unsnapped 10-day window is 10/7 weeks and not 2.
    """

    tz: str
    start_day: dt.date
    end_day: dt.date
    utc_start: dt.datetime
    utc_end: dt.datetime
    days: int


def build_window(
    *, start_day: dt.date, end_day: dt.date, tz: str, snap_to_weeks: bool
) -> AnalyticsWindow:
    """Validate, optionally snap, and convert an inclusive local date range (D-03, U-01).

    Pure and synchronous on purpose: every guard here is a business rule, and encoding a
    business rule in SQL makes it untestable without a container.

    The clamp is applied to the RANGE THE CALLER ASKED FOR, before snapping, so the error
    message describes their request rather than a widened version of it. Every message names
    the failure and carries no date value and no user id, because it will be logged.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    if (end_day - start_day).days + 1 > MAX_ANALYTICS_WINDOW_DAYS:
        raise ValueError("requested analytics window exceeds the maximum span")

    # ASVS V5: `users.timezone` carries no DB CHECK constraint, and this string is about to
    # reach the query as a bound timezone parameter. Rejecting it here beats an
    # unknown-timezone failure raised from inside an aggregate query.
    zone = validate_timezone(tz)

    resolved_start, resolved_end = (
        snap_local_week_range(start_day, end_day) if snap_to_weeks else (start_day, end_day)
    )
    utc_start, utc_end = local_range_bounds(resolved_start, resolved_end, zone)
    return AnalyticsWindow(
        tz=zone,
        start_day=resolved_start,
        end_day=resolved_end,
        utc_start=utc_start,
        utc_end=utc_end,
        days=(resolved_end - resolved_start).days + 1,
    )


async def resolve_window(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    snap_to_weeks: bool,
) -> AnalyticsWindow:
    """Read the user's timezone (FOUND-03) and build the window.

    The timezone comes from ``users.timezone`` and is never a module constant, an environment
    variable or a caller default: a hardcoded default would let a wrong-timezone bug pass every
    test, and at UTC+7 every instant between 17:00Z and 24:00Z belongs to the NEXT local day --
    which is every morning workout.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return build_window(start_day=start_day, end_day=end_day, tz=tz, snap_to_weeks=snap_to_weeks)

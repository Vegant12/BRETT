"""VOL-01: hard sets, reps and modality-aware tonnage per whole local week.

Five rules below are counter-intuitive. The first three were each measured producing a silently
wrong number against the live 327-workout database; the last two are about what a bucket *is*.

**Hard sets are an EXCLUSION of ``warmup``, never an allow-list of ``normal``.** Filtering to
``normal`` would discard 823 live dropset sets -- 12% of all hard sets -- and would silently
start discarding ``failure`` sets the day the provider first sends one. The exclusion has one
site, ``rollup.WARMUP_SET_TYPE``, applied inside the aggregate; nothing here re-filters.

**Tonnage is gated on OPERAND PRESENCE and reported as ``None`` rather than ``0``.** The product
``weight x reps`` is NULL whenever either operand is, and SQL ``SUM`` skips those rows without a
warning -- 543 of 7,719 live non-warmup sets produce a NULL product. So a week is reported with
``tonnage_kg=None`` and ``tonnage_sets=0`` whenever its modalities cannot produce weight x reps.
"We could not compute tonnage for this week" is a different fact from "tonnage was zero", and
VOL-01's "where the modality supports it" is exactly that distinction. ``tonnage_sets`` travels
beside the figure so the population it was computed over is visible rather than assumed.

**A ``weight_kg`` of ``0`` is a real hard set contributing ``Decimal("0.000")``, not a missing
value.** 48 live non-warmup sets carry one -- a bodyweight-weighted exercise performed with no
added load. "Cleaning" the tonnage input with ``weight_kg > 0`` would drop every one of them and
under-report the weeks that contain them.

**U-01: the requested window is snapped OUTWARD to whole Monday-start weeks.** Without it,
asking for a window starting Wednesday 2026-07-01 produces a first bucket of Monday 2026-06-29
holding only part of that week -- a partial total that is not comparable to a full week and
reads as "volume dropped". Frequency (VOL-03) deliberately does NOT snap: it divides by the true
window length instead (D-03), so an incomplete week is already handled by the arithmetic.

**The week list is a gap-free SPINE enumerated from the window**, never inferred from the rows
the query returned. A week with no training returns no rows at all, and a silently missing zero
week is the most diagnostically interesting one Claude could have seen -- "you did not train"
must be a zero row, not an absence.

Composition only: every heavy mechanism lives elsewhere. The window guards and the aggregate are
``app.analytics.rollup``; the envelope is ``app.analytics.metadata``; the spine is
``app.core.time``. Plan 04-08 appends ``get_muscle_group_volume`` (VOL-02) to this module, which
follows the same shape with a muscle fan-out in the middle.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import FRESHNESS_RESOURCES_WORKOUTS, build_coverage, build_freshness
from app.analytics.rollup import SetRollupRow, resolve_window, weekly_set_rows
from app.analytics.schemas import WeeklyVolumeResult, WeeklyVolumeWeek
from app.core.time import local_week_spine


@dataclass(slots=True)
class _WeekTotals:
    """Accumulator for one local week. Intermediate; the frozen Pydantic model is the result.

    Mutable for the same reason ``rollup.MuscleBucket`` is: it is folded into, never returned.
    ``schemas.py``'s models are the frozen ones a caller ever sees.
    """

    hard_sets: int = 0
    total_reps: int | None = None
    tonnage_sets: int = 0
    tonnage_kg: Decimal = field(default_factory=lambda: Decimal(0))
    session_ids: set[uuid.UUID] = field(default_factory=set)


def _fold_week_totals(rows: Sequence[SetRollupRow]) -> dict[dt.date, _WeekTotals]:
    """Collapse (week, workout, template) rows into per-week totals.

    Pure and synchronous -- no session, no I/O -- so every rule here is unit-testable with no
    container, which is the whole reason the aggregate stops at this grain.

    ``total_reps`` stays ``None`` until some row actually reports reps, so a week whose only sets
    are duration holds returns ``None`` rather than a confident ``0``. ``session_ids`` is a SET
    for the same reason it is one in the muscle fold: one workout with three exercises is one
    session, and counting the rows instead inflates the figure while it still looks plausible.
    """
    weeks: dict[dt.date, _WeekTotals] = {}
    for row in rows:
        totals = weeks.setdefault(row.week_start, _WeekTotals())
        totals.hard_sets += row.hard_sets
        if row.total_reps is not None:
            totals.total_reps = (totals.total_reps or 0) + row.total_reps
        totals.tonnage_sets += row.tonnage_sets
        if row.tonnage_kg is not None:
            # Decimal, never binary floating point: two arithmetically identical weekly totals
            # must compare equal, or "did my tonnage change this week?" becomes a coin flip.
            totals.tonnage_kg += row.tonnage_kg
        totals.session_ids.add(row.workout_id)
    return weeks


async def get_weekly_volume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
) -> WeeklyVolumeResult:
    """VOL-01: hard sets, reps and modality-aware tonnage per whole local week.

    The window is snapped outward to whole Monday-start weeks (U-01), so every bucket is a
    comparable full week. Frequency deliberately does NOT snap -- it divides by the true window
    length instead (D-03).

    Takes the session positionally and everything else keyword-only, matching
    ``app/db/repositories/``. ``user_id`` has no default: ASVS V4, the schema is
    multi-user-ready, so forgetting it must be a ``TypeError`` and never a cross-tenant read.
    The caller owns the transaction; nothing here writes.
    """
    window = await resolve_window(
        session,
        user_id=user_id,
        start_day=start_day,
        end_day=end_day,
        snap_to_weeks=True,
    )
    # ONE aggregate, folded once. Re-querying per figure defeats the reason the grain is this
    # fine, and re-deriving a window total by summing these per-week session counts would
    # double-count every workout -- call the whole-window fold on the same rows instead.
    rows = await weekly_set_rows(session, user_id=user_id, window=window)
    folded = _fold_week_totals(rows)

    weeks: list[WeeklyVolumeWeek] = []
    # The SPINE, not the folded keys: a zero-training week must appear as a zero row.
    for week_start in local_week_spine(window.start_day, window.end_day):
        totals = folded.get(week_start)
        if totals is None:
            totals = _WeekTotals()
        weeks.append(
            WeeklyVolumeWeek(
                week_start=week_start,
                # Distinct workouts, never a row count: one workout with three exercises is
                # three rows at this grain and exactly one session.
                sessions=len(totals.session_ids),
                hard_sets=totals.hard_sets,
                total_reps=totals.total_reps,
                tonnage_sets=totals.tonnage_sets,
                # None, never 0: "we could not compute tonnage for this week" is a different
                # fact from "tonnage was zero", and VOL-01's "where the modality supports it"
                # is exactly this distinction.
                tonnage_kg=totals.tonnage_kg if totals.tonnage_sets else None,
            )
        )

    return WeeklyVolumeResult(
        weeks=weeks,
        coverage=await build_coverage(
            session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
        ),
        # VOL-01 depends on `workouts` alone -- it never resolves a muscle map, so
        # `exercise_templates` staleness cannot change any number here. A per-muscle answer
        # must ask for the other tuple, or it reports a freshness it does not actually have.
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_WORKOUTS
        ),
    )

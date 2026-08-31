"""Exercise progression, trend and plateau analytics (PROG-01, PROG-02, PROG-03).

All three requirements consume the identical artefact -- the per-(exercise, local day)
best-qualifying-set series D-04 defines -- so they share one module and one fold. Splitting them
into three files means three importers of a private series builder, or three copies of it.

**The day's headline set is the one with the highest ESTIMATED 1RM, not the heaviest.** Epley
maps 60 kg x 10 to 80.000 and 70 kg x 5 to 81.667: a lighter set at more reps can imply more
strength. Picking the heaviest weight instead returns a number that is real, in the right units,
and wrong -- and it silently flattens a lifter who progressed by adding reps rather than load.

**A day whose sets fail the e1RM gates still produces a point.** PROG-01 must report the weight,
reps and sets it saw, with a REASON for the missing estimate. On live data 376 of 2,239
exercise-sessions (16.8%) have no e1RM-qualifying set at all -- a deload week, a 5/3/1 wave, a
high-rep accessory day. Dropping those days would make a rep-periodized block look like a
training gap. D-07a's plateau SKIP is applied by the plateau scanner reading the resulting
``None``; it is not applied here.

**Days with no training are ABSENT, not zero rows** -- deliberately unlike ``volume.py``'s
gap-free week spine. A zero-training week is diagnostically interesting; a non-training day is
every day.

**Epley across a 5-to-12 rep spread swings 20% at unchanged strength.** Every high-frequency
template on the live account spans reps 5 to 12 with a standard deviation of 1.9-2.4, and Epley's
multiplier ranges 1.167 to 1.400 across that span. D-04's max-per-day absorbs most of it; D-07's
2% tolerance and D-05's 4-week minimum absorb the rest. Do not "fix" a 3% week-to-week wobble --
it is rep-scheme noise, and per-rep-range normalization is AN-V1X territory.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.estimates import NoEstimateReason, estimate_1rm
from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,
    build_coverage,
    build_freshness,
)
from app.analytics.rollup import QualifyingSetRow, qualifying_set_rows, resolve_window
from app.analytics.schemas import ExerciseProgressionResult, ProgressionPoint

# The leading slot of the comparison key: an ESTIMATED set always outranks an unestimated one,
# whatever their magnitudes. `Decimal` rather than `int` so the whole key is one numeric type and
# a tuple comparison never mixes them.
_ESTIMATED = Decimal(1)
_UNESTIMATED = Decimal(0)

# Ranks a missing weight BELOW every real one, including a genuine `Decimal("0.000")`. 48 live
# non-warm-up sets carry a real zero weight -- a bodyweight-weighted exercise performed with no
# added load -- so the sentinel has to sit strictly below zero rather than at it.
_NO_WEIGHT_RANK = Decimal(-1)


@dataclass(slots=True)
class SessionBest:
    """One (exercise, local day). Accumulator during the fold; never returned to a caller.

    Mutable for the same reason ``volume._WeekTotals`` and ``rollup.MuscleBucket`` are: it is
    folded into, and ``schemas.py``'s frozen Pydantic models are the ones a caller ever sees.

    ``sets``, ``total_reps``, ``volume_kg`` and ``volume_sets`` describe the WHOLE day for this
    exercise. ``best_*`` describes only the D-04 selected set. Do not conflate them: "you did four
    sets" and "your best set was 100 kg x 5" are different facts.

    ``volume_sets`` sits beside ``volume_kg`` for the reason ``tonnage_sets`` sits beside
    ``tonnage_kg``: a sum computed over a silently smaller population is a real number that is
    wrong, and only the count makes the shortfall visible.
    """

    local_day: dt.date
    template_external_id: str
    workout_id: uuid.UUID
    title: str | None = None
    exercise_type: str | None = None
    sets: int = 0
    total_reps: int | None = None
    volume_kg: Decimal = field(default_factory=lambda: Decimal(0))
    volume_sets: int = 0
    best_weight_kg: Decimal | None = None
    best_reps: int | None = None
    best_e1rm_kg: Decimal | None = None
    no_estimate_reason: NoEstimateReason | None = None


def best_set_per_day(
    rows: Sequence[QualifyingSetRow],
) -> dict[tuple[str, dt.date], SessionBest]:
    """D-04: one entry per (template, local day), headlined by the highest-e1RM set.

    PUBLIC and pure rather than private, for the same class of reason ``sessions_per_week`` is
    public: PROG-02, PROG-03, PROG-04's estimated-1RM record and CMP-01's per-exercise level all
    need "the lifter's best set that day", and three private copies is how three of them would
    eventually disagree about whether the lifter got stronger. No session, no I/O -- so D-04's
    tie-break is testable with no container.

    THE TIE-BREAK IS PART OF THE SPEC, not an implementation detail. At equal e1RM, prefer MORE
    reps; at equal reps, prefer the LOWER ``set_index``. Genuine ties happen constantly on machine
    stacks with fixed increments, and preferring more reps is the conservative reading -- more
    total work for the same estimate. Without a stated tie-break the answer depends on row order,
    which once PROG-03 scans it as a streak is a WRONG answer rather than a flaky one.

    A day whose sets ALL fail the gates still gets an entry. Its ``best_*`` fields come from the
    heaviest set (``weight_kg``, ``None`` ranked last), tie-broken the same way, and
    ``no_estimate_reason`` is that set's reason.
    """
    bests: dict[tuple[str, dt.date], SessionBest] = {}
    # The winning comparison key per entry, held BESIDE the accumulator rather than on it: it is
    # ranking scaffolding, not a fact about the day, and putting it on `SessionBest` would leak
    # it to every caller of this function.
    winning: dict[tuple[str, dt.date], tuple[Decimal, ...]] = {}

    # Iterated in the order given -- `qualifying_set_rows` already orders by
    # (template, local_day, workout_id, set_index), and re-sorting here would silently make the
    # fold's answer depend on a second ordering rule that nothing states.
    for row in rows:
        key = (row.template_external_id, row.local_day)
        best = bests.get(key)
        if best is None:
            # Seeded from the FIRST row seen for this key. `workout_id` is provisional and is
            # replaced below the moment a better set is found, so a day whose selected set came
            # from the second workout reports that second workout.
            best = SessionBest(
                local_day=row.local_day,
                template_external_id=row.template_external_id,
                workout_id=row.workout_id,
                title=row.title,
                exercise_type=row.exercise_type,
            )
            bests[key] = best

        # Day totals accumulate over EVERY row, selected or not. This is the "you did four sets"
        # half of the entry and it must not be narrowed to the headline set.
        best.sets += 1
        if row.reps is not None:
            # Stays `None` until some set actually reports reps, so a day of duration-only holds
            # returns `None` rather than a confident `0`.
            best.total_reps = (best.total_reps or 0) + row.reps
        if row.weight_kg is not None and row.reps is not None:
            # Operand presence, never a modality allow-list -- the same gate `rollup.py` applies
            # to tonnage. Decimal * int stays exact.
            best.volume_kg += row.weight_kg * row.reps
            best.volume_sets += 1

        # Called EXACTLY ONCE per row. Both slots are needed -- the value to rank by and the
        # reason to report when there is no value -- and a second call would be a second chance
        # for the two to disagree.
        value, reason = estimate_1rm(
            weight_kg=row.weight_kg, reps=row.reps, exercise_type=row.exercise_type
        )

        # The leading 0/1 rank is what stops a heavy 20-rep set from outranking an estimated
        # 5-rep set. The two populations are not comparable and must not be compared by
        # magnitude -- an estimated set always wins, and only then does the value decide.
        #
        # Slots 3 and 4 are D-04's tie-break, spelled into the key rather than applied as a
        # follow-up comparison: more reps wins, then the LOWER set_index (negated, so that
        # "lower is better" stays "greater is better" for the whole tuple).
        candidate: tuple[Decimal, ...] = (
            _ESTIMATED if value is not None else _UNESTIMATED,
            value
            if value is not None
            else (row.weight_kg if row.weight_kg is not None else _NO_WEIGHT_RANK),
            Decimal(row.reps or 0),
            Decimal(-row.set_index),
        )

        incumbent = winning.get(key)
        # STRICTLY greater: at a full tie the earlier row -- which the ordering guarantees has
        # the lower set_index -- keeps the slot.
        if incumbent is None or candidate > incumbent:
            winning[key] = candidate
            best.workout_id = row.workout_id
            best.best_weight_kg = row.weight_kg
            best.best_reps = row.reps
            best.best_e1rm_kg = value
            best.no_estimate_reason = reason

    # Returned UNSORTED on purpose: the caller decides the output order, and PROG-01 sorts by
    # local day while PROG-02 and PROG-03 group by template first.
    return bests


async def get_exercise_progression(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exercise_template_external_id: str,
    start_day: dt.date,
    end_day: dt.date,
) -> ExerciseProgressionResult:
    """PROG-01: weight, reps, sets, volume and a trusted estimated 1RM per local training day.

    Takes the session positionally and everything else keyword-only, matching
    ``app/db/repositories/``. ``user_id`` has no default: ASVS V4, the schema is multi-user-ready,
    so forgetting it must be a ``TypeError`` and never a cross-tenant read a single-user suite
    cannot see. The caller owns the transaction; nothing here writes.

    The window is resolved WITHOUT week snapping. This follows ``frequency.py``, not
    ``volume.py``: weekly volume widens outward because its buckets must be comparable to one
    another, and a per-day series has no such requirement. Snapping would silently return days
    the caller did not ask for.

    ``freshness`` names BOTH ``workouts`` and ``exercise_templates``, not just workouts, because
    ``exercise_type`` -- the D-03 e1RM gate -- comes from the templates table. A stale template
    sync silently changes every eligibility decision in this response, with no error anywhere in
    the stack.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=False
    )
    # ONE aggregate, folded once, narrowed to this exercise by a BOUND `IN` list (ASVS V5).
    # Re-querying per figure defeats the reason the grain is this fine.
    rows = await qualifying_set_rows(
        session,
        user_id=user_id,
        window=window,
        template_external_ids=[exercise_template_external_id],
    )
    bests = best_set_per_day(rows)

    points = [
        ProgressionPoint(
            local_day=best.local_day,
            workout_id=best.workout_id,
            sets=best.sets,
            total_reps=best.total_reps,
            # None, never 0: "no set that day had both a weight and reps" is a different fact
            # from "the day's volume was zero kilograms" -- the same distinction `volume.py`
            # draws for tonnage, and the reason `volume_sets` is carried at all.
            volume_kg=best.volume_kg if best.volume_sets else None,
            volume_sets=best.volume_sets,
            best_weight_kg=best.best_weight_kg,
            best_reps=best.best_reps,
            estimated_1rm_kg=best.best_e1rm_kg,
            no_estimate_reason=best.no_estimate_reason,
        )
        # Ascending by local day. Deterministic ordering is a repo-wide rule, and for a series
        # Claude reads chronologically it is also the only correct one.
        for _, best in sorted(bests.items(), key=lambda item: item[0][1])
    ]

    return ExerciseProgressionResult(
        exercise_template_external_id=exercise_template_external_id,
        # Read off the rows rather than re-queried: `qualifying_set_rows` already carries the
        # title and modality from its tenant-scoped template outerjoin, which is why
        # `frequency._template_titles` is neither needed nor copied here.
        title=next((row.title for row in rows), None),
        exercise_type=next((row.exercise_type for row in rows), None),
        window_start=window.start_day,
        window_end=window.end_day,
        points=points,
        coverage=await build_coverage(
            session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
        ),
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_MUSCLE
        ),
    )

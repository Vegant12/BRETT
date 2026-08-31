"""Personal records (PROG-04). SET grain, never the collapsed per-day series.

D-04's last sentence is the design constraint: PRs are found by scanning individual qualifying
sets, not by first collapsing to one value per date. Collapsing first would hide a 22-rep PR set
performed on a day whose headline set was a heavy triple -- the exact day a rep PR is most likely
to happen.

**Only 'warmup' is excluded, and the exclusion happens once, in SQL.** D-08 keeps `dropset` (823
live sets, 12% of all hard sets) and the declared-but-never-sent `failure` type fully eligible for
every record type: a to-failure set is a real, hard effort, and rep PRs in particular happen ON a
to-failure set by design. This module therefore does NOT re-check `set_type` --
`rollup._hard_set_predicates()` is the one definition, and an allow-list of `'normal'` here would
silently delete a tenth of the data.

**D-02's 12-rep cap gates the ESTIMATE, never the observation.** The rep PR and the max-weight PR
are deliberately un-gated. Applying the cap to them would hide the 320 live sets at exactly 20
reps and all 879 at 15 -- and the rep PR is precisely the record that lives above 12 reps.

**On a tie, the EARLIEST date wins (D-09).** "When did I first hit this" is the convention, not
"when did I most recently reconfirm it". Expressed as a SINGLE sort key so the rule cannot be
forgotten at one of five call sites: ``(value, -achieved_on.toordinal())`` maximised gives the
highest value at the earliest date. The numbers still look plausible under the wrong rule, which
is why this has to be structural rather than reviewed.

**The per-weight rep list is bounded by the DATA, not by a cap.** The live account has at most 12
distinct weights per exercise (mean 5.0), so returning the whole list satisfies MCP-03's "no
unbounded result sets" by shape. Do not add a row cap -- a silent truncation is a wrong answer,
and the absence of one is asserted statically rather than left to review.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER
owns the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.estimates import estimate_1rm
from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,
    build_coverage,
    build_freshness,
)
from app.analytics.rollup import (
    QualifyingSetRow,
    qualifying_set_rows,
    resolve_window,
)
from app.analytics.schemas import (
    PersonalRecord,
    PersonalRecordsResult,
    PersonalRecordType,
    RepsAtWeightRecord,
)

# Mirrors `workout_sets.weight_kg` Numeric(7, 3), and quantized at the boundary in ONE place for
# `_E1RM_QUANTUM`'s reason: a session-volume sum inherits the widest scale of its operands, and a
# coach reads `2140.000` rather than a figure whose scale depends on which sets were logged.
_VOLUME_QUANTUM = Decimal("0.001")

# `(value, -achieved_on.toordinal())`. Built only by `_key` and compared only by `_better`, so
# D-09 has exactly one implementation rather than one per record type.
_RecordKey = tuple[Decimal, int]


def _key(value: Decimal, achieved_on: dt.date) -> _RecordKey:
    """D-09's tie-break, folded INTO the value being compared.

    Negating the ordinal is what turns "highest value, earliest date" into a single ``>``, rather
    than a value comparison followed by a date comparison that someone has to remember to write
    the right way round at five separate call sites.
    """
    return value, -achieved_on.toordinal()


def _better(candidate: _RecordKey, incumbent: _RecordKey | None) -> bool:
    """D-09 as ONE comparison. ``candidate`` is ``(value, -achieved_on.toordinal())``.

    Higher value wins; at equal value the LARGER second element wins, and because the ordinal is
    negated that is the EARLIER date. One function, five call sites, one rule.
    """
    return incumbent is None or candidate > incumbent


@dataclass(slots=True)
class _SessionVolume:
    """One exercise-session's tonnage accumulator. Mutable -- an intermediate, never returned.

    ``volume_sets`` sits beside ``volume_kg`` for the reason ``tonnage_sets`` sits beside
    ``tonnage_kg`` in ``rollup.SetRollupRow``: the sum is computed only over sets carrying BOTH
    operands, and 543 of 7,719 live non-warm-up sets carry only one. Without the count, a partial
    computation is indistinguishable from a complete one.

    ``local_day`` is carried per WORKOUT and never per set: every set in one workout shares the
    workout's local day, and that day is what D-09 breaks ties on.
    """

    local_day: dt.date
    volume_kg: Decimal = field(default_factory=lambda: Decimal(0))
    volume_sets: int = 0


async def get_personal_records(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exercise_template_external_id: str,
    start_day: dt.date,
    end_day: dt.date,
) -> PersonalRecordsResult:
    """PROG-04: five record types with the date each was first reached, warm-ups excluded.

    Session positional, everything else keyword-only; ``user_id`` has no default (ASVS V4). The
    caller owns the transaction; nothing here writes. The window is resolved WITHOUT week
    snapping -- a record is a point in time and has no bucket to be comparable with.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=False
    )
    rows = await qualifying_set_rows(
        session,
        user_id=user_id,
        window=window,
        # A BOUND `IN` list that can only NARROW (T-05-31): the tenant predicate inside the
        # aggregate is unconditional and leads it, so this cannot widen the scope.
        template_external_ids=[exercise_template_external_id],
    )

    best_weight: tuple[_RecordKey, QualifyingSetRow] | None = None
    best_reps: tuple[_RecordKey, QualifyingSetRow] | None = None
    best_e1rm: tuple[_RecordKey, QualifyingSetRow] | None = None
    # Keyed on the exact Decimal the driver returned. Never normalise or round the key --
    # 60.000 and 60.0 are the same weight and Decimal already compares them equal, but quantizing
    # here would merge 60.000 and 60.005, which are different plates.
    per_weight: dict[Decimal, tuple[_RecordKey, dt.date]] = {}
    per_session: dict[uuid.UUID, _SessionVolume] = {}

    # ONE pass, feeding every accumulator from the same row. Nothing below consults how a set was
    # classified -- the warm-up exclusion already happened, in SQL, once.
    #
    # (A comment here must never OPEN with the four characters `# type` followed by a colon:
    # mypy reads that as a PEP 484 type comment and fails the file with a bare `Invalid syntax`
    # pointing at the comment line, which is a genuinely baffling half hour.)
    for row in rows:
        if row.weight_kg is not None:
            weight_candidate = _key(row.weight_kg, row.local_day)
            if _better(weight_candidate, best_weight[0] if best_weight is not None else None):
                best_weight = (weight_candidate, row)

        if row.reps is not None:
            # The estimate's trusted rep range is deliberately NOT applied here: this is an
            # OBSERVATION, and the rep PR is precisely the record that lives above that range.
            reps_candidate = _key(Decimal(row.reps), row.local_day)
            if _better(reps_candidate, best_reps[0] if best_reps is not None else None):
                best_reps = (reps_candidate, row)

        # Called once per row, and its gates (D-02 modality, D-03 rep range) bound ONLY this
        # record. A `None` here is an ineligible ESTIMATE, never an ineligible set.
        estimated, _ = estimate_1rm(
            weight_kg=row.weight_kg, reps=row.reps, exercise_type=row.exercise_type
        )
        if estimated is not None:
            e1rm_candidate = _key(estimated, row.local_day)
            if _better(e1rm_candidate, best_e1rm[0] if best_e1rm is not None else None):
                best_e1rm = (e1rm_candidate, row)

        # Operand presence, never a modality allow-list -- `rollup.weekly_set_rows`' tonnage rule,
        # applied at set grain. A set missing either operand contributes to neither the per-weight
        # list nor the session sum, and is not counted in `volume_sets`.
        if row.weight_kg is None or row.reps is None:
            continue

        at_weight = per_weight.get(row.weight_kg)
        rep_candidate = _key(Decimal(row.reps), row.local_day)
        if _better(rep_candidate, at_weight[0] if at_weight is not None else None):
            per_weight[row.weight_kg] = (rep_candidate, row.local_day)

        accumulated = per_session.setdefault(row.workout_id, _SessionVolume(row.local_day))
        accumulated.volume_kg += row.weight_kg * row.reps
        accumulated.volume_sets += 1

    # Per EXERCISE-SESSION, never per window: "your best session was 2,140 kg" and "you moved
    # 2,140 kg this month" are different facts, and summing across the window silently answers
    # the second when the first was asked.
    best_volume: tuple[_RecordKey, _SessionVolume] | None = None
    for session_volume in per_session.values():
        volume_candidate = _key(
            session_volume.volume_kg.quantize(_VOLUME_QUANTUM), session_volume.local_day
        )
        if _better(volume_candidate, best_volume[0] if best_volume is not None else None):
            best_volume = (volume_candidate, session_volume)

    # A record type with no eligible set is ABSENT, never present with a zero -- an exercise
    # never loaded has no max-weight record, and a zero would read as one.
    records: list[PersonalRecord] = []
    if best_weight is not None:
        weight_key, weight_row = best_weight
        records.append(
            PersonalRecord(
                record_type=PersonalRecordType.MAX_WEIGHT,
                value=weight_key[0],
                achieved_on=weight_row.local_day,
                weight_kg=weight_row.weight_kg,
                reps=weight_row.reps,
                volume_sets=None,
            )
        )
    if best_reps is not None:
        reps_key, reps_row = best_reps
        records.append(
            PersonalRecord(
                record_type=PersonalRecordType.MAX_REPS,
                value=reps_key[0],
                achieved_on=reps_row.local_day,
                # May be None -- a `reps_only` set sets a rep PR and has no weight, and inventing
                # a zero here would read as "22 reps at 0 kg".
                weight_kg=reps_row.weight_kg,
                reps=reps_row.reps,
                volume_sets=None,
            )
        )
    if best_e1rm is not None:
        e1rm_key, e1rm_row = best_e1rm
        records.append(
            PersonalRecord(
                record_type=PersonalRecordType.ESTIMATED_1RM,
                value=e1rm_key[0],
                achieved_on=e1rm_row.local_day,
                weight_kg=e1rm_row.weight_kg,
                reps=e1rm_row.reps,
                volume_sets=None,
            )
        )
    if best_volume is not None:
        volume_key, volume = best_volume
        records.append(
            PersonalRecord(
                record_type=PersonalRecordType.SESSION_VOLUME,
                value=volume_key[0],
                achieved_on=volume.local_day,
                weight_kg=None,
                reps=None,
                volume_sets=volume.volume_sets,
            )
        )

    # Sorted by a stated key, never dict- or append-order -- Phase 6 will diff these between
    # runs, and a flaky ordering is a flaky test.
    records.sort(key=lambda record: record.record_type.value)
    reps_at_weight = sorted(
        (
            RepsAtWeightRecord(weight_kg=weight, reps=int(rep_key[0]), achieved_on=achieved_on)
            for weight, (rep_key, achieved_on) in per_weight.items()
        ),
        key=lambda record: record.weight_kg,
        reverse=True,
    )

    return PersonalRecordsResult(
        exercise_template_external_id=exercise_template_external_id,
        # Every row belongs to the one requested template, so the first row's title is the
        # exercise's title. `None` when the template is not synced locally -- the outer join in
        # `qualifying_set_rows` keeps those sets rather than dropping them.
        title=next((row.title for row in rows), None),
        window_start=window.start_day,
        window_end=window.end_day,
        records=records,
        reps_at_weight=reps_at_weight,
        coverage=await build_coverage(
            session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
        ),
        # BOTH resources: `exercise_type` is the D-03 gate for the estimated-1RM record and it
        # comes from the templates table, so a stale template sync silently changes which sets
        # are eligible for that record with no error anywhere in the stack.
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_MUSCLE
        ),
    )

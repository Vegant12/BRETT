"""Estimated one-rep-max (PROG-01 / D-01, D-02, D-03). Pure: no session, no I/O, no SQL.

A sibling of ``frequency.sessions_per_week`` in every respect that matters -- public, pure,
``Decimal``, quantized at the boundary -- and public for the same reason: every other Phase 5
number (PROG-01's series, PROG-02's slope, PROG-03's plateau streak, PROG-04's estimated-1RM
record) is derived from this one function, so a second copy is how two of them would eventually
disagree about whether the lifter got stronger.

**NEVER write this formula in SQL.** ``weight_kg * (1 + reps / 30)`` in PostgreSQL uses INTEGER
division for ``reps / 30``, which is ``0`` for every rep count below 30, so the "estimate"
silently becomes the bare weight lifted. Verified against the live database:
``SELECT 10 * (1 + 8/30)`` returns ``10`` -- a number of the right magnitude, in the right
units, on which every downstream ``>`` and ``max`` still works, and which no reviewer would
catch. ``backend/tests/test_analytics_isolation.py`` asserts this statically because the
docstring alone is not a defence.

**Epley is not rep-invariant, and that is the largest noise source in this phase.** Every
high-frequency template on the live account spans reps 5 to 12 with a standard deviation of
1.9-2.4 reps. Epley's multiplier ranges 1.167 (5 reps) to 1.400 (12 reps) -- a 20% swing at
completely unchanged strength. D-04's "best set of the day", D-07's 2% plateau tolerance and
D-05's 4-week minimum window each absorb part of it. Do not "fix" a 3% week-to-week wobble: it
is rep-scheme noise, not a defect, and per-rep-range normalization is AN-V1X territory.
"""

from decimal import Decimal
from enum import StrEnum

# D-02. Epley's error grows fast past ~12 reps as fatigue and form breakdown stop being
# proportional to load. 12 rather than the literature's usual 10 is a DATA-DRIVEN choice, and
# the tension with published guidance is recorded here deliberately rather than left as an
# oversight: reps=12 is this account's single largest bucket (1,043 of 6,939 weight_reps hard
# sets) and reps=11 adds 103 more. Cutting at 10 would discard 23.9% of otherwise-eligible sets
# and blind the analytics to the user's most-programmed rep scheme.
MAX_TRUSTED_REPS = 12

# D-03. An EXACT-MATCH gate, not an allow-list to be extended. `db/models/exercise.py`'s column
# comment warns against hardcoding a modality allow-list from its live distribution; this is the
# one place in the package a modality string is compared at all, and it compares against exactly
# one value. 4,802 of 7,719 live hard sets pass both gates -- the null-with-reason path is the
# majority-adjacent case, not an edge case, which is why the reason is a required return value.
E1RM_EXERCISE_TYPE = "weight_reps"

# Quantized at the boundary, in ONE place, for `_RATE_QUANTUM`'s reason: 100 kg x 7 reps is
# Decimal('123.3333333333333333333333333') unquantized -- a number no coach reads and no test
# asserts on stably. Three decimals mirrors `workout_sets.weight_kg` Numeric(7, 3).
_E1RM_QUANTUM = Decimal("0.001")

_THIRTY = Decimal(30)


class NoEstimateReason(StrEnum):
    """Why ``estimated_1rm`` is None. PROG-01 requires a REASON, never a bare null.

    Lives here rather than in ``schemas.py`` because it is an INPUT-side business rule, produced
    by the gates immediately below it. ``schemas.py`` imports it, the same direction that file
    already imports ``CanonicalMuscleGroup`` from ``app.normalization``.
    """

    MODALITY = "modality_not_weight_reps"
    REP_RANGE = "reps_above_trusted_range"
    MISSING_OPERAND = "missing_weight_or_reps"


def estimate_1rm(
    *, weight_kg: Decimal | None, reps: int | None, exercise_type: str | None
) -> tuple[Decimal | None, NoEstimateReason | None]:
    """Epley (D-01): ``weight x (1 + reps / 30)``, or ``(None, reason)``.

    Exactly one of the two returned slots is populated, ever. Keyword-only so a caller cannot
    transpose ``weight_kg`` and ``reps`` -- which would still typecheck and still return a
    plausible number.

    Gate ORDER is deliberate and is part of the contract: modality first, because "we do not
    estimate 1RM for bodyweight work at all" is a more useful explanation than "your reps were
    too high" for a set that would have failed both. ``exercise_type=None`` -- a workout
    referencing a template that is not synced locally -- is naturally MODALITY, not a crash.

    ``Decimal`` throughout, never binary floating point. ``Decimal(reps) / _THIRTY`` is inexact
    for most rep counts (7/30 repeats), but it is DETERMINISTIC under a fixed context and it is
    quantized immediately, so two runs on two machines agree exactly and a test can assert
    equality without ``pytest.approx``.
    """
    if exercise_type != E1RM_EXERCISE_TYPE:
        return None, NoEstimateReason.MODALITY
    if weight_kg is None or reps is None:
        return None, NoEstimateReason.MISSING_OPERAND
    if reps < 1 or reps > MAX_TRUSTED_REPS:
        return None, NoEstimateReason.REP_RANGE
    return (weight_kg * (Decimal(1) + Decimal(reps) / _THIRTY)).quantize(_E1RM_QUANTUM), None

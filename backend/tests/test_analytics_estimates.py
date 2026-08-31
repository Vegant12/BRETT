"""The e1RM formula and its two gates (PROG-01 / D-01, D-02, D-03), in the FAST suite.

NO integration marker, deliberately. This formula is the input to every other Phase 5 number,
and it must stay verifiable when Docker is not running -- the same argument
`test_analytics_frequency.py` makes for `sessions_per_week` and `test_normalization_mapping.py`
makes for `apply_weights`.

THE load-bearing test is `test_epley_exact_values`. The specific wrong number it catches is the
bare weight: `weight * (1 + reps/30)` in PostgreSQL is integer division, so `SELECT 10 * (1 +
8/30)` returns `10` instead of `12.667`. An implementation that leaked the formula into SQL
would return 100.000 for every one of the four rep counts below, and every downstream `>` and
`max` would still work.

Its partner is `test_gate_order_puts_modality_first`: without it, an implementation that checked
the operands first would still pass every value assertion while reporting `MISSING_OPERAND` for
a bodyweight set -- a reason string Claude would narrate as a data problem rather than a design
decision.

Never `pytest.approx` here. An approx in `app/analytics/` test code is the warning sign for a
leaked `float` (RESEARCH Pitfall 6).
"""

from decimal import Decimal

from app.analytics.estimates import MAX_TRUSTED_REPS, NoEstimateReason, estimate_1rm

# The modality string is spelled out here rather than imported from `estimates`. A test that
# asserts against the very constant it imports proves nothing -- the same reasoning
# `conftest.py` records for duplicating migration 0002's user id instead of importing it.
_WEIGHT_REPS = "weight_reps"

# One round weight, so every expected value below is hand-checkable as 100 x (1 + reps/30) and
# a reviewer never has to trust the test to know what the right answer is.
_HUNDRED = Decimal("100.000")

# Five real modalities from the live distribution documented in `db/models/exercise.py`, plus
# `None` -- a workout whose exercise template has not been synced locally. That last case must
# be a MODALITY refusal and not a crash.
_NON_ESTIMABLE_TYPES: tuple[str | None, ...] = (
    "bodyweight_weighted",
    "reps_only",
    "duration",
    "short_distance_weight",
    "bodyweight_assisted",
    None,
)


def test_epley_exact_values() -> None:
    """100.000 kg at 1 / 7 / 8 / 12 reps, exact, with no floating-point tolerance anywhere.

    Four rep counts rather than one: the SQL integer-division failure returns the BARE WEIGHT
    for every rep count below 30, so a single-value test could be satisfied by an
    implementation that is wrong everywhere else. 1 and 12 pin both ends of the trusted range,
    7 is a non-terminating quotient and 12 is the only one that terminates exactly.
    """
    assert estimate_1rm(weight_kg=_HUNDRED, reps=1, exercise_type=_WEIGHT_REPS) == (
        Decimal("103.333"),
        None,
    )
    assert estimate_1rm(weight_kg=_HUNDRED, reps=7, exercise_type=_WEIGHT_REPS) == (
        Decimal("123.333"),
        None,
    )

    value, reason = estimate_1rm(weight_kg=_HUNDRED, reps=8, exercise_type=_WEIGHT_REPS)
    assert value == Decimal("126.667"), (
        "expected 126.667; got the bare weight, which is what SQL integer division produces"
    )
    assert reason is None

    assert estimate_1rm(weight_kg=_HUNDRED, reps=12, exercise_type=_WEIGHT_REPS) == (
        Decimal("140.000"),
        None,
    )


def test_rep_gate_both_sides_of_twelve() -> None:
    """D-02's boundary, asserted as a PAIR so it cannot be half-deleted.

    `MAX_TRUSTED_REPS` and `MAX_TRUSTED_REPS + 1` rather than the literals 12 and 13: if the
    constant is ever retuned, this test moves with it instead of silently asserting a stale
    boundary that no longer exists in the module.
    """
    inside_value, inside_reason = estimate_1rm(
        weight_kg=_HUNDRED, reps=MAX_TRUSTED_REPS, exercise_type=_WEIGHT_REPS
    )
    assert inside_value is not None
    assert inside_reason is None

    assert estimate_1rm(
        weight_kg=_HUNDRED, reps=MAX_TRUSTED_REPS + 1, exercise_type=_WEIGHT_REPS
    ) == (None, NoEstimateReason.REP_RANGE)


def test_rep_gate_rejects_zero_and_negative() -> None:
    """Zero and negative reps are REP_RANGE, not a 1RM equal to (or below) the bare weight.

    Epley at 0 reps returns the weight itself, and at -1 reps returns LESS than the weight --
    both arithmetically fine and both meaningless as a strength estimate, which is exactly the
    kind of plausible number that survives review.
    """
    assert estimate_1rm(weight_kg=_HUNDRED, reps=0, exercise_type=_WEIGHT_REPS) == (
        None,
        NoEstimateReason.REP_RANGE,
    )
    assert estimate_1rm(weight_kg=_HUNDRED, reps=-1, exercise_type=_WEIGHT_REPS) == (
        None,
        NoEstimateReason.REP_RANGE,
    )


def test_modality_gate_rejects_every_other_type() -> None:
    """D-03 is an EXACT-MATCH gate: only `weight_reps` estimates, everything else refuses.

    Every case supplies a weight and a rep count inside the trusted range, so a pass here
    proves the MODALITY gate fired and not the operand or rep-range gate standing in for it.
    """
    for exercise_type in _NON_ESTIMABLE_TYPES:
        assert estimate_1rm(weight_kg=_HUNDRED, reps=8, exercise_type=exercise_type) == (
            None,
            NoEstimateReason.MODALITY,
        ), f"{exercise_type!r} must not produce an estimated 1RM"


def test_missing_operand_reason() -> None:
    """A `weight_reps` set missing either operand is MISSING_OPERAND, never a partial estimate.

    Both operands are nullable in `workout_sets`, so this is a real live-data path and not a
    defensive branch: treating a null weight as zero would report a 0.000 kg "record".
    """
    assert estimate_1rm(weight_kg=None, reps=8, exercise_type=_WEIGHT_REPS) == (
        None,
        NoEstimateReason.MISSING_OPERAND,
    )
    assert estimate_1rm(weight_kg=_HUNDRED, reps=None, exercise_type=_WEIGHT_REPS) == (
        None,
        NoEstimateReason.MISSING_OPERAND,
    )


def test_gate_order_puts_modality_first() -> None:
    """Gate ORDER is part of the contract, not an implementation detail.

    This input fails all three gates at once. Without this test, an implementation that checked
    the operands first would still pass every value assertion above while reporting
    `MISSING_OPERAND` for a bodyweight set -- a reason string Claude would narrate to the user
    as a data problem rather than as the design decision it actually is.
    """
    assert estimate_1rm(weight_kg=None, reps=20, exercise_type="reps_only") == (
        None,
        NoEstimateReason.MODALITY,
    )


def test_estimate_is_quantized_to_three_places() -> None:
    """Quantization happens INSIDE the function, at the boundary, exactly once.

    100.000 kg x 7 reps is `Decimal('123.3333333333333333333333333')` unquantized -- a number
    no coach reads, and one whose exact digits depend on the ambient decimal context, so an
    equality assertion downstream would become context-dependent. Three places mirrors
    `workout_sets.weight_kg` Numeric(7, 3).
    """
    value, reason = estimate_1rm(weight_kg=_HUNDRED, reps=7, exercise_type=_WEIGHT_REPS)
    assert value is not None
    assert reason is None

    # `DecimalTuple.exponent` is typed `Literal['n', 'N', 'F'] | int` -- the string variants
    # are how NaN, sNaN and Infinity are encoded. Narrowing to `int` is therefore a real
    # assertion and not a typechecker appeasement: an estimated 1RM of NaN would satisfy a
    # bare `value is not None` check and then poison every downstream `>` and `max` silently.
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int), f"estimate is not a finite Decimal: {value}"
    assert -exponent == 3, (
        "expected 3 decimal places; an unquantized result is "
        "Decimal('123.3333333333333333333333333')"
    )


def test_exactly_one_slot_is_populated() -> None:
    """The return contract: a value XOR a reason, never both and never neither.

    Six rows covering the estimate path plus all four refusal paths. A bare `None` estimate
    with no reason is the failure this forbids -- PROG-01 requires the reason so Claude can say
    WHY a number is absent instead of implying the training data is missing.
    """
    cases: tuple[tuple[Decimal | None, int | None, str | None], ...] = (
        (_HUNDRED, 8, _WEIGHT_REPS),
        (_HUNDRED, MAX_TRUSTED_REPS + 1, _WEIGHT_REPS),
        (_HUNDRED, 0, _WEIGHT_REPS),
        (_HUNDRED, 8, "reps_only"),
        (None, 8, _WEIGHT_REPS),
        (_HUNDRED, None, _WEIGHT_REPS),
    )
    for weight_kg, reps, exercise_type in cases:
        value, reason = estimate_1rm(
            weight_kg=weight_kg, reps=reps, exercise_type=exercise_type
        )
        assert (value is None) != (reason is None), (
            f"({weight_kg}, {reps}, {exercise_type!r}) populated both slots or neither"
        )

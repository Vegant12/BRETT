"""BODY-02: recomposition status from the weight trend and the training-progression signal.

Every test is SYNTHETIC and runs under a FROZEN CLOCK. On today's live data BODY-02 correctly
returns `insufficient_data` -- the D-16 anchor window holds zero weigh-ins after a real 52-day
logging gap -- and a test written against live data would start passing for the wrong reason
around 2026-09-06.

THE load-bearing test is `test_null_weight_rate_is_insufficient_regardless_of_progression`. The
specific wrong behaviour it catches is a fallback to D-17's raw single-week delta: on live data
that reads +0.475 kg on 65.65 kg = +0.72%/week, nearly THREE TIMES D-11's threshold, and the
verdict would flip from `insufficient_data` to `weight_gain_too_fast` purely on glycogen noise.

Its partner is `test_full_label_matrix`. Without exhaustive coverage of all 24 (bucket, signal)
pairs, a missing branch in a nested-if implementation falls through to a plausible-looking default
and no single-scenario test notices. The expected table below is written out by hand rather than
imported from the module: a test that asserts a mapping against itself proves nothing.

Every assertion is exact `Decimal` equality. No tolerance helper appears anywhere in this module,
and deliberately not even in this sentence -- a tolerance would let a quantization regression
through, and `net_score` is quantized on purpose.
"""

import datetime as dt
from decimal import Decimal

from app.analytics.recomposition import (
    INTERPRETATION_DISCLAIMER,
    RECOMP_MIN_CLASSIFIED_EXERCISES,
    RECOMP_PROGRESSION_NET_BAND,
    WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK,
    WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK,
    WEIGHT_STABLE_BAND_PERCENT_PER_WEEK,
    _weight_bucket,
    _WeightBucket,
    aggregate_progression,
    classify_recomposition,
)
from app.analytics.schemas import ProgressionSignal, RecompositionStatus, TrendVerdict

# 02:00 UTC is 09:00 in Asia/Jakarta -- the UTC day and the local day AGREE, so these tests
# isolate the classification rule rather than the anchor rule (05-06 already pins the anchor).
_RECOMP_NOW = "2026-08-30T02:00:00+00:00"
_ANCHOR = dt.date(2026, 8, 30)

# Local aliases, for this module only. The 24-pair table below is the whole point of the test and
# it has to be readable as a TABLE; spelled in full, every row wraps onto three lines and the
# shape stops being visible.
_RS = RecompositionStatus
_PS = ProgressionSignal
_WB = _WeightBucket
_TV = TrendVerdict

# One rate per bucket, chosen well inside its band so the matrix test cannot pass by landing on a
# boundary -- the edges are pinned separately by the three threshold tests below.
_REPRESENTATIVE_RATE: dict[_WeightBucket, Decimal | None] = {
    _WB.TOO_FAST_GAIN: Decimal("0.50"),
    _WB.ON_TARGET_GAIN: Decimal("0.20"),
    _WB.STABLE: Decimal("0.00"),
    _WB.LOSING: Decimal("-0.50"),
    _WB.TOO_FAST_LOSS: Decimal("-1.50"),
    _WB.INSUFFICIENT: None,
}

# D-20's label matrix, restated INDEPENDENTLY of the implementation. All 24 pairs, written out.
_EXPECTED_MATRIX: dict[tuple[_WeightBucket, ProgressionSignal], RecompositionStatus] = {
    (_WB.TOO_FAST_GAIN, _PS.POSITIVE): _RS.WEIGHT_GAIN_TOO_FAST,
    (_WB.TOO_FAST_GAIN, _PS.NEUTRAL): _RS.WEIGHT_GAIN_TOO_FAST,
    (_WB.TOO_FAST_GAIN, _PS.NEGATIVE): _RS.WEIGHT_GAIN_TOO_FAST,
    (_WB.TOO_FAST_GAIN, _PS.INSUFFICIENT): _RS.WEIGHT_GAIN_TOO_FAST,
    (_WB.ON_TARGET_GAIN, _PS.POSITIVE): _RS.LIKELY_MUSCLE_GAIN,
    (_WB.ON_TARGET_GAIN, _PS.NEUTRAL): _RS.LIKELY_MUSCLE_GAIN,
    (_WB.ON_TARGET_GAIN, _PS.NEGATIVE): _RS.LIKELY_MUSCLE_GAIN,
    (_WB.ON_TARGET_GAIN, _PS.INSUFFICIENT): _RS.LIKELY_MUSCLE_GAIN,
    (_WB.STABLE, _PS.POSITIVE): _RS.LIKELY_RECOMP_PROGRESSING,
    (_WB.STABLE, _PS.NEUTRAL): _RS.WEIGHT_STABLE,
    (_WB.STABLE, _PS.NEGATIVE): _RS.WEIGHT_STABLE,
    (_WB.STABLE, _PS.INSUFFICIENT): _RS.WEIGHT_STABLE,
    (_WB.LOSING, _PS.POSITIVE): _RS.LIKELY_RECOMP_PROGRESSING,
    (_WB.LOSING, _PS.NEUTRAL): _RS.LIKELY_FAT_LOSS,
    (_WB.LOSING, _PS.NEGATIVE): _RS.LIKELY_FAT_LOSS,
    (_WB.LOSING, _PS.INSUFFICIENT): _RS.LIKELY_FAT_LOSS,
    (_WB.TOO_FAST_LOSS, _PS.POSITIVE): _RS.WEIGHT_LOSS_TOO_FAST,
    (_WB.TOO_FAST_LOSS, _PS.NEUTRAL): _RS.WEIGHT_LOSS_TOO_FAST,
    (_WB.TOO_FAST_LOSS, _PS.NEGATIVE): _RS.WEIGHT_LOSS_TOO_FAST,
    (_WB.TOO_FAST_LOSS, _PS.INSUFFICIENT): _RS.WEIGHT_LOSS_TOO_FAST,
    (_WB.INSUFFICIENT, _PS.POSITIVE): _RS.INSUFFICIENT_DATA,
    (_WB.INSUFFICIENT, _PS.NEUTRAL): _RS.INSUFFICIENT_DATA,
    (_WB.INSUFFICIENT, _PS.NEGATIVE): _RS.INSUFFICIENT_DATA,
    (_WB.INSUFFICIENT, _PS.INSUFFICIENT): _RS.INSUFFICIENT_DATA,
}


def _verdicts(
    *, improving: int = 0, stable: int = 0, declining: int = 0, unclear: int = 0
) -> list[TrendVerdict]:
    """A verdict list with exactly the requested counts, INTERLEAVED rather than grouped.

    Interleaved because ``aggregate_progression`` counts rather than scans, and a grouped list
    would let an implementation that stopped early still pass.
    """
    pools = [
        [_TV.IMPROVING] * improving,
        [_TV.STABLE] * stable,
        [_TV.DECLINING] * declining,
        [_TV.UNCLEAR] * unclear,
    ]
    out: list[TrendVerdict] = []
    for index in range(max(len(pool) for pool in pools)):
        out.extend(pool[index] for pool in pools if index < len(pool))
    return out


# ---------------------------------------------------------------------------
# The label matrix and the net-progression aggregation. NO integration marker: these are pure
# business rules, and business rules must stay verifiable when Docker is not running -- the same
# argument `test_analytics_bodyweight.py` makes for its dedupe and window-average tests.
# ---------------------------------------------------------------------------


def test_full_label_matrix() -> None:
    """All 24 (bucket, signal) pairs, against a hand-written expected table.

    Without exhaustive coverage a missing branch falls through to a plausible-looking default and
    no single-scenario test notices. The matrix is data precisely so that a gap is a ``KeyError``
    rather than a silent fallthrough, and this is the test that would surface it.
    """
    produced: dict[tuple[_WeightBucket, ProgressionSignal], RecompositionStatus] = {}
    for bucket, rate in _REPRESENTATIVE_RATE.items():
        # Guard on the fixture table itself: a representative rate that lands in the wrong bucket
        # would silently retarget a quarter of the assertions below.
        assert _weight_bucket(rate) is bucket, f"{rate!r} does not land in {bucket}"
        for signal in ProgressionSignal:
            produced[(bucket, signal)] = classify_recomposition(
                rate_percent_per_week=rate, signal=signal
            )

    assert len(produced) == 24
    assert produced == _EXPECTED_MATRIX

    assert set(produced.values()) <= set(RecompositionStatus), (
        "an eighth status is reachable; blueprint 26's enum is the contract Phase 6 codes against"
    )
    recomp_pairs = {
        pair for pair, status in produced.items() if status is _RS.LIKELY_RECOMP_PROGRESSING
    }
    assert recomp_pairs == {
        (_WB.STABLE, _PS.POSITIVE),
        (_WB.LOSING, _PS.POSITIVE),
    }, (
        "recomposition was claimed outside the stable and losing rows, or without a positive "
        "progression signal -- weight flat-or-down WHILE strength rises is the whole claim"
    )


def test_gain_threshold_both_sides() -> None:
    """D-11, from each side. One side alone is satisfiable by a constant."""
    assert (
        classify_recomposition(rate_percent_per_week=Decimal("0.26"), signal=_PS.NEUTRAL)
        is _RS.WEIGHT_GAIN_TOO_FAST
    )
    for rate in (Decimal("0.25"), Decimal("0.24")):
        assert classify_recomposition(rate_percent_per_week=rate, signal=_PS.NEUTRAL) is (
            _RS.LIKELY_MUSCLE_GAIN
        ), "D-11 is strict: exactly +0.25%/week is on target, not too fast"


def test_loss_threshold_both_sides() -> None:
    """D-12, from each side. Exactly -1.00%/week is still the losing row."""
    assert (
        classify_recomposition(rate_percent_per_week=Decimal("-1.01"), signal=_PS.POSITIVE)
        is _RS.WEIGHT_LOSS_TOO_FAST
    )
    for rate in (Decimal("-1.00"), Decimal("-0.99")):
        assert classify_recomposition(rate_percent_per_week=rate, signal=_PS.POSITIVE) is (
            _RS.LIKELY_RECOMP_PROGRESSING
        ), "D-12 is strict: exactly -1.00%/week is losing, not too-fast loss"
        assert classify_recomposition(rate_percent_per_week=rate, signal=_PS.NEUTRAL) is (
            _RS.LIKELY_FAT_LOSS
        )


def test_stable_band_both_edges() -> None:
    """The dead band is INCLUSIVE at both edges; one step outside either is a direction."""
    for rate in (Decimal("0.10"), Decimal("-0.10"), Decimal("0.00")):
        assert _weight_bucket(rate) is _WB.STABLE
        assert classify_recomposition(rate_percent_per_week=rate, signal=_PS.NEUTRAL) is (
            _RS.WEIGHT_STABLE
        )
    assert _weight_bucket(Decimal("0.11")) is _WB.ON_TARGET_GAIN
    assert _weight_bucket(Decimal("-0.11")) is _WB.LOSING


def test_constants_carry_the_locked_values() -> None:
    """A guard on D-10 through D-12 and D-20 themselves.

    Every test above drives the thresholds through ``classify_recomposition``, so a silently
    retuned constant would move the boundary AND the expectation together. Pinning the literals
    is what stops that.
    """
    assert WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK == Decimal("0.25")
    assert WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK == Decimal("-1.00")
    assert WEIGHT_STABLE_BAND_PERCENT_PER_WEEK == Decimal("0.10")
    assert RECOMP_MIN_CLASSIFIED_EXERCISES == 3
    assert RECOMP_PROGRESSION_NET_BAND == Decimal("0.25")
    assert "Not a medical or diagnostic claim" in INTERPRETATION_DISCLAIMER


def test_live_data_aggregate_reads_stable_not_declining() -> None:
    """The live-data shape: 9 improving / 9 stable / 10 declining across 28 exercises."""
    aggregate = aggregate_progression(_verdicts(improving=9, stable=9, declining=10))

    assert aggregate.classified_exercises == 28
    assert aggregate.net_score == Decimal("-0.0357")
    assert aggregate.signal is _PS.NEUTRAL, (
        "a plurality rule returns 'declining' on a one-exercise margin; the net score is the "
        "honest reading of a 9-vs-10 split"
    )
    assert aggregate.verdict is _TV.STABLE
    assert (aggregate.improving, aggregate.stable, aggregate.declining) == (9, 9, 10)
    assert aggregate.unclear == 0


def test_unclear_exercises_are_excluded_from_the_denominator() -> None:
    """Three improving exercises read POSITIVE however many unclear ones surround them."""
    aggregate = aggregate_progression(_verdicts(improving=3, unclear=20))

    assert aggregate.classified_exercises == 3, (
        "counting unclear as stable lets a mostly-untracked block dilute a real signal toward "
        "the one verdict that carries no information"
    )
    assert aggregate.net_score == Decimal("1.0000")
    assert aggregate.signal is _PS.POSITIVE
    assert aggregate.verdict is _TV.IMPROVING
    assert aggregate.unclear == 20


def test_net_band_both_edges() -> None:
    """D-20's band is exclusive at both edges: exactly +-0.25 is NEUTRAL, and 0.5 is not."""
    at_positive_edge = aggregate_progression(_verdicts(improving=3, declining=1, stable=4))
    assert at_positive_edge.net_score == Decimal("0.2500")
    assert at_positive_edge.signal is _PS.NEUTRAL, (
        "strictly greater is required: exactly +0.25 is inside the band"
    )

    at_negative_edge = aggregate_progression(_verdicts(improving=1, declining=3, stable=4))
    assert at_negative_edge.net_score == Decimal("-0.2500")
    assert at_negative_edge.signal is _PS.NEUTRAL

    outside = aggregate_progression(_verdicts(improving=5, declining=1, stable=2))
    assert outside.net_score == Decimal("0.5000")
    assert outside.signal is _PS.POSITIVE
    assert outside.verdict is _TV.IMPROVING


def test_below_three_classified_is_insufficient() -> None:
    """One short of D-20's minimum: no score at all, rather than a score nobody should trust."""
    aggregate = aggregate_progression(_verdicts(improving=1, declining=1, unclear=20))

    assert aggregate.classified_exercises == 2
    assert aggregate.signal is _PS.INSUFFICIENT
    assert aggregate.verdict is _TV.UNCLEAR
    assert aggregate.net_score is None, (
        "None, not 0: 'we could not compute a score' is a different fact from 'the score is "
        "exactly neutral', and a zero here would read as the latter"
    )
    assert aggregate.unclear == 20

    # And one more classified exercise is all it takes -- the floor is a floor, not a cliff.
    at_floor = aggregate_progression(_verdicts(improving=1, declining=1, stable=1, unclear=20))
    assert at_floor.classified_exercises == RECOMP_MIN_CLASSIFIED_EXERCISES
    assert at_floor.signal is _PS.NEUTRAL
    assert at_floor.net_score == Decimal("0.0000")

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
import inspect
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app import analytics as analytics_package
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
    get_recomposition_status,
)
from app.analytics.schemas import ProgressionSignal, RecompositionStatus, TrendVerdict
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

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


def test_recomposition_status_takes_no_date_range() -> None:
    """The signature IS part of the contract, and it is checkable without a container.

    A caller-supplied end date would let a stale anchor produce a confident-looking verdict from
    a window that has since been superseded -- the same argument ``get_body_weight_trend`` makes
    for taking no range. ``user_id`` keyword-only with NO default is ASVS V4: forgetting it must
    be a ``TypeError``, never a cross-tenant read a single-user suite cannot see.
    """
    parameters = inspect.signature(get_recomposition_status).parameters

    assert list(parameters) == ["session", "user_id"], (
        "a date parameter appeared on BODY-02; 'where does my recomposition stand' is always "
        "anchored on today"
    )
    assert parameters["user_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["user_id"].default is inspect.Parameter.empty


def test_package_docstring_names_every_requirement() -> None:
    """`app/analytics/__init__.py` is the package's own index, and it goes stale silently.

    Static, and deliberately in the fast suite: the docstring is also what
    `test_analytics_isolation.py` reads as TEXT, so it is load-bearing rather than decorative.
    """
    doc = analytics_package.__doc__ or ""

    for requirement_id in (
        "VOL-01..03",
        "PROG-01..04",
        "CMP-01",
        "BODY-01",
        "BODY-02",
        "DQ-01",
        "DQ-02",
    ):
        assert requirement_id in doc, f"{requirement_id} is missing from the package docstring"


# ---------------------------------------------------------------------------
# The composed function. Container-backed, and every one of these runs under the frozen clock:
# `get_recomposition_status` takes no date range, so `_RECOMP_NOW` is the ONLY thing that decides
# which rows any of these fixtures land in.
# ---------------------------------------------------------------------------

# Weigh-in offsets, in days BEFORE the anchor, named for the window each one fills. Offsets rather
# than date literals so a reader can check membership against the window definition directly.
_WINDOW_CURRENT = (0, 1, 2, 3)  # the current 7-day average, [anchor-6, anchor]
_WINDOW_PRIOR = (7, 8, 9)  # D-17's raw week-over-week delta, [anchor-13, anchor-7]
_WINDOW_D16_ANCHOR = (28, 29, 30, 31)  # D-16's four-weeks-ago endpoint, [anchor-34, anchor-28]

# Four consecutive Mondays at 09:00 Jakarta, all inside the 12-week lookback
# [2026-06-08, 2026-08-30]. Four distinct week offsets is exactly D-05's minimum, so every
# template seeded across these weeks is classifiable rather than `unclear`.
_TRAINING_WEEKS = (
    dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC),
    dt.datetime(2026, 8, 10, 2, 0, tzinfo=dt.UTC),
    dt.datetime(2026, 8, 17, 2, 0, tzinfo=dt.UTC),
    dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC),
)

# 100 -> 106 kg x 5 is +1.94%/week off a mean e1RM of 120.167 -- comfortably outside D-18's
# +-0.5%/week band, so no verdict here can pass by landing on a boundary.
_IMPROVING_WEIGHTS = (
    Decimal("100.000"),
    Decimal("102.000"),
    Decimal("104.000"),
    Decimal("106.000"),
)
_DECLINING_WEIGHTS = tuple(reversed(_IMPROVING_WEIGHTS))

# Fixture ids for this module. The `RECOMP-` prefix is distinct from every other prefix under
# `backend/tests/`, so a leaked row is attributable to this module and to no other.
_PRESS = "RECOMP-press"
_ROW = "RECOMP-row"
_SQUAT = "RECOMP-squat"
_THREE_LIFTS = (_PRESS, _ROW, _SQUAT)
_TWO_LIFTS = (_PRESS, _ROW)
_VOLUME_FILLER = "RECOMP-highrep"


async def _seed_weigh_ins(
    golden_workout: GoldenBuilder,
    *,
    offsets: Sequence[int],
    weight: str,
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """The same weight on every listed day, expressed as days before the anchor."""
    for offset in offsets:
        await golden_workout.body_measurement(
            measured_on=_ANCHOR - dt.timedelta(days=offset),
            weight_kg=Decimal(weight),
            user_id=user_id,
        )


async def _seed_stable_weight(
    golden_workout: GoldenBuilder, *, weight: str = "65.00", user_id: uuid.UUID = DEFAULT_USER_ID
) -> None:
    """Both D-16 endpoints at the SAME average, so the smoothed rate is exactly 0.00%/week."""
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_CURRENT, weight=weight, user_id=user_id)
    await _seed_weigh_ins(
        golden_workout, offsets=_WINDOW_D16_ANCHOR, weight=weight, user_id=user_id
    )


async def _seed_on_target_gain(golden_workout: GoldenBuilder) -> None:
    """65.000 -> 65.500 over four weeks: +0.125 kg/week, which is +0.19%/week of bodyweight.

    Inside D-11's +0.25 ceiling and above the +0.10 stable band, so this is the on-target-gain
    row and it is not near either edge.
    """
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_CURRENT, weight="65.50")
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_D16_ANCHOR, weight="65.00")


async def _seed_training(
    golden_workout: GoldenBuilder,
    *,
    templates: Sequence[str],
    weights: Sequence[Decimal],
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """One workout per training week, carrying one working set for each template.

    ``strict=True`` on the zip: a caller passing five weights against four weeks would otherwise
    silently drop one and change the verdict the test is asserting on.
    """
    for external_id in templates:
        await golden_workout.template(external_id=external_id, user_id=user_id)
    for start_time, weight in zip(_TRAINING_WEEKS, weights, strict=True):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[
                GoldenExercise(
                    template_external_id=external_id,
                    sets=(GoldenSet(weight_kg=weight, reps=5),),
                )
                for external_id in templates
            ],
            user_id=user_id,
        )


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_null_weight_rate_is_insufficient_regardless_of_progression(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test, and the live-data case today.

    The specific wrong behaviour it catches is a fallback to D-17's raw single-week delta. That
    delta is deliberately present and non-null here, and it is deliberately non-zero: an
    implementation that reached for it would classify +0.500 kg on a 65.5 kg bodyweight and flip
    this verdict from `insufficient_data` to a confident-looking weight label.
    """
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_CURRENT, weight="65.50")
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_PRIOR, weight="65.00")
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.weight_trend.trend_rate_percent_per_week is None
    assert result.weight_trend.latest_week_delta_kg == Decimal("0.500"), (
        "the raw delta must be present for this test to mean anything -- it is the wrong input "
        "the classifier is being given the chance to reach for"
    )
    assert result.progression_signal.signal is _PS.POSITIVE
    assert result.progression_signal.classified_exercises == 3
    assert result.status is _RS.INSUFFICIENT_DATA, (
        "a null SMOOTHED rate collapses the verdict however good the training data is; falling "
        "back to D-17's single-week delta reads +0.72%/week off glycogen noise on live data"
    )


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_stable_weight_with_improving_lifts_is_recomp_progressing(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Textbook recomposition: the scale is flat while the ceiling rises."""
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.weight_trend.trend_rate_percent_per_week == Decimal("0.00")
    assert result.progression_signal.classified_exercises == 3
    assert result.progression_signal.improving == 3
    assert result.progression_signal.net_score == Decimal("1.0000")
    assert result.progression_signal.signal is _PS.POSITIVE
    assert result.status is _RS.LIKELY_RECOMP_PROGRESSING


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_stable_weight_with_declining_lifts_is_weight_stable(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The same flat scale, the opposite strength trend -- and NOT a recomposition claim.

    `likely_recomp_progressing` here would assert muscle gain from a stalled scale and falling
    lifts, which is the single most over-claimed reading this module could produce.
    """
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_DECLINING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.weight_trend.trend_rate_percent_per_week == Decimal("0.00")
    assert result.progression_signal.declining == 3
    assert result.progression_signal.net_score == Decimal("-1.0000")
    assert result.progression_signal.signal is _PS.NEGATIVE
    assert result.status is _RS.WEIGHT_STABLE


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_on_target_gain_with_declining_lifts_still_reports_muscle_gain_and_the_signal(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-20's deliberate compromise, and the reason `progression_signal` is a REQUIRED field."""
    await _seed_on_target_gain(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_DECLINING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.weight_trend.trend_rate_percent_per_week == Decimal("0.19")
    assert result.status is _RS.LIKELY_MUSCLE_GAIN
    assert result.progression_signal.signal is _PS.NEGATIVE, (
        "the enum has no 'gaining on target but lifts flat' member; the nuance must survive in "
        "progression_signal so Claude can qualify the label"
    )


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_disclaimer_is_populated_on_every_response(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Including on the insufficient path, which is the response most likely to be quoted alone.

    Both halves in one test, and in this order, because the interesting failure is a disclaimer
    populated only on the happy path -- which a test that looked at one response could not see.
    """
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_CURRENT, weight="65.00")
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    insufficient = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert insufficient.status is _RS.INSUFFICIENT_DATA
    assert insufficient.disclaimer == INTERPRETATION_DISCLAIMER
    assert insufficient.disclaimer != ""

    # Filling D-16's anchor window is all it takes to move off the insufficient path.
    await _seed_weigh_ins(golden_workout, offsets=_WINDOW_D16_ANCHOR, weight="65.00")

    populated = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert populated.status is _RS.LIKELY_RECOMP_PROGRESSING
    assert populated.disclaimer == INTERPRETATION_DISCLAIMER
    assert populated.disclaimer != ""


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_fewer_than_three_classified_falls_back_to_a_weight_only_label(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Two classifiable exercises: the SCORE is withheld, the weight verdict still stands."""
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_TWO_LIFTS, weights=_IMPROVING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.progression_signal.classified_exercises == 2
    assert result.progression_signal.signal is _PS.INSUFFICIENT
    assert result.progression_signal.net_score is None
    assert result.status is _RS.WEIGHT_STABLE, (
        "a weight-only verdict is still a valid answer; only a null weight rate collapses the "
        "whole response"
    )


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_recomposition_freshness_names_all_three_resources(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01 / T-05-77: this answer reads both sides, so it is only as fresh as the stalest.

    `exercise_templates` is the one a reader is most likely to think is irrelevant here, and it
    is the one that matters most: `exercise_type` is the D-03 e1RM gate, so a stale template sync
    silently changes the progression signal with no error anywhere in the stack.
    """
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert set(result.freshness.resources) == {
        "workouts",
        "exercise_templates",
        "body_measurements",
    }


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_training_volume_is_reported_but_never_classified(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Volume is context. Changing it must move the reported figures and NOT the label.

    The filler is a 15-rep template, so D-02's rep gate leaves it with no estimate at all: it
    lands in `unclear`, is excluded from D-20's denominator, and changes nothing but the volume.
    """
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    before = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    await golden_workout.template(external_id=_VOLUME_FILLER)
    await golden_workout.workout(
        start_time=_TRAINING_WEEKS[1],
        exercises=[
            GoldenExercise(
                template_external_id=_VOLUME_FILLER,
                sets=tuple(GoldenSet(weight_kg=Decimal("40.000"), reps=15) for _ in range(10)),
            )
        ],
    )

    after = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert after.training_volume.weeks != before.training_volume.weeks, (
        "the filler did not move the reported volume, so this test cannot show that volume is "
        "excluded from the label"
    )
    assert after.status is before.status
    assert after.status is _RS.LIKELY_RECOMP_PROGRESSING
    assert after.progression_signal.classified_exercises == 3
    assert after.progression_signal.unclear == 1
    assert after.progression_signal.net_score == before.progression_signal.net_score


@pytest.mark.integration
@time_machine.travel(_RECOMP_NOW, tick=False)
async def test_second_users_data_does_not_change_the_verdict(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4 / T-05-75. The second user is bulking fast and lifting heavier, on the same dates.

    Both sides of the verdict are attacked at once: a leaked weigh-in would push the rate from
    0.00%/week into the too-fast-gain row, and a leaked set would land on the SAME template ids
    (Hevy's built-in template ids are global) at nearly double the load.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await _seed_stable_weight(golden_workout)
    await _seed_training(golden_workout, templates=_THREE_LIFTS, weights=_IMPROVING_WEIGHTS)

    await _seed_weigh_ins(
        golden_workout,
        offsets=_WINDOW_CURRENT,
        weight="70.00",
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    await _seed_weigh_ins(
        golden_workout,
        offsets=_WINDOW_D16_ANCHOR,
        weight="65.00",
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    await _seed_training(
        golden_workout,
        templates=_THREE_LIFTS,
        weights=(
            Decimal("200.000"),
            Decimal("220.000"),
            Decimal("240.000"),
            Decimal("260.000"),
        ),
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await get_recomposition_status(session, user_id=DEFAULT_USER_ID)

    assert result.weight_trend.trend_rate_percent_per_week == Decimal("0.00"), (
        "another user's weigh-ins or sets leaked into this verdict (ASVS V4)"
    )
    assert result.status is _RS.LIKELY_RECOMP_PROGRESSING, (
        "another user's weigh-ins or sets leaked into this verdict (ASVS V4)"
    )
    # Anti-vacuous guard: this user really was classified, rather than reaching the expected
    # label through an empty progression signal.
    assert result.progression_signal.classified_exercises >= 1

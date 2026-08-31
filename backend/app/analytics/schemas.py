"""Public return types for every analytics metric
(VOL-01..03, PROG-01..04, CMP-01, BODY-01, BODY-02, DQ-01, DQ-02).

Declared here once and imported by every other Phase 4 module. These are the contract Phase 6
codes against; renaming a field after the fact costs a rewrite of every expected value in every
analytics test.

Pydantic rather than a frozen dataclass, and not for the validation: MCP SDK v2 auto-generates a
tool's ``outputSchema`` and populates ``structured_content`` from a returned ``BaseModel``
(``app/mcp/tools/ping.py:24-28``). Phase 6 gets its wire contract for free, from types that know
nothing about MCP.

``Decimal``, never ``float``, for every summed magnitude. Binary floating point makes two
arithmetically identical weekly totals compare unequal, which turns a deterministic analytics
test flaky and a "did my tonnage change this week?" answer into a coin flip.

``tonnage_kg is None`` is a DIFFERENT FACT from ``Decimal("0.000")``. ``None`` means "this
week's modalities cannot produce weight x reps"; zero means "computed, and it is zero" -- a real
bodyweight week. SQL ``SUM`` silently skips NULL products, and 543 of 7,719 non-warmup live sets
have one, so the shortfall never shows up in the total itself. ``tonnage_sets`` is what makes it
visible: it counts the sets the tonnage figure was actually computed over.

Per-muscle set counts legitimately EXCEED the week's hard-set total. One live template maps to
up to 9 muscle groups, so a single set lands in 9 muscle buckets. Never sum ``direct_sets``
across muscle groups and never present a cross-muscle total -- it is several times the truth and
it looks plausible.
"""

import datetime as dt
import uuid
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.analytics.estimates import NoEstimateReason
from app.normalization.muscles import CanonicalMuscleGroup


class _AnalyticsModel(BaseModel):
    """Shared config for every analytics return type.

    ``hide_input_in_errors`` for the same reason ``hevy/schemas.py`` sets it: a ValidationError
    would otherwise render ``input_value=...`` -- weekly tonnage, workout counts, body-composition
    adjacent numbers -- into a message that could reach a log line (FOUND-05).

    Extra fields are FORBIDDEN here, not ignored -- the opposite of the wire models: these are
    internal domain types, not a mirror of somebody else's format. An unexpected field here is a
    bug in this repo, and it should fail loudly rather than be dropped. ``frozen=True`` because
    this is a read path -- a result object that a caller can mutate is a result object two
    callers will disagree about.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)


class FreshnessMetadata(_AnalyticsModel):
    """DQ-01. Per-resource ``last_synced_at``, keyed by the ``RESOURCE_*`` constants.

    A per-resource breakdown, not one collapsed timestamp: ``get_muscle_group_volume`` depends
    on BOTH ``workouts`` and ``exercise_templates``, and a stale template sync silently changes
    every per-muscle number. The two do drift -- 25 minutes apart on the live database. A single
    "oldest of the relevant resources" scalar is a lossy projection Phase 6 can derive in one
    line; the reverse is impossible.

    Carries ``last_synced_at`` ONLY. Never ``sync_state.last_error``, ``status``, ``cursor_page``
    or ``cursor_timestamp`` -- MCP-06 and CLAUDE.md forbid internal tokens or error text in
    anything Claude can read, and ``format_sync_error`` exists precisely to bound that leak.
    """

    resources: dict[str, dt.datetime | None]


class CoverageMetadata(_AnalyticsModel):
    """DQ-02. Exactly D-06's three fields -- do not add a fourth.

    ``earliest_data_at`` is what lets Claude tell "you did not train in this window" apart from
    "your synced history does not reach back that far". Echoing the requested date range back
    here was explicitly considered and NOT selected; do not add it.
    """

    sessions_in_window: int
    insufficient_data: bool
    earliest_data_at: dt.datetime | None


class WeeklyVolumeWeek(_AnalyticsModel):
    """One whole local Monday-start week of VOL-01 totals. Warm-up sets excluded from all of it."""

    week_start: dt.date
    sessions: int
    hard_sets: int
    total_reps: int | None
    tonnage_sets: int
    tonnage_kg: Decimal | None


class WeeklyVolumeResult(_AnalyticsModel):
    """VOL-01. ``weeks`` is ascending and GAP-FREE: a week with no training is a zero row."""

    weeks: list[WeeklyVolumeWeek]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class MuscleGroupVolume(_AnalyticsModel):
    """VOL-02 / D-04 for ONE muscle group in ONE week.

    ``direct_sets`` and ``indirect_sets`` count sets REACHING this muscle. One template maps to
    up to 9 muscle groups, so summing these across the week's muscle groups legitimately exceeds
    the week's ``hard_sets``. That is the grain, not a bug -- never present a cross-muscle total.

    ``sessions`` and ``insufficient_data`` are U-03: they are per-muscle and additive to, not a
    replacement for, the response-level ``CoverageMetadata``. They exist so "plenty of chest data
    but only one rear-delt session" is expressible.
    """

    muscle_group: CanonicalMuscleGroup
    direct_sets: int
    indirect_sets: int
    weighted_sets: Decimal
    sessions: int
    insufficient_data: bool


class MuscleGroupVolumeWeek(_AnalyticsModel):
    """One whole local week. ``muscle_groups`` is sorted by ``muscle_group.value``, ascending."""

    week_start: dt.date
    sessions: int
    muscle_groups: list[MuscleGroupVolume]


class MuscleGroupVolumeResult(_AnalyticsModel):
    """VOL-02. ``weeks`` is ascending and gap-free, same spine as ``WeeklyVolumeResult``."""

    weeks: list[MuscleGroupVolumeWeek]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class MuscleGroupFrequency(_AnalyticsModel):
    """VOL-03 per muscle group. ``sessions`` is DISTINCT workouts, never a sum of exercises."""

    muscle_group: CanonicalMuscleGroup
    sessions: int
    sessions_per_week: Decimal
    insufficient_data: bool


class ExerciseFrequency(_AnalyticsModel):
    """VOL-03 per exercise. ``title`` is None when the template is not synced locally."""

    exercise_template_external_id: str
    title: str | None
    sessions: int
    sessions_per_week: Decimal
    insufficient_data: bool


class TrainingFrequencyResult(_AnalyticsModel):
    """VOL-03 over the RAW requested range (D-03) -- deliberately not week-snapped.

    ``muscle_groups`` is sorted by ``muscle_group.value``; ``exercises`` by
    ``exercise_template_external_id``. Never dict-iteration order: a flaky ordering is a flaky
    test, and Phase 6 will diff these between runs.
    """

    sessions_per_week: Decimal
    muscle_groups: list[MuscleGroupFrequency]
    exercises: list[ExerciseFrequency]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class TrendVerdict(StrEnum):
    """PROG-02 / blueprint 20. ``UNCLEAR`` is a first-class answer, not an error.

    D-05: fewer than four distinct training weeks for an exercise means ``UNCLEAR``, never a
    guess -- "do not classify progression based on a single workout", scaled to a number.
    """

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    UNCLEAR = "unclear"


class PlateauConfidence(StrEnum):
    """PROG-03 / D-07b. Derived from the qualifying-session count, never invented per call."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProgressionSignal(StrEnum):
    """BODY-02 / D-20. The net-progression score's own classification.

    Reported ALONGSIDE the recomposition status so Claude can qualify a label rather than have
    the seven-value enum silently hide a disagreement between the weight trend and the strength
    trend. ``INSUFFICIENT`` means fewer than three exercises were classifiable at all.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    INSUFFICIENT = "insufficient"


class RecompositionStatus(StrEnum):
    """BODY-02 / blueprint 26. Exactly seven values -- an eighth would change the contract.

    Decision support, never a diagnosis. ``RecompositionResult.disclaimer`` carries that framing
    as a required FIELD rather than as documentation, so a Phase 6 serialization change cannot
    drop it.
    """

    LIKELY_RECOMP_PROGRESSING = "likely_recomp_progressing"
    LIKELY_MUSCLE_GAIN = "likely_muscle_gain"
    LIKELY_FAT_LOSS = "likely_fat_loss"
    WEIGHT_STABLE = "weight_stable"
    WEIGHT_GAIN_TOO_FAST = "weight_gain_too_fast"
    WEIGHT_LOSS_TOO_FAST = "weight_loss_too_fast"
    INSUFFICIENT_DATA = "insufficient_data"


class PersonalRecordType(StrEnum):
    """PROG-04's five record types. ``value`` units differ per type -- see ``PersonalRecord``.

    Four members, not five: the fifth -- "max reps at a given weight" -- is a LIST keyed by
    weight, not a single scalar record, so it has its own model (``RepsAtWeightRecord``) rather
    than a member here.
    """

    MAX_WEIGHT = "max_weight"
    MAX_REPS = "max_reps"
    ESTIMATED_1RM = "estimated_1rm"
    SESSION_VOLUME = "session_volume"


class MeasurementCoverage(_AnalyticsModel):
    """DQ-02 for day-grained weigh-ins. A SIBLING of ``CoverageMetadata``, never a subclass.

    ``CoverageMetadata.sessions_in_window`` counts WORKOUTS. Overloading it with a weigh-in count
    would make ``insufficient_data`` mean two different things inside one response -- and BODY-02
    carries both, because it reads training data and body-weight data.

    ``window_days`` is echoed back because D-15 gives each window its OWN floor (7-day needs 3
    measured days, 14-day needs 5, 30-day needs 10), so the flag is not interpretable without
    knowing which window produced it. Same additive relationship as ``MuscleGroupVolume``'s
    per-muscle flag sitting alongside the response-level one, not replacing it.

    ``earliest_measurement_at`` is a ``dt.date``, not a ``dt.datetime``: ``measured_on`` is a
    calendar date, and ``db/models/body.py``'s module docstring is explicit that inventing a
    time of day for a weigh-in would be wrong.
    """

    window_days: int
    measured_days_in_window: int
    insufficient_data: bool
    earliest_measurement_at: dt.date | None


class ProgressionPoint(_AnalyticsModel):
    """PROG-01: one local day of one exercise.

    ``estimated_1rm_kg`` and ``no_estimate_reason`` are MUTUALLY EXCLUSIVE and exactly one is
    populated. A number with no reason is a trusted estimate; a reason with no number says why
    there is none -- PROG-01 requires the reason and forbids a bare null.

    ``sets``, ``total_reps`` and ``volume_kg`` describe the WHOLE day for this exercise;
    ``best_weight_kg``, ``best_reps`` and ``estimated_1rm_kg`` describe only the D-04 selected
    set. Do not conflate them: "you did four sets" and "your best set was 100 kg x 5" are
    different facts.

    ``volume_kg is None`` is a DIFFERENT FACT from ``Decimal("0.000")``, exactly as
    ``tonnage_kg`` is: ``None`` means no set that day had both a weight and reps.
    ``volume_sets`` counts the population the figure was computed over.
    """

    local_day: dt.date
    workout_id: uuid.UUID
    sets: int
    total_reps: int | None
    volume_kg: Decimal | None
    volume_sets: int
    best_weight_kg: Decimal | None
    best_reps: int | None
    estimated_1rm_kg: Decimal | None
    no_estimate_reason: NoEstimateReason | None


class ExerciseProgressionResult(_AnalyticsModel):
    """PROG-01. ``points`` is ascending by ``local_day``.

    Days with no training are ABSENT, not zero rows -- deliberately unlike ``WeeklyVolumeResult``'s
    gap-free week spine. "You did not do this exercise on Tuesday" is not a diagnostically
    interesting zero; it is every non-training day, and a spine would bury the signal in them.
    """

    exercise_template_external_id: str
    title: str | None
    exercise_type: str | None
    window_start: dt.date
    window_end: dt.date
    points: list[ProgressionPoint]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class ExerciseTrend(_AnalyticsModel):
    """PROG-02 for one exercise. Carries the WINDOW and the RATE, not just the label.

    PROG-02 and PROG-03 answer different questions over different windows and will legitimately
    disagree on real data -- Overhead Press is ``improving`` at +1.51%/week over 11 weeks AND
    plateaued over its last 4 sessions. Both are true. Neither result is interpretable without
    the window that produced it, which is why the window is a field and not a docstring note.

    ``rate_percent_per_week`` is ``None`` exactly when ``verdict`` is ``UNCLEAR``.
    """

    exercise_template_external_id: str
    title: str | None
    verdict: TrendVerdict
    rate_percent_per_week: Decimal | None
    weeks_with_data: int


class ExerciseTrendsResult(_AnalyticsModel):
    """PROG-02. ``exercises`` is sorted by ``exercise_template_external_id``, ascending.

    Never dict-iteration order: a flaky ordering is a flaky test, and Phase 6 will diff these
    between runs.
    """

    window_start: dt.date
    window_end: dt.date
    exercises: list[ExerciseTrend]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class PlateauResult(_AnalyticsModel):
    """PROG-03 / D-07b for one exercise. Blueprint 21's shape, plus the window and threshold.

    Never a bare boolean. ``recent_performance_kg`` beside ``historical_best_kg`` is the pair
    that separates a plateau from a DETRAINED exercise: on live data Leg Extension's recent
    performance is 68.2% of its all-time best, which is not "stuck at your ceiling", it is
    "training well below a ceiling set in a different block". A boolean cannot express that and
    Claude would narrate it as a stall.

    ``threshold_percent`` is ``PLATEAU_IMPROVEMENT_TOLERANCE * 100``; ``min_sessions`` and
    ``min_elapsed_days`` are D-06's two floors; ``lookback_start`` / ``lookback_end`` echo D-19's
    bounded window back. PROG-03's requirement text demands the window and threshold be returned
    ALONGSIDE the result, so all six are fields.
    """

    exercise_template_external_id: str
    title: str | None
    plateaued: bool
    plateau_duration_days: int | None
    qualifying_sessions_in_streak: int
    recent_performance_kg: Decimal | None
    historical_best_kg: Decimal | None
    confidence: PlateauConfidence
    threshold_percent: Decimal
    min_sessions: int
    min_elapsed_days: int
    lookback_start: dt.date
    lookback_end: dt.date


class PlateauReport(_AnalyticsModel):
    """PROG-03. ``exercises`` is sorted by ``exercise_template_external_id``, ascending."""

    lookback_weeks: int
    lookback_start: dt.date
    lookback_end: dt.date
    exercises: list[PlateauResult]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class PersonalRecord(_AnalyticsModel):
    """PROG-04: one record. The unit of ``value`` depends on ``record_type``.

    ``MAX_WEIGHT`` -> kilograms; ``MAX_REPS`` -> a rep count as a Decimal; ``ESTIMATED_1RM`` ->
    kilograms; ``SESSION_VOLUME`` -> kilograms summed over one exercise-session.

    D-09: on a tie, ``achieved_on`` is the EARLIEST date the value was first reached -- "when did
    I first hit this", not "when did I most recently reconfirm it".

    ``weight_kg`` and ``reps`` describe the set the record came from, so a rep PR is readable as
    "22 reps at 40 kg" rather than a bare number. ``volume_sets`` is populated only for
    ``SESSION_VOLUME`` and counts the sets the sum was computed over -- a partial computation
    must be visible, exactly as ``tonnage_sets`` makes it visible for VOL-01.
    """

    record_type: PersonalRecordType
    value: Decimal
    achieved_on: dt.date
    weight_kg: Decimal | None
    reps: int | None
    volume_sets: int | None


class RepsAtWeightRecord(_AnalyticsModel):
    """PROG-04's "max reps at a weight", one row per distinct weight lifted.

    Bounded by the data, not by a cap: the live account has at most 12 distinct weights per
    exercise (mean 5.0), so the whole list is safe to return and MCP-03's "no unbounded result
    sets" is satisfied by the shape rather than by truncation.
    """

    weight_kg: Decimal
    reps: int
    achieved_on: dt.date


class PersonalRecordsResult(_AnalyticsModel):
    """PROG-04. ``records`` is sorted by ``record_type.value``; ``reps_at_weight`` DESCENDING by
    ``weight_kg``.

    A record type with no eligible set is ABSENT from ``records`` rather than present with a
    zero -- an exercise never loaded has no max-weight record, and a zero would read as one.
    """

    exercise_template_external_id: str
    title: str | None
    window_start: dt.date
    window_end: dt.date
    records: list[PersonalRecord]
    reps_at_weight: list[RepsAtWeightRecord]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class ComparisonRate(_AnalyticsModel):
    """CMP-01: a COUNT or a SUM, normalized per week. Never a maximum, a rate or an average.

    Per-week normalization is what makes a 28-day period comparable to a 14-day one, and it is
    only valid for counts and sums. Dividing a maximum by the number of weeks produces a MORE
    misleading delta, not a less misleading one -- an e1RM quartered by a four-week window is
    a quarter of the number the progression endpoint reports for the same exercise. Levels go in
    ``ComparisonLevel``; the two types exist separately so a future metric cannot be added to the
    wrong bucket by review alone.

    ``delta_percent`` is ``None`` when the period-A baseline is zero -- a real case (an exercise
    trained in B and not in A). Not an exception, not infinity, not a silent zero.
    """

    metric: str
    exercise_template_external_id: str | None
    title: str | None
    period_a_per_week: Decimal | None
    period_b_per_week: Decimal | None
    delta_per_week: Decimal | None
    delta_percent: Decimal | None


class ComparisonLevel(_AnalyticsModel):
    """CMP-01: a LEVEL (a maximum), compared as-is and NEVER divided by weeks. See
    ``ComparisonRate``'s docstring for why the separation is structural."""

    metric: str
    exercise_template_external_id: str | None
    title: str | None
    period_a_value: Decimal | None
    period_b_value: Decimal | None
    delta: Decimal | None
    delta_percent: Decimal | None


class MuscleGroupComparison(_AnalyticsModel):
    """CMP-01 per muscle group. All three figures are per-week-normalized set COUNTS.

    Never present a cross-muscle total: one template maps to up to 9 muscle groups, so summing
    these across groups is several times the truth and it looks plausible.
    """

    muscle_group: CanonicalMuscleGroup
    direct_sets: ComparisonRate
    indirect_sets: ComparisonRate
    weighted_sets: ComparisonRate


class PeriodSummary(_AnalyticsModel):
    """CMP-01: one period's identity and its OWN coverage.

    Coverage is per period, not per response. A comparison where period A holds one session is
    not a comparison, and a single response-level block cannot express that.
    """

    start_day: dt.date
    end_day: dt.date
    days: int
    coverage: CoverageMetadata


class PeriodComparisonResult(_AnalyticsModel):
    """CMP-01. ``totals`` sorted by ``metric``; ``exercises`` and ``exercise_levels`` sorted by
    ``exercise_template_external_id``; ``muscle_groups`` by ``muscle_group.value``.

    ``muscle_groups`` is an EMPTY LIST unless the caller passed ``include_muscle_groups=True``.
    16 muscle groups x 3 figures x 2 periods plus deltas is 96+ numbers, and MCP-03 wants
    compact JSON -- so the expansion is opt-in rather than always-on.

    Neither period is week-snapped: a 4-week period against a 23-day period must both be
    expressed per week, not both widened to whole weeks.
    """

    period_a: PeriodSummary
    period_b: PeriodSummary
    totals: list[ComparisonRate]
    exercises: list[ComparisonRate]
    exercise_levels: list[ComparisonLevel]
    muscle_groups: list[MuscleGroupComparison]
    freshness: FreshnessMetadata


class BodyWeightTrendResult(_AnalyticsModel):
    """BODY-01. Each window carries its OWN coverage (D-15) -- the floors are independent.

    A 30-day average can be trustworthy while the 7-day one is not, and vice versa. That is the
    same additive relationship ``MuscleGroupVolume``'s per-muscle flag has with the response-level
    one: additive to it, never a replacement for it.

    ``trend_rate_percent_per_week`` is the D-16 SMOOTHED four-week rate
    ``(current_7d_avg - 7d_avg_from_4_weeks_ago) / 4``, expressed as a percentage of
    ``average_7d_kg``. It is ``None`` when EITHER of those two windows fails its own floor.
    This is the only figure BODY-02 classifies against.

    ``latest_week_delta_kg`` is D-17: the raw single-week delta, surfaced for context and
    NEVER classified against. On live data it reads +0.475 kg for a week, which on 65.65 kg is
    +0.72%/week -- nearly 3x the lean-bulk threshold, entirely from glycogen and water noise.
    That is precisely why it is not the classifier.

    ``anchor_day`` is the user's LOCAL calendar day, never the server's UTC date.
    """

    anchor_day: dt.date
    average_7d_kg: Decimal | None
    average_14d_kg: Decimal | None
    average_30d_kg: Decimal | None
    coverage_7d: MeasurementCoverage
    coverage_14d: MeasurementCoverage
    coverage_30d: MeasurementCoverage
    trend_anchor_coverage: MeasurementCoverage
    trend_rate_kg_per_week: Decimal | None
    trend_rate_percent_per_week: Decimal | None
    latest_week_delta_kg: Decimal | None
    freshness: FreshnessMetadata


class AggregateProgression(_AnalyticsModel):
    """BODY-02 / D-20: the net-progression score over exercises PROG-02 could classify.

    ``net_score`` is ``(improving - declining) / classified_exercises``. ``unclear`` exercises are
    EXCLUDED from the denominator, not counted as stable -- counting them as stable would let a
    mostly-untracked block dilute a real signal toward the one verdict carrying no information.

    A plurality rule was rejected: on live data 9 improving / 9 stable / 10 declining over 28
    exercises returns ``declining`` on a one-exercise margin under plurality, and ``stable`` under
    the net score. The net score is the honest reading of a 9-vs-10 split.

    Below three classified exercises the score is not trusted: ``signal`` is ``INSUFFICIENT``,
    ``verdict`` is ``UNCLEAR`` and ``net_score`` is ``None``.
    """

    verdict: TrendVerdict
    signal: ProgressionSignal
    net_score: Decimal | None
    classified_exercises: int
    improving: int
    stable: int
    declining: int
    unclear: int


class RecompositionResult(_AnalyticsModel):
    """BODY-02. ``disclaimer`` is a REQUIRED FIELD, not documentation.

    Encoding the decision-support framing as a field is what stops a Phase 6 serialization change
    from dropping it. It is a fixed constant safety label, NOT backend-generated coaching prose --
    the exclusion in REQUIREMENTS.md targets generated insight, not a static disclaimer, and this
    distinction is recorded here so a future reviewer does not delete it.

    ``progression_signal`` is required and ALWAYS populated (D-20), so Claude reading
    ``likely_muscle_gain`` alongside a ``negative`` signal can say "you are gaining at a lean-bulk
    rate but your lifts are going backwards" instead of taking the label at face value.

    ``training_volume`` is reported for context only. BODY-02 classifies on the weight trend and
    the progression signal; volume is never an input to the label.
    """

    status: RecompositionStatus
    disclaimer: str
    weight_trend: BodyWeightTrendResult
    progression_signal: AggregateProgression
    training_volume: WeeklyVolumeResult
    freshness: FreshnessMetadata

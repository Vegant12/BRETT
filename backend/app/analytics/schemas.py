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
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from app.analytics.estimates import NoEstimateReason
from app.db.models.physique import PhysiqueRatingLevel
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


class TrainingProgram(StrEnum):
    """GOAL-01/GOAL-02: the user's active training program, as data rather than a constant.

    Each member's VALUE is the EXACT string stored in ``user_program_history.program`` and
    in ``program_switch_tokens.to_program``, so there is no second name->value mapping for a
    future rename to leave behind -- the same discipline ``BodyMeasurementMetric`` applies to
    column names.

    A ``StrEnum`` and not a free string: the MCP SDK derives the write tool's ``inputSchema``
    from this annotation, so "Lean Bulk", "cutting" or a hallucinated fourth program is
    rejected at the schema layer before any code in this repo runs. Three members and no
    fourth -- ``recomposition.py`` carries one fully explicit threshold table and one label
    matrix PER member (D-04), so a fourth would be a missing table, not a missing branch.
    """

    LEAN_BULK = "lean_bulk"
    CUT = "cut"
    RECOMP = "recomp"


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

    ``last_max_weight_kg`` is the most recent IN-WINDOW training day's best set weight (D-07:
    ``series[-1].best_weight_kg`` after the existing ascending-by-local_day sort) -- the
    literal last weight lifted, not necessarily the last plateau-streak-QUALIFYING session; a
    deload or high-rep week can break streak membership while still being real, recent
    training. ``None`` means the most recent day's selected set had no weight recorded (a
    bodyweight or duration-only exercise), never a literal ``Decimal("0")`` standing in for a
    real observation. It plays NO role in computing ``plateaued``, ``threshold_percent``, or
    any other field on this model -- estimated-1RM alone continues to classify. Distinct from
    ``PersonalRecordType.MAX_WEIGHT`` (``fitness_get_personal_records``), which answers "what
    is the heaviest you have EVER lifted"; this field answers "what did you lift MOST RECENTLY".
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
    last_max_weight_kg: Decimal | None


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


class RecentRecord(_AnalyticsModel):
    """One personal record that was SET inside a window, with the exercise that set it.

    Deliberately NOT ``PersonalRecordsResult`` narrowed. That model answers "what are this
    exercise's best-ever numbers", is scoped to ONE exercise by a mandatory
    ``exercise_template_external_id``, and its ``records`` are the best values found INSIDE the
    window whether or not they beat anything. This model answers a different question -- "what
    got beaten this week, across everything I trained" -- and a value that merely led its own
    window is not a record. Reporting one as the other is the plausible-looking-but-quietly-wrong
    failure this project treats as its primary risk.

    ``previous_value`` is the incumbent this record beat, computed from all history strictly
    BEFORE ``window_start``. ``None`` means there was no incumbent -- the first time this
    exercise produced an eligible set of this type -- which is a real and different fact from
    "beat a small number", and collapsing the two would let a first-ever log read as a
    breakthrough.
    """

    exercise_template_external_id: str
    title: str | None
    record: PersonalRecord
    previous_value: Decimal | None


class RecentRecordsResult(_AnalyticsModel):
    """PROG-04 asked cross-exercise, for D-02's report "PR highlights".

    ``records`` is sorted ``achieved_on`` DESCENDING, then ``record.record_type.value``, then
    ``exercise_template_external_id`` -- newest first, because the consumer TRUNCATES this list
    to a small cap and the most recent record is the one a weekly report is about. The two
    secondary keys exist so the truncation point is deterministic rather than planner-dependent,
    which is the same reason ``get_recent_periods`` spells out its full ordering.

    ``window_start``/``window_end`` are echoed as FIELDS for ``PlateauResult``'s reason: a
    figure whose window the reader cannot see is a figure the reader has to trust blindly. They
    matter more here than usual, because the report that embeds this carries a
    ``get_recomposition_status`` verdict anchored on a DIFFERENT window (D-01).
    """

    window_start: dt.date
    window_end: dt.date
    records: list[RecentRecord]
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


class BodyMeasurementMetric(StrEnum):
    """BODY-05's closed metric selector: the 16 non-weight ``body_measurements`` columns.

    Each member's VALUE is the EXACT column name on ``db/models/body.py::BodyMeasurement``, and
    that is load-bearing rather than cosmetic: the analytics layer resolves the SQLAlchemy
    attribute with ``getattr(BodyMeasurement, metric.value)``, so there is no second name->column
    mapping for a future column rename to leave behind. ``test_analytics_body_measurements.py``
    asserts the two sets are equal, which is what keeps that true.

    ``weight_kg`` is deliberately ABSENT. BODY-01's ``fitness_get_body_weight_trend`` already
    owns weight with a rolling-average shape this two-point comparison does not share; a member
    here would give the same question two different answers depending on which tool was called.

    A ``StrEnum`` and not a free string (D-09): the MCP SDK derives the tool's ``inputSchema``
    from this annotation, so an unrecognized metric name is rejected at the schema layer before
    any code in this repo runs. A hand-written ``if metric not in {...}`` branch would be a
    second copy of the same list.
    """

    NECK_CM = "neck_cm"
    SHOULDER_CM = "shoulder_cm"
    CHEST_CM = "chest_cm"
    LEFT_BICEP_CM = "left_bicep_cm"
    RIGHT_BICEP_CM = "right_bicep_cm"
    LEFT_FOREARM_CM = "left_forearm_cm"
    RIGHT_FOREARM_CM = "right_forearm_cm"
    ABDOMEN_CM = "abdomen_cm"
    WAIST_CM = "waist_cm"
    HIPS_CM = "hips_cm"
    LEFT_THIGH_CM = "left_thigh_cm"
    RIGHT_THIGH_CM = "right_thigh_cm"
    LEFT_CALF_CM = "left_calf_cm"
    RIGHT_CALF_CM = "right_calf_cm"
    FAT_PERCENT = "fat_percent"
    LEAN_MASS_KG = "lean_mass_kg"


class BodyMeasurementTrendResult(_AnalyticsModel):
    """BODY-05: the latest reading against the earliest reading inside a fixed 90-day window.

    **Deliberately NOT ``BodyWeightTrendResult``'s shape (D-05).** A rolling average across the
    7-day, 14-day and 30-day windows with 3, 5 and 10 measured-day floors is the right design for
    a metric recorded daily; it is the wrong design for a tape measure. On live production data,
    13 of these 16 columns have never been recorded once, and the best-covered one (``waist_cm``)
    holds 2 readings in the trailing 90 days. A rolling average would answer ``insufficient_data``
    to essentially every real call.

    **``insufficient_data`` and ``is_stale`` are INDEPENDENT (D-08), never one flag.** Two
    readings four months apart are sufficient for a comparison AND stale; one fresh reading is
    stale=False AND insufficient. Collapsing them would make "we cannot compare" and "this is old
    news" the same sentence, and only one of them is a reason to stop trusting the number.

    Population rules, in order of how easily they are got wrong:

    * ``latest_value``/``latest_measured_on`` are populated whenever AT LEAST ONE reading exists
      in the window, ``coverage.insufficient_data`` notwithstanding. A single reading is a real
      observation and worth surfacing; suppressing it would report "no data" for a metric the
      user demonstrably measured.
    * ``earliest_value``/``earliest_measured_on``/``delta_value`` are populated ONLY when
      ``coverage.insufficient_data`` is False. With one reading, "earliest" IS "latest", and a
      ``delta_value`` of 0 would read as "no change" rather than "one data point".
    * ``days_since_latest_reading`` is ``None`` exactly when ``latest_measured_on`` is ``None``.

    ``window_days`` and ``stale_after_days`` are echoed as FIELDS, not left in a comment, for the
    same reason ``PlateauResult`` echoes ``threshold_percent`` and ``min_sessions``: a flag whose
    threshold the reader cannot see is a flag the reader has to trust blindly.
    """

    metric: BodyMeasurementMetric
    window_days: int
    anchor_day: dt.date
    coverage: MeasurementCoverage
    latest_value: Decimal | None
    latest_measured_on: dt.date | None
    earliest_value: Decimal | None
    earliest_measured_on: dt.date | None
    delta_value: Decimal | None
    is_stale: bool
    days_since_latest_reading: int | None
    stale_after_days: int
    freshness: FreshnessMetadata


class ActivityMetric(StrEnum):
    """HEALTH-12's closed activity vocabulary. Each VALUE is the exact Health Auto Export wire
    metric name stored in ``health_daily_metrics.metric``.

    Declared here rather than imported from
    ``app/integrations/health_auto_export/registry.py`` because ``test_analytics_isolation.py``
    forbids ``app.analytics`` importing ``app.integrations`` (a provider field rename must not
    become an analytics rename) -- the same relationship ``BodyMeasurementMetric`` has with the
    ORM's own column names. The drift risk that separation creates is closed by a TEST asserting
    this enum's value set equals the registry's ``kind == "activity"`` key set, not by trusting
    the two lists to be copied correctly once.
    """

    STEP_COUNT = "step_count"
    ACTIVE_ENERGY = "active_energy"
    BASAL_ENERGY_BURNED = "basal_energy_burned"
    WALKING_RUNNING_DISTANCE = "walking_running_distance"
    FLIGHTS_CLIMBED = "flights_climbed"


class NutritionMetric(StrEnum):
    """NUTR-04's closed nutrition vocabulary. Each VALUE is the exact Health Auto Export wire
    metric name stored in ``health_daily_metrics.metric``.

    The registry's naming trap, reproduced here because guessing it wrong is SILENT (D-04 drops
    an unlisted metric with a log line and no test failure): it is ``total_fat``, never
    ``fat``; ``dietary_sugar``, never ``sugar``; ``protein``, never ``dietary_protein``. Only
    ``dietary_energy`` and ``dietary_sugar`` carry the ``dietary_`` prefix.
    """

    DIETARY_ENERGY = "dietary_energy"
    PROTEIN = "protein"
    CARBOHYDRATES = "carbohydrates"
    TOTAL_FAT = "total_fat"
    FIBER = "fiber"
    DIETARY_SUGAR = "dietary_sugar"
    SODIUM = "sodium"


# `MappingProxyType` for `registry.py`'s reason: a caller must not be able to retune these at
# runtime.
ACTIVITY_METRIC_UNITS: Mapping[ActivityMetric, str] = MappingProxyType(
    {
        ActivityMetric.STEP_COUNT: "count",
        ActivityMetric.ACTIVE_ENERGY: "kcal",
        ActivityMetric.BASAL_ENERGY_BURNED: "kcal",
        ActivityMetric.WALKING_RUNNING_DISTANCE: "km",
        ActivityMetric.FLIGHTS_CLIMBED: "count",
    }
)
NUTRITION_METRIC_UNITS: Mapping[NutritionMetric, str] = MappingProxyType(
    {
        NutritionMetric.DIETARY_ENERGY: "kcal",
        NutritionMetric.PROTEIN: "g",
        NutritionMetric.CARBOHYDRATES: "g",
        NutritionMetric.TOTAL_FAT: "g",
        NutritionMetric.FIBER: "g",
        NutritionMetric.DIETARY_SUGAR: "g",
        NutritionMetric.SODIUM: "mg",
    }
)


class MetricWindowAverage(_AnalyticsModel):
    """One rolling window's average for one HEALTH-12/NUTR-04 metric.

    ``average`` and ``total`` are BOTH ``None`` when ``coverage.insufficient_data`` is True --
    the arithmetic exists either way, but a 30-day step average built from two logged days
    presents a fiction as a trend, exactly ``BodyWeightTrendResult``'s rule. ``total`` sums the
    MEASURED days only, never the window length: there is no interpolation and no carry-forward
    (``bodyweight.py`` D-13's reason), so ``total`` answers "how much did you log across the
    days you logged" and never "how much did you do this week" -- a distinction that matters
    most for nutrition, where a missed logging day is not a fasted day.
    """

    window_days: int
    average: Decimal | None
    total: Decimal | None
    coverage: MeasurementCoverage


class MetricTrend(_AnalyticsModel):
    """One metric's full HEALTH-12/NUTR-04 trend: three independent windows plus a rate.

    ``windows`` holds exactly three entries in ascending ``window_days`` order (7, 14, 30) -- a
    list rather than three named fields because every consumer iterates them and because the
    per-window independence is the point (D-15: a 30-day average can be trustworthy while the
    7-day one is not).

    ``change_percent_7d_vs_30d`` is HEALTH-12's "rate of change" and is deliberately NOT
    ``bodyweight.py``'s four-week smoothed anchor: that anchor exists to strip water and
    glycogen noise from a slow signal whose raw weekly delta is nearly three times the threshold
    it is compared against, whereas activity and intake are fast, high-variance, daily-measured
    signals whose real question is "has my activity dropped off lately" -- this week against the
    last month. It is ``None`` when EITHER window fails its own floor, because a ratio with one
    trustworthy endpoint and one guess is not half-trustworthy, it is wrong.

    ``latest_measured_on``/``latest_value`` are populated independently of every floor: one real
    observation is worth surfacing, and suppressing it would report "no data" for a metric the
    user demonstrably recorded.
    """

    metric: str
    unit: str
    windows: list[MetricWindowAverage]
    change_percent_7d_vs_30d: Decimal | None
    latest_measured_on: dt.date | None
    latest_value: Decimal | None


class ActivityTrendResult(_AnalyticsModel):
    """HEALTH-12. ``metrics`` always holds all five, in ``ActivityMetric`` declaration order.

    A metric with no rows is PRESENT with null averages and zero-measured-day coverage, never
    omitted -- an omitted metric is indistinguishable from a metric that does not exist, and
    "you have no flights-climbed data" is the answer to a question about flights climbed.

    Activity data is recomposition CONTEXT, never a classifier input. Nothing in
    ``recomposition.py`` reads this module, and nothing should.
    """

    anchor_day: dt.date
    metrics: list[MetricTrend]
    freshness: FreshnessMetadata


class NutritionTrendResult(_AnalyticsModel):
    """NUTR-04. ``metrics`` always holds all seven (D-08 -- no metric selector, ever).

    Per 13-RESEARCH.md Pitfall 2, each entry carries its OWN coverage: real production data
    shows the macros are not perfectly co-logged (2026-09-03, eleven of twelve registry metrics
    present, ``sodium`` absent), and one shared ``measured_days`` anchored on ``dietary_energy``
    would advertise a sodium average as trustworthy on the strength of days that recorded no
    sodium at all.
    """

    anchor_day: dt.date
    metrics: list[MetricTrend]
    freshness: FreshnessMetadata


class MetricPeriodSummary(_AnalyticsModel):
    """One metric's HEALTH-12/NUTR-04 figure over an explicit report period, not a rolling window.

    Separate from ``MetricWindowAverage`` because the coverage story differs.
    ``MEASURED_DAY_FLOORS`` is defined for exactly four window lengths and
    ``is_measurement_insufficient`` raises on any other, while a report period is 1-7 days
    (Monday through today) or 1-31 days (the calendar month so far) -- so its floor is COMPUTED,
    not looked up. ``floor_days`` is echoed as a field for ``PlateauResult.threshold_percent``'s
    reason: a flag whose threshold the reader cannot see is a flag the reader has to trust
    blindly. There is deliberately no ``freshness`` field -- this model is always embedded in a
    report that already carries the five-resource ``FRESHNESS_RESOURCES_REPORT`` envelope, and a
    per-metric copy would put twelve duplicate envelopes in one payload.
    """

    metric: str
    unit: str
    daily_average: Decimal | None
    total: Decimal | None
    measured_days: int
    days_in_period: int
    floor_days: int
    insufficient_data: bool


class ActivityPeriodSummary(_AnalyticsModel):
    """RPT-01/RPT-02's activity section, over the REPORT's own closed period.

    Sharing the report's window rather than carrying an independent rolling one is deliberate --
    a report whose training figures cover Monday-to-today and whose activity figures cover the
    trailing thirty days has two sections visibly disagreeing about what "this week" means.
    ``fitness_get_activity_trend`` is where the rolling view lives.
    """

    window_start: dt.date
    window_end: dt.date
    days_in_period: int
    metrics: list[MetricPeriodSummary]


class NutritionPeriodSummary(_AnalyticsModel):
    """RPT-01/RPT-02's nutrition section, over the REPORT's own closed period.

    Same four fields, same period-sharing rule as ``ActivityPeriodSummary`` -- sharing the
    report's window rather than an independent rolling one, so the report cannot visibly
    disagree with itself about what "this week" means.
    """

    window_start: dt.date
    window_end: dt.date
    days_in_period: int
    metrics: list[MetricPeriodSummary]


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

    ``active_program`` is ALWAYS populated -- it names the thresholds this verdict was actually
    classified against, which is the difference between "you are losing too fast" and "you are
    losing exactly as planned". It falls back to ``LEAN_BULK`` on a database with no period row at
    all (only possible before migration 0006 has run against that database), and
    ``program_started_on`` is ``None`` exactly in that case.

    ``program_switch_in_window`` is True exactly when more than one program period overlaps the
    12-week lookback. ``previous_program`` and ``program_switched_on`` are populated exactly when
    it is True, and are ``None`` exactly when it is False.

    D-10, stated as the reason rather than left implicit: a straddled window is still CLASSIFIED,
    against the CURRENT program's thresholds for the whole window. Refusing to classify would hide
    a verdict the user asked for; classifying silently would misrepresent it. These three fields
    are what let Claude say "this mixes 3 weeks of cut with 9 weeks of lean bulk" beside the
    verdict.

    ``program_switched_on`` is the ACTIVE period's ``started_on`` -- the day the current program
    began. With three or more periods in one window, ``previous_program`` names the one
    immediately before the active period; ``program_switch_in_window`` is the flag that tells
    Claude the window is mixed at all.
    """

    status: RecompositionStatus
    active_program: TrainingProgram
    program_started_on: dt.date | None
    program_switch_in_window: bool
    previous_program: TrainingProgram | None
    program_switched_on: dt.date | None
    disclaimer: str
    weight_trend: BodyWeightTrendResult
    progression_signal: AggregateProgression
    training_volume: WeeklyVolumeResult
    freshness: FreshnessMetadata


class ReportPeriod(StrEnum):
    """D-04's period selector. Two members and no third.

    ``WEEKLY`` is Monday of the current local week through today; ``MONTHLY`` is the first
    of the current local calendar month through today. Both are CLOSED-PERIOD anchored --
    the start is a calendar boundary, not "seven days ago" -- which is the distinction D-01
    draws. Both end on TODAY, matching D-04's literal "the current week" / "the current
    calendar month" and every other anchored tool in this codebase.
    """

    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportResult(_AnalyticsModel):
    """RPT-01/RPT-02: the composed report, before any presentation cap is applied.

    **Composed, never computed.** Every field below is another analytics function's return
    value, carried through. ``analytics/reports.py`` owns the WINDOW and the ASSEMBLY and
    nothing else -- ARCHITECTURE.md's Anti-Pattern #9 ("report tools as a fourth copy of the
    analytics arithmetic") and D-02/D-03.

    **Two anchors, both named.** ``window_start``/``window_end`` govern
    ``weekly_volume``, ``muscle_volume``, ``frequency``, ``pr_highlights``, ``activity`` and
    ``nutrition``. They do NOT govern ``recomposition`` (its own fixed 12-week lookback
    ending today -- ``get_recomposition_status`` takes no window and D-01 forbids adding
    one), ``plateau_highlights`` (``plateau_lookback_weeks`` back from today, because "you
    have not PR'd in 40 days" is only meaningful relative to now), or
    ``measurement_highlights`` (a fixed 90-day comparison window that is a module constant in
    ``body_measurements.py``). Each of those three carries its own window in its own fields,
    which is why they are embedded whole rather than projected: a reader must be able to see
    that the verdict beside this week's volume is not a verdict about this week.

    **No recommendations field, deliberately (D-03).** This is composed DATA. Claude
    synthesizes the recommendation from it and ``docs/coaching-instructions.md``'s decision
    framework. A backend-computed "you should deload" is arithmetic-adjacent judgment in a
    payload that has no way to express its own uncertainty.

    **Lists are UNCAPPED here.** ``pr_highlights`` and ``plateau_highlights`` are full
    lists; the MCP layer applies ``MAX_REPORT_*`` with ``_common.truncate()`` and carries
    ``was_truncated``/``total`` beside them. A silent truncation inside the analytics layer
    would be a wrong answer, which is the rule ``records.py`` already states about
    ``reps_at_weight``.

    ``active_program`` context is NOT a field here: it is read off ``recomposition``
    (``active_program``, ``program_started_on``, ``program_switch_in_window``,
    ``previous_program``, ``program_switched_on``), which Phase 12 already resolved inside
    that call. Re-querying ``db/repositories/programs.py`` would be a second answer to a
    question already answered in this same transaction.
    """

    period: ReportPeriod
    window_start: dt.date
    window_end: dt.date
    days_in_period: int
    weekly_volume: WeeklyVolumeResult
    muscle_volume: MuscleGroupVolumeResult
    frequency: TrainingFrequencyResult
    recomposition: RecompositionResult
    recomposition_anchor_day: dt.date
    pr_highlights: RecentRecordsResult
    plateau_highlights: PlateauReport
    plateau_lookback_weeks: int
    measurement_highlights: list[BodyMeasurementTrendResult]
    activity: ActivityPeriodSummary
    nutrition: NutritionPeriodSummary
    coverage: CoverageMetadata
    freshness: FreshnessMetadata


class PhysiqueDiffVerdict(StrEnum):
    """PHYS-09's four outcomes per muscle group. Ordinal comparison only -- no score, no average.

    `NOT_COMPARABLE` is a first-class verdict, not a missing value: it is what a `Not Assessable`
    rating on EITHER side produces, which for `abductors`/`adductors` is the ordinary case rather
    than an error (PHYS-02). Collapsing it into `UNCHANGED` would report "no change" for a muscle
    nobody ever rated.
    """

    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"
    NOT_COMPARABLE = "not_comparable"


class PhysiqueMuscleDiff(_AnalyticsModel):
    """One muscle group's verdict across two observations.

    `level_delta` is the raw ordinal index difference (later minus earlier) and is reported
    ALONGSIDE the verdict rather than folded into it. With `PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2`, a
    one-level
    move classifies as `UNCHANGED` -- the Phase 15 spike measured the rater's own noise floor at
    exactly 1 level, so a single step is indistinguishable from the instrument. Surfacing the raw
    delta keeps that honest: "unchanged" here means "no change above the measured noise floor", and
    the reader can see the 1 that produced it.

    `level_delta` is `None` exactly when the verdict is `NOT_COMPARABLE`.
    """

    muscle_group: CanonicalMuscleGroup
    earlier_level: PhysiqueRatingLevel | None
    later_level: PhysiqueRatingLevel | None
    level_delta: int | None
    verdict: PhysiqueDiffVerdict


class PhysiqueDiffResult(_AnalyticsModel):
    """PHYS-09. All 19 muscle groups, sorted by ``muscle_group.value``, never a subset.

    The gap-free 19-row spine is `get_muscle_group_volume`'s own convention and it matters for the
    same reason: a caller that receives only the groups that changed cannot tell "no change" from
    "not in this response".

    `min_level_delta` and `min_elapsed_days` are SURFACED, not enforced. `min_elapsed_days` is
    `PHYSIQUE_MIN_ELAPSED_DAYS`, and PHYS-F01 -- the hard floor that would refuse or flag a
    too-close pair -- is deferred; carrying the constant beside the real `elapsed_days` lets a
    reader see that an 8-day interval is inside the recommended floor without this module
    inventing a refusal the phase did not authorize.
    """

    earlier_observed_on: dt.date
    later_observed_on: dt.date
    elapsed_days: int
    min_elapsed_days: int
    min_level_delta: int
    muscle_groups: list[PhysiqueMuscleDiff]
    disclaimer: str


class PhysiqueVolumeFlag(_AnalyticsModel):
    """One muscle group that is BOTH underdeveloped and undertrained (PHYS-10, D-01/D-02)."""

    muscle_group: CanonicalMuscleGroup
    rating_level: PhysiqueRatingLevel
    weighted_sets: Decimal


class PhysiqueVolumeCrossReference(_AnalyticsModel):
    """PHYS-10. The flagged list ONLY (D-04), never a 19-row level-and-quartile table.

    D-04's reasoning: this answers a specific question ("is the underdeveloped area also the
    undertrained one?"), and a full table would hand Claude the raw material to re-derive the same
    conclusion itself -- which is the join PHYS-10 exists to stop asking it to do. The narrow,
    purpose-built shape follows `MAX_REPORT_PR_HIGHLIGHTS`'s precedent.

    `undertrained_threshold_weighted_sets` is the volume total of the highest-ranked group still
    inside the bottom quartile -- i.e. the cut. It is reported so the flag list is auditable
    against `get_muscle_group_volume`'s own numbers rather than being a verdict with no working.
    """

    observed_on: dt.date
    lookback_weeks: int
    window_start: dt.date
    window_end: dt.date
    undertrained_threshold_weighted_sets: Decimal
    flagged: list[PhysiqueVolumeFlag]
    disclaimer: str

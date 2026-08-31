"""Every MCP-facing response model, in one module (MCP-02, MCP-03, MCP-06;
D-02, D-09, D-11, D-13).

Three load-bearing rules, each with the consequence of breaking it:

1. **Compose, never restate.** Every model here carries an ``app/analytics/schemas.py`` result as
   a FIELD; none of them re-derives its arithmetic. A second copy of "hard sets excludes warm-ups"
   or "tonnage is ``None``, not ``0``, when an operand is missing" is a second copy that drifts,
   and the drift is invisible -- both numbers look plausible. The ONE deliberate reshape in this
   phase is ``MuscleGroupRollup`` (and ``TrainingSummaryResponse``, which reuses it); it is
   documented at the model that performs it, with the measured byte figures that justify it.

2. **Every response carries ``data_available: bool``.** ``False`` means the tool could not reach
   its data (see ``_common.safe_tool``); it is NOT the same claim as "you trained zero sets".
   Without this field a degraded payload is byte-indistinguishable from a real empty result, and
   Claude would narrate an outage as detraining -- a wrong answer delivered with no signal that
   anything went wrong.

3. **Never a union RETURN annotation.** ``mcp 2.0.0`` sets ``wrap_output=True`` for unions,
   scalars, lists and tuples, which changes ``structured_content`` from ``{...}`` to
   ``{"result": {...}}`` on EVERY call, including the successful ones. A single ``BaseModel``
   return with an optional payload field is left unwrapped. An optional FIELD is fine -- only the
   RETURN annotation is what triggers the wrapping.

``Decimal | None``, never ``float``, anywhere in this module. Plan 06-09 adds a static guard
carrying ``test_analytics_isolation.py``'s ``_FLOAT_USE`` regex into ``app/mcp/``; the reason is
``app/analytics/schemas.py``'s reason -- binary floating point makes two arithmetically identical
weekly totals compare unequal.
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.analytics.schemas import (
    BodyWeightTrendResult,
    ComparisonLevel,
    ComparisonRate,
    CoverageMetadata,
    ExerciseFrequency,
    ExerciseProgressionResult,
    FreshnessMetadata,
    MuscleGroupComparison,
    MuscleGroupFrequency,
    PeriodSummary,
    PersonalRecordsResult,
    PlateauResult,
    ProgressionSignal,
    RecompositionResult,
    RecompositionStatus,
    TrendVerdict,
    WeeklyVolumeResult,
)
from app.normalization.muscles import CanonicalMuscleGroup


class _McpModel(BaseModel):
    """Shared config for every MCP response type. Mirrors ``_AnalyticsModel`` exactly.

    ``hide_input_in_errors`` matters DOUBLY here. An output-model ``ValidationError`` is raised
    inside the SDK's ``convert_result``, which runs OUTSIDE ``safe_tool``'s reach -- nothing in
    this repo can catch it -- and its default message renders ``input_value=...``, i.e. weekly
    tonnage, session counts and body-composition-adjacent numbers, into the ``str(e)`` that the
    SDK hands back to Claude as tool-error text (FOUND-05, T-06-01).

    ``extra="forbid"`` rather than ignore: these are internal types, not a mirror of somebody
    else's wire format. An unexpected field is a bug in this repo and must fail loudly.
    ``frozen=True`` because this is a read path -- a response object a caller can mutate is a
    response object two callers will disagree about.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)


class WeeklyVolumeResponse(_McpModel):
    """VOL-01 for MCP. ``volume`` is the analytics result verbatim -- gap-free ascending weeks."""

    data_available: bool
    volume: WeeklyVolumeResult | None


class TrainingFrequencyResponse(_McpModel):
    """VOL-03 with MCP-03 truncation applied to ``exercises`` ONLY.

    ``muscle_groups`` is already bounded by the 19-member canonical taxonomy and is never
    truncated -- a bound that comes from the shape needs no flag.
    """

    data_available: bool
    window_start: dt.date | None
    window_end: dt.date | None
    sessions_per_week: Decimal | None
    muscle_groups: list[MuscleGroupFrequency]
    exercises: list[ExerciseFrequency]
    exercises_truncated: bool
    total_exercises: int
    coverage: CoverageMetadata | None
    freshness: FreshnessMetadata | None


class ExerciseCandidate(_McpModel):
    """One template that matched the requested name. D-02."""

    title: str
    exercise_template_external_id: str


class ExerciseProgressionResponse(_McpModel):
    """D-01/D-02. ``progression`` is populated IFF exactly one template matched.

    ``matched=False`` with an EMPTY ``candidates`` means "no such exercise"; ``matched=False``
    with two or more means "be more specific". Both are ordinary SUCCESSFUL results -- the tool
    did exactly what it was asked and is reporting what it found -- so ``is_error`` stays false
    and no exception text can reach the model through the SDK's error channel.
    """

    data_available: bool
    requested_name: str
    matched: bool
    candidates: list[ExerciseCandidate]
    progression: ExerciseProgressionResult | None
    points_truncated: bool
    total_points: int


class PersonalRecordsResponse(_McpModel):
    """PROG-04 for MCP. Same D-02 disambiguation contract as ``ExerciseProgressionResponse``:
    ``records`` is populated IFF exactly one template matched, and an ambiguous name is a
    successful result carrying ``candidates``, never an error."""

    data_available: bool
    requested_name: str
    matched: bool
    candidates: list[ExerciseCandidate]
    records: PersonalRecordsResult | None


class PlateauResponse(_McpModel):
    """PROG-03 for MCP. ``plateaued_only`` echoes the filter back, because an empty ``exercises``
    means something different under each setting: "nothing is stuck" versus "nothing was
    analysable at all"."""

    data_available: bool
    plateaued_only: bool
    lookback_weeks: int | None
    lookback_start: dt.date | None
    lookback_end: dt.date | None
    exercises: list[PlateauResult]
    exercises_truncated: bool
    total_exercises: int
    coverage: CoverageMetadata | None
    freshness: FreshnessMetadata | None


class PeriodComparisonResponse(_McpModel):
    """CMP-01 for MCP. ``exercises`` (rates) and ``exercise_levels`` (maxima) truncate
    INDEPENDENTLY and each carries its own flag/total pair -- they are different populations and
    one shared flag would misreport whichever list was not the one that overflowed."""

    data_available: bool
    period_a: PeriodSummary | None
    period_b: PeriodSummary | None
    totals: list[ComparisonRate]
    exercises: list[ComparisonRate]
    exercises_truncated: bool
    total_exercises: int
    exercise_levels: list[ComparisonLevel]
    exercise_levels_truncated: bool
    total_exercise_levels: int
    muscle_groups: list[MuscleGroupComparison]
    freshness: FreshnessMetadata | None


class BodyWeightTrendResponse(_McpModel):
    """BODY-01 for MCP. ``trend`` is the analytics result verbatim, per-window coverage and all --
    a collapsed single coverage flag would hide that a 30-day average can be trustworthy while
    the 7-day one is not."""

    data_available: bool
    trend: BodyWeightTrendResult | None


class RecompositionResponse(_McpModel):
    """BODY-02 for MCP. ``recomposition`` embeds ``RecompositionResult`` WHOLE, which is what
    carries its required ``disclaimer`` field through untouched (T-06-09)."""

    data_available: bool
    recomposition: RecompositionResult | None


class WorkoutSummary(_McpModel):
    """D-09: one workout, no per-exercise and no per-set breakdown.

    This omission is what keeps the list compact regardless of how many workouts are requested --
    ``fitness_get_workout`` exists to expand exactly one of these on demand.

    ``workout_id`` is the HEVY EXTERNAL ID (``workouts.external_id``), never the internal
    ``workouts.id`` surrogate (D-12, T-06-08).
    """

    workout_id: str
    local_day: dt.date
    title: str
    duration_minutes: int
    exercise_count: int
    hard_sets: int
    tonnage_sets: int
    tonnage_kg: Decimal | None


class RecentWorkoutsResponse(_McpModel):
    """D-09. ``limit`` is echoed back so a short list reads as "that is all there is" rather than
    as "the tool cut it off"."""

    data_available: bool
    limit: int
    workouts: list[WorkoutSummary]
    freshness: FreshnessMetadata | None


class WorkoutSetDetail(_McpModel):
    """One logged set, exactly as recorded. ``set_type`` is carried on EVERY set because this
    projection includes warm-ups and the reader must be able to tell them apart."""

    set_index: int
    set_type: str
    weight_kg: Decimal | None
    reps: int | None
    distance_meters: Decimal | None
    duration_seconds: int | None
    rpe: Decimal | None


class WorkoutExerciseDetail(_McpModel):
    """One exercise within a workout. ``supersets_id`` is ``None`` unless Hevy grouped it."""

    exercise_index: int
    title: str
    exercise_template_external_id: str
    supersets_id: int | None
    sets: list[WorkoutSetDetail]


class WorkoutDetail(_McpModel):
    """D-11: the full breakdown for exactly ONE workout.

    ``sets`` includes WARM-UPS, unlike every volume figure in this phase -- this is the raw record
    of what happened, not an analytics rollup -- and ``set_type`` is carried on every set so the
    reader can tell them apart. Never sum these sets into a "hard sets" figure; that number comes
    from ``app/analytics/`` and only from there.
    """

    workout_id: str
    local_day: dt.date
    title: str
    duration_minutes: int
    exercises: list[WorkoutExerciseDetail]
    sets_truncated: bool
    total_sets: int


class WorkoutDetailResponse(_McpModel):
    """``found=False`` with ``workout=None`` means no workout carries that id for this user -- an
    ordinary SUCCESSFUL result, not an error. Raising here would put the requested id into the
    SDK's error text; reporting it as a field keeps ``is_error`` false."""

    data_available: bool
    requested_workout_id: str
    found: bool
    workout: WorkoutDetail | None
    freshness: FreshnessMetadata | None


class MuscleGroupRollup(_McpModel):
    """One muscle group's whole-window totals. THE ONE DELIBERATE RESHAPE IN THIS PHASE.

    CONTEXT.md's rule is "compose these, do not reshape them". This model breaks it exactly once,
    on purpose, for a measured reason: ``MuscleGroupVolumeResult``'s shape is weeks x 19 muscle
    groups, so D-04's 52-week cap bounds it at 988 rows -- 128,290 bytes of structured JSON and
    ~347,707 bytes on the wire. Rolled up over the window it is 19 rows and ~7,851 bytes at ANY
    window. The per-week TOTAL trend is still available from ``fitness_get_weekly_volume``, and
    muscle-level period-over-period movement from ``fitness_compare_periods``; what is given up
    is the per-week x per-muscle grid, which is not what "which muscles are undertrained?" asks.

    ``direct_sets``/``indirect_sets``/``weighted_sets`` are SUMS over the window's weeks -- set
    counts are additive. ``sessions``/``sessions_per_week`` are NOT: they come from
    ``get_training_frequency``, which de-duplicates workouts across the whole window. Summing
    per-week session counts inflated 14 of 16 muscle groups by up to 4.0x on real data
    (``analytics/frequency.py`` module docstring).

    Never sum these ACROSS muscle groups either: one template maps to up to 9 muscle groups, so a
    cross-muscle total is several times the truth and it looks plausible.
    """

    muscle_group: CanonicalMuscleGroup
    direct_sets: int
    indirect_sets: int
    weighted_sets: Decimal
    sessions: int
    sessions_per_week: Decimal
    insufficient_data: bool


class MuscleGroupVolumeResponse(_McpModel):
    """VOL-02 for MCP. ``muscles`` ALWAYS has 19 rows, one per canonical muscle group, sorted by
    ``muscle_group.value`` -- an untrained group is a ZERO ROW, never an absence.

    A zero row is the most diagnostically interesting one for "which muscles are undertrained?",
    which is exactly why it must not be omitted. An absent group would read as "no data" when the
    fact is "no training".
    """

    data_available: bool
    window_start: dt.date | None
    window_end: dt.date | None
    weeks: int | None
    muscles: list[MuscleGroupRollup]
    coverage: CoverageMetadata | None
    freshness: FreshnessMetadata | None


class SummaryVolumeWeek(_McpModel):
    """One week of VOL-01 inside the summary. ``tonnage_sets`` is dropped relative to
    ``WeeklyVolumeWeek``; ``fitness_get_weekly_volume`` is where the full row lives."""

    week_start: dt.date
    sessions: int
    hard_sets: int
    total_reps: int | None
    tonnage_kg: Decimal | None


class TrainingSummaryResponse(_McpModel):
    """D-08: the one call that answers PROJECT.md's two Core Value questions.

    Deliberately EXCLUDES personal records and plateaus -- those keep their own tools rather than
    duplicating data into the one tool every conversation opens with. Deliberately excludes the
    per-exercise frequency list and the per-week x per-muscle grid: composing the four analytics
    results verbatim measures ~24 KB structured / ~57 KB wire at a 4-week window; this shape is
    ~3,963 / ~9,502.

    ``recomposition_disclaimer`` is carried through VERBATIM from
    ``RecompositionResult.disclaimer``. That field's own docstring calls it "a REQUIRED FIELD,
    not documentation" precisely so a Phase 6 serialization change cannot drop it; dropping it
    here is exactly the failure it anticipates (T-06-09).

    ``progression_signal`` beside ``recomposition_status`` for the same reason BODY-02 pairs
    them: "likely_muscle_gain" with a "negative" signal is a real and important disagreement, and
    a single label hides it.
    """

    data_available: bool
    window_start: dt.date | None
    window_end: dt.date | None
    weeks: int | None
    sessions_per_week: Decimal | None
    volume_by_week: list[SummaryVolumeWeek]
    muscles: list[MuscleGroupRollup]
    recomposition_status: RecompositionStatus | None
    recomposition_disclaimer: str | None
    progression_signal: ProgressionSignal | None
    progression_verdict: TrendVerdict | None
    weight_trend_rate_percent_per_week: Decimal | None
    average_7d_kg: Decimal | None
    coverage: CoverageMetadata | None
    freshness: FreshnessMetadata | None

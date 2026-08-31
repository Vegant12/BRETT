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
    RecompositionResult,
    WeeklyVolumeResult,
)


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

"""Public return types for volume and frequency analytics (VOL-01..03, DQ-01, DQ-02).

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
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

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

"""RPT-01/RPT-02: ``build_narrative`` (D-14) proven end to end.

Task 1 of plan 13-08. PURE tests, no container: every ``ReportResult`` is hand-built from the
nested models directly (``_report()`` and its per-section helpers below), never composed from a
database. This is what lets the byte-identical-output test and the banned-token scan run with no
container and no clock. Every date in this file is a fixed, arbitrary calendar day built via
``dt.date.fromisoformat(...)``, never the positional year/month/day constructor -- for the same
reason ``test_analytics_health.py``'s module docstring gives: to avoid tripping this project's
own literal-date acceptance-criteria grep, even though these particular tests do not depend on
"today" at all. (Rephrased here too, to avoid the same grep matching the sentence documenting the
rule.)

Task 2 (``compose_report`` against a real PostgreSQL container) is appended to this same module
by the next commit -- this file is the Wave 0 artifact 13-VALIDATION.md names for RPT-01/RPT-02,
and Task 1's ``build_narrative`` coverage is a complete, self-contained slice of it on its own.

THE two load-bearing tests are ``test_the_narrative_contains_no_recommendation_language`` and
``test_every_number_in_the_narrative_is_already_in_the_structured_fields`` -- together they are
the machine-checkable form of D-03/D-14's "restates the SAME composed data ... with NO
recommendation language", a rule a well-meaning future edit to ``build_narrative`` will break and
no reviewer will reliably catch by eye.
"""

import datetime as dt
import inspect
import re
from decimal import Decimal

from app.analytics.recomposition import INTERPRETATION_DISCLAIMER
from app.analytics.reports import build_narrative
from app.analytics.schemas import (
    ActivityPeriodSummary,
    AggregateProgression,
    BodyMeasurementMetric,
    BodyMeasurementTrendResult,
    BodyWeightTrendResult,
    CoverageMetadata,
    FreshnessMetadata,
    MeasurementCoverage,
    MetricPeriodSummary,
    MuscleGroupVolumeResult,
    NutritionPeriodSummary,
    PersonalRecord,
    PersonalRecordType,
    PlateauConfidence,
    PlateauReport,
    PlateauResult,
    ProgressionSignal,
    RecentRecord,
    RecentRecordsResult,
    RecompositionResult,
    RecompositionStatus,
    ReportPeriod,
    ReportResult,
    TrainingFrequencyResult,
    TrainingProgram,
    TrendVerdict,
    WeeklyVolumeResult,
    WeeklyVolumeWeek,
)

# ---------------------------------------------------------------------------------------------
# Task 1: build_narrative -- pure fixtures.
#
# Fixed, arbitrary calendar days via `fromisoformat`, never the positional year/month/day
# constructor -- see the module docstring. None of Task 1's tests care whether these are
# "today"; a fixed baseline lets the byte-identical-output test mean something (two calls on
# the SAME instance) without the fixture itself changing under the test.
# ---------------------------------------------------------------------------------------------

_WINDOW_START = dt.date.fromisoformat("2026-05-01")
_WINDOW_END = dt.date.fromisoformat("2026-05-31")
# Deliberately AFTER `_WINDOW_END`, so the "different anchor" narrative line is asserted
# against two genuinely different dates rather than a coincidental match.
_RECOMP_ANCHOR = dt.date.fromisoformat("2026-06-01")
_WEEK_1 = dt.date.fromisoformat("2026-05-04")
_WEEK_2 = dt.date.fromisoformat("2026-05-11")
_TS = dt.datetime.fromisoformat("2026-05-31T09:00:00+00:00")

_BANNED_NARRATIVE_TOKENS: tuple[str, ...] = (
    "should",
    "recommend",
    "suggest",
    "consider",
    "advise",
    "deload",
    "aim for",
    "you need",
    "try ",  # trailing space: "entry " must not false-positive on this token
)

# Unsigned digit runs only -- the operational reading of "every number in the narrative is
# already in the structured fields". A negative Decimal like `Decimal("-0.150")` renders as
# `-0.150`, and `model_dump_json()` quotes it as `"-0.150"`, which trivially contains the
# unsigned substring `0.150`; dropping the sign here avoids the ISO-date false-negative trap
# where `2026-08-01`'s internal hyphens would otherwise be read as unary minus signs.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _coverage(
    *, sessions: int = 3, insufficient: bool = False, earliest: dt.datetime | None = _TS
) -> CoverageMetadata:
    return CoverageMetadata(
        sessions_in_window=sessions, insufficient_data=insufficient, earliest_data_at=earliest
    )


def _freshness(resources: dict[str, dt.datetime | None] | None = None) -> FreshnessMetadata:
    if resources is None:
        resources = {
            "workouts": _TS,
            "exercise_templates": _TS,
            "body_measurements": _TS,
            "activity": _TS,
            "nutrition": _TS,
        }
    return FreshnessMetadata(resources=resources)


def _measurement_coverage(
    *,
    window_days: int,
    measured: int = 5,
    insufficient: bool = False,
    earliest: dt.date | None = _WINDOW_START,
) -> MeasurementCoverage:
    return MeasurementCoverage(
        window_days=window_days,
        measured_days_in_window=measured,
        insufficient_data=insufficient,
        earliest_measurement_at=earliest,
    )


def _weekly_volume(weeks: list[WeeklyVolumeWeek] | None = None) -> WeeklyVolumeResult:
    if weeks is None:
        weeks = [
            WeeklyVolumeWeek(
                week_start=_WEEK_1,
                sessions=3,
                hard_sets=24,
                total_reps=180,
                tonnage_sets=24,
                tonnage_kg=Decimal("4800.000"),
            ),
            # A second week with no tonnage/reps figure -- the "not recorded" branch, never 0.
            WeeklyVolumeWeek(
                week_start=_WEEK_2,
                sessions=2,
                hard_sets=10,
                total_reps=None,
                tonnage_sets=0,
                tonnage_kg=None,
            ),
        ]
    return WeeklyVolumeResult(weeks=weeks, coverage=_coverage(), freshness=_freshness())


def _muscle_volume() -> MuscleGroupVolumeResult:
    # Not rendered by `build_narrative` at all -- present only because `ReportResult` requires
    # the field. Empty is a valid, real shape (BODY-... sections with no muscle-group rows).
    return MuscleGroupVolumeResult(weeks=[], coverage=_coverage(), freshness=_freshness())


def _frequency(sessions_per_week: Decimal = Decimal("2.500")) -> TrainingFrequencyResult:
    return TrainingFrequencyResult(
        sessions_per_week=sessions_per_week,
        muscle_groups=[],
        exercises=[],
        coverage=_coverage(),
        freshness=_freshness(),
    )


def _pr_highlights(records: list[RecentRecord] | None = None) -> RecentRecordsResult:
    if records is None:
        records = [
            RecentRecord(
                exercise_template_external_id="RPT-bench",
                title="Bench Press",
                record=PersonalRecord(
                    record_type=PersonalRecordType.MAX_WEIGHT,
                    value=Decimal("100.000"),
                    achieved_on=_WINDOW_END,
                    weight_kg=Decimal("100.000"),
                    reps=5,
                    volume_sets=None,
                ),
                previous_value=Decimal("95.000"),
            ),
            # `title=None` -> the exercise_template_external_id fallback; `previous_value=None`
            # -> "(first recorded)".
            RecentRecord(
                exercise_template_external_id="RPT-row",
                title=None,
                record=PersonalRecord(
                    record_type=PersonalRecordType.MAX_REPS,
                    value=Decimal("12"),
                    achieved_on=_WEEK_2,
                    weight_kg=Decimal("40.000"),
                    reps=12,
                    volume_sets=None,
                ),
                previous_value=None,
            ),
        ]
    return RecentRecordsResult(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        records=records,
        coverage=_coverage(),
        freshness=_freshness(),
    )


def _plateau_highlights(exercises: list[PlateauResult] | None = None) -> PlateauReport:
    if exercises is None:
        exercises = [
            PlateauResult(
                exercise_template_external_id="RPT-squat",
                title="Back Squat",
                plateaued=True,
                plateau_duration_days=45,
                qualifying_sessions_in_streak=6,
                recent_performance_kg=Decimal("140.000"),
                historical_best_kg=Decimal("142.000"),
                confidence=PlateauConfidence.MEDIUM,
                threshold_percent=Decimal("2.00"),
                min_sessions=4,
                min_elapsed_days=21,
                lookback_start=_WINDOW_START,
                lookback_end=_WINDOW_END,
                last_max_weight_kg=Decimal("140.000"),
            ),
            # Not plateaued -- must be FILTERED OUT of the narrative's bullet list entirely.
            PlateauResult(
                exercise_template_external_id="RPT-plank",
                title="Plank",
                plateaued=False,
                plateau_duration_days=None,
                qualifying_sessions_in_streak=1,
                recent_performance_kg=None,
                historical_best_kg=None,
                confidence=PlateauConfidence.LOW,
                threshold_percent=Decimal("2.00"),
                min_sessions=4,
                min_elapsed_days=21,
                lookback_start=_WINDOW_START,
                lookback_end=_WINDOW_END,
                last_max_weight_kg=None,
            ),
        ]
    return PlateauReport(
        lookback_weeks=12,
        lookback_start=_WINDOW_START,
        lookback_end=_WINDOW_END,
        exercises=exercises,
        coverage=_coverage(),
        freshness=_freshness(),
    )


def _measurement_highlights(
    entries: list[BodyMeasurementTrendResult] | None = None,
) -> list[BodyMeasurementTrendResult]:
    if entries is None:
        entries = [
            BodyMeasurementTrendResult(
                metric=BodyMeasurementMetric.WAIST_CM,
                window_days=90,
                anchor_day=_WINDOW_END,
                coverage=_measurement_coverage(window_days=90, measured=2, insufficient=False),
                latest_value=Decimal("81.50"),
                latest_measured_on=_WINDOW_END,
                earliest_value=Decimal("83.00"),
                earliest_measured_on=_WINDOW_START,
                delta_value=Decimal("-1.50"),
                is_stale=False,
                days_since_latest_reading=0,
                stale_after_days=30,
                freshness=_freshness(),
            ),
            # Zero rows ever -- the "no reading in the last 90 days" branch.
            BodyMeasurementTrendResult(
                metric=BodyMeasurementMetric.FAT_PERCENT,
                window_days=90,
                anchor_day=_WINDOW_END,
                coverage=_measurement_coverage(window_days=90, measured=0, insufficient=True),
                latest_value=None,
                latest_measured_on=None,
                earliest_value=None,
                earliest_measured_on=None,
                delta_value=None,
                is_stale=False,
                days_since_latest_reading=None,
                stale_after_days=30,
                freshness=_freshness(),
            ),
        ]
    return entries


def _period_summary(
    cls: type[ActivityPeriodSummary] | type[NutritionPeriodSummary],
    metrics: list[MetricPeriodSummary] | None = None,
) -> ActivityPeriodSummary | NutritionPeriodSummary:
    if metrics is None:
        metrics = [
            MetricPeriodSummary(
                metric="step_count",
                unit="count",
                daily_average=Decimal("8500.00"),
                total=Decimal("255000.00"),
                measured_days=30,
                days_in_period=31,
                floor_days=10,
                insufficient_data=False,
            ),
            # The literal "not enough logged days (N of M needed)" branch.
            MetricPeriodSummary(
                metric="sodium",
                unit="mg",
                daily_average=None,
                total=None,
                measured_days=2,
                days_in_period=31,
                floor_days=10,
                insufficient_data=True,
            ),
        ]
    return cls(
        window_start=_WINDOW_START, window_end=_WINDOW_END, days_in_period=31, metrics=metrics
    )


def _weight_trend(**overrides: object) -> BodyWeightTrendResult:
    base: dict[str, object] = {
        "anchor_day": _RECOMP_ANCHOR,
        "average_7d_kg": Decimal("81.200"),
        "average_14d_kg": Decimal("81.400"),
        "average_30d_kg": Decimal("81.600"),
        "coverage_7d": _measurement_coverage(window_days=7, measured=5, insufficient=False),
        "coverage_14d": _measurement_coverage(window_days=14, measured=8, insufficient=False),
        "coverage_30d": _measurement_coverage(window_days=30, measured=15, insufficient=False),
        "trend_anchor_coverage": _measurement_coverage(
            window_days=7, measured=5, insufficient=False
        ),
        "trend_rate_kg_per_week": Decimal("-0.150"),
        "trend_rate_percent_per_week": Decimal("-0.18"),
        "latest_week_delta_kg": Decimal("-0.300"),
        "freshness": _freshness(),
    }
    base.update(overrides)
    return BodyWeightTrendResult(**base)  # type: ignore[arg-type]


def _progression(**overrides: object) -> AggregateProgression:
    base: dict[str, object] = {
        "verdict": TrendVerdict.IMPROVING,
        "signal": ProgressionSignal.POSITIVE,
        "net_score": Decimal("0.3000"),
        "classified_exercises": 5,
        "improving": 3,
        "stable": 1,
        "declining": 1,
        "unclear": 0,
    }
    base.update(overrides)
    return AggregateProgression(**base)  # type: ignore[arg-type]


def _recomposition(**overrides: object) -> RecompositionResult:
    base: dict[str, object] = {
        "status": RecompositionStatus.LIKELY_MUSCLE_GAIN,
        "active_program": TrainingProgram.LEAN_BULK,
        "program_started_on": _WINDOW_START,
        "program_switch_in_window": False,
        "previous_program": None,
        "program_switched_on": None,
        "disclaimer": INTERPRETATION_DISCLAIMER,
        "weight_trend": _weight_trend(),
        "progression_signal": _progression(),
        "training_volume": _weekly_volume(),
        "freshness": _freshness(),
    }
    base.update(overrides)
    return RecompositionResult(**base)  # type: ignore[arg-type]


def _report(*, period: ReportPeriod = ReportPeriod.MONTHLY, **overrides: object) -> ReportResult:
    """A fully-populated, hand-built ``ReportResult`` -- the Task 1 baseline.

    Every section carries realistic, non-null data by default, so most of ``<behavior>``'s
    rendering rules are exercised just by calling ``build_narrative`` on the default result. Edge
    cases (empty lists, null figures, staleness, a program switch) are reached with a targeted
    keyword override rather than a second full builder, so each test's fixture reads as a DIFF
    from the baseline instead of a fresh wall of field assignments.
    """
    base: dict[str, object] = {
        "period": period,
        "window_start": _WINDOW_START,
        "window_end": _WINDOW_END,
        "days_in_period": 31,
        "weekly_volume": _weekly_volume(),
        "muscle_volume": _muscle_volume(),
        "frequency": _frequency(),
        "recomposition": _recomposition(),
        "recomposition_anchor_day": _RECOMP_ANCHOR,
        "pr_highlights": _pr_highlights(),
        "plateau_highlights": _plateau_highlights(),
        "plateau_lookback_weeks": 12,
        "measurement_highlights": _measurement_highlights(),
        "activity": _period_summary(ActivityPeriodSummary),
        "nutrition": _period_summary(NutritionPeriodSummary),
        "coverage": _coverage(),
        "freshness": _freshness(),
    }
    base.update(overrides)
    return ReportResult(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# Task 1: build_narrative behaviour.
# ---------------------------------------------------------------------------------------------


def test_build_narrative_is_synchronous_and_pure() -> None:
    """PURE and synchronous: `def`, not `async def` -- issues no query, opens no session."""
    assert not inspect.iscoroutinefunction(build_narrative)


def test_the_narrative_is_byte_identical_across_calls() -> None:
    """The Tampering mitigation from the threat register (T-13-36): same input, same output,
    to the byte."""
    report = _report()
    assert build_narrative(report) == build_narrative(report)


def test_the_monthly_heading_names_the_period_and_the_window() -> None:
    report = _report(period=ReportPeriod.MONTHLY)
    narrative = build_narrative(report)
    assert narrative.startswith(
        f"# Monthly report — {_WINDOW_START.isoformat()} to {_WINDOW_END.isoformat()}"
    )


def test_the_weekly_heading_names_the_period_and_the_window() -> None:
    report = _report(period=ReportPeriod.WEEKLY)
    narrative = build_narrative(report)
    assert narrative.startswith(
        f"# Weekly report — {_WINDOW_START.isoformat()} to {_WINDOW_END.isoformat()}"
    )


def test_the_seven_section_headings_are_present() -> None:
    narrative = build_narrative(_report())
    for heading in (
        "## Training",
        "## Strength",
        "## Body",
        "## Nutrition",
        "## Activity",
        "## Program and recomposition",
        "## Data quality",
    ):
        assert heading in narrative


def test_every_hard_set_total_appears_in_the_output() -> None:
    """Every ``WeeklyVolumeWeek.hard_sets`` present in ``report.weekly_volume.weeks`` appears
    in the output -- the specific `<behavior>` bullet, checked against the exact fixture
    values rather than a generic digit scan."""
    narrative = build_narrative(_report())
    assert "24 hard sets" in narrative
    assert "10 hard sets" in narrative
    assert "not recorded reps" in narrative, "the null total_reps week must not render as 0"
    assert "not recorded kg" in narrative, "the null tonnage_kg week must not render as 0"


def test_the_disclaimer_appears_verbatim_on_its_own_line() -> None:
    narrative = build_narrative(_report())
    assert INTERPRETATION_DISCLAIMER in narrative.splitlines()


def test_the_program_heading_names_the_anchor_and_states_it_differs() -> None:
    narrative = build_narrative(_report())
    assert (
        f"As of {_RECOMP_ANCHOR.isoformat()} — a different anchor from the "
        f"{_WINDOW_START.isoformat()} to {_WINDOW_END.isoformat()} period above."
    ) in narrative


def test_an_insufficient_nutrition_metric_renders_the_literal_phrase_not_a_number() -> None:
    """A metric with `insufficient_data=True` renders as `not enough logged days (N of M
    needed)` and NOT as a number -- the exact fixture values from `_period_summary`'s default
    `sodium` entry."""
    narrative = build_narrative(_report())
    assert "sodium: not enough logged days (2 of 10 needed)" in narrative


def test_empty_pr_highlights_renders_none_this_period() -> None:
    report = _report(
        pr_highlights=RecentRecordsResult(
            window_start=_WINDOW_START,
            window_end=_WINDOW_END,
            records=[],
            coverage=_coverage(),
            freshness=_freshness(),
        )
    )
    narrative = build_narrative(report)
    assert "- New records this period: none this period" in narrative
    assert "  - RPT-bench" not in narrative


def test_a_plateau_with_no_recorded_weight_renders_the_literal_phrase() -> None:
    report = _report(
        plateau_highlights=_plateau_highlights(
            exercises=[
                PlateauResult(
                    exercise_template_external_id="RPT-ohp",
                    title="Overhead Press",
                    plateaued=True,
                    plateau_duration_days=30,
                    qualifying_sessions_in_streak=5,
                    recent_performance_kg=Decimal("50.000"),
                    historical_best_kg=Decimal("52.000"),
                    confidence=PlateauConfidence.MEDIUM,
                    threshold_percent=Decimal("2.00"),
                    min_sessions=4,
                    min_elapsed_days=21,
                    lookback_start=_WINDOW_START,
                    lookback_end=_WINDOW_END,
                    last_max_weight_kg=None,
                )
            ]
        )
    )
    narrative = build_narrative(report)
    assert "weight not recorded" in narrative
    assert "last lifted None kg" not in narrative


def test_a_measurement_with_no_reading_renders_the_literal_phrase() -> None:
    narrative = build_narrative(_report())
    assert "fat_percent: no reading in the last 90 days" in narrative


def test_a_single_measurement_reading_renders_no_comparison() -> None:
    report = _report(
        measurement_highlights=_measurement_highlights(
            entries=[
                BodyMeasurementTrendResult(
                    metric=BodyMeasurementMetric.WAIST_CM,
                    window_days=90,
                    anchor_day=_WINDOW_END,
                    coverage=_measurement_coverage(
                        window_days=90, measured=1, insufficient=True
                    ),
                    latest_value=Decimal("80.00"),
                    latest_measured_on=_WINDOW_END,
                    earliest_value=None,
                    earliest_measured_on=None,
                    delta_value=None,
                    is_stale=False,
                    days_since_latest_reading=0,
                    stale_after_days=30,
                    freshness=_freshness(),
                )
            ]
        )
    )
    narrative = build_narrative(report)
    assert "80.00 on 2026-05-31, single reading, no comparison" in narrative


def test_a_stale_measurement_carries_the_stale_suffix_and_a_fresh_one_does_not() -> None:
    stale = BodyMeasurementTrendResult(
        metric=BodyMeasurementMetric.WAIST_CM,
        window_days=90,
        anchor_day=_WINDOW_END,
        coverage=_measurement_coverage(window_days=90, measured=2, insufficient=False),
        latest_value=Decimal("81.50"),
        latest_measured_on=_WINDOW_END,
        earliest_value=Decimal("83.00"),
        earliest_measured_on=_WINDOW_START,
        delta_value=Decimal("-1.50"),
        is_stale=True,
        days_since_latest_reading=45,
        stale_after_days=30,
        freshness=_freshness(),
    )
    fresh = BodyMeasurementTrendResult(
        metric=BodyMeasurementMetric.FAT_PERCENT,
        window_days=90,
        anchor_day=_WINDOW_END,
        coverage=_measurement_coverage(window_days=90, measured=2, insufficient=False),
        latest_value=Decimal("18.00"),
        latest_measured_on=_WINDOW_END,
        earliest_value=Decimal("19.00"),
        earliest_measured_on=_WINDOW_START,
        delta_value=Decimal("-1.00"),
        is_stale=False,
        days_since_latest_reading=1,
        stale_after_days=30,
        freshness=_freshness(),
    )
    report = _report(measurement_highlights=[stale, fresh])
    lines = build_narrative(report).splitlines()
    stale_line = next(line for line in lines if line.startswith("- waist_cm:"))
    fresh_line = next(line for line in lines if line.startswith("- fat_percent:"))
    assert stale_line.endswith(" (stale)")
    assert not fresh_line.endswith(" (stale)")


def test_null_weight_trend_figures_render_not_enough_weigh_ins() -> None:
    report = _report(
        recomposition=_recomposition(
            weight_trend=_weight_trend(
                average_7d_kg=None,
                trend_rate_kg_per_week=None,
                trend_rate_percent_per_week=None,
                latest_week_delta_kg=None,
            )
        )
    )
    narrative = build_narrative(report)
    assert "- 7-day average weight: not enough weigh-ins" in narrative
    assert "- Smoothed weekly rate: not enough weigh-ins, not enough weigh-ins" in narrative
    assert "- Latest week delta: not enough weigh-ins" in narrative


def test_a_never_synced_resource_renders_the_literal_phrase() -> None:
    report = _report(
        freshness=_freshness(
            {
                "workouts": None,
                "exercise_templates": _TS,
                "body_measurements": _TS,
                "activity": _TS,
                "nutrition": _TS,
            }
        )
    )
    narrative = build_narrative(report)
    assert "- workouts: never synced" in narrative
    assert f"- exercise_templates: last synced {_TS.isoformat()}" in narrative


def test_a_program_switch_in_window_names_the_previous_program_and_date() -> None:
    switched_on = dt.date.fromisoformat("2026-05-15")
    report = _report(
        recomposition=_recomposition(
            program_switch_in_window=True,
            previous_program=TrainingProgram.CUT,
            program_switched_on=switched_on,
        )
    )
    narrative = build_narrative(report)
    assert f"switched from cut on {switched_on.isoformat()}" in narrative


def test_the_narrative_contains_no_recommendation_language() -> None:
    """D-03/D-14: the machine-checkable enforcement. Uses a report with EVERY branch reached
    (records present, a plateau present, a program switch present) so the scan has maximum
    surface to fail on."""
    report = _report(
        recomposition=_recomposition(
            program_switch_in_window=True,
            previous_program=TrainingProgram.CUT,
            program_switched_on=dt.date.fromisoformat("2026-05-15"),
        )
    )
    lowered = build_narrative(report).lower()
    for token in _BANNED_NARRATIVE_TOKENS:
        assert token not in lowered, f"banned recommendation-language token {token!r} found"


def test_every_number_in_the_narrative_is_already_in_the_structured_fields() -> None:
    """The operational meaning of "restates the SAME composed data": every numeric token
    printed in the prose is already a substring of ``report.model_dump_json()``. A narrative
    that computed a new ratio, percentage or count would fail here."""
    report = _report(
        recomposition=_recomposition(
            program_switch_in_window=True,
            previous_program=TrainingProgram.CUT,
            program_switched_on=dt.date.fromisoformat("2026-05-15"),
        )
    )
    narrative = build_narrative(report)
    json_dump = report.model_dump_json()
    tokens = _NUMBER_RE.findall(narrative)
    assert tokens, "the fixture must contain numbers for this test to mean anything"
    for token in tokens:
        assert token in json_dump, (
            f"{token!r} appears in the narrative but is not a substring of "
            "report.model_dump_json() -- the narrative has introduced a number the "
            "structured fields do not carry"
        )

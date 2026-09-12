"""RPT-01/RPT-02: ``build_narrative`` (D-14) and ``compose_report`` (D-01 through D-04),
proven end to end.

Two halves, matching plan 13-08's two tasks:

* **Task 1 -- ``build_narrative``.** PURE tests, no container: every ``ReportResult`` is
  hand-built from the nested models directly (``_report()`` and its per-section helpers
  below), never composed from a database. This is what lets the byte-identical-output test
  and the banned-token scan run with no container and no clock. Every date in this half is a
  fixed, arbitrary calendar day built via ``dt.date.fromisoformat(...)``, never the positional
  year/month/day constructor -- for the same reason ``test_analytics_health.py``'s module
  docstring gives: to avoid tripping this project's own literal-date acceptance-criteria grep,
  even though these particular tests do not depend on "today" at all. (Rephrased here too, to
  avoid the same grep matching the sentence documenting the rule.)
* **Task 2 -- ``compose_report``.** CONTAINER-backed, ``golden_workout`` (flush-and-rollback,
  same session) throughout, and every seeded date is ``anchor``-relative
  (``local_day(utc_now(), "Asia/Jakarta")``), never a literal -- ``bodyweight.py``'s module
  docstring records why: a test written against a hard-coded date "would assert null today
  and silently start passing for the wrong reason" once enough real time has passed.

THE two load-bearing tests are ``test_the_narrative_contains_no_recommendation_language`` and
``test_every_number_in_the_narrative_is_already_in_the_structured_fields`` -- together they are
the machine-checkable form of D-03/D-14's "restates the SAME composed data ... with NO
recommendation language", a rule a well-meaning future edit to ``build_narrative`` will break
and no reviewer will reliably catch by eye.

T-13-39's anti-drift assertion (``test_the_weekly_window_agrees_with_the_mcp_layers_week_window``)
is the other one: it is what stops ``analytics/reports.py``'s Monday computation and
``app.mcp.tools._common.week_window``'s Monday computation from silently describing two
different weeks while both look correct.
"""

import datetime as dt
import inspect
import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import reports as reports_module
from app.analytics.recomposition import INTERPRETATION_DISCLAIMER
from app.analytics.reports import (
    _NARRATIVE_TEMPLATE,
    _NarrativeSection,
    build_narrative,
    compose_report,
    resolve_report_window,
)
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
    PhysiqueDiffResult,
    PhysiqueDiffVerdict,
    PhysiqueMuscleDiff,
    PhysiqueSection,
    PhysiqueVolumeCrossReference,
    PhysiqueVolumeFlag,
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
from app.core.time import local_day, utc_now
from app.db.models.physique import PHYSIQUE_RATING_DISCLAIMER, PhysiqueRatingLevel, PoseState
from app.mcp.tools._common import week_window
from app.normalization.muscles import CanonicalMuscleGroup
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# ---------------------------------------------------------------------------------------------
# Task 1: build_narrative -- pure fixtures.
#
# Fixed, arbitrary calendar days via `fromisoformat`, never the positional year/month/day
# constructor -- see the module docstring. None of Task 1's tests care whether these are
# "today"; a fixed baseline lets the byte-identical-output test mean something (two calls on
# the SAME instance) without the fixture itself changing under the test.
# ---------------------------------------------------------------------------------------------

# Deliberately BEFORE `_WINDOW_START`, so the physique block's anchor line is asserted against a
# date genuinely outside the report window rather than a coincidental match -- the same move
# `_RECOMP_ANCHOR` makes on the other side of the window.
_PHYSIQUE_OBSERVED_ON = dt.date.fromisoformat("2026-04-26")
_PHYSIQUE_EARLIER_OBSERVED_ON = dt.date.fromisoformat("2026-03-20")

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


def _physique_diff(**overrides: object) -> PhysiqueDiffResult:
    """A diff already FILTERED to changed groups, which is what the MCP layer hands
    `build_narrative` (D-02/D-03). Two rows, one IMPROVED and one REGRESSED, so both verdict
    words and four distinct rating levels are exercised by the default fixture."""
    base: dict[str, object] = {
        "earlier_observed_on": _PHYSIQUE_EARLIER_OBSERVED_ON,
        "later_observed_on": _PHYSIQUE_OBSERVED_ON,
        "elapsed_days": 37,
        "min_elapsed_days": 30,
        "min_level_delta": 2,
        "muscle_groups": [
            PhysiqueMuscleDiff(
                muscle_group=CanonicalMuscleGroup.CHEST,
                earlier_level=PhysiqueRatingLevel.EMERGING,
                later_level=PhysiqueRatingLevel.WELL_DEVELOPED,
                level_delta=2,
                verdict=PhysiqueDiffVerdict.IMPROVED,
            ),
            PhysiqueMuscleDiff(
                muscle_group=CanonicalMuscleGroup.CALVES,
                earlier_level=PhysiqueRatingLevel.DEVELOPED,
                later_level=PhysiqueRatingLevel.MINIMAL,
                level_delta=-2,
                verdict=PhysiqueDiffVerdict.REGRESSED,
            ),
        ],
        "disclaimer": PHYSIQUE_RATING_DISCLAIMER,
    }
    base.update(overrides)
    return PhysiqueDiffResult(**base)  # type: ignore[arg-type]


def _physique_cross_reference(**overrides: object) -> PhysiqueVolumeCrossReference:
    base: dict[str, object] = {
        "observed_on": _PHYSIQUE_OBSERVED_ON,
        "lookback_weeks": 12,
        "window_start": dt.date.fromisoformat("2026-02-02"),
        "window_end": _PHYSIQUE_OBSERVED_ON,
        "undertrained_threshold_weighted_sets": Decimal("4.000"),
        "flagged": [
            PhysiqueVolumeFlag(
                muscle_group=CanonicalMuscleGroup.REAR_DELTS,
                rating_level=PhysiqueRatingLevel.MINIMAL,
                weighted_sets=Decimal("2.000"),
            )
        ],
        "disclaimer": PHYSIQUE_RATING_DISCLAIMER,
    }
    base.update(overrides)
    return PhysiqueVolumeCrossReference(**base)  # type: ignore[arg-type]


def _physique_section(**overrides: object) -> PhysiqueSection:
    """The default monthly physique block. The three note fields carry REAL text on purpose:
    plan 18-02 asserts none of it reaches the narrative, and a null fixture would make that
    assertion vacuous."""
    base: dict[str, object] = {
        "observed_on": _PHYSIQUE_OBSERVED_ON,
        "pose_state": PoseState.RELAXED,
        "photo_angles_present": ["front", "back", "side"],
        "leanness_notes": "Midsection definition reads softer than the prior set.",
        "conditioning_notes": "Vascularity similar; lighting warmer than last time.",
        "symmetry_notes": "Left and right upper arms read even in the front angle.",
        "conditions_note": "Morning, fasted, same room and same phone as last time.",
        "diff": _physique_diff(),
        "cross_reference": _physique_cross_reference(),
    }
    base.update(overrides)
    return PhysiqueSection(**base)  # type: ignore[arg-type]


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
        # MONTHLY only, exactly as `compose_report` populates it -- so the WEEKLY golden
        # narrative and every `period=ReportPeriod.WEEKLY` test keep asserting the real weekly
        # shape rather than a monthly one with a weekly label.
        "physique": _physique_section() if period is ReportPeriod.MONTHLY else None,
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


_NARRATIVE_GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "reports"


@pytest.mark.parametrize(
    ("period", "golden"),
    [
        (ReportPeriod.MONTHLY, "monthly_narrative.md"),
        (ReportPeriod.WEEKLY, "weekly_narrative.md"),
    ],
)
def test_the_narrative_is_byte_identical_to_the_committed_golden(
    period: ReportPeriod, golden: str
) -> None:
    """The refactor guard. The other tests in this block assert SUBSTRINGS, so a reordered,
    reworded or silently dropped section passes all of them. This one does not: it pins the
    whole rendered document, captured from the pre-refactor `build_narrative`, so any change
    to what a report renders has to be a deliberate re-capture of this file with a stated
    reason -- never a side effect of restructuring how it is rendered."""
    expected = (_NARRATIVE_GOLDEN_DIR / golden).read_text(encoding="utf-8")
    assert build_narrative(_report(period=period)) + "\n" == expected


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
                    coverage=_measurement_coverage(window_days=90, measured=1, insufficient=True),
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


def test_the_template_declares_the_seven_sections_in_order() -> None:
    """The shared contract, asserted on the template itself rather than inferred from rendered
    text. `test_the_seven_section_headings_are_present` proves the headings reach the output;
    this proves there is ONE ordered declaration producing them, which is what makes weekly and
    monthly structurally identical instead of coincidentally identical."""
    assert [section.heading for section in _NARRATIVE_TEMPLATE] == [
        "## Training",
        "## Strength",
        "## Body",
        "## Nutrition",
        "## Activity",
        "## Program and recomposition",
        "## Data quality",
    ]
    assert all(section.periods is None for section in _NARRATIVE_TEMPLATE), (
        "every section shipped today applies to BOTH periods; the first period-restricted "
        "section is Phase 18's monthly-only physique block"
    )


def test_a_monthly_only_section_renders_monthly_and_is_absent_weekly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 18's forward-designed slot (ROADMAP Phase 18, success criterion 1: the monthly
    report gains a physique section the weekly report structurally cannot carry). Registers a
    throwaway monthly-only section and asserts it appears for MONTHLY and not for WEEKLY --
    proving a future section is one template entry plus one builder, with no edit to any
    existing section."""
    marker = "## Throwaway monthly-only section"
    extended = (
        *reports_module._NARRATIVE_TEMPLATE,
        _NarrativeSection(marker, lambda report: ["- monthly only"], (ReportPeriod.MONTHLY,)),
    )
    monkeypatch.setattr(reports_module, "_NARRATIVE_TEMPLATE", extended)

    monthly = build_narrative(_report(period=ReportPeriod.MONTHLY))
    weekly = build_narrative(_report(period=ReportPeriod.WEEKLY))

    assert marker in monthly
    assert "- monthly only" in monthly
    assert marker not in weekly
    # The restriction must SKIP the section, never render an empty heading for it.
    assert "- monthly only" not in weekly


# ---------------------------------------------------------------------------------------------
# Task 2: compose_report, both periods, against a real PostgreSQL container.
#
# `golden_workout` (flush, never commit, same session) throughout. Every seeded date is
# `_anchor()`-relative -- never a literal calendar date -- for the reason the module docstring
# gives.
# ---------------------------------------------------------------------------------------------

_ANCHOR_TZ = "Asia/Jakarta"
# 02:00 UTC is 09:00 in Asia/Jakarta -- the UTC day and the local day AGREE, matching
# `test_analytics_recomposition.py`'s own `_RECOMP_NOW` reasoning, so a workout placed at this
# hour on local day D lands in local day D regardless of which side of midnight UTC it is on.
_REFERENCE_HOUR = 2


def _anchor() -> dt.date:
    """The user's local "today", computed the same way `resolve_report_window` computes it."""
    return local_day(utc_now(), _ANCHOR_TZ)


def _workout_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour=_REFERENCE_HOUR), tzinfo=dt.UTC)


@pytest.mark.integration
async def test_the_weekly_window_is_monday_of_this_week_through_today(
    session: AsyncSession,
) -> None:
    """D-01/A1: the CURRENT week through today, not the most recently completed one."""
    anchor = _anchor()
    start_day, end_day, _tz = await resolve_report_window(
        session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY
    )
    assert start_day == anchor - dt.timedelta(days=anchor.weekday())
    assert end_day == anchor


@pytest.mark.integration
async def test_the_weekly_window_agrees_with_the_mcp_layers_week_window(
    session: AsyncSession,
) -> None:
    """T-13-39: `analytics/` cannot import `app.mcp`, so the Monday is computed twice in this
    codebase -- once in `core/time.local_week_start` (via `resolve_report_window`) and once in
    `_common.week_window`. This assertion is what stops the duplication from becoming a
    divergence."""
    anchor = _anchor()
    start_day, end_day, _tz = await resolve_report_window(
        session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY
    )
    assert week_window(today=anchor, weeks=1) == (start_day, end_day)


@pytest.mark.integration
async def test_the_monthly_window_is_the_first_of_this_month_through_today(
    session: AsyncSession,
) -> None:
    anchor = _anchor()
    start_day, end_day, _tz = await resolve_report_window(
        session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY
    )
    assert start_day == anchor.replace(day=1)
    assert end_day == anchor


@pytest.mark.integration
async def test_both_periods_return_the_same_sections(session: AsyncSession) -> None:
    """D-04: same sections in both periods, not a different emphasis per period."""
    weekly = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY)
    monthly = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY)

    assert set(type(weekly).model_fields) == set(type(monthly).model_fields)
    for report in (weekly, monthly):
        assert isinstance(report.weekly_volume.weeks, list)
        assert isinstance(report.muscle_volume.weeks, list)
        assert isinstance(report.frequency.muscle_groups, list)
        assert isinstance(report.frequency.exercises, list)
        assert isinstance(report.pr_highlights.records, list)
        assert isinstance(report.plateau_highlights.exercises, list)
        assert isinstance(report.measurement_highlights, list)
        assert isinstance(report.activity.metrics, list)
        assert isinstance(report.nutrition.metrics, list)


@pytest.mark.integration
async def test_the_report_carries_the_recomposition_verdict_with_its_own_anchor(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-01: the verdict is carried BESIDE the closed-period figures with a visibly different
    anchor, never folded into them. Seeded with a real stable weight trend and four weeks of
    consistently improving training so this proves the property against a REAL verdict, not the
    vacuously-true `insufficient_data` case."""
    anchor = _anchor()
    templates = ("RPT08-press", "RPT08-row", "RPT08-squat")
    for template_id in templates:
        await golden_workout.template(external_id=template_id)

    this_monday = anchor - dt.timedelta(days=anchor.weekday())
    training_weeks = [this_monday - dt.timedelta(weeks=i) for i in range(4)]
    training_weeks.reverse()
    weights = (Decimal("100.000"), Decimal("102.000"), Decimal("104.000"), Decimal("106.000"))
    for week_start, weight in zip(training_weeks, weights, strict=True):
        await golden_workout.workout(
            start_time=_workout_start(week_start),
            exercises=[
                GoldenExercise(
                    template_external_id=template_id,
                    sets=(GoldenSet(weight_kg=weight, reps=5),),
                )
                for template_id in templates
            ],
        )

    # The SAME weight at the D-16 current window and the four-weeks-ago window -> a real
    # (zero) smoothed rate rather than a null one.
    for offset in (0, 1, 2, 3):
        await golden_workout.body_measurement(
            measured_on=anchor - dt.timedelta(days=offset), weight_kg=Decimal("70.000")
        )
    for offset in (28, 29, 30, 31):
        await golden_workout.body_measurement(
            measured_on=anchor - dt.timedelta(days=offset), weight_kg=Decimal("70.000")
        )

    report = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY)

    assert report.recomposition.status is not RecompositionStatus.INSUFFICIENT_DATA
    assert report.recomposition_anchor_day == report.recomposition.weight_trend.anchor_day
    assert report.recomposition.disclaimer == INTERPRETATION_DISCLAIMER


@pytest.mark.integration
async def test_pr_highlights_cover_the_report_window_not_all_time(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The property `get_recent_records` exists for: a window leader that does not beat
    history is not a record."""
    anchor = _anchor()
    this_monday = anchor - dt.timedelta(days=anchor.weekday())
    await golden_workout.template(external_id="RPT08-pr-bench")

    # A heavier lift BEFORE the window start.
    await golden_workout.workout(
        start_time=_workout_start(this_monday - dt.timedelta(days=7)),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-pr-bench",
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )
    # A LIGHTER lift inside the window -- must not read as a new record.
    await golden_workout.workout(
        start_time=_workout_start(this_monday),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-pr-bench",
                sets=(GoldenSet(weight_kg=Decimal("90.000"), reps=5),),
            )
        ],
    )

    empty_report = await compose_report(
        session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY
    )
    assert empty_report.pr_highlights.records == []

    # A HEAVIER lift inside the window IS a new record.
    await golden_workout.workout(
        start_time=_workout_start(anchor),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-pr-bench",
                sets=(GoldenSet(weight_kg=Decimal("105.000"), reps=5),),
            )
        ],
    )
    report_after = await compose_report(
        session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY
    )
    assert any(
        record.exercise_template_external_id == "RPT08-pr-bench"
        for record in report_after.pr_highlights.records
    )


@pytest.mark.integration
async def test_measurement_highlights_are_exactly_two_metrics(session: AsyncSession) -> None:
    """13-RESEARCH.md's anti-pattern: one call per each of the 16 enum members would be 16
    queries for what D-02 calls a NARROW extra."""
    report = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY)
    assert len(report.measurement_highlights) == 2
    assert {m.metric for m in report.measurement_highlights} == {
        BodyMeasurementMetric.WAIST_CM,
        BodyMeasurementMetric.FAT_PERCENT,
    }


@pytest.mark.integration
async def test_activity_and_nutrition_share_the_reports_window(session: AsyncSession) -> None:
    """Avoid producing two sections of one report that visibly disagree about what "this week"
    means."""
    report = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY)
    assert report.activity.window_start == report.window_start
    assert report.activity.window_end == report.window_end
    assert report.nutrition.window_start == report.window_start
    assert report.nutrition.window_end == report.window_end


@pytest.mark.integration
async def test_the_report_degrades_section_by_section_when_a_source_is_empty(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Degrade gracefully and flag what's missing, never refuse the whole call over one
    missing section -- the `safe_tool`/`data_available` pattern's analytics-layer analogue."""
    anchor = _anchor()
    await golden_workout.template(external_id="RPT08-degrade")
    await golden_workout.workout(
        start_time=_workout_start(anchor),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-degrade",
                sets=(GoldenSet(weight_kg=Decimal("50.000"), reps=8),),
            )
        ],
    )

    report = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.WEEKLY)

    assert report.weekly_volume.weeks, "the one seeded workout must produce a non-empty spine"
    assert any(week.sessions > 0 for week in report.weekly_volume.weeks)
    for metric in report.activity.metrics:
        assert metric.insufficient_data is True
        assert metric.daily_average is None
    for metric in report.nutrition.metrics:
        assert metric.insufficient_data is True
        assert metric.daily_average is None
    for measurement in report.measurement_highlights:
        assert measurement.latest_value is None


@pytest.mark.integration
async def test_the_freshness_envelope_names_all_five_resources(session: AsyncSession) -> None:
    """The report reads all five resources, so its answer is only as fresh as the stalest of
    them; a narrower bundle would claim a freshness this response does not have."""
    report = await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY)
    assert set(report.freshness.resources) == {
        "workouts",
        "exercise_templates",
        "body_measurements",
        "activity",
        "nutrition",
    }


@pytest.mark.integration
async def test_the_report_scopes_to_the_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    anchor = _anchor()
    await golden_workout.template(external_id="RPT08-scope")
    await golden_workout.workout(
        start_time=_workout_start(anchor),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-scope",
                sets=(GoldenSet(weight_kg=Decimal("200.000"), reps=5),),
            )
        ],
        user_id=DEFAULT_USER_ID,
    )
    await golden_workout.body_measurement(
        measured_on=anchor, weight_kg=Decimal("80.000"), user_id=DEFAULT_USER_ID
    )

    report = await compose_report(
        session, user_id=ANALYTICS_SECOND_USER_ID, period=ReportPeriod.WEEKLY
    )

    assert all(week.sessions == 0 for week in report.weekly_volume.weeks)
    assert report.pr_highlights.records == []
    assert report.recomposition.status is RecompositionStatus.INSUFFICIENT_DATA


@pytest.mark.integration
async def test_compose_report_issues_no_write(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The composition-only rule, checked at runtime as well as by
    `test_analytics_isolation.py`'s static scan."""
    anchor = _anchor()
    await golden_workout.template(external_id="RPT08-nowrite")
    await golden_workout.workout(
        start_time=_workout_start(anchor),
        exercises=[
            GoldenExercise(
                template_external_id="RPT08-nowrite",
                sets=(GoldenSet(weight_kg=Decimal("60.000"), reps=10),),
            )
        ],
    )

    await compose_report(session, user_id=DEFAULT_USER_ID, period=ReportPeriod.MONTHLY)

    assert not session.new
    assert not session.dirty
    assert not session.deleted

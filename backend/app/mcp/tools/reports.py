"""The composed weekly and monthly reports (RPT-01, RPT-02; MCP-02, MCP-03, MCP-05, MCP-06;
D-01 through D-04, D-14).

Two tools, ONE composer -- ``analytics/reports.py``'s ``compose_report``, called with the
period each tool is named for. Like every other tool here this module owns no arithmetic: each
number was computed by a function under ``app/analytics/`` that already has its own tests, and
the composer itself owns only the WINDOW and the ASSEMBLY.

**What these tools deliberately EXCLUDE, and why.**

*The per-week x per-muscle grid* is rolled to 19 rows by ``roll_up_muscles``, for the same
measured reason ``fitness_get_training_summary`` rolls it up -- composing it verbatim grows with
the window where a rollup does not.

*The per-exercise frequency list* is dropped entirely; ``fitness_get_training_frequency`` is where
it lives.

*The FULL PR and plateau lists* keep their own tools (``fitness_get_personal_records``,
``fitness_get_plateaus``). A report carries HIGHLIGHTS -- capped at ``MAX_REPORT_PR_HIGHLIGHTS``
and ``MAX_REPORT_PLATEAU_HIGHLIGHTS``, with ``was_truncated`` and ``total`` beside each -- because
a coaching answer that cites more than a handful of individual lifts has stopped summarizing.

*Fourteen of the sixteen* ``BodyMeasurementMetric`` columns. ``REPORT_MEASUREMENT_METRICS`` picks
two (``waist_cm``, ``fat_percent``), and ``fitness_get_body_measurement_trend`` answers for the
rest.

*The unchanged and not-comparable muscle groups* are dropped from the monthly report's physique
diff (RPT-04/D-02). The analytics layer keeps all 19; a monthly summary reports the ones that
moved. The weekly report carries no physique section at all -- ``WeeklyReportResponse`` has no
such field, which is a structural absence rather than an omission by convention.

**What these tools COST.**

``compose_report`` issues roughly nine analytics calls, one of which
(``get_recomposition_status``) internally runs three more over its own fixed 12-week lookback --
so the two report tools carry the heaviest single-transaction cost in the system after
``fitness_compare_periods``. All inside ONE read-only transaction, which is correct rather than
merely convenient: one consistent snapshot, so this week's volume and the recomposition verdict
cannot describe two different databases. Claude's connector budgets are 10 s for discovery and
30 s for a call; if this ever needs optimizing, the recomposition call is the half that does the
most work.

**Neither tool takes a parameter.** The period is fixed by which tool was called (D-04). Do not
add a ``weeks`` argument for symmetry -- the composer derives its window from a calendar boundary
and the user's timezone, and a caller-supplied window would reintroduce exactly the two-anchor
confusion D-01 exists to prevent.

**The disclaimer travels verbatim** (T-06-09), and the freshness envelope comes from
``ReportResult.freshness`` -- the five-resource report bundle -- never from an embedded result's
narrower one (T-06-14, one level up from ``summary.py``'s version of the same trap).
"""

from typing import Any

import structlog
from mcp.server.mcpserver import Context

from app.analytics.reports import build_narrative, compose_report
from app.analytics.schemas import (
    PhysiqueDiffVerdict,
    PhysiqueSection,
    ReportPeriod,
    ReportResult,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_REPORT_PLATEAU_HIGHLIGHTS,
    MAX_REPORT_PR_HIGHLIGHTS,
    read_only_session,
    resolve_user_id,
    safe_tool,
    truncate,
)
from app.mcp.tools.schemas import MonthlyReportResponse, SummaryVolumeWeek, WeeklyReportResponse
from app.mcp.tools.volume import roll_up_muscles

log = structlog.get_logger()


def _report_body_fields(report: ReportResult) -> dict[str, Any]:
    """The projection both responses share. ONE implementation, so D-04's "same sections in
    both" cannot drift into two.
    """
    # PR highlights: the report's own closed window, newest-first, capped at
    # MAX_REPORT_PR_HIGHLIGHTS.
    pr_highlights, pr_highlights_truncated, pr_highlights_total = truncate(
        report.pr_highlights.records, MAX_REPORT_PR_HIGHLIGHTS
    )

    # Plateau highlights: filtered to PLATEAUED exercises FIRST, then capped. So
    # `plateau_highlights_total` is the number of plateaued exercises, not the number scanned --
    # the two are different claims, and the wrong one reads as "you have 30 stalled lifts" for
    # what is really "of the 30 exercises analysed, this many are stuck".
    plateaued = [exercise for exercise in report.plateau_highlights.exercises if exercise.plateaued]
    (
        plateau_highlights,
        plateau_highlights_truncated,
        plateau_highlights_total,
    ) = truncate(plateaued, MAX_REPORT_PLATEAU_HIGHLIGHTS)

    recomposition = report.recomposition

    return {
        "data_available": True,
        "period": report.period,
        "window_start": report.window_start,
        "window_end": report.window_end,
        "days_in_period": report.days_in_period,
        "sessions_per_week": report.frequency.sessions_per_week,
        # `tonnage_sets` is dropped from each row on purpose, exactly as `summary.py` drops it:
        # it is the operand-presence denominator for `tonnage_kg`, which matters when auditing a
        # number and not when summarizing one.
        "volume_by_week": [
            SummaryVolumeWeek(
                week_start=week.week_start,
                sessions=week.sessions,
                hard_sets=week.hard_sets,
                total_reps=week.total_reps,
                tonnage_kg=week.tonnage_kg,
            )
            for week in report.weekly_volume.weeks
        ],
        # The SAME fold `fitness_get_muscle_group_volume` and `fitness_get_training_summary` use,
        # imported rather than re-derived, so the three tools can never disagree about a muscle's
        # set count.
        "muscles": roll_up_muscles(report.muscle_volume, report.frequency),
        "recomposition_status": recomposition.status,
        # VERBATIM (T-06-09).
        "recomposition_disclaimer": recomposition.disclaimer,
        "recomposition_anchor_day": report.recomposition_anchor_day,
        # Reported BESIDE the status, not folded into it, for the same reason BODY-02 pairs them:
        # a real disagreement between the label and the signal is exactly what Claude needs to see.
        "progression_signal": recomposition.progression_signal.signal,
        "progression_verdict": recomposition.progression_signal.verdict,
        "weight_trend_rate_percent_per_week": (
            recomposition.weight_trend.trend_rate_percent_per_week
        ),
        "average_7d_kg": recomposition.weight_trend.average_7d_kg,
        # Program context, also read off `recomposition` -- Phase 12 already resolved it inside
        # that same call, so re-querying here would be a second answer to a question already
        # answered in this transaction.
        "active_program": recomposition.active_program,
        "program_started_on": recomposition.program_started_on,
        "program_switch_in_window": recomposition.program_switch_in_window,
        "previous_program": recomposition.previous_program,
        "program_switched_on": recomposition.program_switched_on,
        "pr_highlights": pr_highlights,
        "pr_highlights_truncated": pr_highlights_truncated,
        "pr_highlights_total": pr_highlights_total,
        "plateau_highlights": plateau_highlights,
        "plateau_highlights_truncated": plateau_highlights_truncated,
        "plateau_highlights_total": plateau_highlights_total,
        "plateau_lookback_weeks": report.plateau_lookback_weeks,
        "measurements": report.measurement_highlights,
        "activity": report.activity,
        "nutrition": report.nutrition,
        "coverage": report.coverage,
        "freshness": report.freshness,
    }


# D-02: the two verdicts a monthly summary reports. `UNCHANGED` and `NOT_COMPARABLE` are
# deliberately absent -- the report layer already made this exact narrowing once, for plateaus
# (`plateaued=True` before the cap), and for the same reason: of the 19 groups analysed, these
# are the ones that moved.
_REPORT_PHYSIQUE_VERDICTS: tuple[PhysiqueDiffVerdict, ...] = (
    PhysiqueDiffVerdict.IMPROVED,
    PhysiqueDiffVerdict.REGRESSED,
)


def _filtered_physique(report: ReportResult) -> PhysiqueSection | None:
    """D-02/D-03: the presentation narrowing, applied HERE and not in `compose_report`.

    `ReportResult`'s own docstring states the rule this follows -- "Lists are UNCAPPED here",
    and a silent truncation inside the analytics layer would be a wrong answer. So
    `report.physique.diff` arrives with its gap-free 19-row spine intact and leaves here with
    only the rows that moved.

    NO cap and no `was_truncated`/`total` pair (D-06): the population is a fixed, published 19
    (`CanonicalMuscleGroup`), and `cross_reference.flagged` is the intersection of two narrow
    subsets of it. A truncation apparatus for a list that cannot exceed 19 would be ceremony
    with no failure mode behind it.

    Returns ONE object, which `fitness_get_monthly_report` then uses for BOTH the response
    field and the `capped_report` copy handed to `build_narrative`. That is what makes the
    WR-01 bug class -- the narrative and the JSON field beside it silently disagreeing --
    structurally unreachable here rather than merely tested against.
    """
    physique = report.physique
    if physique is None:
        return None
    diff = physique.diff
    if diff is None:
        # D-12: exactly one observation. Nothing to narrow; the narrative renders its own
        # explicit "first recorded observation" line off this same None.
        return physique
    changed = [row for row in diff.muscle_groups if row.verdict in _REPORT_PHYSIQUE_VERDICTS]
    return physique.model_copy(update={"diff": diff.model_copy(update={"muscle_groups": changed})})


def _degraded_body_fields() -> dict[str, Any]:
    """Every ``_ReportBody`` field, emptied rather than partially filled (T-06-01).

    A response carrying a real muscle rollup beside a missing verdict reads as "no recomposition
    signal" rather than as "this call failed" -- ``data_available=False`` is the only honest claim
    available here, matching ``summary.py``'s ``_degraded_summary``.
    """
    return {
        "data_available": False,
        "period": None,
        "window_start": None,
        "window_end": None,
        "days_in_period": None,
        "sessions_per_week": None,
        "volume_by_week": [],
        "muscles": [],
        "recomposition_status": None,
        "recomposition_disclaimer": None,
        "recomposition_anchor_day": None,
        "progression_signal": None,
        "progression_verdict": None,
        "weight_trend_rate_percent_per_week": None,
        "average_7d_kg": None,
        "active_program": None,
        "program_started_on": None,
        "program_switch_in_window": None,
        "previous_program": None,
        "program_switched_on": None,
        "pr_highlights": [],
        "pr_highlights_truncated": False,
        "pr_highlights_total": 0,
        "plateau_highlights": [],
        "plateau_highlights_truncated": False,
        "plateau_highlights_total": 0,
        "plateau_lookback_weeks": None,
        "measurements": [],
        "activity": None,
        "nutrition": None,
        "coverage": None,
        "freshness": None,
    }


def _degraded_weekly() -> WeeklyReportResponse:
    return WeeklyReportResponse(**_degraded_body_fields())


def _degraded_monthly() -> MonthlyReportResponse:
    # `physique=None` sits beside `narrative=None` rather than inside the SHARED
    # `_degraded_body_fields()` dict, for the same reason `narrative` does: the weekly response
    # type has neither field (D-14, criterion 1).
    return MonthlyReportResponse(**_degraded_body_fields(), narrative=None, physique=None)


@safe_tool(degraded=_degraded_weekly)
async def fitness_get_weekly_report(ctx: Context[AppContext]) -> WeeklyReportResponse:
    """This week's complete picture in one call: Monday-to-today training volume and per-muscle
    work, personal records set this week, exercises that have stalled, waist and body-fat
    movement, nutrition and activity averages, the active training program, and the current
    recomposition verdict with its disclaimer.
    """
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        report = await compose_report(session, user_id=user, period=ReportPeriod.WEEKLY)
    return WeeklyReportResponse(**_report_body_fields(report))


@safe_tool(degraded=_degraded_monthly)
async def fitness_get_monthly_report(ctx: Context[AppContext]) -> MonthlyReportResponse:
    """This calendar month's complete picture in one call -- the same sections as the weekly
    report over a longer window -- plus a markdown narrative restating the same figures as prose.
    """
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        report = await compose_report(session, user_id=user, period=ReportPeriod.MONTHLY)
    # OUTSIDE the `async with`: `build_narrative` is pure and synchronous, and holding a
    # transaction open across string formatting would be a transaction held for no reason.
    body_fields = _report_body_fields(report)
    # D-02/D-03: narrowed ONCE, here, and used twice below -- so the `physique` field the
    # response carries and the one `build_narrative` narrates are literally the same object.
    physique = _filtered_physique(report)
    # `build_narrative` must narrate the SAME capped/filtered lists the structured fields above
    # carry, never the raw `report`. Passing the uncapped report here would let the narrative --
    # the one field `docs/coaching-instructions.md` tells Claude to quote directly -- silently
    # outgrow the MAX_REPORT_PR_HIGHLIGHTS/MAX_REPORT_PLATEAU_HIGHLIGHTS caps the JSON fields
    # above already enforce, and (since plan 18-03) would let it narrate 19 physique rows beside
    # a JSON field carrying only the ones that moved.
    capped_report = report.model_copy(
        update={
            "pr_highlights": report.pr_highlights.model_copy(
                update={"records": body_fields["pr_highlights"]}
            ),
            "plateau_highlights": report.plateau_highlights.model_copy(
                update={"exercises": body_fields["plateau_highlights"]}
            ),
            "physique": physique,
        }
    )
    return MonthlyReportResponse(
        **body_fields, narrative=build_narrative(capped_report), physique=physique
    )

"""Two-period comparison (CMP-01). Counts and sums per week; levels never divided.

Structurally "call the Phase 4 machinery twice and diff", which is exactly why
``frequency.sessions_per_week`` was made public in Phase 4 -- its docstring names CMP-01 as the
reason. Importing it is the pattern; re-deriving the quotient inline is the anti-pattern.

**Per-week normalization applies to COUNTS AND SUMS ONLY.** A maximum, an average and an
already-per-week rate are all destroyed by dividing by weeks. A best e1RM quartered by a
four-week window is not a smaller misleading delta, it is a bigger one: it is a quarter of the
number the progression endpoint reports for the same exercise in the same window, and it still
looks like a weight. That is why rates and levels are two DIFFERENT TYPES rather than one type
with a flag a reviewer has to check -- the numbers still look plausible under the wrong rule,
which is why this has to be structural rather than reviewed.

**Neither period is snapped to whole weeks.** Phase 4's D-03 carries forward unchanged: the raw
requested range IS the window and the rate divides by its TRUE length. Snapping is what weekly
volume does, because its buckets must be comparable to one another; a rate has no such
requirement, and a 4-week period compared against a 23-day period must both be expressed per week
rather than both widened.

**A zero baseline yields a null percent delta.** An exercise trained in period B and not in period
A is a real and common case. Raising would make a normal comparison an error; reporting a
non-finite quotient would put an unserialisable magnitude on the wire; substituting zero would
claim "no change" for the biggest change there is.

**Per-muscle rows are opt-in.** 16 muscle groups x 3 figures x 2 periods plus deltas is 96+
numbers, against MCP-03's "compact, structured JSON". And never present a cross-muscle total: one
template maps to up to 9 muscle groups, so a sum across groups is several times the truth.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER
owns the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.frequency import sessions_per_week
from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,
    build_coverage,
    build_freshness,
)
from app.analytics.progression import best_set_per_day
from app.analytics.rollup import (
    AnalyticsWindow,
    MuscleBucket,
    SetRollupRow,
    fold_window_by_muscle,
    fold_window_by_template,
    qualifying_set_rows,
    resolve_row_muscles,
    resolve_window,
    weekly_set_rows,
)
from app.analytics.schemas import (
    ComparisonLevel,
    ComparisonRate,
    CoverageMetadata,
    MuscleGroupComparison,
    PeriodComparisonResult,
    PeriodSummary,
)
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole

# One quantum per quantity, at the boundary. Matches `frequency._RATE_QUANTUM` so a sessions rate
# CMP-01 reports and the same rate VOL-03 reports are byte-identical rather than nearly equal.
_PER_WEEK_QUANTUM = Decimal("0.01")
_PERCENT_QUANTUM = Decimal("0.01")
_LEVEL_QUANTUM = Decimal("0.001")

# The divisor `sessions_per_week` uses, spelled once. Seven days is one week exactly, and
# `Decimal` rather than `int` so the quotient never touches binary floating point.
_DAYS_PER_WEEK = Decimal(7)

_HUNDRED = Decimal(100)


def _per_week(value: Decimal, days: int) -> Decimal:
    """``sessions_per_week`` generalised from an int COUNT to a Decimal SUM.

    Deliberately a sibling rather than a replacement: integer session counts still go through
    ``frequency.sessions_per_week`` itself, so the sessions figure CMP-01 reports is the SAME
    figure VOL-03 reports for the same window, not a second implementation that agrees today.
    A test asserts the two agree across a table of inputs, because "two copies eventually
    disagree" is the failure this codebase repeatedly guards against.

    Zero days is a caller bug, not a zero rate. Same message as ``sessions_per_week``'s, and it
    carries no user data because it will be logged.
    """
    if days <= 0:
        raise ValueError("window length must be positive")
    weeks = Decimal(days) / _DAYS_PER_WEEK
    return (value / weeks).quantize(_PER_WEEK_QUANTUM)


def _delta_percent(period_a: Decimal | None, period_b: Decimal | None) -> Decimal | None:
    """``100 * (b - a) / a``, or ``None`` when the baseline is zero or either side is missing.

    ``None``, never zero and never an exception -- see the module docstring. A zero baseline is
    the ordinary case of an exercise that appears in one period and not the other, so it must not
    be an error path, and it must not be reported as "no change".
    """
    if period_a is None or period_b is None or period_a == 0:
        return None
    return (_HUNDRED * (period_b - period_a) / period_a).quantize(_PERCENT_QUANTUM)


def _rate(
    *,
    metric: str,
    period_a: Decimal | None,
    period_b: Decimal | None,
    exercise_template_external_id: str | None = None,
    title: str | None = None,
) -> ComparisonRate:
    """One per-week-normalized comparison row. Callers pass ALREADY-normalized values.

    Normalization happens at the call site, against that period's own ``days``, because the two
    periods have different lengths -- which is the entire point of CMP-01. Doing it inside here
    would need both day counts and would invite passing the wrong one.

    A missing value on either side yields a ``None`` delta rather than a delta against zero:
    "you did not do this exercise" and "you did it zero times per week" read the same in a
    subtraction and only one of them is true.
    """
    delta = None if period_a is None or period_b is None else period_b - period_a
    return ComparisonRate(
        metric=metric,
        exercise_template_external_id=exercise_template_external_id,
        title=title,
        period_a_per_week=period_a,
        period_b_per_week=period_b,
        delta_per_week=delta,
        delta_percent=_delta_percent(period_a, period_b),
    )


def _level(
    *,
    metric: str,
    period_a: Decimal | None,
    period_b: Decimal | None,
    exercise_template_external_id: str | None = None,
    title: str | None = None,
) -> ComparisonLevel:
    """One LEVEL comparison. No division by weeks happens here or at any call site.

    A separate function from ``_rate`` with a separate return type, so "normalize this one too"
    is not a one-word edit a reviewer might wave through. ``ComparisonLevel`` has no per-week
    field at all, which is what makes the wrong thing unrepresentable rather than merely
    discouraged.
    """
    delta = None if period_a is None or period_b is None else period_b - period_a
    return ComparisonLevel(
        metric=metric,
        exercise_template_external_id=exercise_template_external_id,
        title=title,
        period_a_value=period_a,
        period_b_value=period_b,
        delta=delta,
        delta_percent=_delta_percent(period_a, period_b),
    )


def _maybe_per_week(value: Decimal | int | None, days: int) -> Decimal | None:
    """``_per_week``, propagating an ABSENCE as ``None`` rather than as a zero rate.

    "This exercise does not appear in that period at all" and "it appears at zero per week" read
    identically in a subtraction, and only the first lets ``delta_percent`` stay honest. The same
    distinction ``volume.py`` draws between a ``None`` tonnage and a ``Decimal("0.000")`` one.
    """
    return None if value is None else _per_week(Decimal(value), days)


@dataclass(frozen=True, slots=True)
class _PeriodFacts:
    """Everything one period contributes to the comparison. INTERNAL -- never returned.

    Holds the RAW figures, deliberately un-normalized: normalization is per period and against
    that period's own ``window.days``, so baking it in here would make the two periods'
    quantities look interchangeable when the entire point of CMP-01 is that they are not.

    ``tonnage_kg`` is already gated to ``None`` when ``tonnage_sets`` is zero, because the
    ``None``-versus-zero rule is a fact about the period and belongs beside the sum it qualifies
    rather than at each of the places that read it.
    """

    window: AnalyticsWindow
    set_rows: list[SetRollupRow]
    sessions: int
    hard_sets: int
    total_reps: int | None
    tonnage_kg: Decimal | None
    tonnage_sets: int
    template_sessions: dict[str, int]
    best_e1rm: dict[str, Decimal]
    titles: dict[str, str | None]
    coverage: CoverageMetadata


async def _period_facts(
    session: AsyncSession, *, user_id: uuid.UUID, start_day: dt.date, end_day: dt.date
) -> _PeriodFacts:
    """Gather ONE period. Called once per period, by one function, from one place.

    A single function rather than two inlined blocks, so the two periods cannot drift apart --
    the failure mode where period A counts warm-ups and period B does not is completely invisible
    in the output, because both numbers stay plausible and only their difference is wrong.

    The window resolves WITHOUT week snapping (Phase 4's D-03): the raw requested range IS the
    window, and every rate divides by its TRUE length.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=False
    )
    set_rows = await weekly_set_rows(session, user_id=user_id, window=window)

    hard_sets = 0
    total_reps: int | None = None
    tonnage_kg = Decimal(0)
    tonnage_sets = 0
    for row in set_rows:
        hard_sets += row.hard_sets
        if row.total_reps is not None:
            # Stays `None` until some row actually reports reps, so a period of duration-only
            # holds returns `None` rather than a confident zero. The accumulation form is
            # `volume._fold_week_totals`'s, deliberately -- one rule, spelled the same way.
            total_reps = (total_reps or 0) + row.total_reps
        tonnage_sets += row.tonnage_sets
        if row.tonnage_kg is not None:
            # Decimal, never binary floating point: two arithmetically identical period totals
            # must compare equal, or "did my tonnage change?" becomes a coin flip.
            tonnage_kg += row.tonnage_kg

    # len(session_ids), never a sum: one workout containing three hamstring exercises is one
    # session, and summing inflated 14 of 16 muscle groups by up to 4.0x on real data.
    template_sessions = {
        template_id: len(workout_ids)
        for template_id, workout_ids in fold_window_by_template(set_rows).items()
    }

    # The SAME D-04 selection PROG-01 and PROG-02 use. A second "best set" rule here is how the
    # comparison and the progression endpoint would report different numbers for the same
    # exercise and the same window.
    qrows = await qualifying_set_rows(session, user_id=user_id, window=window)
    best_e1rm: dict[str, Decimal] = {}
    for (template_id, _local_day), best in best_set_per_day(qrows).items():
        if best.best_e1rm_kg is None:
            # A day whose sets all failed the e1RM gates still produced a point, but it
            # contributes no LEVEL. Substituting the bare weight lifted would silently mix two
            # incomparable populations -- `estimates.py`'s whole reason for a reason code.
            continue
        incumbent = best_e1rm.get(template_id)
        if incumbent is None or best.best_e1rm_kg > incumbent:
            # Quantized at the boundary in ONE place, for `_PER_WEEK_QUANTUM`'s reason: the
            # level's scale is pinned HERE rather than inherited from whatever produced it, so a
            # future level metric sourced from something other than `estimate_1rm` cannot ship
            # a number no coach reads and no test asserts on stably.
            best_e1rm[template_id] = best.best_e1rm_kg.quantize(_LEVEL_QUANTUM)

    titles: dict[str, str | None] = {}
    for qrow in qrows:
        # Read off the aggregate, never a second query: `qualifying_set_rows` already carries the
        # title from its tenant-scoped template outerjoin, which is exactly why
        # `frequency._template_titles` stays private and is not copied here. `setdefault` so the
        # first row for a template wins and the title cannot flip between rows.
        titles.setdefault(qrow.template_external_id, qrow.title)

    coverage = await build_coverage(
        session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
    )
    return _PeriodFacts(
        window=window,
        set_rows=set_rows,
        # Reused, never re-implemented: this is the same distinct-workout count VOL-01 reports
        # for the same window, so the two answers cannot disagree about how much was trained.
        sessions=coverage.sessions_in_window,
        hard_sets=hard_sets,
        total_reps=total_reps,
        # None, never 0: "we could not compute tonnage for this period" is a different fact from
        # "tonnage was zero", and a real bodyweight period is the second one.
        tonnage_kg=tonnage_kg if tonnage_sets else None,
        tonnage_sets=tonnage_sets,
        template_sessions=template_sessions,
        best_e1rm=best_e1rm,
        titles=titles,
        coverage=coverage,
    )


def _title(facts_a: _PeriodFacts, facts_b: _PeriodFacts, template_id: str) -> str | None:
    """The exercise title from whichever period saw it, period A first.

    A template can appear in only one of the two periods -- that is the ordinary "you started
    doing this exercise" case -- so falling back to period B is what stops the row being labelled
    with nothing at all.
    """
    title = facts_a.titles.get(template_id)
    return title if title is not None else facts_b.titles.get(template_id)


def _muscle_comparison(
    *,
    muscle_group: CanonicalMuscleGroup,
    bucket_a: MuscleBucket | None,
    bucket_b: MuscleBucket | None,
    days_a: int,
    days_b: int,
) -> MuscleGroupComparison:
    """One muscle group's three per-week-normalized set COUNTS.

    Both day counts are required parameters and neither has a default: normalizing both sides
    against one period's length is the precise bug CMP-01 exists to prevent, and it would produce
    a delta that looks like training change and is really calendar arithmetic.

    Never sum these across muscle groups. One template maps to up to 9 groups, so a cross-muscle
    total is several times the truth and it looks entirely plausible.
    """
    return MuscleGroupComparison(
        muscle_group=muscle_group,
        direct_sets=_rate(
            metric="direct_sets",
            period_a=_maybe_per_week(None if bucket_a is None else bucket_a.direct_sets, days_a),
            period_b=_maybe_per_week(None if bucket_b is None else bucket_b.direct_sets, days_b),
        ),
        indirect_sets=_rate(
            metric="indirect_sets",
            period_a=_maybe_per_week(None if bucket_a is None else bucket_a.indirect_sets, days_a),
            period_b=_maybe_per_week(None if bucket_b is None else bucket_b.indirect_sets, days_b),
        ),
        weighted_sets=_rate(
            metric="weighted_sets",
            period_a=_maybe_per_week(None if bucket_a is None else bucket_a.weighted_sets, days_a),
            period_b=_maybe_per_week(None if bucket_b is None else bucket_b.weighted_sets, days_b),
        ),
    )


async def _muscle_group_rows(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    facts_a: _PeriodFacts,
    facts_b: _PeriodFacts,
    weights: Mapping[MuscleRole, Decimal] | None,
) -> list[MuscleGroupComparison]:
    """The opt-in per-muscle expansion, sorted by ``muscle_group.value``.

    ``resolve_row_muscles`` delegates to ``effective_muscles_bulk``. Never join the muscle-mapping
    tables here: the override rule is REPLACEMENT, not merge, and a join is byte-identical today
    only because the override table has zero rows. ``test_analytics_isolation.py`` bans the ORM
    class names outright, which is the only defence that survives a reviewer.
    """
    resolved_a = await resolve_row_muscles(session, user_id=user_id, rows=facts_a.set_rows)
    resolved_b = await resolve_row_muscles(session, user_id=user_id, rows=facts_b.set_rows)
    buckets_a = fold_window_by_muscle(facts_a.set_rows, resolved_a, weights)
    buckets_b = fold_window_by_muscle(facts_b.set_rows, resolved_b, weights)
    return [
        _muscle_comparison(
            muscle_group=muscle_group,
            bucket_a=buckets_a.get(muscle_group),
            bucket_b=buckets_b.get(muscle_group),
            days_a=facts_a.window.days,
            days_b=facts_b.window.days,
        )
        # Sorted by a STATED key, never dict-iteration order -- Phase 6 will diff these between
        # runs, and a flaky ordering is a flaky test.
        for muscle_group in sorted(set(buckets_a) | set(buckets_b), key=lambda group: group.value)
    ]


def _period_summary(facts: _PeriodFacts) -> PeriodSummary:
    """One period's identity and its OWN coverage block.

    Coverage is per period rather than per response: a comparison where one period holds a single
    session is not a comparison, and one response-level block cannot express that.
    """
    return PeriodSummary(
        start_day=facts.window.start_day,
        end_day=facts.window.end_day,
        days=facts.window.days,
        coverage=facts.coverage,
    )


async def compare_periods(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    period_a_start: dt.date,
    period_a_end: dt.date,
    period_b_start: dt.date,
    period_b_end: dt.date,
    include_muscle_groups: bool = False,
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> PeriodComparisonResult:
    """CMP-01: two periods, counts and sums per week, levels compared as levels.

    Period A is the BASELINE and period B is the comparison, so every delta reads "B minus A" and
    a positive number means "more recently". Callers asking "last 4 weeks vs the previous 4"
    therefore pass the OLDER range as A. Stated here because the opposite convention is equally
    defensible and silently inverts every sign.

    Session positional, everything else keyword-only, ``user_id`` with no default (ASVS V4). The
    caller owns the transaction; nothing here writes.

    Both windows resolve WITHOUT week snapping -- Phase 4's D-03. Widening a 23-day period to
    whole weeks would divide by a length the caller never asked for.
    """
    facts_a = await _period_facts(
        session, user_id=user_id, start_day=period_a_start, end_day=period_a_end
    )
    facts_b = await _period_facts(
        session, user_id=user_id, start_day=period_b_start, end_day=period_b_end
    )

    # Each figure normalized against its OWN period's window.days. The `sessions` row goes
    # through `frequency.sessions_per_week` itself rather than the Decimal sibling, so the rate
    # CMP-01 reports and the rate VOL-03 reports for the same window are byte-identical.
    totals = [
        _rate(
            metric="sessions",
            period_a=sessions_per_week(facts_a.sessions, facts_a.window.days),
            period_b=sessions_per_week(facts_b.sessions, facts_b.window.days),
        ),
        _rate(
            metric="hard_sets",
            period_a=_per_week(Decimal(facts_a.hard_sets), facts_a.window.days),
            period_b=_per_week(Decimal(facts_b.hard_sets), facts_b.window.days),
        ),
        _rate(
            metric="total_reps",
            period_a=_maybe_per_week(facts_a.total_reps, facts_a.window.days),
            period_b=_maybe_per_week(facts_b.total_reps, facts_b.window.days),
        ),
        _rate(
            # None, never 0: "we could not compute tonnage for this period" is a different fact
            # from "tonnage was zero", and `_PeriodFacts` has already applied that gate.
            metric="tonnage_kg",
            period_a=_maybe_per_week(facts_a.tonnage_kg, facts_a.window.days),
            period_b=_maybe_per_week(facts_b.tonnage_kg, facts_b.window.days),
        ),
    ]
    totals.sort(key=lambda row: row.metric)

    # Every template appearing in EITHER period. Absent means None, not zero per week: "you did
    # not do this exercise" and "you did it zero times per week" read the same but only one of
    # them lets `delta_percent` stay honest.
    template_ids = sorted(set(facts_a.template_sessions) | set(facts_b.template_sessions))
    exercises = [
        _rate(
            metric="sessions",
            exercise_template_external_id=template_id,
            title=_title(facts_a, facts_b, template_id),
            period_a=_maybe_per_week(
                facts_a.template_sessions.get(template_id), facts_a.window.days
            ),
            period_b=_maybe_per_week(
                facts_b.template_sessions.get(template_id), facts_b.window.days
            ),
        )
        for template_id in template_ids
    ]

    exercise_levels = [
        # NEVER divided by weeks. A best e1RM quartered by a four-week window is a quarter of the
        # number `get_exercise_progression` reports for the same exercise in the same window, and
        # it still looks like a weight -- Pitfall 8.
        _level(
            metric="best_estimated_1rm_kg",
            exercise_template_external_id=template_id,
            title=_title(facts_a, facts_b, template_id),
            period_a=facts_a.best_e1rm.get(template_id),
            period_b=facts_b.best_e1rm.get(template_id),
        )
        for template_id in template_ids
    ]

    # 16 muscle groups x 3 figures x 2 periods plus deltas is 96+ numbers against MCP-03's
    # "compact, structured JSON", so Phase 6 opts in when it wants them.
    muscle_groups = (
        await _muscle_group_rows(
            session, user_id=user_id, facts_a=facts_a, facts_b=facts_b, weights=weights
        )
        if include_muscle_groups
        else []
    )

    return PeriodComparisonResult(
        period_a=_period_summary(facts_a),
        period_b=_period_summary(facts_b),
        totals=totals,
        exercises=exercises,
        exercise_levels=exercise_levels,
        muscle_groups=muscle_groups,
        # BOTH resources: the muscle map and the e1RM modality gate both come from
        # exercise_templates, so a stale template sync silently changes numbers in this response.
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_MUSCLE
        ),
    )

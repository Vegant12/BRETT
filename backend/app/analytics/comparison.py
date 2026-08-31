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

from decimal import Decimal

from app.analytics.schemas import ComparisonLevel, ComparisonRate

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

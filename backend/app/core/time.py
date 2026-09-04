"""Timezone bucketing. FOUND-03 (configurable tz) and FOUND-04 (UTC storage).

Every day/week grouping in this project routes through this module. In SQL,
always write ``AT TIME ZONE :tz`` before ``date_trunc``, and use
``local_day_bounds()`` for WHERE-clause filtering.

``tz`` is always a parameter, never a module constant and never an environment
variable: FOUND-03 says the timezone comes from user configuration
(``users.timezone``). A module-level default would let a wrong-timezone bug
pass every test.

Getting this wrong is not a rounding error. At a UTC+7 offset, any instant
between 17:00Z and 24:00Z belongs to the *next* local day -- which is every
morning workout.
"""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now() -> dt.datetime:
    """The only sanctioned source of "now". Always aware, always UTC.

    Never use the legacy ``datetime.utc_now``-style helper (the no-argument
    UTC constructor deprecated in Python 3.12): it returns a *naive* datetime.
    Ruff's ``DTZ`` rules ban it repo-wide; this function is the replacement.
    """
    return dt.datetime.now(dt.UTC)


def _require_aware(ts: dt.datetime) -> dt.datetime:
    """Fail loudly on naive datetimes.

    FOUND-04 is enforced by a guard, not a convention. Silently assuming UTC
    for a naive input is how a local-time value ends up mis-bucketed with no
    error anywhere in the stack.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware UTC")
    return ts


def validate_timezone(tz: str) -> str:
    """Reject a non-IANA timezone at the boundary rather than deep in analytics.

    ``users.timezone`` carries no DB-level CHECK constraint, so a bad value
    would otherwise surface as a ``ZoneInfoNotFoundError`` from inside an
    aggregate query.
    """
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown IANA timezone") from None
    return tz


def to_local(ts: dt.datetime, tz: str) -> dt.datetime:
    """Convert an aware UTC instant into the user's local wall time."""
    return _require_aware(ts).astimezone(ZoneInfo(tz))


def local_day(ts: dt.datetime, tz: str) -> dt.date:
    """The user's local calendar day that this instant falls on. FOUND-03."""
    return to_local(ts, tz).date()


def local_week_start(ts: dt.datetime, tz: str) -> dt.date:
    """Monday of the user's local ISO week -- matches ``date_trunc('week', ...)``."""
    day = local_day(ts, tz)
    return day - dt.timedelta(days=day.weekday())


def local_month_start(ts: dt.datetime, tz: str) -> dt.date:
    """First calendar day of the user's local month -- matches ``date_trunc('month', ...)``.

    The month sibling of ``local_week_start``, and it lives here for the reason this module's
    docstring gives: every day/week grouping in this project routes through here. RPT-02's
    calendar-month report window is the first month-grained question the project has asked, and
    an ad-hoc ``day.replace(day=1)`` inside ``analytics/reports.py`` would be the second place
    the timezone rule is applied and the first place it could be applied wrongly.

    At UTC+7, 18:00Z on the last day of a month is already 01:00 on the FIRST of the next one.
    Deriving the month from the server's UTC date instead would report the previous month for
    seven hours out of every twenty-four -- silently, as a report that is one month stale.
    """
    day = local_day(ts, tz)
    return day.replace(day=1)


def local_day_bounds(day: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime]:
    """Half-open ``[start, end)`` UTC range covering one local day.

    Use this to FILTER in SQL. It compares the raw timestamp column against
    two constants, so an index on that column is usable -- unlike wrapping the
    column in ``AT TIME ZONE``, which forces a sequential scan.
    """
    zone = ZoneInfo(tz)
    start_local = dt.datetime.combine(day, dt.time.min, tzinfo=zone)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.UTC), end_local.astimezone(dt.UTC)


def local_range_bounds(
    start_day: dt.date, end_day: dt.date, tz: str
) -> tuple[dt.datetime, dt.datetime]:
    """Half-open ``[start, end)`` UTC range covering an INCLUSIVE local date range.

    D-03: Phase 4 analytics windows are arbitrary start/end dates, so this generalizes
    ``local_day_bounds``, which it DELEGATES to rather than repeating the ``ZoneInfo``
    arithmetic -- a second copy is how the two would eventually disagree about a DST
    transition day.

    Same reason for existing as ``local_day_bounds``: it produces two constants to compare
    a BARE timestamp column against, keeping ``ix_workouts_user_id_start_time`` usable.
    Wrapping the column in ``AT TIME ZONE`` instead was measured on the live database as a
    Seq Scan removing 299 of 327 rows, versus a Bitmap Index Scan for this form.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    start_utc, _ = local_day_bounds(start_day, tz)
    _, end_utc = local_day_bounds(end_day, tz)
    return start_utc, end_utc


def snap_local_week_range(start_day: dt.date, end_day: dt.date) -> tuple[dt.date, dt.date]:
    """Widen an inclusive local date range OUTWARD to whole Monday-start weeks.

    Weekly volume only. Asking for a window starting Wednesday 2026-07-01 otherwise produces
    a first bucket of Monday 2026-06-29 holding only the part of the week inside the window --
    a partial week whose total is not comparable to a full one, which reads as "volume
    dropped". Snapping outward is the user-locked resolution (extends D-02/D-03).

    Training frequency does NOT use this: it divides by the true window length (D-03), so an
    incomplete week is already handled by the arithmetic.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    return (
        start_day - dt.timedelta(days=start_day.weekday()),
        end_day + dt.timedelta(days=6 - end_day.weekday()),
    )


def local_week_spine(start_day: dt.date, end_day: dt.date) -> list[dt.date]:
    """Every local week-start Monday in an inclusive range, ascending and gap-free.

    Built by enumeration rather than inferred from the rows a query returned, because a week
    in which nothing was trained returns no rows -- and a silently missing zero week is the
    most diagnostically interesting one Claude could have seen.

    Enumerated in Python rather than with ``generate_series`` so it stays unit-testable with
    no container, and so SQLAlchemy's set-returning-function alias trap
    (``UndefinedColumnError`` without ``.render_derived()``) never applies.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    week = start_day - dt.timedelta(days=start_day.weekday())
    spine: list[dt.date] = []
    while week <= end_day:
        spine.append(week)
        week += dt.timedelta(weeks=1)
    return spine

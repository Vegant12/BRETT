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

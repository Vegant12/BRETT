"""FOUND-03 / FOUND-04 acceptance tests for ``app.core.time``.

The boundary table below was verified against live ``zoneinfo`` and a live
Postgres 18. ``2026-08-23T23:30:00+00:00`` is the "near midnight UTC" case
named directly in the Phase 1 success criteria: naive-UTC bucketing puts it on
2026-08-23, the correct Jakarta-local answer is 2026-08-24.

| UTC instant               | Jakarta local    | correct local day |
|---------------------------|------------------|-------------------|
| 2026-08-23T16:30:00+00:00 | 2026-08-23 23:30 | 2026-08-23        |
| 2026-08-23T17:00:00+00:00 | 2026-08-24 00:00 | 2026-08-24        |
| 2026-08-23T23:30:00+00:00 | 2026-08-24 06:30 | 2026-08-24        |
| 2026-08-24T00:30:00+00:00 | 2026-08-24 07:30 | 2026-08-24        |

FOUND-03 means the timezone comes from ``users.timezone``. Every bucketing
test below therefore reads it with ``select timezone from users`` and passes
the *result* to the helper. Hardcoding the argument would make these tests
pass even if the column were ignored entirely.

The Postgres container is session-scoped and shared, and ``test_migrations``
asserts ``count(*) == 1`` on ``users`` plus the seeded ``Asia/Jakarta`` value.
The two tests here that mutate state therefore never commit -- they roll back
in a ``finally``, which is strictly stronger than a compensating UPDATE
because it also survives an assertion failure mid-test.

D-03 makes a Phase 4 analytics window an arbitrary inclusive start/end local
date pair, not a single day, so ``local_range_bounds`` is the shape the
aggregates filter on. U-01: weekly volume snaps that window outward to whole
Monday-start weeks. Without the snap the first and last buckets are partial
weeks whose totals invite a false "volume dropped" reading. Frequency keeps the
raw range because it divides by the true window length.
"""

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import (
    local_day,
    local_day_bounds,
    local_month_start,
    local_range_bounds,
    local_week_spine,
    local_week_start,
    snap_local_week_range,
    to_local,
    utc_now,
    validate_timezone,
)
from app.db.models.user import User

# The instant the ROADMAP names explicitly. Kept as one constant so the
# boundary case cannot drift apart between tests.
NEAR_MIDNIGHT_UTC = dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC)


async def _user_timezone(session: AsyncSession) -> str:
    """Read the tz from the database -- the FOUND-03 source of truth."""
    tz = (await session.execute(sa.text("select timezone from users"))).scalar_one()
    assert isinstance(tz, str)
    return tz


# --------------------------------------------------------------------------
# FOUND-03: configurable timezone, used for daily/weekly bucketing
# --------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("utc_iso", "expected_day"),
    [
        ("2026-08-23T16:30:00+00:00", dt.date(2026, 8, 23)),
        ("2026-08-23T17:00:00+00:00", dt.date(2026, 8, 24)),  # exact Jakarta midnight
        ("2026-08-23T23:30:00+00:00", dt.date(2026, 8, 24)),  # "near midnight UTC"
        ("2026-08-24T00:30:00+00:00", dt.date(2026, 8, 24)),
    ],
)
async def test_local_day_uses_user_timezone(
    session: AsyncSession, utc_iso: str, expected_day: dt.date
) -> None:
    """The verified boundary table, bucketed with the tz stored on the user row."""
    tz = await _user_timezone(session)
    assert tz == "Asia/Jakarta"

    ts = dt.datetime.fromisoformat(utc_iso)
    assert ts.utcoffset() == dt.timedelta(0)

    assert local_day(ts, tz) == expected_day


@pytest.mark.integration
async def test_timezone_is_configurable(session: AsyncSession) -> None:
    """Changing ``users.timezone`` changes the bucket a given instant falls into.

    This is the test that distinguishes "reads user configuration" from
    "hardcodes Asia/Jakarta somewhere".
    """
    assert await _user_timezone(session) == "Asia/Jakarta"
    assert local_day(NEAR_MIDNIGHT_UTC, "Asia/Jakarta") == dt.date(2026, 8, 24)

    try:
        await session.execute(
            sa.text("update users set timezone = :tz"), {"tz": "America/New_York"}
        )
        tz = await _user_timezone(session)
        assert tz == "America/New_York"

        # Same instant, different configured zone, different local day.
        assert local_day(NEAR_MIDNIGHT_UTC, tz) == dt.date(2026, 8, 23)
    finally:
        # Belt: undo the value. Braces: discard the whole transaction, so the
        # shared container is untouched even if an assertion above failed.
        await session.execute(sa.text("update users set timezone = :tz"), {"tz": "Asia/Jakarta"})
        await session.rollback()

    assert await _user_timezone(session) == "Asia/Jakarta"


@pytest.mark.integration
async def test_python_and_sql_bucketing_agree(session: AsyncSession) -> None:
    """The Python helpers and Postgres ``AT TIME ZONE`` must not diverge.

    Analytics filter in Python and aggregate in SQL; if these two disagree the
    numbers are wrong in a way no single-layer test would catch. Bound
    parameters only -- never f-string SQL (Ruff ``S608``).
    """
    tz = await _user_timezone(session)
    params = {"ts": NEAR_MIDNIGHT_UTC, "tz": tz}

    sql_day = (
        await session.execute(
            sa.text(
                "select date_trunc('day', cast(:ts as timestamptz) AT TIME ZONE cast(:tz as text))"
                "::date"
            ),
            params,
        )
    ).scalar_one()
    sql_week = (
        await session.execute(
            sa.text(
                "select date_trunc('week', cast(:ts as timestamptz) AT TIME ZONE cast(:tz as text))"
                "::date"
            ),
            params,
        )
    ).scalar_one()

    assert sql_day == local_day(NEAR_MIDNIGHT_UTC, tz) == dt.date(2026, 8, 24)
    assert sql_week == local_week_start(NEAR_MIDNIGHT_UTC, tz) == dt.date(2026, 8, 24)


def test_week_start_with_frozen_clock() -> None:
    """A frozen clock must produce a deterministic week bucket.

    ``time_machine.travel`` is given an AWARE datetime deliberately: a naive
    argument makes the internal comparison offset-naive vs offset-aware and
    raises ``TypeError``.
    """
    with time_machine.travel(NEAR_MIDNIGHT_UTC, tick=False):
        assert local_week_start(utc_now(), "Asia/Jakarta") == dt.date(2026, 8, 24)


# --------------------------------------------------------------------------
# FOUND-04: UTC storage, converted only at calculation boundaries
# --------------------------------------------------------------------------


@pytest.mark.integration
async def test_timestamps_are_timestamptz(session: AsyncSession) -> None:
    """The standing guard: every future table inherits this assertion.

    Scoped to the whole ``public`` schema rather than ``users``, so a new model
    that reaches for a bare ``DateTime()`` fails here rather than silently
    truncating offsets in production.
    """
    rows = (
        await session.execute(
            sa.text(
                "select table_name, column_name, data_type "
                "from information_schema.columns "
                "where table_schema = 'public' and data_type like 'timestamp%' "
                "order by table_name, column_name"
            )
        )
    ).all()

    # Guard against a vacuous pass if the schema were empty.
    assert rows, "no timestamp columns found -- the schema is not migrated"
    offenders = [tuple(row) for row in rows if row.data_type != "timestamp with time zone"]
    assert offenders == []


@pytest.mark.integration
async def test_roundtrip_is_aware_utc(session: AsyncSession) -> None:
    """A stored instant comes back aware and at zero UTC offset.

    Never committed: ``flush`` + ``expire`` forces the value through Postgres
    and back inside the transaction, then the rollback leaves the shared
    container with its single seeded user intact.
    """
    user_id = uuid.uuid4()
    try:
        user = User(id=user_id, timezone="Asia/Jakarta", created_at=NEAR_MIDNIGHT_UTC)
        session.add(user)
        await session.flush()
        session.expire(user)

        stored = (await session.execute(sa.select(User).where(User.id == user_id))).scalar_one()

        assert stored.created_at.tzinfo is not None
        assert stored.created_at.utcoffset() == dt.timedelta(0)
        assert stored.created_at == NEAR_MIDNIGHT_UTC
        # The stored instant still buckets to the Jakarta-local next day.
        assert local_day(stored.created_at, "Asia/Jakarta") == dt.date(2026, 8, 24)
    finally:
        await session.rollback()


def test_naive_datetime_rejected() -> None:
    """FOUND-04 is enforced by a guard, not a convention."""
    with pytest.raises(ValueError, match="naive"):
        local_day(dt.datetime(2026, 8, 23, 23, 30), "Asia/Jakarta")  # noqa: DTZ001

    with pytest.raises(ValueError, match="naive"):
        to_local(dt.datetime(2026, 8, 23, 23, 30), "Asia/Jakarta")  # noqa: DTZ001

    with pytest.raises(ValueError, match="naive"):
        local_week_start(dt.datetime(2026, 8, 23, 23, 30), "Asia/Jakarta")  # noqa: DTZ001


# --------------------------------------------------------------------------
# Helper contract (pure unit)
# --------------------------------------------------------------------------


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)


def test_timezone_is_a_parameter_not_a_constant() -> None:
    """The same instant buckets differently per timezone -- proving `tz` is live."""
    assert local_day(NEAR_MIDNIGHT_UTC, "Asia/Jakarta") == dt.date(2026, 8, 24)
    assert local_day(NEAR_MIDNIGHT_UTC, "America/New_York") == dt.date(2026, 8, 23)


def test_local_day_bounds_is_half_open_utc() -> None:
    """Index-friendly filter bounds: the range must be UTC and half-open."""
    start, end = local_day_bounds(dt.date(2026, 8, 24), "Asia/Jakarta")
    assert start == dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 8, 24, 17, 0, tzinfo=dt.UTC)
    assert start.utcoffset() == dt.timedelta(0)
    assert end.utcoffset() == dt.timedelta(0)
    # Half-open: the end bound is the *next* day's start, never inclusive.
    assert local_day(start, "Asia/Jakarta") == dt.date(2026, 8, 24)
    assert local_day(end, "Asia/Jakarta") == dt.date(2026, 8, 25)


def test_validate_timezone() -> None:
    assert validate_timezone("Asia/Jakarta") == "Asia/Jakarta"
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        validate_timezone("Not/AZone")


# --------------------------------------------------------------------------
# D-03 / U-01: arbitrary analytics windows and Monday-start week snapping
# --------------------------------------------------------------------------


def test_local_range_bounds_is_half_open_utc() -> None:
    """Index-friendly filter bounds over an arbitrary range: UTC and half-open (D-03)."""
    start, end = local_range_bounds(dt.date(2026, 8, 24), dt.date(2026, 8, 30), "Asia/Jakarta")
    assert start == dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 8, 30, 17, 0, tzinfo=dt.UTC)
    assert start.utcoffset() == dt.timedelta(0)
    assert end.utcoffset() == dt.timedelta(0)
    # Half-open: the end bound is the *next* local day's start, never inclusive.
    assert local_day(start, "Asia/Jakarta") == dt.date(2026, 8, 24)
    assert local_day(end, "Asia/Jakarta") == dt.date(2026, 8, 31)


def test_local_range_bounds_of_one_day_equals_local_day_bounds() -> None:
    """A one-day range is the day. Proves the generalization did not drift from its base."""
    day = dt.date(2026, 8, 24)
    assert local_range_bounds(day, day, "Asia/Jakarta") == local_day_bounds(day, "Asia/Jakarta")


def test_local_range_bounds_rejects_an_inverted_range() -> None:
    """An inverted window would silently return an empty result set instead of failing."""
    with pytest.raises(ValueError, match="end_day precedes start_day"):
        local_range_bounds(dt.date(2026, 8, 30), dt.date(2026, 8, 24), "Asia/Jakarta")


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # Wednesday start snaps back to Monday; Sunday end is already a week end.
        (dt.date(2026, 7, 1), dt.date(2026, 8, 30), (dt.date(2026, 6, 29), dt.date(2026, 8, 30))),
        # A single Monday expands to that whole week.
        (dt.date(2026, 8, 24), dt.date(2026, 8, 24), (dt.date(2026, 8, 24), dt.date(2026, 8, 30))),
        # Already whole: unchanged, so snapping is idempotent.
        (dt.date(2026, 6, 29), dt.date(2026, 8, 30), (dt.date(2026, 6, 29), dt.date(2026, 8, 30))),
        # Saturday end pushes forward to Sunday.
        (dt.date(2026, 8, 24), dt.date(2026, 8, 29), (dt.date(2026, 8, 24), dt.date(2026, 8, 30))),
    ],
)
def test_snap_local_week_range_widens_outward_to_whole_weeks(
    start: dt.date, end: dt.date, expected: tuple[dt.date, dt.date]
) -> None:
    """U-01: weekly volume must never report a partial week as if it were a whole one."""
    snapped = snap_local_week_range(start, end)
    assert snapped == expected
    assert snapped[0].weekday() == 0
    assert snapped[1].weekday() == 6
    # Outward, never inward: the snapped range always CONTAINS the requested one.
    assert snapped[0] <= start
    assert snapped[1] >= end


def test_snap_local_week_range_rejects_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="end_day precedes start_day"):
        snap_local_week_range(dt.date(2026, 8, 30), dt.date(2026, 8, 24))


def test_local_week_spine_is_gap_free_and_ascending() -> None:
    """Zero-training weeks must appear as buckets, not vanish from the result."""
    spine = local_week_spine(dt.date(2026, 6, 29), dt.date(2026, 8, 30))
    assert spine == [
        dt.date(2026, 6, 29),
        dt.date(2026, 7, 6),
        dt.date(2026, 7, 13),
        dt.date(2026, 7, 20),
        dt.date(2026, 7, 27),
        dt.date(2026, 8, 3),
        dt.date(2026, 8, 10),
        dt.date(2026, 8, 17),
        dt.date(2026, 8, 24),
    ]
    assert all(day.weekday() == 0 for day in spine)
    assert spine == sorted(spine)


def test_local_week_spine_snaps_its_first_entry_to_monday() -> None:
    """A mid-week start still yields the Monday that owns it -- one bucket, not zero."""
    assert local_week_spine(dt.date(2026, 7, 1), dt.date(2026, 7, 1)) == [dt.date(2026, 6, 29)]


def test_local_week_spine_rejects_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="end_day precedes start_day"):
        local_week_spine(dt.date(2026, 8, 30), dt.date(2026, 8, 24))


# --------------------------------------------------------------------------
# RPT-02: calendar-month report window
# --------------------------------------------------------------------------


def test_local_month_start_uses_the_users_month() -> None:
    """The load-bearing case is the UTC+7 boundary: only it can fail from a server-local bug."""
    # 02:00Z on 2026-09-04 is 09:00 local in Jakarta -- squarely inside September, no boundary
    # risk. A trivial "day.replace(day=1)" over the naive UTC date would already get this right.
    assert local_month_start(
        dt.datetime(2026, 9, 4, 2, 0, tzinfo=dt.UTC), "Asia/Jakarta"
    ) == dt.date(2026, 9, 1)

    # THE case: 18:00Z on the last day of August is 01:00 on September 1st at UTC+7. Deriving the
    # month from the server's bare UTC date instead reports August for seven hours out of every
    # twenty-four -- silently, as a report that is one month stale.
    assert local_month_start(
        dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.UTC), "Asia/Jakarta"
    ) == dt.date(2026, 9, 1)

    # The first instant of a month maps to that month, at a zero UTC offset where local and UTC
    # dates always agree -- the sanity case with no timezone arithmetic to get wrong.
    assert local_month_start(dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC), "UTC") == dt.date(
        2026, 9, 1
    )

    with pytest.raises(ValueError, match="naive"):
        local_month_start(dt.datetime(2026, 9, 4, 2, 0), "Asia/Jakarta")  # noqa: DTZ001

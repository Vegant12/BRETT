"""FOUND-03 / FOUND-04 acceptance tests for ``app.core.time``.

The boundary table below was verified against live ``zoneinfo`` and a live
Postgres 18. ``2026-08-23T23:30Z`` is the "near midnight UTC" case named
directly in the Phase 1 success criteria: naive-UTC bucketing puts it on
2026-08-23, the correct Jakarta-local answer is 2026-08-24.
"""

import datetime as dt

import pytest
import time_machine

from app.core.time import (
    local_day,
    local_day_bounds,
    local_week_start,
    to_local,
    utc_now,
    validate_timezone,
)


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)


def test_week_start_with_frozen_clock() -> None:
    """A frozen clock must produce a deterministic week bucket.

    ``time_machine.travel`` is given an AWARE datetime deliberately: a naive
    argument makes the internal comparison offset-naive vs offset-aware and
    raises ``TypeError``.
    """
    with time_machine.travel(dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC), tick=False):
        assert local_week_start(utc_now(), "Asia/Jakarta") == dt.date(2026, 8, 24)


def test_naive_datetime_rejected() -> None:
    """FOUND-04 is enforced by a guard, not a convention."""
    with pytest.raises(ValueError, match="naive"):
        local_day(dt.datetime(2026, 8, 23, 23, 30), "Asia/Jakarta")  # noqa: DTZ001

    with pytest.raises(ValueError, match="naive"):
        to_local(dt.datetime(2026, 8, 23, 23, 30), "Asia/Jakarta")  # noqa: DTZ001


def test_timezone_is_a_parameter_not_a_constant() -> None:
    """The same instant buckets differently per timezone -- proving `tz` is live."""
    ts = dt.datetime(2026, 8, 23, 23, 30, tzinfo=dt.UTC)
    assert local_day(ts, "Asia/Jakarta") == dt.date(2026, 8, 24)
    assert local_day(ts, "America/New_York") == dt.date(2026, 8, 23)


def test_local_day_bounds_is_half_open_utc() -> None:
    start, end = local_day_bounds(dt.date(2026, 8, 24), "Asia/Jakarta")
    assert start == dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 8, 24, 17, 0, tzinfo=dt.UTC)
    assert start.utcoffset() == dt.timedelta(0)
    assert end.utcoffset() == dt.timedelta(0)


def test_validate_timezone() -> None:
    assert validate_timezone("Asia/Jakarta") == "Asia/Jakarta"
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        validate_timezone("Not/AZone")

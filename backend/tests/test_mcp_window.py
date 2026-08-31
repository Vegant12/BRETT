"""D-03 / D-04 window arithmetic: the fast, container-free half of the MCP tool contract.

Deliberately NOT marked ``integration``. Every assertion here is on a pure function, so a
regression in the ``weeks`` -> date-range conversion must fail ``-m "not integration"`` on the
commit that introduces it rather than waiting for a Postgres container to be available.

The interesting test is ``test_snapping_a_weeks_window_yields_exactly_that_many_weeks``. The
volume tools call ``snap_local_week_range`` themselves, which widens a range OUTWARD to whole
Monday-start weeks, so ``week_window``'s Monday anchor is what makes ``weeks=N`` mean N rows.
Without it the round trip returns N+1 for six days out of every seven -- and the symptom is a
row-count assertion failing by one, which reads like an off-by-one in the test rather than a
missing anchor in the helper.

``app.mcp.tools._common`` is imported at module scope on purpose: it pulls in ``app.mcp.context``
but never ``app.mcp.server``, so this file does not depend on conftest's module-scope MCP
environment seeding.
"""

import datetime as dt

import pytest
import time_machine

from app.core.time import local_day, local_week_spine, snap_local_week_range, utc_now
from app.mcp.tools._common import MAX_WEEKS, week_window

# Monday 2026-08-24 through Sunday 2026-08-30 -- one of every weekday. Every parametrized test
# below runs across all seven, because the anchoring bug this file exists to catch is invisible
# on a Monday and wrong on the other six days.
WEEK_OF_DAYS = [dt.date(2026, 8, 24) + dt.timedelta(days=offset) for offset in range(7)]

# 1 and 52 are the boundaries of the permitted range; 4 and 12 are the windows the tools
# actually default to.
WEEK_COUNTS = (1, 4, 12, 52)


def test_weeks_one_is_the_current_monday_to_today() -> None:
    """``weeks=1`` means the week in progress, not the last seven days.

    2026-08-27 is a Thursday, so the window starts on its Monday and ends today. A rolling
    7-day window would start on the previous Friday and mix two calendar weeks.
    """
    assert week_window(today=dt.date(2026, 8, 27), weeks=1) == (
        dt.date(2026, 8, 24),
        dt.date(2026, 8, 27),
    )


@pytest.mark.parametrize("weeks", WEEK_COUNTS)
@pytest.mark.parametrize("today", WEEK_OF_DAYS)
def test_start_day_is_always_a_monday(weeks: int, today: dt.date) -> None:
    """The anchor, asserted directly: no ``today`` and no ``weeks`` may produce a mid-week start."""
    start_day, end_day = week_window(today=today, weeks=weeks)
    assert start_day.weekday() == 0, f"start_day {start_day} is not a Monday"
    assert end_day == today


@pytest.mark.parametrize("weeks", WEEK_COUNTS)
@pytest.mark.parametrize("today", WEEK_OF_DAYS)
def test_snapping_a_weeks_window_yields_exactly_that_many_weeks(weeks: int, today: dt.date) -> None:
    """Pitfall 6: the round trip through the volume tools' own snap must not add a week.

    ``get_weekly_volume`` and ``get_muscle_group_volume`` widen their window outward to whole
    weeks before aggregating. This reproduces that composition end to end.
    """
    start_day, end_day = week_window(today=today, weeks=weeks)
    snapped_start, snapped_end = snap_local_week_range(start_day, end_day)
    spine = local_week_spine(snapped_start, snapped_end)
    assert len(spine) == weeks, (
        f"asked for {weeks} weeks ending {today}, snapped to "
        f"{snapped_start}..{snapped_end} = {len(spine)} week rows. "
        "A 53rd row is a D-04 response-budget failure, not an off-by-one in this test: "
        "week_window's Monday anchor is what stops snap_local_week_range widening backwards."
    )


def test_weeks_above_the_cap_is_rejected() -> None:
    """D-04 is enforced by a guard in the helper, not by each tool remembering to check."""
    with pytest.raises(ValueError):
        week_window(today=dt.date(2026, 8, 31), weeks=MAX_WEEKS + 1)

    with pytest.raises(ValueError):
        week_window(today=dt.date(2026, 8, 31), weeks=0)


def test_the_error_message_carries_no_value() -> None:
    """The message names the failure and echoes nothing back.

    ``rollup.build_window`` states the rule -- "every message names the failure and carries no
    date value and no user id" -- on the grounds that it will be logged. Pitfall 3 raises the
    stakes: ``mcp 2.0.0`` returns an escaping exception's text to the model verbatim, so this
    string is a RESPONSE channel as well as a log one.
    """
    with pytest.raises(ValueError) as too_many:
        week_window(today=dt.date(2026, 8, 31), weeks=MAX_WEEKS + 1)
    assert "53" not in str(too_many.value)

    with pytest.raises(ValueError) as too_few:
        week_window(today=dt.date(2026, 8, 31), weeks=0)
    assert "0" not in str(too_few.value)


def test_evening_utc_belongs_to_next_local_day() -> None:
    """D-13: the window ends on the user's local today, never the server's UTC date.

    At UTC+7 every instant between 17:00Z and 24:00Z belongs to the NEXT local day. A
    UTC-derived ``end_day`` therefore drops the whole of today's training for seven hours out
    of every twenty-four -- silently, as a slightly-low number rather than an error.

    ``time_machine.travel`` is given an AWARE datetime rather than an ISO string: string
    parsing routes through ``dateutil``, which this project does not depend on, and a naive
    datetime makes time_machine's internal comparison offset-naive vs offset-aware and raises
    ``TypeError`` (the same trap ``test_time.py`` documents).
    """
    evening_utc = dt.datetime(2026, 8, 30, 17, 30, tzinfo=dt.UTC)
    with time_machine.travel(evening_utc, tick=False):
        assert utc_now().date() == dt.date(2026, 8, 30)
        jakarta_today = local_day(utc_now(), "Asia/Jakarta")
        assert jakarta_today == dt.date(2026, 8, 31)

        # 2026-08-31 is itself a Monday, so `weeks=1` is a single-day window on the week that
        # started hours ago in Jakarta and has not started at all in UTC.
        assert week_window(today=jakarta_today, weeks=1) == (
            dt.date(2026, 8, 31),
            dt.date(2026, 8, 31),
        )


def test_max_weeks_is_fifty_two() -> None:
    """D-04 pinned as a value, so widening the cap is a deliberate edit and not a drift."""
    assert MAX_WEEKS == 52, "D-04 caps a window at one year of week buckets"

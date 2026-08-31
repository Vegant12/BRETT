"""BODY-01: rolling body-weight averages and the smoothed rate (D-13 through D-17).

Every test here is SYNTHETIC and runs under a FROZEN CLOCK. A test written against live data
would assert `trend_rate_percent_per_week is None` today -- correctly, because the D-16 anchor
window 2026-07-26..2026-08-01 holds zero weigh-ins after a real 52-day logging gap -- and would
then start passing for the wrong reason around 2026-09-06 when the gap fills in.

THE load-bearing test is `test_windows_gate_independently`. The specific wrong behaviour it
catches is a single response-level flag: an implementation with one shared `insufficient_data`
returns a null 30-day average whenever the 7-day window is sparse, deleting the one number that
IS trustworthy after a travel week.

Its partner is `test_smoothed_rate_is_null_when_the_anchor_window_is_empty`: without it, an
implementation that fell back to the prior-week delta would report +0.72%/week off one week of
glycogen noise -- nearly three times BODY-02's lean-bulk threshold -- and it would look entirely
plausible.

The dedupe and window-average tests carry NO integration marker on purpose. D-13's
"no interpolation" rule and D-14's tie-break are business rules, and business rules must stay
verifiable when Docker is not running -- the same argument `test_analytics_frequency.py` makes
for its `sessions_per_week` tests.

Never `pytest.approx`.
"""

import datetime as dt
from decimal import Decimal

from app.analytics.bodyweight import (
    MANUAL_SOURCE,
    BodyMeasurementRow,
    _dedupe_by_day,
    _window_average,
)

# The frozen instants. 02:00 UTC is 09:00 in Asia/Jakarta -- an instant where the UTC day and the
# LOCAL day AGREE, so the coverage tests isolate the coverage rule. `_DISAGREE_INSTANT` is the
# opposite case on purpose: 18:00Z on the 29th is 01:00 local on the 30th.
_AGREE_INSTANT = "2026-08-30T02:00:00+00:00"
_DISAGREE_INSTANT = "2026-08-29T18:00:00+00:00"
_ANCHOR = dt.date(2026, 8, 30)

_HEVY_SOURCE = "hevy"


def _row(day_offset: int, weight: str | None, source: str = _HEVY_SOURCE) -> BodyMeasurementRow:
    """One weigh-in `day_offset` days BEFORE the anchor. `weight` is a Decimal string or None."""
    return BodyMeasurementRow(
        measured_on=_ANCHOR - dt.timedelta(days=day_offset),
        source=source,
        weight_kg=None if weight is None else Decimal(weight),
    )


def test_manual_wins_over_hevy_for_the_same_day() -> None:
    """D-14, asserted in BOTH input orderings so the rule is order-independent, not lucky."""
    hevy = _row(0, "65.00")
    manual = _row(0, "66.00", source=MANUAL_SOURCE)

    for rows in ([hevy, manual], [manual, hevy]):
        by_day = _dedupe_by_day(rows)
        assert by_day == {_ANCHOR: Decimal("66.00")}, (
            "D-14: the natural key permits two rows per day; averaging them or counting the day "
            "twice both produce plausible numbers"
        )


def test_rows_without_a_weight_are_dropped() -> None:
    """A waist-only weigh-in is not a body-weight data point.

    Counting it toward a coverage floor would make sparse data read as sufficient -- the exact
    failure D-15's floors exist to prevent.
    """
    rows = [_row(0, "65.00"), _row(1, None), _row(2, "67.00")]

    by_day = _dedupe_by_day(rows)

    assert _ANCHOR - dt.timedelta(days=1) not in by_day
    assert len(by_day) == 2
    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("66.000"), 2)


def test_window_average_is_exact_and_quantized() -> None:
    """Exact `Decimal` equality, never `pytest.approx`: 196.50 / 3 is exactly 65.500."""
    by_day = _dedupe_by_day([_row(0, "65.00"), _row(1, "65.50"), _row(2, "66.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("65.500"), 3)


def test_no_interpolation_across_a_gap() -> None:
    """D-13: a 7-day window with weigh-ins on days 1, 2 and 7 averages exactly those three.

    The count is 3, not 7. An implementation that carried the last known value forward would
    return 7 here and a smoothed average that was never measured -- which on live data would
    fabricate a real 52-day logging gap into a straight line.
    """
    by_day = _dedupe_by_day([_row(6, "64.00"), _row(5, "65.00"), _row(0, "66.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (Decimal("65.000"), 3)


def test_an_empty_window_is_none_and_not_zero() -> None:
    """A bodyweight of zero is not the same fact as "nobody weighed in"."""
    by_day = _dedupe_by_day([_row(40, "65.00")])

    assert _window_average(by_day, end_day=_ANCHOR, window_days=7) == (None, 0)

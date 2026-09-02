"""Unit coverage for the HAE normalizer: HEALTH-06, HEALTH-08, NUTR-02, D-01, D-02, D-04.

Pure and container-free on purpose. `normalize.py` touches no database, so every case here runs
in the FAST suite and fails on the commit that breaks it rather than after a deploy.

What deliberately lives ELSEWHERE:

* **Idempotency and the `ON CONFLICT` clause** -- plan 08-06, against a real Postgres container.
  This file proves that ONE delivery collapses to one row per key; whether a SECOND delivery of
  the same window is a no-op is a property of the upsert, not of this function. The two halves
  of Pitfall N-2 are split exactly there.
* **Wire parsing, the unit-conversion arithmetic and the date-format table** -- plan 08-04's
  `test_health_auto_export_schema.py`. Cases here take those as given and assert only that the
  normalizer routes through them.
* **The webhook route, its bearer check and its status codes** -- plan 08-07.

Non-ASCII source names are written as ESCAPES (`\\u2019`), never as literals: `Vegant's iPhone`
carries U+2019 RIGHT SINGLE QUOTATION MARK, which is invisible in a diff and which one careless
editor normalising to an ASCII apostrophe would silently turn into a different test.
"""

import datetime as dt
import io
import json
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
import structlog

from app.config import Settings
from app.integrations.health_auto_export import normalize
from app.integrations.health_auto_export.normalize import (
    UNKNOWN_SOURCE_NAME,
    is_hevy_sourced,
    normalize_payload,
)
from app.integrations.health_auto_export.schemas import HAEPayload
from app.logging import configure_logging

# `users.timezone` today. The phone emits +0700 to match, so Pitfall N-4 is dormant -- which is
# exactly why plan 08-05 Task 3 pins it rather than leaving it to be discovered on travel.
TZ = "Asia/Jakarta"  # +07:00

MORNING = "2025-08-15 08:00:00 +0900"  # 06:00 in Jakarta -> 2025-08-15
EVENING = "2025-08-15 19:00:00 +0900"  # 17:00 in Jakarta -> 2025-08-15
DAY = dt.date(2025, 8, 15)

# The device name from the user's real export, spelled with U+2019. It must NOT match the Hevy
# predicate: HEALTH-08 is about the APP that wrote the sample, not the phone it was written on.
DEVICE_NAME = "Vegant\u2019s iPhone"

_OMITTED: Any = object()


# ---------------------------------------------------------------------------
# Payload builders. Built in code rather than as fixture files because the point of the big
# cases is the COUNT (189 datapoints, 59 fragments) and a 189-element JSON file is unreadable.
# ---------------------------------------------------------------------------


def _point(*, qty: Any = 100, date: Any = MORNING, source: Any = "iPhone") -> dict[str, Any]:
    """One wire datapoint. Pass `_OMITTED` to leave a KEY OUT, which is not the same as null --
    real payloads omit `source` entirely for gait metrics."""
    raw = {"qty": qty, "date": date, "source": source}
    return {key: value for key, value in raw.items() if value is not _OMITTED}


def _metric(name: str, *, units: str = "count", points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "units": units, "data": points}


def _payload(*metrics: dict[str, Any], **extra: Any) -> HAEPayload:
    data: dict[str, Any] = {"metrics": list(metrics), **extra}
    return HAEPayload.model_validate({"data": data})


def run_capturing_logs[T](
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], T]
) -> tuple[T, list[dict[str, Any]]]:
    """Run `action` with the REAL logging pipeline rendered into a buffer.

    Not `structlog.testing.capture_logs`: that replaces the configured processor chain for its
    duration, which would leave a no-values-in-logs assertion green over a pipeline that never
    ran (`test_secret_redaction.py`'s Pitfall 6, and `test_hevy_body.py`'s note on the same).

    `configure_logging` turns structlog's first-use cache ON. A proxy already cached by an
    earlier test keeps that test's configuration and would write somewhere else entirely,
    leaving this buffer empty -- a capture that silently checks nothing. So the cache is
    disabled and the module is handed a fresh proxy for the duration.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")  # JSONRenderer; development is console
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_log = normalize.log
    try:
        configure_logging(Settings(_env_file=None))
        structlog.configure(cache_logger_on_first_use=False)
        monkeypatch.setattr(normalize, "log", structlog.get_logger())
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        result = action()
        rendered = buffer.getvalue()
    finally:
        normalize.log = saved_log
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
    return result, [json.loads(line) for line in rendered.splitlines() if line.strip()]


def _events(entries: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("event") == name]


# ---------------------------------------------------------------------------
# HEALTH-08: the source-level exclusion predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["Hevy", "hevy", "HEVY", "  HEVY  ", "\tHevy\n"])
def test_is_hevy_sourced_matches_the_app_name_whatever_its_case_or_padding(source: str) -> None:
    """HEALTH-08. The webhook's exact spelling is Assumption A1, still unverified against a
    payload from this phone, so the predicate must not be brittle about case or whitespace."""
    assert is_hevy_sourced(source), (
        f"HEALTH-08 violated: {source!r} was not recognised as Hevy-sourced. Hevy writes "
        f"ActiveEnergyBurned to Apple Health on every training day at 70-88% of that day's "
        f"total, so a predicate that misses it double-counts a session BRETT already holds "
        f"at set-level detail"
    )


@pytest.mark.parametrize(
    "source",
    [
        DEVICE_NAME,
        "Vegant's iPhone",
        "iPhone",
        "Foodvisor",
        "Built With Science",
        "hevyapp",
        "not hevy",
        "",
        None,
    ],
)
def test_is_hevy_sourced_ignores_device_names_and_every_other_app(source: str | None) -> None:
    """Pitfall N-3: match the APP name, never the device name.

    The device was renamed mid-history (366,339 records under one name, 70,900 under the other)
    and its name carries U+2019, so a device-name comparison is unstable AND silently wrong. A
    predicate that matched a device name would drop the iPhone's own active energy -- the very
    data HEALTH-08 exists to keep.
    """
    assert not is_hevy_sourced(source), (
        f"HEALTH-08 violated in the other direction: {source!r} was treated as Hevy-sourced. "
        f"Pitfall N-3's warning sign is a source filter that excludes more than it should; "
        f"this one would delete the iPhone's own samples"
    )


def test_a_hevy_sourced_datapoint_never_becomes_a_row() -> None:
    """Open Question 1: the exclusion happens at WRITE time, so HEALTH-08 is a row-count fact
    rather than a rule every future analytics reader has to remember."""
    result = normalize_payload(
        _payload(
            _metric(
                "active_energy",
                units="kcal",
                points=[
                    _point(qty=666.5, source="Hevy"),
                    _point(qty=31.4, source=DEVICE_NAME),
                ],
            )
        ),
        tz=TZ,
    )

    assert len(result.rows) == 1, (
        f"HEALTH-08 violated: expected the Hevy datapoint to be dropped and only the device row "
        f"to survive. Observed sources: {sorted(row.source_name for row in result.rows)}"
    )
    assert result.rows[0].source_name == DEVICE_NAME
    assert result.rows[0].sample_count == 1
    assert result.datapoints_dropped == 1


def test_hevy_exclusion_is_logged_once_per_metric_with_a_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall N-3's stated warning sign is 'a source-exclusion filter that never excludes
    anything'. Without this log line that condition is invisible; with it, it is a grep."""
    payload = _payload(
        _metric(
            "active_energy",
            units="kcal",
            points=[
                _point(qty=666.5, source="Hevy"),
                _point(qty=12.0, source="hevy", date=EVENING),
                _point(qty=31.4, source=DEVICE_NAME),
            ],
        )
    )

    result, entries = run_capturing_logs(monkeypatch, lambda: normalize_payload(payload, tz=TZ))

    excluded = _events(entries, "health_ingest_hevy_source_excluded")
    assert len(excluded) == 1, (
        f"HEALTH-08: expected exactly one hevy-exclusion log line for one metric, got "
        f"{len(excluded)}. One line per datapoint would bury the signal on a 189-point day"
    )
    assert excluded[0]["metric"] == "active_energy"
    assert excluded[0]["points"] == 2
    assert len(result.rows) == 1


# ---------------------------------------------------------------------------
# D-04: an unlisted metric costs itself and nothing else
# ---------------------------------------------------------------------------


def test_unrecognized_metric_contributes_no_rows_and_is_counted() -> None:
    """HEALTH-06: `METRIC_REGISTRY` is the allowlist, and it is the ONLY gate on what is
    stored."""
    result = normalize_payload(
        _payload(_metric("sleep_analysis", units="hr", points=[_point(qty=6.75)])), tz=TZ
    )

    assert result.rows == ()
    assert result.metrics_unrecognized == 1
    assert result.kinds_present == frozenset()


def test_unrecognized_metric_is_logged_once_per_metric_not_once_per_datapoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-04. A real payload carries 189 datapoints for one metric-day; one log line per
    datapoint would make an unrecognised metric a 189-line incident in the log sink."""
    payload = _payload(
        _metric(
            "sleep_analysis",
            units="hr",
            points=[_point(qty=1.0), _point(qty=2.0, date=EVENING), _point(qty=3.0)],
        )
    )

    _, entries = run_capturing_logs(monkeypatch, lambda: normalize_payload(payload, tz=TZ))

    unrecognized = _events(entries, "health_ingest_unrecognized_metric")
    assert len(unrecognized) == 1, (
        f"D-04: expected exactly one log line for one unrecognised metric carrying three "
        f"datapoints, got {len(unrecognized)}"
    )
    assert unrecognized[0]["metric"] == "sleep_analysis"


def test_unrecognized_metric_does_not_cost_the_recognised_metrics_beside_it() -> None:
    """D-04, and the reason `HAEMetric.name` is a free-form `str` rather than a `Literal`.

    Health Auto Export has no documented retry, so rejecting a batch over one unexpected name
    is permanent loss of that window's activity AND nutrition -- not just of the odd part.
    """
    result = normalize_payload(
        _payload(
            _metric("sleep_analysis", units="hr", points=[_point(qty=6.75)]),
            _metric("step_count", units="count", points=[_point(qty=2044)]),
            _metric("walking_speed", units="km/hr", points=[_point(qty=4.68)]),
        ),
        tz=TZ,
    )

    assert [row.metric for row in result.rows] == ["step_count"], (
        f"D-04 violated: an unrecognised metric took its neighbours down with it. Rows: "
        f"{[row.metric for row in result.rows]}"
    )
    assert result.metrics_unrecognized == 2


def test_unrecognized_weight_body_mass_and_workouts_produce_no_rows() -> None:
    """D-01 (no Apple Health body mass in Phase 8) and D-02 (no Apple Health workouts).

    Both are closed by the same allowlist path: `weight_body_mass` is simply absent from the
    registry, and the `workouts` array beside `metrics` is unmodelled, so it cannot reach here
    at all. One mechanism, no second code path to keep in sync.
    """
    result = normalize_payload(
        _payload(
            _metric("weight_body_mass", units="kg", points=[_point(qty=74.35, source="Hevy")]),
            _metric("step_count", units="count", points=[_point(qty=2044)]),
            workouts=[{"name": "Pull day", "start": MORNING}],
        ),
        tz=TZ,
    )

    assert [row.metric for row in result.rows] == ["step_count"], (
        f"D-01/D-02 violated: something other than the allowlisted activity metric became a "
        f"row. Rows: {[row.metric for row in result.rows]}"
    )
    assert result.metrics_unrecognized == 1


# ---------------------------------------------------------------------------
# Per-datapoint drops
# ---------------------------------------------------------------------------


def test_datapoint_missing_qty_is_dropped_and_counted() -> None:
    """A heart-rate metric the user toggles on carries Min/Max/Avg and no `qty`. The blast
    radius must be one datapoint, never one window."""
    result = normalize_payload(
        _payload(
            _metric(
                "step_count",
                units="count",
                points=[_point(qty=_OMITTED), _point(qty=2044, date=EVENING)],
            )
        ),
        tz=TZ,
    )

    assert result.datapoints_seen == 2
    assert result.datapoints_dropped == 1
    assert len(result.rows) == 1
    assert result.rows[0].sample_count == 1


def test_datapoint_missing_date_is_dropped_and_counted() -> None:
    """Without a timestamp there is no local day, and guessing one mis-attributes the value."""
    result = normalize_payload(
        _payload(
            _metric(
                "step_count",
                units="count",
                points=[_point(date=None), _point(qty=2044, date=EVENING)],
            )
        ),
        tz=TZ,
    )

    assert result.datapoints_dropped == 1
    assert len(result.rows) == 1


def test_unparseable_date_is_dropped_and_never_logged_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-08-30. The timestamp is user-controlled input reaching a log sink; the class name says
    everything a reader can act on, and the format list is already written down."""
    offending = "15/08/2025 8am-ish"
    payload = _payload(
        _metric("step_count", units="count", points=[_point(qty=2044, date=offending)])
    )

    result, entries = run_capturing_logs(monkeypatch, lambda: normalize_payload(payload, tz=TZ))

    dropped = _events(entries, "health_ingest_datapoint_dropped")
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "HAEDateFormatError"
    assert offending not in json.dumps(entries), (
        "T-08-30 violated: the offending timestamp string was rendered into a log line"
    )
    assert result.rows == ()


def test_unknown_unit_drops_every_datapoint_of_the_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HAE units are a per-metric preference inside the phone app, converted on-device at export
    time, so they can change with no version bump. Storing the raw number would be a plausible
    figure that is quietly wrong -- this project's stated primary risk."""
    payload = _payload(
        _metric(
            "walking_running_distance",
            units="furlongs",
            points=[_point(qty=1.0), _point(qty=2.0, date=EVENING)],
        )
    )

    result, entries = run_capturing_logs(monkeypatch, lambda: normalize_payload(payload, tz=TZ))

    assert result.rows == ()
    assert result.datapoints_dropped == 2
    dropped = _events(entries, "health_ingest_datapoint_dropped")
    assert [entry["reason"] for entry in dropped] == ["UnknownUnitError"] * 2
    assert dropped[0]["metric"] == "walking_running_distance"
    assert dropped[0]["unit"] == "furlongs"


def test_empty_units_is_rejected_like_an_unknown_unit() -> None:
    """The metric-level `units` field was absent. Assuming the canonical unit is EXACTLY the
    silent failure the conversion boundary exists to prevent."""
    result = normalize_payload(
        _payload(_metric("protein", units="", points=[_point(qty=155.7)])), tz=TZ
    )

    assert result.rows == ()
    assert result.datapoints_dropped == 1


# ---------------------------------------------------------------------------
# `source_name` -- a KEY column, so its exact value is load-bearing
# ---------------------------------------------------------------------------


def test_a_datapoint_with_no_source_key_gets_the_unknown_sentinel() -> None:
    """Pitfall N-1. `source_name` is inside the 5-column natural key and PostgreSQL treats NULLs
    as DISTINCT inside a unique constraint, so a null there would let every sourceless datapoint
    INSERT a duplicate row instead of upserting. Real payloads omit `source` for gait metrics."""
    result = normalize_payload(
        _payload(_metric("step_count", units="count", points=[_point(source=_OMITTED)])), tz=TZ
    )

    assert result.rows[0].source_name == UNKNOWN_SOURCE_NAME
    assert UNKNOWN_SOURCE_NAME == "unknown"


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        (DEVICE_NAME, DEVICE_NAME),
        ("  iPhone  ", "iPhone"),
        ("Built With Science", "Built With Science"),
        ("   ", UNKNOWN_SOURCE_NAME),
    ],
)
def test_source_name_is_preserved_verbatim_after_stripping(wire: str, expected: str) -> None:
    """Stored and later matched, so case and non-ASCII must survive intact: `SELECT DISTINCT
    source_name` is how a device rename or a new nutrition app is noticed at all."""
    result = normalize_payload(
        _payload(_metric("step_count", units="count", points=[_point(source=wire)])), tz=TZ
    )

    assert result.rows[0].source_name == expected


def test_row_units_are_canonical_never_the_wire_unit() -> None:
    """The row carries the unit it is STORED in. Recording the wire unit would make every
    downstream reader re-derive the conversion, which is how two readers disagree."""
    result = normalize_payload(
        _payload(_metric("active_energy", units="kJ", points=[_point(qty=418.4)])), tz=TZ
    )

    assert result.rows[0].units == "kcal"
    assert result.rows[0].value == Decimal("100")
    assert result.rows[0].local_day == DAY
    assert result.rows[0].kind == "activity"

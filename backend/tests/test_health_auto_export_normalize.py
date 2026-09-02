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
from app.integrations.health_auto_export.registry import METRIC_REGISTRY, MetricSpec
from app.integrations.health_auto_export.schemas import HAEPayload
from app.logging import configure_logging
from tests.conftest import hae_fixture

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


# ---------------------------------------------------------------------------
# Aggregation: one delivery -> one row per (metric, source_name, local_day)
# ---------------------------------------------------------------------------


def _minute_series(count: int, *, start_hour: int = 8) -> list[str]:
    """`count` HAE timestamps one minute apart, all inside one local day in every zone used
    here. Generated rather than transcribed: the point of the 189-point case is the COUNT."""
    base = dt.datetime(2025, 8, 15, start_hour, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    return [
        (base + dt.timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M:%S %z")
        for offset in range(count)
    ]


def test_many_datapoints_for_one_metric_day_collapse_into_exactly_one_row() -> None:
    """Finding B: a real payload carries 189 datapoints of `walking_running_distance` for a
    single day (1-minute buckets) and the table holds ONE row.

    Aggregating the whole payload before any write is what lets plan 08-06 use replace
    semantics unconditionally -- the first half of Pitfall N-2.
    """
    quantities = [Decimal("0.001") * step for step in range(1, 190)]
    points = [
        _point(qty=str(qty), date=stamp)
        for qty, stamp in zip(quantities, _minute_series(189), strict=True)
    ]

    result = normalize_payload(
        _payload(_metric("walking_running_distance", units="km", points=points)), tz=TZ
    )

    assert len(result.rows) == 1, (
        f"HEALTH-06 violated: 189 datapoints for one metric-day produced {len(result.rows)} "
        f"rows. The table holds one row per (metric, source_name, local_day); anything else "
        f"either violates the unique constraint or silently overwrites itself"
    )
    row = result.rows[0]
    assert row.sample_count == 189, (
        f"sample_count must be truthful -- it is the only signal that a day was built from 189 "
        f"fragments rather than from one daily total. Got {row.sample_count}"
    )
    assert row.value == sum(quantities, Decimal(0))
    assert result.datapoints_seen == 189
    assert result.datapoints_dropped == 0


def test_fractional_count_fragments_survive_aggregation_without_truncation() -> None:
    """Finding C. HAE PRORATES `count` metrics across aggregation buckets, so a real
    `flights_climbed` datapoint arrives as 0.20163697817574894 and 59 of them are one day.

    An integer column or a truncating cast anywhere in this path reads that day as zero flights
    with no error and no failing test -- which is why every value below is under 1.
    """
    fragment = Decimal("0.20163697817574894")
    points = [_point(qty=str(fragment), date=stamp) for stamp in _minute_series(59)]

    result = normalize_payload(
        _payload(_metric("flights_climbed", units="count", points=points)), tz=TZ
    )

    row = result.rows[0]
    assert row.value == fragment * 59, (
        f"HEALTH-06 violated: 59 prorated fragments did not sum to their exact total. Expected "
        f"{fragment * 59}, got {row.value} -- a truncating cast reads this day as 0 flights"
    )
    assert row.value > 1, "a truncated day would land at 0; this one must not"
    assert row.sample_count == 59
    assert isinstance(row.value, Decimal)


def test_two_nutrition_sources_on_one_day_produce_two_rows() -> None:
    """Finding D, measured in the user's own export: on 2026-08-23 BOTH `Foodvisor` (1040 + 504
    + 670) and `Built With Science` (105 + 295.62) wrote `DietaryEnergyConsumed`.

    Blindly blending them yields 2,614.62 kcal, which is right only if the two apps logged
    disjoint food. `source_name` is in the natural key so the ingest can express the ambiguity
    instead of hiding it -- and so a later phase can decide with the evidence still present.
    """
    day = "2026-08-23"
    points = [
        _point(qty=1040, date=f"{day} 12:35:00 +0700", source="Foodvisor"),
        _point(qty=504, date=f"{day} 15:54:00 +0700", source="Foodvisor"),
        _point(qty=670, date=f"{day} 18:23:00 +0700", source="Foodvisor"),
        _point(qty=105, date=f"{day} 13:02:00 +0700", source="Built With Science"),
        _point(qty="295.62", date=f"{day} 19:40:00 +0700", source="Built With Science"),
    ]

    result = normalize_payload(
        _payload(_metric("dietary_energy", units="kcal", points=points)), tz=TZ
    )

    assert len(result.rows) == 2, (
        f"NUTR-02 violated: two sources on one day collapsed into {len(result.rows)} row(s). "
        f"Provenance is part of identity here; blending it is unrecoverable"
    )
    assert [row.source_name for row in result.rows] == ["Built With Science", "Foodvisor"]
    assert [row.value for row in result.rows] == [Decimal("400.62"), Decimal("2214")]
    assert [row.sample_count for row in result.rows] == [2, 3]


def test_nutrition_sodium_converts_from_grams_to_milligrams() -> None:
    """NUTR-02. `sodium` accepts both `g` and `mg` on the wire and is stored in `mg`, so the
    aggregation must run on CONVERTED values -- summing wire units and converting afterwards
    would be right only while a day never mixes them."""
    result = normalize_payload(
        _payload(
            _metric(
                "sodium",
                units="g",
                points=[_point(qty="1.5"), _point(qty="0.75", date=EVENING)],
            )
        ),
        tz=TZ,
    )

    assert result.rows[0].units == "mg"
    assert result.rows[0].value == Decimal("2250")
    assert result.rows[0].kind == "nutrition"


def test_an_avg_metric_produces_the_mean_rather_than_the_sum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `avg` metric is in the Phase 8 registry. The branch exists so Phase 13 does not have
    to reopen this code to add `walking_speed`, and this test is what keeps it honest -- an
    unexercised branch is one that silently sums a rate."""
    fake = {
        **METRIC_REGISTRY,
        "walking_speed": MetricSpec("km/hr", frozenset({"km/hr"}), "avg", "activity"),
    }
    monkeypatch.setattr(normalize, "METRIC_REGISTRY", fake)

    result = normalize_payload(
        _payload(
            _metric(
                "walking_speed",
                units="km/hr",
                points=[_point(qty="4.0"), _point(qty="5.0", date=EVENING)],
            )
        ),
        tz=TZ,
    )

    assert result.rows[0].value == Decimal("4.5"), (
        f"an aggregation='avg' metric was summed instead of averaged: got "
        f"{result.rows[0].value}. A summed rate grows with sampling frequency, which reads as "
        f"the user walking faster every time HAE's interval shrinks"
    )
    assert result.rows[0].sample_count == 2


# ---------------------------------------------------------------------------
# Open Question 2: kinds_present drives which D-03 sync_state resource advances
# ---------------------------------------------------------------------------


def test_kinds_present_is_activity_only_for_an_activity_payload() -> None:
    result = normalize_payload(
        _payload(_metric("step_count", units="count", points=[_point(qty=2044)])), tz=TZ
    )

    assert result.kinds_present == frozenset({"activity"})


def test_kinds_present_is_nutrition_only_for_a_nutrition_payload() -> None:
    result = normalize_payload(
        _payload(_metric("protein", units="g", points=[_point(qty="155.7")])), tz=TZ
    )

    assert result.kinds_present == frozenset({"nutrition"})


def test_kinds_present_covers_activity_and_nutrition_for_a_mixed_payload() -> None:
    result = normalize_payload(
        _payload(
            _metric("step_count", units="count", points=[_point(qty=2044)]),
            _metric("protein", units="g", points=[_point(qty="155.7")]),
        ),
        tz=TZ,
    )

    assert result.kinds_present == frozenset({"activity", "nutrition"})


def test_kinds_present_is_empty_when_every_datapoint_was_dropped() -> None:
    """Open Question 2. A payload that PARSED but yielded nothing must not advance either
    `sync_state` resource: reporting nutrition "fresh" while the logging app has stopped
    writing to HealthKit is precisely the blind spot D-03 exists to remove."""
    result = normalize_payload(
        _payload(
            _metric("protein", units="furlongs", points=[_point(qty="155.7")]),
            _metric("step_count", units="count", points=[_point(qty=None)]),
        ),
        tz=TZ,
    )

    assert result.rows == ()
    assert result.kinds_present == frozenset(), (
        f"Open Question 2 violated: a payload whose every datapoint was dropped reported "
        f"kinds {sorted(result.kinds_present)} as present, which would advance a sync_state "
        f"cursor over data that was never stored"
    )


# ---------------------------------------------------------------------------
# Determinism, ordering, and the multi-point-day guard
# ---------------------------------------------------------------------------


def test_rows_are_sorted_by_metric_then_source_name_then_local_day() -> None:
    """The order is part of the CONTRACT: plan 08-06 writes rows in it, and a nondeterministic
    order would make two runs over one payload produce different SAVEPOINT sequences -- a
    difference that only ever surfaces under a partial failure."""
    result = normalize_payload(
        _payload(
            _metric(
                "step_count",
                units="count",
                points=[
                    _point(qty=1, source="iPhone", date=EVENING),
                    _point(qty=2, source="Apple Watch", date=MORNING),
                    _point(qty=3, source="iPhone", date="2025-08-14 08:00:00 +0900"),
                ],
            ),
            _metric("protein", units="g", points=[_point(qty=10)]),
        ),
        tz=TZ,
    )

    assert [(row.metric, row.source_name, row.local_day) for row in result.rows] == [
        ("protein", "iPhone", DAY),
        ("step_count", "Apple Watch", DAY),
        ("step_count", "iPhone", dt.date(2025, 8, 14)),
        ("step_count", "iPhone", DAY),
    ]


def test_multi_point_day_warns_once_per_key_and_never_with_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall N-2's silent failure made observable.

    More than one datapoint for a key means HAE's aggregation interval is not daily, so a batch
    boundary CAN fall inside a day and replace-semantics has become lossy. Under a correct
    device configuration this warning never fires.
    """
    payload = _payload(
        _metric(
            "step_count",
            units="count",
            points=[_point(qty=1000), _point(qty=2044, date=EVENING)],
        ),
        _metric("protein", units="g", points=[_point(qty="155.7")]),
    )

    result, entries = run_capturing_logs(monkeypatch, lambda: normalize_payload(payload, tz=TZ))

    warnings = _events(entries, "health_ingest_multi_point_day")
    assert len(warnings) == 1, (
        f"Pitfall N-2: expected exactly one multi-point warning -- one for the two-point "
        f"step_count key and none for the single-point protein key. Got {len(warnings)}"
    )
    assert warnings[0]["metric"] == "step_count"
    assert warnings[0]["source_name"] == "iPhone"
    assert warnings[0]["local_day"] == DAY.isoformat()
    assert warnings[0]["points"] == 2
    for forbidden in ("1000", "2044", "3044", "155.7"):
        assert forbidden not in json.dumps(warnings), (
            f"T-08-30 violated: the quantity {forbidden} reached the multi-point warning. This "
            f"line reports the SHAPE of a device misconfiguration, never the measurement"
        )
    assert result.rows[0].sample_count == 1  # protein sorts first


def test_normalize_payload_is_deterministic() -> None:
    """Pure and order-independent: two runs over one payload must be indistinguishable, or the
    idempotency plan 08-06 builds on top is only accidental."""
    payload = _payload(
        _metric(
            "step_count",
            units="count",
            points=[_point(qty=1000), _point(qty=2044, date=EVENING)],
        ),
        _metric("dietary_energy", units="kcal", points=[_point(qty=1857, source="Foodvisor")]),
        _metric("sleep_analysis", units="hr", points=[_point(qty="6.75")]),
    )

    assert normalize_payload(payload, tz=TZ) == normalize_payload(payload, tz=TZ)


def test_every_datapoint_is_either_inside_a_row_or_explained_by_a_drop() -> None:
    """The accounting identity `NormalizeResult` documents. Without it a datapoint could vanish
    between the registry gate and the bucket with nothing to show for it."""
    payload = _payload(
        _metric(
            "active_energy",
            units="kcal",
            points=[
                _point(qty="666.5", source="Hevy"),
                _point(qty="31.4", source=DEVICE_NAME),
                _point(qty=None),
                _point(qty="42.8", date="not a date"),
            ],
        ),
        _metric("sleep_analysis", units="hr", points=[_point(qty="6.75"), _point(qty="1.0")]),
        _metric("protein", units="g", points=[_point(qty="155.7")]),
    )

    result = normalize_payload(payload, tz=TZ)

    assert sum(row.sample_count for row in result.rows) == (
        result.datapoints_seen - result.datapoints_dropped
    ), (
        f"accounting identity broken: rows account for "
        f"{sum(row.sample_count for row in result.rows)} datapoints but "
        f"{result.datapoints_seen - result.datapoints_dropped} were accepted"
    )
    assert result.datapoints_seen == 7
    assert result.datapoints_dropped == 5
    assert result.metrics_unrecognized == 1


# ---------------------------------------------------------------------------
# Pitfall N-4: the local day is resolved from `users.timezone`, not from the wire date part
# ---------------------------------------------------------------------------

# A nutrition app writing a DAILY TOTAL anchors it at its own local midnight. Verbatim from a
# real captured payload.
MIDNIGHT_JST = "2025-08-15 00:00:00 +0900"


def test_midnight_anchored_point_uses_local_day_not_the_payload_date() -> None:
    """Pitfall N-4. A nutrition app writes a DAILY TOTAL anchored at its own local midnight.

    `"2025-08-15 00:00:00 +0900"` read in Asia/Jakarta (+07:00) is 2025-08-14 22:00, so the row
    belongs to 2025-08-14. That is the INTENDED answer, not a bug: `local_day` is the
    project-wide rule (FOUND-03), and a travelling user's nutrition genuinely belongs to the
    local day they ate it. Today the phone emits +0700 and `users.timezone` is Asia/Jakarta, so
    the two agree and this is dormant -- it activates on travel or a mis-set timezone, which is
    exactly when nobody would be looking. This test is the documentation.
    """
    result = normalize_payload(
        _payload(
            _metric(
                "dietary_energy",
                units="kcal",
                points=[_point(qty=1857, date=MIDNIGHT_JST, source="Foodvisor")],
            )
        ),
        tz=TZ,
    )

    assert result.rows[0].local_day == dt.date(2025, 8, 14), (
        f"NUTR-02: a midnight-anchored daily total was attributed to "
        f"{result.rows[0].local_day} instead of the local day the +07:00 user was living in. "
        f"The visible symptom is a nutrition day reading zero next to a neighbouring day "
        f"reading double"
    )


def test_the_same_instant_lands_on_the_next_day_in_a_matching_timezone() -> None:
    """The counterpart. Identical payload, `tz` the only difference -- which is what proves the
    parameter is genuinely read.

    `core/time.py` is explicit that a module-level timezone default "would let a
    wrong-timezone bug pass every test". A single-timezone test suite is that default in
    disguise: it cannot tell a correct `local_day(ts, tz)` from a hardcoded one.
    """
    payload = _payload(
        _metric(
            "dietary_energy",
            units="kcal",
            points=[_point(qty=1857, date=MIDNIGHT_JST, source="Foodvisor")],
        )
    )

    assert normalize_payload(payload, tz="Asia/Tokyo").rows[0].local_day == dt.date(2025, 8, 15)
    assert normalize_payload(payload, tz=TZ).rows[0].local_day == dt.date(2025, 8, 14)


@pytest.mark.parametrize(
    ("timezone", "expected"),
    [
        ("Asia/Tokyo", dt.date(2025, 8, 15)),  # +09:00, the device's own zone
        ("Asia/Jakarta", dt.date(2025, 8, 14)),  # +07:00, today's users.timezone
        ("UTC", dt.date(2025, 8, 14)),  # +00:00
        ("America/New_York", dt.date(2025, 8, 14)),  # -04:00, the far side
    ],
)
def test_the_timezone_parameter_alone_decides_the_day(timezone: str, expected: dt.date) -> None:
    """FOUND-03. Four zones, one instant, three distinct answers -- a hardcoded zone anywhere in
    the path collapses these into one and fails here."""
    result = normalize_payload(
        _payload(
            _metric(
                "dietary_energy",
                units="kcal",
                points=[_point(qty=1857, date=MIDNIGHT_JST, source="Foodvisor")],
            )
        ),
        tz=timezone,
    )

    assert result.rows[0].local_day == expected


# ---------------------------------------------------------------------------
# The real captured fixtures, end to end
# ---------------------------------------------------------------------------


def test_the_hevy_fixture_excludes_hevy_and_keeps_the_iphone_rows() -> None:
    """HEALTH-08 against the measured 2026-01-02 training day: Hevy wrote 666.5 kcal in one
    lump record, the iPhone wrote 94.2 kcal across three."""
    result = normalize_payload(HAEPayload.model_validate(hae_fixture("hevy_active_energy")), tz=TZ)

    assert "Hevy" not in {row.source_name for row in result.rows}, (
        "HEALTH-08 violated: a Hevy-sourced active_energy datapoint became a row. Hevy writes "
        "ActiveEnergyBurned to Apple Health on every training day at 70-88% of that day's "
        "total, so ingesting it double-counts a session BRETT already holds at set-level "
        f"detail. Observed source names: {sorted({row.source_name for row in result.rows})}"
    )
    # The negative space. A predicate that excluded EVERYTHING would satisfy the assertion
    # above vacuously, and Pitfall N-3's stated warning sign is a filter that never matches.
    assert result.rows, (
        "HEALTH-08 satisfied vacuously: the exclusion removed every row, including the "
        "iPhone's own active energy. That is data loss wearing the costume of a passing test"
    )
    assert {row.source_name for row in result.rows} == {DEVICE_NAME}
    assert result.rows[0].value == Decimal("94.2")
    assert result.rows[0].sample_count == 3
    assert result.rows[0].local_day == dt.date(2026, 1, 2)
    assert all(row.value < Decimal("666.5") for row in result.rows), (
        "HEALTH-08: a row carries at least the Hevy lump record's magnitude, so the exclusion "
        "either did not run or ran after aggregation"
    )
    assert result.datapoints_dropped == 1


def test_the_activity_and_nutrition_fixture_produces_one_row_per_metric() -> None:
    """All twelve allowlisted metrics in HAE's real envelope, with the verified vendor
    spellings. This is the case that proves activity and nutrition need ONE normalizer."""
    result = normalize_payload(
        HAEPayload.model_validate(hae_fixture("activity_and_nutrition")), tz=TZ
    )

    assert len(result.rows) == 12, (
        f"HEALTH-06/NUTR-02: expected one row per allowlisted metric, got {len(result.rows)}"
    )
    assert {row.metric for row in result.rows} == set(METRIC_REGISTRY)
    assert result.kinds_present == frozenset({"activity", "nutrition"})
    assert result.metrics_unrecognized == 0

    by_metric = {row.metric: row for row in result.rows}
    assert by_metric["sodium"].units == "mg", (
        f"NUTR-02: sodium is stored in milligrams -- a gram-valued sodium row is off by 1000 "
        f"and looks plausible. Got {by_metric['sodium'].units}"
    )
    assert by_metric["flights_climbed"].value == Decimal("0.20163697817574894"), (
        "Finding C: HAE prorates count metrics, so this real datapoint is fractional. A "
        "truncating cast reads it as 0 flights with no error anywhere"
    )
    # Both two-point metrics land on the same local day, so neither splits into two rows.
    assert by_metric["step_count"].sample_count == 2
    assert by_metric["walking_running_distance"].sample_count == 2
    # The nutrition metrics are all midnight-anchored at +0900 -- Pitfall N-4 in the fixture.
    assert by_metric["protein"].local_day == dt.date(2025, 8, 14)
    assert by_metric["step_count"].local_day == DAY


def test_the_unrecognized_fixture_still_produces_the_step_count_row() -> None:
    """D-04, D-01 and D-02 in one payload: `walking_speed` (unlisted), `sleep_analysis`
    (unlisted), `weight_body_mass` (D-01) and a `workouts` sibling (D-02) all cost only
    themselves, and the one allowlisted metric beside them still lands."""
    result = normalize_payload(
        HAEPayload.model_validate(hae_fixture("unrecognized_and_sourceless")), tz=TZ
    )

    assert [row.metric for row in result.rows] == ["step_count"], (
        f"D-04 violated: an unlisted metric took the recognised one down with it. Health Auto "
        f"Export has no documented retry, so that is permanent loss of the window. Rows: "
        f"{[row.metric for row in result.rows]}"
    )
    assert result.metrics_unrecognized >= 3
    assert "weight_body_mass" not in {row.metric for row in result.rows}, (
        "D-01 violated: Apple Health body mass became a row. Phase 8 deliberately adds no "
        "third source to body_measurements, and there is nothing to arbitrate a conflict with"
    )
    assert result.rows[0].sample_count == 1
    assert result.rows[0].local_day == DAY


# ---------------------------------------------------------------------------
# T-08-30 / FOUND-05: no measured quantity may reach the log sink
# ---------------------------------------------------------------------------


def _qty_origins(name: str) -> dict[str, str]:
    """Map every `qty` spelling in a fixture to the metric it came from.

    Walked out of the parsed fixture rather than listed by hand, so the forbidden set cannot
    drift away from the files it exists to protect. The VALUE is the key and the ORIGIN is the
    payload, so a failure can name the metric without printing the measurement.
    """
    origins: dict[str, str] = {}
    for metric in hae_fixture(name)["data"]["metrics"]:
        for point in metric.get("data", []):
            if "qty" not in point:
                continue
            for spelling in (str(point["qty"]), str(Decimal(str(point["qty"])))):
                origins[spelling] = f"{name}:{metric['name']}"
    return origins


def test_no_quantity_from_any_fixture_reaches_the_log_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blueprint 44 / FOUND-05. A calorie count and a macro gram figure are personal health
    data; a sync-lifecycle log carries counts and names and nothing else (T-08-30).

    Every logging path in the module is exercised: the unrecognised-metric warning, the
    hevy-exclusion line, the multi-point-day warning, and -- via a units-broken copy of the
    activity fixture -- the per-datapoint drop, which is the one that also carries a unit.
    """
    origins: dict[str, str] = {}
    payloads: list[dict[str, Any]] = []
    for name in ("activity_and_nutrition", "hevy_active_energy", "unrecognized_and_sourceless"):
        origins |= _qty_origins(name)
        payloads.append(hae_fixture(name))

    broken = hae_fixture("activity_and_nutrition")
    for metric in broken["data"]["metrics"]:
        metric["units"] = "furlongs"
    payloads.append(broken)

    def _normalize_all() -> None:
        for raw in payloads:
            normalize_payload(HAEPayload.model_validate(raw), tz=TZ)

    _, entries = run_capturing_logs(monkeypatch, _normalize_all)

    # Without these the whole test passes trivially on an empty buffer, which is exactly what a
    # mis-wired capture produces.
    for expected in (
        "health_ingest_unrecognized_metric",
        "health_ingest_hevy_source_excluded",
        "health_ingest_multi_point_day",
        "health_ingest_datapoint_dropped",
    ):
        assert _events(entries, expected), f"log capture is not wired: no {expected} event"

    # `timestamp` is dropped before the scan: its microsecond field is an unconstrained
    # six-digit number that will eventually contain a short quantity by chance, and a suite
    # that goes red once a fortnight teaches people to re-run it rather than read it.
    scanned = json.dumps(
        [{key: value for key, value in entry.items() if key != "timestamp"} for entry in entries]
    )
    leaked = sorted({origin for spelling, origin in origins.items() if spelling in scanned})

    assert not leaked, (
        f"FOUND-05 / T-08-30 violated: a measured quantity reached the log stream. Log lines "
        f"carry a metric name, a unit, a local_day, a source_name, a count or an exception "
        f"class name -- never a measurement. Leaking payload:metric pair(s): {leaked}"
    )

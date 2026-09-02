"""Two contracts of the Health Auto Export quarantine boundary (HEALTH-06, NUTR-02).

* **The metric-name registry** -- the twelve wire identifiers BRETT ingests, their canonical
  units and their aggregation functions. This half exists because of D-04: an unlisted metric
  is dropped with a log line and **no error**, so a misspelled name is a silent failure that no
  other test in this repo can see. The drift guard below is the only thing standing between a
  typo and a permanently empty nutrition table.
* **The wire models** -- that real captured HAE payloads survive the round trip into typed
  Python, and that the failures fail in the right direction: one odd datapoint must never cost
  the whole window, and a `ValidationError` must never echo this person's calorie counts.

This file never touches Postgres and never opens a socket.
"""

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.integrations.health_auto_export.errors import (
    HAEDateFormatError,
    HAEError,
    UnknownUnitError,
)
from app.integrations.health_auto_export.registry import METRIC_REGISTRY, to_canonical
from app.integrations.health_auto_export.schemas import (
    HAEDataPoint,
    HAEMetric,
    HAEPayload,
    parse_hae_datetime,
)
from tests.conftest import hae_fixture

# ---------------------------------------------------------------------------
# The registry: names
# ---------------------------------------------------------------------------

# Written out as LITERALS, duplicated from the registry on purpose -- exactly as
# `test_mcp_tool_schemas.py`'s `EXPECTED_TOOLS` is. Importing the constant and comparing it to
# itself would make this test assert a tautology and pass through any rename.
EXPECTED_METRICS = frozenset(
    {
        # Activity (HEALTH-06)
        "step_count",
        "active_energy",
        "basal_energy_burned",
        "walking_running_distance",
        "flights_climbed",
        # Nutrition (NUTR-02)
        "dietary_energy",
        "protein",
        "carbohydrates",
        "total_fat",
        "fiber",
        "dietary_sugar",
        "sodium",
    }
)


def test_metric_registry_is_exactly_the_expected_set() -> None:
    """The wire-name contract, asserted as EQUALITY so both failure directions are caught.

    Every one of these twelve names is `[VERIFIED]` three independent ways: the vendor's own
    reference server enum, five real captured device payloads, and an independent third-party
    Go receiver.
    """
    actual = set(METRIC_REGISTRY)

    assert actual == set(EXPECTED_METRICS), (
        f"the ingestible metric set changed. A REMOVED name means that metric is now silently "
        f"dropped by D-04 -- a log line, no error, and an empty column three phases later. An "
        f"ADDED name means data is being ingested that nothing downstream expects. "
        f"Missing: {sorted(EXPECTED_METRICS - actual)}; "
        f"unexpected: {sorted(actual - EXPECTED_METRICS)}"
    )


def test_metric_registry_has_exactly_twelve_entries() -> None:
    """Five activity + seven nutrition. A count is the cheapest possible drift signal."""
    assert len(METRIC_REGISTRY) == 12, f"expected 12 metrics, got {len(METRIC_REGISTRY)}"


def test_body_mass_and_workouts_are_not_ingestible() -> None:
    """D-01 and D-02, asserted rather than left to a code review.

    D-01: no Apple Health body mass in Phase 8 -- 52 of 79 body-mass records in the user's real
    export are Hevy's own HealthKit write-back, and there is no third source on
    `body_measurements` to arbitrate.
    D-02: nothing workout-shaped, ever -- 218 of 221 Apple Health workouts are Hevy re-exports
    that BRETT already holds at higher fidelity.
    """
    for forbidden in ("weight_body_mass", "weight_&_body_mass", "workouts"):
        assert forbidden not in METRIC_REGISTRY, (
            f"{forbidden!r} is in METRIC_REGISTRY. D-01 excludes Apple Health body mass and "
            f"D-02 excludes anything workout-shaped; ingesting either double-counts data BRETT "
            f"already holds from Hevy at higher fidelity"
        )


def test_nutrition_names_do_not_carry_a_spurious_dietary_prefix() -> None:
    """The naming trap, pinned in both directions.

    HAE's `dietary_` prefix is INCONSISTENT: the vendor's TypeScript enum KEYS are uniformly
    `DIETARY_*` while the WIRE VALUES mostly are not. Anyone reading the enum keys -- or
    generalising from `dietary_energy` -- writes `dietary_protein`, which D-04 drops silently.
    A real third-party fixture in the wild (`jare0014/obsidian-health-connect`) does exactly
    this and is wrong.
    """
    for wrong in ("dietary_protein", "dietary_carbohydrates", "dietary_fiber", "fat", "sugar"):
        assert wrong not in METRIC_REGISTRY, (
            f"{wrong!r} is in METRIC_REGISTRY but HAE never sends that name. D-04 would drop "
            f"the real metric silently and this column would simply stay empty"
        )

    for right in ("protein", "carbohydrates", "fiber", "total_fat", "dietary_sugar"):
        assert right in METRIC_REGISTRY, (
            f"{right!r} is missing from METRIC_REGISTRY. It is the spelling HAE actually "
            f"sends; without it that macro is never ingested and nothing fails"
        )


def test_registry_is_immutable() -> None:
    """`MappingProxyType`, for the reason `exercise_map.py`'s tables use it.

    A caller must not be able to retune ingestion at runtime -- a test or a request handler
    that mutated the table would change which metrics reach the database for every subsequent
    caller in the process (T-08-23).
    """
    with pytest.raises(TypeError):
        METRIC_REGISTRY["step_count"] = METRIC_REGISTRY["sodium"]  # type: ignore[index]


def test_canonical_unit_is_always_accepted() -> None:
    """A canonical unit outside its own `accepted_units` makes the metric unconvertible.

    Every datapoint would raise `UnknownUnitError` even when it arrived in precisely the unit
    BRETT stores -- a whole metric silently reduced to zero rows.
    """
    for metric, spec in METRIC_REGISTRY.items():
        assert spec.canonical_unit in spec.accepted_units, (
            f"{metric!r} declares canonical unit {spec.canonical_unit!r} which is not in its "
            f"own accepted_units {sorted(spec.accepted_units)} -- every datapoint for this "
            f"metric would be rejected"
        )


def test_every_metric_declares_a_known_kind_and_aggregation() -> None:
    """`kind` maps 1:1 onto D-03's two `sync_state` resources; a third value would orphan rows."""
    for metric, spec in METRIC_REGISTRY.items():
        assert spec.kind in ("activity", "nutrition"), f"{metric!r} has kind {spec.kind!r}"
        assert spec.aggregation in ("sum", "avg"), f"{metric!r} aggregates by {spec.aggregation!r}"


# ---------------------------------------------------------------------------
# The registry: unit conversion (selectable with `-k unit_conversion`)
# ---------------------------------------------------------------------------


def test_unit_conversion_kj_to_kcal_divides_by_the_thermochemical_constant() -> None:
    """HAE units are a user preference in the phone app; a kJ export must not be stored raw."""
    result = to_canonical(
        Decimal("1000"), "kJ", METRIC_REGISTRY["dietary_energy"], metric="dietary_energy"
    )

    assert result == Decimal("1000") / Decimal("4.184")


def test_unit_conversion_leaves_a_canonical_value_untouched() -> None:
    """mg IS sodium's canonical unit, so the observed value must survive bit-for-bit.

    `3177.165354330709` is a real observed qty -- the long mantissa is HAE's own unit
    conversion, and a scale factor applied here would be invisible and wrong.
    """
    observed = Decimal("3177.165354330709")

    result = to_canonical(observed, "mg", METRIC_REGISTRY["sodium"], metric="sodium")

    assert result == observed


def test_unit_conversion_grams_to_milligrams_scales_by_a_thousand() -> None:
    """The one nutrition metric whose canonical unit is not `g`."""
    result = to_canonical(Decimal("3.2"), "g", METRIC_REGISTRY["sodium"], metric="sodium")

    assert result == Decimal("3.2") * Decimal("1000")


def test_unit_conversion_miles_to_kilometres() -> None:
    """A US-locale iPhone sends `mi` even when HAE itself is set to metric."""
    result = to_canonical(
        Decimal("1"),
        "mi",
        METRIC_REGISTRY["walking_running_distance"],
        metric="walking_running_distance",
    )

    assert result == Decimal("1.609344")


def test_unit_conversion_rejects_an_unaccepted_unit() -> None:
    """An UNKNOWN unit is a rejected datapoint, never a silently stored raw number."""
    with pytest.raises(UnknownUnitError) as excinfo:
        to_canonical(Decimal("1"), "lb", METRIC_REGISTRY["sodium"], metric="sodium")

    assert excinfo.value.unit == "lb"
    assert excinfo.value.metric == "sodium"
    assert isinstance(excinfo.value, HAEError)


def test_unit_conversion_rejects_an_absent_units_field() -> None:
    """An empty `wire_unit` reaches the same rejection, deliberately.

    The metric-level `units` field was absent. Assuming the canonical unit here is exactly the
    silent failure `to_canonical` exists to prevent -- a plausible number that is quietly wrong.
    """
    with pytest.raises(UnknownUnitError):
        to_canonical(Decimal("155.7"), "", METRIC_REGISTRY["protein"], metric="protein")


def test_unit_conversion_error_carries_no_quantity() -> None:
    """T-08-22: a metric name and a unit are structural facts; a qty is personal health data."""
    leaky_qty = Decimal("3177.165354330709")

    with pytest.raises(UnknownUnitError) as excinfo:
        to_canonical(leaky_qty, "lb", METRIC_REGISTRY["sodium"], metric="sodium")

    rendered = str(excinfo.value)
    assert "3177" not in rendered
    assert re.search(r"\d", rendered) is None, (
        f"UnknownUnitError rendered a digit run: {rendered!r}. Nothing numeric belongs in this "
        f"message -- it reaches a log line and `sync_state.last_error`"
    )
    assert "lb" in rendered
    assert "sodium" in rendered


def test_unit_conversion_error_truncates_an_attacker_controlled_unit() -> None:
    """The unit string comes off the wire and lands in a log line, so it is bounded."""
    error = UnknownUnitError(metric="sodium", unit="x" * 500)

    assert len(error.unit) == 32
    assert len(str(error)) < 200


# ---------------------------------------------------------------------------
# The wire models
# ---------------------------------------------------------------------------

JAKARTA = dt.timezone(dt.timedelta(hours=7))
TOKYO = dt.timezone(dt.timedelta(hours=9))

# Distinctive on purpose, and planted in the field that actually FAILS validation: pydantic
# only renders the offending field's input, so putting this in a valid neighbouring field
# would make the assertion pass for the wrong reason.
LEAKY_QTY = "919293-must-not-be-echoed"

# Written as an ESCAPE, never as a literal, for the reason the parser's own constant is:
# a bare U+202F is invisible in every diff and every review.
NARROW_NO_BREAK_SPACE = "\u202f"


def test_the_real_captured_payload_yields_all_twelve_metrics() -> None:
    """The whole point of the fixture: HAE's real envelope round-trips into typed Python."""
    payload = HAEPayload.model_validate(hae_fixture("activity_and_nutrition"))

    names = [metric.name for metric in payload.data.metrics]

    assert len(names) == 12
    assert set(names) == set(EXPECTED_METRICS)
    for metric in payload.data.metrics:
        assert metric.units, f"{metric.name!r} lost its metric-level units field"
        assert metric.data, f"{metric.name!r} lost its datapoints"


def test_units_are_read_from_the_metric_level_not_the_datapoint() -> None:
    """The vendor's own TypeScript declares `units` per datapoint; no real payload has it there.

    The vendor's `mapMetric` reads `metric.units`. Reading a datapoint-level field would find
    nothing in every real payload and silently make every unit unknown.
    """
    payload = HAEPayload.model_validate(hae_fixture("activity_and_nutrition"))
    by_name = {metric.name: metric for metric in payload.data.metrics}

    assert by_name["sodium"].units == "mg"
    assert by_name["dietary_energy"].units == "kcal"
    assert by_name["flights_climbed"].units == "count"
    assert not hasattr(by_name["sodium"].data[0], "units")


def test_a_datapoint_with_no_source_key_validates() -> None:
    """`source` is ABSENT ENTIRELY for gait metrics in every real captured payload.

    The vendor's interface declares it required. A model that agreed would raise here, and
    because pydantic validates atomically that would cost the whole window -- including the
    `step_count` metric sitting beside it, which is perfectly good data.
    """
    payload = HAEPayload.model_validate(hae_fixture("unrecognized_and_sourceless"))
    by_name = {metric.name: metric for metric in payload.data.metrics}

    walking_speed = by_name["walking_speed"]

    assert walking_speed.data, "the sourceless metric lost its datapoints"
    for point in walking_speed.data:
        assert point.source is None
    assert by_name["step_count"].data[0].source == "iPhone"


def test_a_metric_with_no_units_key_validates_as_empty_string() -> None:
    """A units-less metric must not fail the whole payload.

    `to_canonical` rejects `""` per datapoint, loudly and one row at a time, which is the
    correct blast radius for this failure.
    """
    metric = HAEMetric.model_validate(
        {"name": "protein", "data": [{"qty": 155.7, "date": "2025-08-15 00:00:00 +0900"}]}
    )

    assert metric.units == ""

    with pytest.raises(UnknownUnitError):
        to_canonical(Decimal("155.7"), metric.units, METRIC_REGISTRY["protein"], metric="protein")


def test_a_heart_rate_shaped_metric_without_qty_does_not_fail_the_payload() -> None:
    """The sharpest case D-04 exists for.

    A user toggling heart rate on in the phone app produces datapoints carrying Min/Max/Avg and
    NO `qty` at all. Health Auto Export has no documented retry, so a rejected batch is
    permanent data loss -- one required field here would destroy a whole day of steps AND
    nutrition because of a metric BRETT does not even want.
    """
    payload = HAEPayload.model_validate(
        {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate",
                        "units": "count/min",
                        "data": [
                            {
                                "date": "2025-08-15 08:00:00 +0900",
                                "source": "iPhone",
                                "Min": 48,
                                "Max": 131,
                                "Avg": 62.5,
                            }
                        ],
                    },
                    {
                        "name": "step_count",
                        "units": "count",
                        "data": [{"qty": 4821.0, "date": "2025-08-15 08:00:00 +0900"}],
                    },
                ]
            }
        }
    )

    heart_rate, step_count = payload.data.metrics

    assert heart_rate.data[0].qty is None
    assert step_count.data[0].qty == Decimal("4821.0")


def test_the_workouts_sibling_is_structurally_ignored() -> None:
    """D-02, implemented by `extra="ignore"` rather than by a filter someone must remember.

    218 of 221 Apple Health workouts in the user's real export are Hevy re-exports. The array
    sits right beside `metrics` inside `data`; not modelling it is what makes it unreachable.
    """
    raw = hae_fixture("unrecognized_and_sourceless")
    assert "workouts" in raw["data"], "the fixture no longer exercises D-02"

    payload = HAEPayload.model_validate(raw)

    assert not hasattr(payload.data, "workouts")
    assert "workouts" not in payload.data.model_dump()


def test_qty_round_trips_exactly() -> None:
    """Finding C: HAE prorates `count` metrics, so a fraction with a long mantissa is REAL.

    `json.loads` hands pydantic a Python float and pydantic converts float->Decimal via the
    value's STRING form. If it went through the binary representation instead,
    `0.20163697817574894` would gain a 50-digit tail and every summed day would carry it.
    """
    payload = HAEPayload.model_validate(hae_fixture("activity_and_nutrition"))
    by_name = {metric.name: metric for metric in payload.data.metrics}

    assert by_name["flights_climbed"].data[0].qty == Decimal("0.20163697817574894")
    assert by_name["sodium"].data[0].qty == Decimal("3177.165354330709")


def test_the_date_stays_a_raw_wire_string() -> None:
    """Parsing inside the model would make one malformed timestamp a whole-payload failure."""
    payload = HAEPayload.model_validate(hae_fixture("activity_and_nutrition"))

    first = payload.data.metrics[0].data[0]

    assert first.date == "2025-08-15 08:00:00 +0900"
    assert isinstance(first.date, str)


# --- parse_hae_datetime ------------------------------------------------------


def test_parse_hae_datetime_handles_the_24_hour_wire_format() -> None:
    """The format all five real captured payloads use. Not ISO 8601."""
    parsed = parse_hae_datetime("2025-08-15 00:00:00 +0900")

    assert parsed == dt.datetime(2025, 8, 15, 0, 0, 0, tzinfo=TOKYO)
    assert parsed.utcoffset() == dt.timedelta(hours=9)


def test_parse_hae_datetime_handles_the_12_hour_locale_variant() -> None:
    """A 12-hour-locale phone sends AM/PM. Same data, different device settings."""
    parsed = parse_hae_datetime("2025-08-15 08:02:00 AM +0900")

    assert parsed == dt.datetime(2025, 8, 15, 8, 2, 0, tzinfo=TOKYO)


def test_parse_hae_datetime_handles_the_narrow_no_break_space_before_am() -> None:
    """Newer iOS inserts U+202F NARROW NO-BREAK SPACE before AM/PM, not a plain space.

    Built from an ESCAPE for the same reason the parser writes it as one: a bare U+202F is
    invisible in every diff and every review, and one editor normalising it to a plain space
    would silently turn this into a duplicate of the test above -- still green, testing nothing.
    The two guard assertions below fail loudly if that ever happens.
    """
    wire = f"2025-08-15 08:02:00{NARROW_NO_BREAK_SPACE}AM +0900"
    assert NARROW_NO_BREAK_SPACE in wire, "the narrow no-break space was normalised away"
    assert wire != "2025-08-15 08:02:00 AM +0900", "this is now a duplicate of the test above"

    parsed = parse_hae_datetime(wire)

    assert parsed == dt.datetime(2025, 8, 15, 8, 2, 0, tzinfo=TOKYO)


def test_parse_hae_datetime_handles_the_iso_variant() -> None:
    """A third-party receiver reports seeing a true ISO form; accepting it costs nothing."""
    parsed = parse_hae_datetime("2024-01-01T12:00:00+00:00")

    assert parsed == dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


def test_parse_hae_datetime_handles_the_users_own_records_csv_format() -> None:
    """The SAME parser serves Phase 9. Two parsers produce two shapes and a silent disagreement."""
    parsed = parse_hae_datetime("2026-08-21 12:35:53 +0700")

    assert parsed == dt.datetime(2026, 8, 21, 12, 35, 53, tzinfo=JAKARTA)


def test_parse_hae_datetime_rejects_an_unknown_format_without_echoing_it() -> None:
    """FOUND-04. A naive or unparsed timestamp silently mis-buckets a whole local day."""
    with pytest.raises(HAEDateFormatError) as excinfo:
        parse_hae_datetime("15/08/2025")

    assert "15/08/2025" not in str(excinfo.value)
    assert isinstance(excinfo.value, HAEError)


def test_parse_hae_datetime_rejects_a_naive_timestamp() -> None:
    """`core.time._require_aware` exists for exactly this reason.

    An ISO string with no offset parses fine and is WRONG: it would be bucketed against the
    server's idea of a day rather than the user's.
    """
    with pytest.raises(HAEDateFormatError):
        parse_hae_datetime("2024-01-01T12:00:00")


# --- failing in the right direction ------------------------------------------


def test_a_payload_missing_data_is_a_validation_error() -> None:
    """The one field that IS required. Its absence is a broken envelope, not an odd datapoint."""
    with pytest.raises(ValidationError):
        HAEPayload.model_validate({"metrics": []})


def test_metrics_that_is_not_a_list_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        HAEPayload.model_validate({"data": {"metrics": "not-a-list"}})


def test_validation_error_does_not_echo_the_payload() -> None:
    """T-08-21: `ValidationError.__str__` renders `input_value=...` unless told not to.

    That is this person's calorie counts and macro grams, in a string that reaches a log line
    and `sync_state.last_error`.
    """
    bad: dict[str, Any] = {
        "data": {
            "metrics": [
                {"name": "dietary_energy", "units": "kcal", "data": LEAKY_QTY},
            ]
        }
    }

    with pytest.raises(ValidationError) as excinfo:
        HAEPayload.model_validate(bad)

    rendered = str(excinfo.value)
    assert "input_value" not in rendered
    assert LEAKY_QTY not in rendered, (
        f"the ValidationError echoed the offending input. `hide_input_in_errors=True` is what "
        f"keeps health data out of this message. Got: {rendered!r}"
    )


def test_a_datapoint_accepts_every_field_being_absent() -> None:
    """Every field optional is a DELIBERATE deviation, so it is asserted rather than inferred."""
    point = HAEDataPoint.model_validate({})

    assert point.qty is None
    assert point.date is None
    assert point.source is None

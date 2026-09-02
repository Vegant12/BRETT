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

import re
from decimal import Decimal

import pytest

from app.integrations.health_auto_export.errors import HAEError, UnknownUnitError
from app.integrations.health_auto_export.registry import METRIC_REGISTRY, to_canonical

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

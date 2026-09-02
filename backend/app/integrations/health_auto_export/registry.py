"""The metric allowlist and the unit conversion (HEALTH-06, NUTR-02).

One table drives ingestion. What differs between an activity metric and a nutrition metric is
DATA, not code: the canonical unit, the accepted wire units, the aggregation function, and
which ``sync_state`` resource it advances (D-03). The vendor's own ``mapMetric`` routes all
twelve of these through one identical ``{qty, date, source}`` branch, so BRETT needs one
normalizer and one table, not two of each.
"""

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, NamedTuple

from app.integrations.health_auto_export.errors import UnknownUnitError

Agg = Literal["sum", "avg"]
Kind = Literal["activity", "nutrition"]  # maps 1:1 to D-03's two sync_state resources


class MetricSpec(NamedTuple):
    canonical_unit: str
    accepted_units: frozenset[str]  # every unit HAE is known to emit for this metric
    aggregation: Agg
    kind: Kind


# The ONLY place a metric name appears. `MappingProxyType` for the reason `exercise_map.py`'s
# tables use it: a caller must not be able to retune ingestion at runtime (T-08-23).
#
# ### The naming trap ###
# HAE's `dietary_` prefix is INCONSISTENT and guessing it wrong is SILENT, not an error --
# D-04 drops an unlisted metric with a log line and no test failure. The vendor's TypeScript
# enum KEYS are uniformly `DIETARY_*` while the WIRE VALUES mostly are not:
#     carries the prefix : dietary_energy, dietary_sugar
#     does NOT carry it  : protein, carbohydrates, total_fat, fiber, sodium
# It is `total_fat`, never `fat`. It is `dietary_sugar`, never `sugar`. It is `protein`, never
# `dietary_protein` -- a real third-party fixture in the wild gets this wrong.
#
# Absent on purpose: `weight_body_mass` (D-01 -- no Apple Health body mass in Phase 8, and no
# third source on `body_measurements` to arbitrate) and anything workout-shaped (D-02).
METRIC_REGISTRY: Mapping[str, MetricSpec] = MappingProxyType(
    {
        # --- Activity (HEALTH-06) ---
        "step_count": MetricSpec("count", frozenset({"count"}), "sum", "activity"),
        "active_energy": MetricSpec("kcal", frozenset({"kcal", "kJ"}), "sum", "activity"),
        "basal_energy_burned": MetricSpec("kcal", frozenset({"kcal", "kJ"}), "sum", "activity"),
        "walking_running_distance": MetricSpec("km", frozenset({"km", "mi"}), "sum", "activity"),
        "flights_climbed": MetricSpec("count", frozenset({"count"}), "sum", "activity"),
        # --- Nutrition (NUTR-02) ---
        "dietary_energy": MetricSpec("kcal", frozenset({"kcal", "kJ"}), "sum", "nutrition"),
        "protein": MetricSpec("g", frozenset({"g"}), "sum", "nutrition"),
        "carbohydrates": MetricSpec("g", frozenset({"g"}), "sum", "nutrition"),
        "total_fat": MetricSpec("g", frozenset({"g"}), "sum", "nutrition"),
        "fiber": MetricSpec("g", frozenset({"g"}), "sum", "nutrition"),
        "dietary_sugar": MetricSpec("g", frozenset({"g"}), "sum", "nutrition"),
        "sodium": MetricSpec("mg", frozenset({"mg", "g"}), "sum", "nutrition"),
    }
)

_KJ_PER_KCAL = Decimal("4.184")
_KM_PER_MILE = Decimal("1.609344")
_MG_PER_G = Decimal("1000")


def to_canonical(qty: Decimal, wire_unit: str, spec: MetricSpec, *, metric: str) -> Decimal:
    """Convert at the boundary. An UNKNOWN unit is a REJECTED DATAPOINT, never a raw number.

    HAE units are a per-metric user preference inside the phone app and are converted on-device
    at export time, so a settings change silently alters the wire units on the next export.
    Storing an unconverted value would be a plausible number that is quietly wrong -- this
    project's stated primary risk. An empty ``wire_unit`` (the metric-level ``units`` field was
    absent) reaches the same rejection, deliberately: assuming the canonical unit is exactly the
    silent failure this function exists to prevent.
    """
    if wire_unit not in spec.accepted_units:
        raise UnknownUnitError(metric=metric, unit=wire_unit)
    if wire_unit == spec.canonical_unit:
        return qty
    if spec.canonical_unit == "kcal" and wire_unit == "kJ":
        return qty / _KJ_PER_KCAL
    if spec.canonical_unit == "km" and wire_unit == "mi":
        return qty * _KM_PER_MILE
    if spec.canonical_unit == "mg" and wire_unit == "g":
        return qty * _MG_PER_G
    # Unreachable while `accepted_units` and the branches above agree; a KeyError-equivalent
    # rather than a silent `return qty`, which is how an unconverted value gets stored.
    raise UnknownUnitError(metric=metric, unit=wire_unit)

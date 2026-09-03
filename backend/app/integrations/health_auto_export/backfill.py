"""Historical Apple Health backfill: export.xml -> the SAME rows the webhook writes (HEALTH-10).

The only new domain logic this phase is allowed is the XML tag walk and the twelve-entry
identifier mapping. Allowlisting, unit conversion, the Hevy exclusion, day bucketing and
aggregation all stay inside ``normalize.normalize_payload``, which is called ONCE for the whole
file. The ROADMAP's stated failure mode for Phase 9 is "two parsers produce two shapes and the
historical trend silently disagrees with the ongoing one"; the shortest way not to have two
parsers is not to write a second one.

PURE, and deliberately so. This module opens no connection and writes nothing: a path goes in, a
:class:`BackfillScan` comes out. The database half lives elsewhere, which is what lets every rule
below be pinned by a unit test in the fast suite instead of by an integration run.

Why this reuses ``normalize_payload`` literally
-----------------------------------------------
The CONTEXT non-negotiable is that the backfill and the webhook produce byte-identical rows for
the same logical datapoint. Two reuse shapes were measured end to end against the user's real
191 MB ``export.xml`` and BOTH produce the same answer -- 8,077 rows, identical counters:

    literal ``HAEPayload`` -> ``normalize_payload``    310.9 MB peak
    purpose-built streaming aggregator                  66.8 MB peak

The literal-payload shape costs 4.6x the memory and buys correctness BY CONSTRUCTION. The
purpose-built aggregator would re-derive allowlisting, unit conversion, the Hevy exclusion, day
bucketing and aggregation -- five places for the historical trend to drift away from the ongoing
one, each of which fails silently rather than loudly. 311 MB is irrelevant here because D-01 runs
this command on the user's own laptop, once, and never on Cloud Run's 1 GiB instance (T-09-09).

The two-clear memory discipline
-------------------------------
``elem.clear()`` alone is not enough. It empties the element but leaves it attached to the root,
so ``HealthData`` accumulates 438,649 empty ``Element`` objects. Measured on the real file:

    both clears                 2.5 s     16.2 MB
    ``elem.clear()`` only       2.6 s     53.5 MB
    no clear at all             3.2 s    385.2 MB
    ``ET.parse()`` full DOM     2.7 s    316.5 MB

Stdlib ``Element`` has no ``getparent()``, so there is no parent to clear from the element. The
workaround is not a parent stack: capture the root from the FIRST ``start`` event and call
``root.clear()`` in the same breath as ``elem.clear()``. That is safe here, and only here,
because every ``Record`` is a direct child of ``HealthData`` and is fully consumed at its ``end``
event -- nothing later in the walk reads a sibling.

Never key on ``type=`` alone
----------------------------
``<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="228" unit="kcal"/>``
is a CHILD of ``<Workout>`` -- 224 of them in the real file. It carries the same ``type=`` string
as a real ``Record``, it uses ``sum=`` rather than ``value=``, and it has no ``sourceName`` of its
own, so ``is_hevy_sourced(None)`` returns ``False`` by design (that ``None`` branch exists for the
gait-metric case) and would let Hevy's own workout energy in through the back door -- the exact
double-count HEALTH-08 exists to prevent, while the D-04 skip counter still cheerfully reported
the parent workout as skipped (T-09-06). Branch on ``elem.tag == "Record"`` FIRST, always.

Whole file, then write
----------------------
Positional chunking of the parse would be a data-loss bug, not an optimisation. ``export.xml`` is
grouped by record TYPE and only then chronologically, so one local day's records are scattered
across the entire file (``StepCount`` starts at line 88, ``DietaryFatTotal`` at line 229,852), and
the replace-semantics upsert silently drops the earlier half of a split day. It is also the reason
a multi-row ``ON CONFLICT DO UPDATE`` cannot raise ``CardinalityViolationError`` here:
``normalize_payload`` returns rows keyed by a dict, so duplicate conflict keys are structurally
impossible. The aggregate is 8,077 rows for 4.5 years -- hold the whole thing.

The logging rule
----------------
A metric **name**, a HealthKit **type identifier**, a **local_day**, a **source_name**, a **count**
and an exception **class name** are loggable. A measured quantity is not, ever, and neither is a
raw attribute value read out of the file: it is user-controlled input reaching a log sink, and the
counters already say everything a reader could act on (T-09-07, and the same rule ``ingest.py``
and ``normalize.py`` state).

XML trust
---------
The T-09-05 disposition is ACCEPT, recorded on the ``ET`` import below rather than only in the
threat register, because the ``noqa`` is where a future reader meets the decision.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# ruff's `S` (bandit) set flags stdlib XML parsing and recommends `defusedxml`. The disposition
# here is ACCEPT, not oversight (T-09-05). `defusedxml` was verified working on the real file
# (2.8 s, 16.6 MB, all 438,649 records) but its last release is 2021-03-08, and CLAUDE.md's
# "What NOT to Use" table rejects `python-jose` explicitly for being LESS stale than that. The
# input is a file the user exported from their own phone and stores locally; it is never network
# input; its DTD declares zero `ENTITY` declarations (pinned by
# `test_fixture_parses_and_declares_no_entities`); and Python's expat does not resolve external
# entities by default. A NETWORK-SOURCED XML path would require revisiting this decision.
from xml.etree import ElementTree as ET  # noqa: S314

import structlog

from app.integrations.health_auto_export.normalize import NormalizeResult
from app.integrations.health_auto_export.registry import METRIC_REGISTRY

log = structlog.get_logger()

# What `ET.iterparse(..., events=("start", "end"))` yields. Named so the scan's plumbing reads as
# prose and so the `("start", "end")` pairing is stated once rather than inferred at three sites.
_XMLEvent = tuple[str, ET.Element]

_RECORD_TAG = "Record"
_HK_BODY_MASS = "HKQuantityTypeIdentifierBodyMass"

# Counted and skipped BY NAME rather than lumped into "unrecognized": D-04 wants these two numbers
# on the summary specifically, because they are how success criterion #4 is confirmed without a
# persisted cross-check table. `WorkoutStatistics` is deliberately absent -- it is accounted for by
# its parent `Workout`, and counting it separately would suggest 224 extra skipped things.
_SKIP_AND_COUNT: frozenset[str] = frozenset({"Workout", "ActivitySummary"})

# The HealthKit identifier -> HAE wire metric name mapping. `MappingProxyType` for the reason
# `registry.py`'s table uses it: a caller must not be able to retune the backfill at runtime.
#
# ### The naming traps ###
# Each of these is a SILENT failure. An unlisted wire name is dropped by `normalize_payload`'s
# D-04 branch with one log line and no test failure -- the column simply stops filling.
#
#   DietaryFatTotal        -> total_fat                 (not `fat`, not `dietary_fat`)
#   DietarySugar           -> dietary_sugar             (KEEPS the prefix)
#   DietaryProtein         -> protein                   (DROPS the prefix)
#   DietaryEnergyConsumed  -> dietary_energy            (keeps prefix, drops `Consumed`)
#   DistanceWalkingRunning -> walking_running_distance  (word order REVERSES)
#
# Absent on purpose: `HKQuantityTypeIdentifierBodyMass` (D-01 -- `weight_body_mass` is not in
# METRIC_REGISTRY, so the allowlist is SC#4's first line of defence, before the Hevy predicate
# ever runs) and everything workout-shaped (D-02).
HK_TO_WIRE: Mapping[str, str] = MappingProxyType(
    {
        # --- Activity ---
        "HKQuantityTypeIdentifierStepCount": "step_count",
        "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy",
        "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_energy_burned",
        "HKQuantityTypeIdentifierDistanceWalkingRunning": "walking_running_distance",
        "HKQuantityTypeIdentifierFlightsClimbed": "flights_climbed",
        # --- Nutrition ---
        "HKQuantityTypeIdentifierDietaryEnergyConsumed": "dietary_energy",
        "HKQuantityTypeIdentifierDietaryProtein": "protein",
        "HKQuantityTypeIdentifierDietaryCarbohydrates": "carbohydrates",
        "HKQuantityTypeIdentifierDietaryFatTotal": "total_fat",
        "HKQuantityTypeIdentifierDietaryFiber": "fiber",
        "HKQuantityTypeIdentifierDietarySugar": "dietary_sugar",
        "HKQuantityTypeIdentifierDietarySodium": "sodium",
    }
)

# TOTAL in both directions, checked at IMPORT time: a registry entry with no identifier is a
# metric that can never be backfilled, and an identifier pointing at a non-registry name is a
# metric that is silently dropped. Neither has a runtime symptom (T-09-08). A test asserts the
# same thing, but a test only runs when someone runs it -- this fires on the import that the
# broken code would have needed anyway.
if set(HK_TO_WIRE.values()) != set(METRIC_REGISTRY):
    raise RuntimeError("HK_TO_WIRE and METRIC_REGISTRY have diverged")


@dataclass(frozen=True, slots=True)
class BackfillScan:
    """Everything one pass over export.xml produced, BEFORE any database contact.

    Counts and names only -- ``normalized.rows`` carries values, which is why this object is
    never handed to a log call whole.

    The record accounting identity a test pins::

        records_total == normalized.datapoints_seen + records_unrecognized
                         + body_mass_skipped + records_malformed

    Every ``<Record>`` in the file is either inside a datapoint or explained by one of three
    counters, so a silently vanishing record has nowhere to hide. ``workouts_skipped`` and
    ``activity_summaries_skipped`` sit outside the identity on purpose: they count elements that
    are not ``Record``\\ s at all, and D-04 wants them reported separately because they are how
    success criterion #4 is confirmed without a persisted cross-check table.

    ``hevy_datapoints_excluded`` is ADVISORY. The exclusion itself happens inside
    ``normalize_payload``, so there is exactly one implementation of HEALTH-08; this counter only
    lets D-06's summary say how many, and Pitfall N-3's stated warning sign -- "a filter that
    never excludes anything" -- stay observable.
    """

    normalized: NormalizeResult
    records_total: int
    records_unrecognized: int
    records_malformed: int
    body_mass_skipped: int
    workouts_skipped: int
    activity_summaries_skipped: int
    hevy_datapoints_excluded: int
    multi_point_days: int
    unrecognized_types: Mapping[str, int]

"""Historical Apple Health backfill: export.xml -> the SAME rows the webhook writes (HEALTH-10).

The only new domain logic this phase is allowed is the XML tag walk and the twelve-entry
identifier mapping. Allowlisting, unit conversion, the Hevy exclusion, day bucketing and
aggregation all stay inside ``normalize.normalize_payload``, which is called ONCE for the whole
file. The ROADMAP's stated failure mode for Phase 9 is "two parsers produce two shapes and the
historical trend silently disagrees with the ongoing one"; the shortest way not to have two
parsers is not to write a second one.

Two halves, and the seam between them is load-bearing. :func:`scan_export` is PURE: a path goes
in, a :class:`BackfillScan` comes out, no connection is opened and nothing is written, which is
what lets every parsing rule below be pinned by a unit test in the fast suite instead of by an
integration run. :func:`run_backfill` is the write half, and it does nothing the parse can do --
it takes the finished aggregate and puts it in the database.

The write half: chunked, with a per-row fallback
------------------------------------------------
Phase 8's ``ingest_payload`` opens a SAVEPOINT per row. Measured against real PostgreSQL 18 that
is **3.0 round trips per row** (``SAVEPOINT`` + ``INSERT`` + ``RELEASE``), which is correct and
cheap for a 23-row webhook delivery and ruinous for 8,077: 24,231 round trips over the public
internet to Neon, roughly 12 minutes at 30 ms RTT and 90 minutes at 230 ms. A chunked multi-row
``INSERT ... ON CONFLICT DO UPDATE`` costs 0.0025 round trips per row -- about 17 statements for
the whole file.

:func:`_write_rows` is the hybrid: one statement per chunk, and when a chunk raises, Phase 8's
exact per-row path is replayed for THAT CHUNK ONLY. D-07's guarantee -- one bad row costs that
row and never the run -- is preserved at about 1/1400 the round trips, and the worst case for a
single bad value is 500 rows' worth of retries rather than 8,077.

The fallback arm is expected to be dead code in practice: the value audit found zero malformed
values in the real file. It exists for the guarantee, not for the traffic.

Why a multi-row upsert is safe here specifically
-----------------------------------------------
A multi-row ``ON CONFLICT DO UPDATE`` carrying two rows with the same conflict key raises
``CardinalityViolationError`` ("command cannot affect row a second time") -- reproduced against
real PostgreSQL 18. It cannot happen here because ``normalize_payload`` returns rows keyed by a
dict on ``(metric, source_name, local_day)``, so duplicate conflict keys are structurally
impossible. That is a second, independent reason the whole-file aggregation below is mandatory
rather than an optimisation, and it holds only as long as the chunk list is built from a SINGLE
``NormalizeResult`` and never from two concatenated ones.

The conflict clause is IMPORTED, not restated
---------------------------------------------
:func:`_upsert_many` binds ``ON CONFLICT`` to ``ingest._CONFLICT_CONSTRAINT`` and sets exactly
the four columns ``ingest.upsert_health_metric`` sets. Both facts are enforced by reuse rather
than by comment: re-declaring the constraint name as a literal here would defeat the whole point
of binding by name, and a divergent ``set_`` dict would mean a day written by the backfill and
re-written by the webhook ends up shaped differently from one written by the webhook twice.

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

The rule extends to STDOUT. ``cli.py`` prints :func:`format_summary`'s block, and a summary line
carrying a calorie total is the same leak as a log line carrying one -- the destination differs,
the data does not (T-09-14).

XML trust
---------
The T-09-05 disposition is ACCEPT, recorded on the ``ET`` import below rather than only in the
threat register, because the ``noqa`` is where a future reader meets the decision.
"""

import datetime as dt
import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
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
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models.health import HealthDailyMetric
from app.db.repositories.sync_state import (
    PROVIDER_APPLE_HEALTH,
    complete_sync,
    ensure_sync_state,
    record_sync_error,
)
from app.integrations.health_auto_export.errors import HAEExportFileError

# The four names below are IMPORTED, never restated. `_CONFLICT_CONSTRAINT` bound by name is the
# whole point of binding by name -- a literal copy here would keep working through a rename and
# silently degrade into duplicate rows. `_KIND_TO_RESOURCE` is D-03's table and must stay total in
# exactly one place. `upsert_health_metric` IS the per-row fallback arm, not a reimplementation of
# it. `_user_timezone` is the FOUND-03 read, and a second copy is how a default would creep in.
from app.integrations.health_auto_export.ingest import (
    _CONFLICT_CONSTRAINT,
    _KIND_TO_RESOURCE,
    _user_timezone,
    upsert_health_metric,
)
from app.integrations.health_auto_export.normalize import (
    SOURCE_APPLE_HEALTH,
    NormalizedRow,
    NormalizeResult,
    is_hevy_sourced,
    normalize_payload,
)
from app.integrations.health_auto_export.registry import METRIC_REGISTRY
from app.integrations.health_auto_export.schemas import HAEPayload

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

# Measured against real PostgreSQL 18: 3.0 round trips per row for the per-row SAVEPOINT path
# (24,231 for 8,077 rows) versus 0.0025 for a chunked multi-row insert. 500 is a TUNING constant
# with no correctness role -- anything from 100 to 2,000 behaves identically at this data volume --
# because `normalize_payload` guarantees no two rows share a conflict key.
_CHUNK = 500

# Heartbeat interval (D-05). The parse is 3.5 s on the real 191 MB file; the NETWORK WRITE is the
# slow phase, which is why the heartbeat lives on the write loop and not on the parse. A parse
# heartbeat would print once. ~16 lines for a full 8,077-row backfill.
_HEARTBEAT_ROWS = 500

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


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    """What the run did. Counts, metric names, units and dates -- never a measured value.

    EXTENDS :class:`BackfillScan` by composition rather than by copying its nine counters: two
    objects holding the same numbers is two places for them to disagree, and the summary block
    reports both halves of the run.

    The logging rule (``ingest.py``) applies to STDOUT as well as to logs. ``cli.py`` prints this
    object through :func:`format_summary`, and a summary line carrying a calorie total is the same
    leak as a log line carrying one (T-09-14).

    ``rows_written`` is a WOULD-WRITE count on a dry run: the number of rows the aggregate holds,
    which is exactly what a real run would upsert. ``resources_advanced`` is empty on a dry run and
    on a real run that wrote nothing -- both are runs with no freshness claim to make.
    """

    scan: BackfillScan
    dry_run: bool
    rows_written: int
    rows_skipped: int
    rows_by_metric: Mapping[str, int]
    first_day: dt.date | None
    last_day: dt.date | None
    resources_advanced: tuple[str, ...]


class _MultiPointDayCounter(logging.Filter):
    """Swallow ``health_ingest_multi_point_day`` and count it instead (Pitfall 4).

    For the WEBHOOK that warning means the device's daily aggregation has drifted and replace
    semantics has become lossy -- ``ingest.py`` is explicit that "under a correct device
    configuration that warning never fires". For the BACKFILL it means raw HealthKit samples are
    per-event, which they always are: 7,403 of 8,077 rows on the real file, 91.7%. Left alone it
    inverts the warning's documented meaning and buries the Hevy-exclusion and skipped-record
    lines that actually matter.

    Attached to the root HANDLERS rather than to a logger: ``configure_logging`` installs one root
    ``StreamHandler``, a handler-level filter sees propagated records while a logger-level one
    does not, and every module in this package logs through its own ``structlog.get_logger()``.

    With ``ProcessorFormatter.wrap_for_formatter``, ``record.msg`` IS the structlog event dict --
    the final processor calls ``logger.warning(event_dict, extra=...)`` -- which is why this reads
    a key rather than matching on a rendered string.
    """

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        event = record.msg.get("event") if isinstance(record.msg, dict) else None
        if event == "health_ingest_multi_point_day":
            self.count += 1
            return False
        return True


@contextmanager
def _suppressing_multi_point_days() -> Iterator[_MultiPointDayCounter]:
    """Suppress-and-count for the duration of ONE ``normalize_payload`` call.

    Scoped deliberately narrowly. ``normalize.py`` is NOT changed: the webhook path must keep
    warning, because there the condition is real. Removal happens in a ``finally`` so a raising
    ``normalize_payload`` cannot leave a process-wide filter installed that silently eats the
    webhook's warning for the rest of the run.

    A process that never called ``configure_logging`` has no root handlers, and unconfigured
    structlog does not route through stdlib logging at all -- so the warnings print and the count
    reads 0. That degrades the D-06 summary line rather than failing the run, and it cannot
    happen on the real path: ``cli.py`` calls ``configure_logging(settings)`` as the first thing
    ``main()`` does, before any logger or engine exists.
    """
    counter = _MultiPointDayCounter()
    # Snapshot the handler list: `configure_logging` replaces `root.handlers` wholesale, so
    # iterating the live list on the way out could remove the filter from a different handler
    # than the one it was added to.
    handlers = list(logging.getLogger().handlers)
    for handler in handlers:
        handler.addFilter(counter)
    try:
        yield counter
    finally:
        for handler in handlers:
            handler.removeFilter(counter)


def scan_export(path: Path, *, tz: str) -> BackfillScan:
    """Stream one ``export.xml`` into the rows the webhook would have written.

    PURE and synchronous: no database, no network, and no I/O beyond reading ``path``. The whole
    file is aggregated before anything is returned, for the two reasons the module docstring
    gives -- replace semantics is only safe on a complete aggregate, and a dict-keyed row set is
    what makes duplicate conflict keys structurally impossible.

    ``tz`` is keyword-only with no default, for the reason ``normalize._user_timezone`` states: a
    hardcoded default is how a wrong-timezone bug passes every test, and at UTC+7 it moves every
    evening datapoint onto the wrong local day.
    """
    try:
        it: Iterator[_XMLEvent] = ET.iterparse(path, events=("start", "end"))  # noqa: S314
        _, root = next(it)
    except (OSError, ET.ParseError, StopIteration) as exc:
        # Class name only, and no path. `str(ParseError)` renders a byte offset into a document
        # that is this person's entire health history (T-09-07), and the path is an operator
        # argument the operator already knows. `from None` for the reason `parse_hae_datetime`
        # gives: chaining re-attaches the exception whose message is the problem.
        log.error("health_backfill_unreadable", reason=type(exc).__name__)
        raise HAEExportFileError from None
    if root.tag != "HealthData":
        # Not a HealthKit export. A structural failure, not a salvageable element -- the same
        # distinction `parse_payload` draws between a broken envelope and an odd datapoint.
        log.error("health_backfill_unreadable", reason="root_element_is_not_healthdata")
        raise HAEExportFileError

    # Keyed on the METRIC NAME *and* the UNIT STRING, which costs nothing and closes a real hole:
    # HAE units are a per-metric user preference that changes silently on the next export, and one
    # `HAEMetric` carries exactly one metric-level `units`. Two entries with the same `name` and
    # different `units` both convert correctly through `to_canonical` and land in the SAME
    # `normalize_payload` bucket, so a mid-file unit change is handled with zero extra logic
    # instead of being silently mis-converted.
    buckets: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    unrecognized_types: dict[str, int] = defaultdict(int)
    skipped: dict[str, int] = defaultdict(int)
    records_total = 0
    records_unrecognized = 0
    records_malformed = 0
    body_mass_skipped = 0
    hevy_excluded = 0

    try:
        for event, elem in it:
            if event != "end":
                continue
            tag = elem.tag
            if tag == _RECORD_TAG:
                # The tag check comes FIRST and the `type=` read lives inside it: a
                # `<WorkoutStatistics>` carries the same `type=` string and no `sourceName`
                # (T-09-06). See the module docstring.
                records_total += 1
                hk_type = elem.get("type", "")
                if hk_type == _HK_BODY_MASS:
                    # Its own counter, not "unrecognized": D-01 is a decision, and a decision
                    # that reads as an accident on the summary invites someone to "fix" it.
                    body_mass_skipped += 1
                elif (wire := HK_TO_WIRE.get(hk_type)) is None:
                    unrecognized_types[hk_type] += 1
                    records_unrecognized += 1
                else:
                    raw_value = elem.get("value")
                    raw_date = elem.get("startDate")
                    unit = elem.get("unit", "")
                    source = elem.get("sourceName")
                    qty = _read_quantity(raw_value, raw_date, hk_type=hk_type)
                    if qty is None:
                        records_malformed += 1
                    else:
                        if is_hevy_sourced(source):
                            # ADVISORY ONLY -- the datapoint is still appended. The actual
                            # exclusion stays inside `normalize_payload`, so there is exactly one
                            # implementation of HEALTH-08 and the two paths cannot drift. Do not
                            # "fix" this apparent double handling by dropping the point here.
                            hevy_excluded += 1
                        point: dict[str, object] = {"qty": qty, "date": raw_date}
                        if source is not None:
                            # OMIT the key when absent, which is NOT the same as null: that is
                            # the gait-metric case `HAEDataPoint` models deliberately.
                            point["source"] = source
                        buckets[(wire, unit)].append(point)
            elif tag in _SKIP_AND_COUNT:
                skipped[tag] += 1
            # Nothing above may `continue` past these two. `MetadataEntry` and
            # `WorkoutStatistics` fall through uncounted and are still cleared --
            # `WorkoutStatistics` is accounted for by its parent `Workout`, and counting it
            # separately would suggest 224 extra skipped things.
            elem.clear()
            root.clear()  # BOTH clears. Without `root.clear()`: 53.5 MB instead of 16.2 MB.
    except ET.ParseError as exc:
        # A STRUCTURAL break, not a bad element: expat cannot continue, so there is no remaining
        # file for D-07's log-and-continue to salvage. Class name only, same T-09-07 reason as
        # above -- the message carries a line and column into this person's health history.
        log.error("health_backfill_unreadable", reason=type(exc).__name__)
        raise HAEExportFileError from None

    datapoints = sum(len(points) for points in buckets.values())
    log.info(
        "health_backfill_parsed",
        records_total=records_total,
        datapoints=datapoints,
        unrecognized_records=records_unrecognized,
        body_mass_skipped=body_mass_skipped,
        malformed=records_malformed,
        workouts_skipped=skipped["Workout"],
        activity_summaries_skipped=skipped["ActivitySummary"],
    )
    # One line per DISTINCT identifier -- about 35 on the real file. One line per unrecognized
    # RECORD would be 208,175 lines. This mirrors `health_ingest_unrecognized_metric`'s
    # per-metric granularity, which is the same trade for the same reason.
    for hk_type, count in sorted(unrecognized_types.items()):
        log.warning("health_backfill_unrecognized_type", hk_type=hk_type, records=count)

    payload = HAEPayload.model_validate(
        {
            "data": {
                "metrics": [
                    {"name": name, "units": unit, "data": points}
                    # `sorted` because `normalize_payload`'s deterministic row order is part of
                    # its contract, and a nondeterministic metric order would make two runs over
                    # the same file produce different SAVEPOINT sequences -- a difference that
                    # only ever shows up under a partial failure.
                    for (name, unit), points in sorted(buckets.items())
                ]
            }
        }
    )
    with _suppressing_multi_point_days() as counter:
        normalized = normalize_payload(payload, tz=tz)

    return BackfillScan(
        normalized=normalized,
        records_total=records_total,
        records_unrecognized=records_unrecognized,
        records_malformed=records_malformed,
        body_mass_skipped=body_mass_skipped,
        workouts_skipped=skipped["Workout"],
        activity_summaries_skipped=skipped["ActivitySummary"],
        hevy_datapoints_excluded=hevy_excluded,
        multi_point_days=counter.count,
        # A plain, immutable snapshot. Handing the live `defaultdict` out would let a caller's
        # missing-key read silently create a zero entry and change what the summary reports.
        unrecognized_types=MappingProxyType(dict(unrecognized_types)),
    )


def _read_quantity(raw_value: str | None, raw_date: str | None, *, hk_type: str) -> Decimal | None:
    """D-07 per-record validation. Returns ``None`` for a record that must be skipped and counted.

    Not duplicated work, and not optional. ``HAEPayload.model_validate`` validates the payload
    ATOMICALLY, so a single ``value="not-a-number"`` anywhere in a 191 MB ``export.xml`` would
    raise ``ValidationError`` for all 230,395 datapoints at once. D-07 says one bad element must
    never cost the run.

    ``reason`` is a short fixed token, NEVER the offending string: that string is a raw attribute
    value out of a health-data file, and the token already says everything a reader can act on
    (T-09-07).
    """
    if raw_value is None:
        log.warning("health_backfill_record_skipped", hk_type=hk_type, reason="missing_value")
        return None
    if raw_date is None:
        log.warning("health_backfill_record_skipped", hk_type=hk_type, reason="missing_start_date")
        return None
    try:
        qty = Decimal(raw_value)
    except (InvalidOperation, ValueError):
        log.warning("health_backfill_record_skipped", hk_type=hk_type, reason="unparsable_value")
        return None
    if not qty.is_finite():
        # `Decimal("NaN")` and `Decimal("Infinity")` PARSE. Left through, they propagate into
        # `normalize_payload`'s sum and land in a `Numeric(14, 4)` column that accepts NaN --
        # a plausible-looking number that is quietly wrong, which is this project's stated
        # primary risk.
        log.warning("health_backfill_record_skipped", hk_type=hk_type, reason="non_finite_value")
        return None
    return qty


# ---------------------------------------------------------------------------
# The write half. Everything above this line is pure; everything below it needs a session.
# ---------------------------------------------------------------------------


async def _upsert_many(
    session: AsyncSession, *, user_id: uuid.UUID, rows: Sequence[NormalizedRow]
) -> None:
    """One ``INSERT ... ON CONFLICT DO UPDATE`` for a whole chunk.

    ``user_id`` is keyword-only with no default (ASVS V4), exactly as ``upsert_health_metric``
    declares it: the schema is multi-user-ready, so an unscoped write is a cross-tenant defect a
    single-user suite cannot see. It is resolved from the CLI argument, server-side. ``export.xml``
    cannot supply a user id and no code path here reads one from it (T-09-11).

    The conflict clause is bound to the constraint BY NAME -- through the IMPORTED
    ``_CONFLICT_CONSTRAINT``, never a literal -- and sets the SAME FOUR COLUMNS
    ``ingest.upsert_health_metric`` sets. Any divergence means a day written by the backfill and
    re-written by the webhook ends up shaped differently from one written by the webhook twice,
    which is exactly the two-paths-two-shapes failure this phase exists to prevent.

    Never commits: the caller owns the transaction, so the rows and the D-03 freshness timestamps
    land together or not at all.
    """
    statement = pg_insert(HealthDailyMetric).values(
        [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "source": SOURCE_APPLE_HEALTH,
                "metric": row.metric,
                "source_name": row.source_name,
                "local_day": row.local_day,
                "value": row.value,
                "units": row.units,
                "sample_count": row.sample_count,
            }
            for row in rows
        ]
    )
    statement = statement.on_conflict_do_update(
        constraint=_CONFLICT_CONSTRAINT,
        set_={
            "value": statement.excluded.value,
            "units": statement.excluded.units,
            "sample_count": statement.excluded.sample_count,
            # Explicit, mirroring `upsert_health_metric` and `sync_state._upsert`: SQLAlchemy's
            # `onupdate=func.now()` fires for an `update()` statement but is NOT injected into an
            # `ON CONFLICT DO UPDATE SET` clause, so omitting it freezes the audit timestamp at
            # row creation.
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)


async def _write_rows(
    session: AsyncSession, *, user_id: uuid.UUID, rows: Sequence[NormalizedRow]
) -> tuple[int, int]:
    """Chunked upsert with a per-row SAVEPOINT fallback. Returns ``(written, skipped)``.

    ``rows`` must come from a SINGLE ``NormalizeResult`` and from nothing else. Concatenating two
    of them would reintroduce duplicate conflict keys inside one statement, which real PostgreSQL
    answers with ``CardinalityViolationError`` -- see the module docstring.

    Never commits: the caller owns the transaction.
    """
    written = 0
    skipped = 0
    for start in range(0, len(rows), _CHUNK):
        chunk = rows[start : start + _CHUNK]
        try:
            async with session.begin_nested():
                await _upsert_many(session, user_id=user_id, rows=chunk)
        except SQLAlchemyError:
            # Fall back to `ingest.py`'s EXACT per-row path for THIS chunk only, so one bad row
            # costs 500 fast rows' worth of retries and never the whole run (D-07). The chunk's
            # own SAVEPOINT has already rolled back, so none of these rows is written twice.
            # The value audit found zero malformed values in the real file: this arm exists for
            # the guarantee, not for expected traffic.
            for row in chunk:
                try:
                    async with session.begin_nested():
                        await upsert_health_metric(session, user_id=user_id, row=row)
                except SQLAlchemyError as exc:
                    skipped += 1
                    # Class name only: `str(DataError)` renders the bound parameters, which here
                    # are this person's calorie counts (T-08-39, T-09-13).
                    log.warning(
                        "health_backfill_row_skipped",
                        metric=row.metric,
                        local_day=row.local_day.isoformat(),
                        source_name=row.source_name,
                        reason=type(exc).__name__,
                    )
                else:
                    written += 1
        else:
            written += len(chunk)
        if written and written % _HEARTBEAT_ROWS < _CHUNK:
            # `log.info`, never `print`: `print` is the answer to a question somebody asked (the
            # D-06 summary), `log.*` is the record of what the process did. The line still reaches
            # the operator's terminal because `configure_logging` installs a root `StreamHandler`
            # on stdout, which is what D-05 asks for.
            log.info("health_backfill_progress", rows_written=written, rows_total=len(rows))
    return written, skipped


def _summarize(
    scan: BackfillScan,
    *,
    dry_run: bool,
    rows_written: int,
    rows_skipped: int,
    resources_advanced: tuple[str, ...],
) -> BackfillSummary:
    """Derive the operator-facing counts from a finished scan. Pure, and the ONLY derivation.

    Both of :func:`run_backfill`'s exits build their summary here. Two copies of the
    ``rows_by_metric`` / ``first_day`` / ``last_day`` arithmetic is how a dry run would eventually
    report a different date range from the real run over the same file -- which is precisely the
    number a dry run exists to be trusted on.
    """
    rows = scan.normalized.rows
    days = [row.local_day for row in rows]
    return BackfillSummary(
        scan=scan,
        dry_run=dry_run,
        rows_written=rows_written,
        rows_skipped=rows_skipped,
        # A plain immutable snapshot, sorted, for the reason `unrecognized_types` is one: handing
        # a live `Counter` out would let a caller's missing-key read create a zero entry and
        # change what the summary reports.
        rows_by_metric=MappingProxyType(dict(sorted(Counter(row.metric for row in rows).items()))),
        first_day=min(days) if days else None,
        last_day=max(days) if days else None,
        resources_advanced=resources_advanced,
    )


async def run_backfill(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    path: Path,
    dry_run: bool,
) -> BackfillSummary:
    """Read ``path``, then write the rows it produced. The one public entry point ``cli.py`` calls.

    Deliberately the ONLY door: ``cli.py`` may not import ``registry`` or ``schemas``
    (``test_health_auto_export_isolation.py`` enforces it by name), so everything HealthKit-shaped
    has to be reachable through this function plus :func:`format_summary` -- exactly as
    ``api/routes/health_ingest.py`` reaches ``ingest`` without ever naming ``HAEPayload``.

    ONE transaction for the whole run. The rows and the two D-03 freshness timestamps commit
    together, so a crash can never leave a ``sync_state`` row claiming history that rolled back
    (T-09-15). Partial-write corruption of 4.5 years is the failure mode this shape closes.
    """
    async with sessionmaker() as session:
        # Read the zone BEFORE anything else and OUTSIDE the write try-block, for
        # `ingest_payload`'s stated reason: an unknown user is a caller bug, not a failed sync,
        # and recording it as one would put a bookkeeping row under a tenant that does not exist.
        tz = await _user_timezone(session, user_id=user_id)

        # Synchronous, pure, and COMPLETE before the first write. That is what makes the replace
        # conflict clause in `_upsert_many` unconditionally correct: `excluded` already carries
        # the whole file's total for a (metric, source_name, local_day) key, so there is nothing
        # left to accumulate.
        scan = scan_export(path, tz=tz)
        rows = scan.normalized.rows

        if dry_run:
            # BEFORE any write, and before any `sync_state` contact. A dry run that freshened
            # Apple Health would claim data is present that was never written (D-03, RESEARCH
            # Open Question 4): `complete_sync` sets `last_synced_at = now`, not "as of the newest
            # imported day".
            log.info("health_backfill_dry_run", rows_would_write=len(rows))
            return _summarize(
                scan, dry_run=True, rows_written=len(rows), rows_skipped=0, resources_advanced=()
            )

        written = 0
        skipped = 0
        advanced: list[str] = []
        try:
            written, skipped = await _write_rows(session, user_id=user_id, rows=rows)

            if written:
                # ONE instant for every resource this run advances, so activity and nutrition
                # cannot report fractionally different ages. Copied from `ingest_payload`.
                #
                # `if written` is the guard RESEARCH Open Question 4 asks for: a run that wrote
                # nothing has no freshness claim to make, and marking Apple Health fresh off an
                # empty run is the same lie a dry run would tell.
                now = utc_now()
                for kind in sorted(scan.normalized.kinds_present):
                    resource = _KIND_TO_RESOURCE[kind]
                    await ensure_sync_state(
                        session,
                        user_id=user_id,
                        provider=PROVIDER_APPLE_HEALTH,
                        resource=resource,
                    )
                    # In the SAME transaction as the rows above, and committed with them. No
                    # cursor is passed: a one-shot import has no resume point, and
                    # `complete_sync`'s own guard is what rejects a naive `last_synced_at`.
                    await complete_sync(
                        session,
                        user_id=user_id,
                        provider=PROVIDER_APPLE_HEALTH,
                        resource=resource,
                        last_synced_at=now,
                    )
                    advanced.append(resource)

            await session.commit()
        except SQLAlchemyError as exc:
            # A FRESH session: the one that raised is in an aborted transaction, and the
            # bookkeeping write has to succeed precisely when the backfill did not.
            async with sessionmaker() as bookkeeping:
                for kind in sorted(scan.normalized.kinds_present):
                    await record_sync_error(
                        bookkeeping,
                        user_id=user_id,
                        provider=PROVIDER_APPLE_HEALTH,
                        resource=_KIND_TO_RESOURCE[kind],
                        exc=exc,
                    )
                await bookkeeping.commit()
            log.warning(
                "health_backfill_failed",
                kinds=sorted(scan.normalized.kinds_present),
                reason=type(exc).__name__,
            )
            raise

    log.info(
        "health_backfill_completed",
        rows_written=written,
        rows_skipped=skipped,
        datapoints_seen=scan.normalized.datapoints_seen,
        datapoints_dropped=scan.normalized.datapoints_dropped,
        records_total=scan.records_total,
        kinds=sorted(scan.normalized.kinds_present),
    )
    return _summarize(
        scan,
        dry_run=False,
        rows_written=written,
        rows_skipped=skipped,
        resources_advanced=tuple(advanced),
    )


# Column widths for the D-06 block. Wide enough for the longest real value in each column
# (`walking_running_distance` is 24 chars; `HKQuantityTypeIdentifierDistanceWalkingRunning` is 46)
# so the numbers stay in one column and an operator can scan down them.
_METRIC_COLUMN = 28
_HK_TYPE_COLUMN = 56


def format_summary(summary: BackfillSummary, *, path: Path) -> list[str]:
    """The D-06 block, as LINES rather than as printed output.

    A pure function returning a list so ``cli.py`` stays a thin dispatcher, so the block is
    testable without capturing stdout, and so no HealthKit vocabulary escapes this package.

    Counts, metric names, HealthKit identifiers, units, dates and file NAMES only -- never a
    measured quantity (T-09-14). ``path.name`` and not ``path``: the full path is the location of
    this person's entire health history, and the operator typed it thirty seconds ago.

    The ``records:`` line spells out the accounting identity rather than just reporting a total,
    so an operator can add the four addends and see that every ``<Record>`` in the file is
    accounted for. A silently dropped record would otherwise leave a plausible summary and a gap
    that only surfaces as a hole in a trend months later.
    """
    scan = summary.scan
    normalized = scan.normalized
    headline = "DRY RUN (nothing written)" if summary.dry_run else "WROTE TO THE DATABASE"

    lines = [
        f"Apple Health backfill — {headline}",
        f"file: {path.name}",
        (
            f"records: {scan.records_total} total"
            f" = {normalized.datapoints_seen} in-scope"
            f" + {scan.records_unrecognized} unrecognized"
            f" + {scan.body_mass_skipped} body-mass"
            f" + {scan.records_malformed} malformed"
        ),
        (
            f"datapoints: {normalized.datapoints_seen} seen,"
            f" {normalized.datapoints_dropped} dropped"
            f" ({scan.hevy_datapoints_excluded} Hevy-sourced)"
        ),
        (
            f"skipped elements: Workout={scan.workouts_skipped}"
            f" ActivitySummary={scan.activity_summaries_skipped}"
        ),
        (
            f"multi-point days: {scan.multi_point_days}"
            " (normal for raw HealthKit samples; warning suppressed)"
        ),
    ]

    if summary.first_day is None or summary.last_day is None:
        # Not "None .. None". An empty run is a real outcome -- a wrong file, a filtered-out
        # export -- and it should read as one rather than as a formatting accident.
        lines.append("date range: (no rows)")
    else:
        lines.append(
            f"date range: {summary.first_day.isoformat()} .. {summary.last_day.isoformat()}"
        )

    lines.append("rows by metric:")
    # By NAME, so two runs over the same file produce byte-identical blocks and a diff between
    # them means the data changed. Sorting by count would reorder on any change at all.
    for metric, count in sorted(summary.rows_by_metric.items()):
        lines.append(f"  {metric:<{_METRIC_COLUMN}}{count:>7}")

    lines.append(f"unrecognized types ({len(scan.unrecognized_types)}):")
    # By count DESCENDING here, because this list is a triage queue: the identifier that cost the
    # most records is the one worth considering for the registry. Ties break on name so the order
    # is still deterministic.
    by_frequency = sorted(scan.unrecognized_types.items(), key=lambda item: (-item[1], item[0]))
    for hk_type, count in by_frequency:
        lines.append(f"  {hk_type:<{_HK_TYPE_COLUMN}}{count:>8}")

    verb = "would write" if summary.dry_run else "written"
    lines.append(f"rows: {summary.rows_written} {verb}, {summary.rows_skipped} skipped")

    if summary.dry_run:
        lines.append("freshness: not advanced (dry run)")
    elif not summary.resources_advanced:
        lines.append("freshness: not advanced (no rows written)")
    else:
        lines.append(f"freshness: {', '.join(summary.resources_advanced)} advanced")

    return lines

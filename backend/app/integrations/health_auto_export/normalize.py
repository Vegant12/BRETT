"""Wire payload -> canonical day-grained rows (HEALTH-06, HEALTH-08, NUTR-02).

PURE. This module opens no connection, awaits nothing and writes nothing: a validated
``HAEPayload`` goes in, the exact set of rows the database should hold comes out. Plan 08-06
owns the write. Keeping the two apart is what lets every rule below be pinned by a unit test
in the fast suite instead of by an integration run.

Finding A -- why a metric allowlist is NOT enough for HEALTH-08
--------------------------------------------------------------
Hevy writes ``ActiveEnergyBurned`` into Apple Health. Measured against this user's own
``records.csv``: **209 records across 209 training days**, one lump record per day, at
**70-88 %** of that day's total active energy (2025-12-19: 494.3 of 580.1; 2026-01-02: 666.5
of 760.7; 2026-01-06: 653.8 of 931.4). ``active_energy`` is *inside* this phase's allowlist,
and the iPhone independently records active energy across the same workout window.

D-01 closed the body-mass route and D-02 closed the workouts route. Nobody checked active
energy, because nobody knew Hevy wrote it. So a metric-name allowlist does not satisfy
HEALTH-08 -- :func:`is_hevy_sourced` is what does. Without it, BRETT's daily activity figure
would be up to 88 % Hevy's own estimate of a session BRETT already holds at set-level detail.

Pitfall N-3 -- match the APP name, never the device name
--------------------------------------------------------
Two source vocabularies exist. The webhook sends ``"iPhone"``; ``export.xml`` says
``"Vegant\u2019s iPhone"``. The device name is unstable -- this device was renamed mid-history
(366,339 records under one name, 70,900 under the other) -- and it carries U+2019 RIGHT SINGLE
QUOTATION MARK rather than an ASCII apostrophe, so any hardcoded device comparison fails
silently and forever. The app name is what HEALTH-08 actually cares about and it survives
device renames. Matching is case-folded and whitespace-stripped.

Assumption A1, STILL OPEN
-------------------------
That the *webhook* spells Hevy the way ``export.xml``'s ``sourceName`` vocabulary does has been
verified only against that vocabulary, never against a payload from this phone. Third-party
captures cannot settle it, because those users do not have Hevy installed.
``_HEVY_SOURCE_ALIASES`` is a frozenset precisely so plan 08-08's device capture can add a
spelling on one line. **The warning sign is a filter that never excludes anything** -- which is
why the exclusion emits a log line rather than happening in silence.

Decisions locked here
---------------------
**Open Question 1 -- the exclusion happens at WRITE time, not read time.** A Hevy-sourced
datapoint never becomes a row. That makes ROADMAP success criterion #4 ("volume, frequency and
body-weight numbers identical before and after Apple Health data exists") provable by a
row-count assertion instead of by auditing every future analytics reader -- the trap
``PITFALLS.md`` Pitfall 9 describes for ``_dedupe_by_day`` -- and it matches D-02's stated
preference for exclusion over quarantine. Cost, accepted and recorded: the evidence is
discarded, and recovering it would need a Phase 9 re-run.

**Open Question 2 -- a data kind is "present" only when the payload carried at least one
ACCEPTED metric of that kind.** ``kinds_present`` drives which of D-03's two ``sync_state``
resources plan 08-06 advances. Advancing both on every delivery would report nutrition "fresh"
while the logging app has quietly stopped writing to HealthKit -- precisely the blind spot D-03
exists to remove.

**Pitfall N-4 -- ``local_day`` wins over the payload's own date part.** A nutrition app writing
a daily total anchors it at its own local midnight (``"2025-08-15 00:00:00 +0900"``). Read in
``Asia/Jakarta`` (+07:00) that instant is 2025-08-14 22:00, i.e. day **2025-08-14**.
``local_day`` is kept, for consistency with every other table in this project and because a
travelling user's nutrition genuinely belongs to the local day they ate it. The behaviour is
pinned by a test with a docstring rather than left to be discovered. Today the user is
``Asia/Jakarta`` and the phone emits +0700, so this is dormant; it activates on travel or a
mis-set ``users.timezone``, which is exactly when nobody would be looking.

The logging rule
----------------
A metric **name**, a **unit**, a **local_day**, a **source_name**, a **count** and an exception
**class name** are loggable. A measured quantity is not, ever (T-08-30, FOUND-05). Nor is a raw
wire timestamp: it is user-controlled input reaching a log sink and the format list already
says everything a reader could act on.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

import structlog

from app.core.time import local_day
from app.integrations.health_auto_export.errors import HAEDateFormatError, UnknownUnitError
from app.integrations.health_auto_export.registry import (
    METRIC_REGISTRY,
    MetricSpec,
    to_canonical,
)
from app.integrations.health_auto_export.schemas import HAEMetric, HAEPayload, parse_hae_datetime

log = structlog.get_logger()

# Goes into `HealthDailyMetric.source`. 12 chars -- fits String(16). NEVER 'health_auto_export':
# the column names the DATA's origin (Apple Health), not the transport that delivered it, and
# Phase 9's XML backfill must land on the same value or the same day would read as two rows.
SOURCE_APPLE_HEALTH = "apple_health"

# The NOT NULL sentinel for a datapoint that arrived with no `source` key -- which real payloads
# genuinely do, for gait metrics. A real value, written here at normalize time, because
# PostgreSQL treats NULLs as DISTINCT inside a unique constraint: a nullable key column would
# silently permit duplicate rows instead of upserting them (Pitfall N-1).
UNKNOWN_SOURCE_NAME = "unknown"

# HEALTH-08. A named constant beside `hevy.body.SOURCE_HEVY`, never an inline literal. A SET,
# not a string, so plan 08-08's device capture can add the real webhook spelling in one line
# without touching the predicate. Compared case-folded and whitespace-stripped.
_HEVY_SOURCE_ALIASES: frozenset[str] = frozenset({"hevy"})


def is_hevy_sourced(source: str | None) -> bool:
    """True when this datapoint came from Hevy's HealthKit write-back (HEALTH-08).

    Matches the APP name, never the device name -- see the module docstring. A missing source
    is not Hevy: it is the gait-metric case, and treating it as Hevy would silently delete the
    phone's own samples.
    """
    if source is None:
        return False
    return source.strip().casefold() in _HEVY_SOURCE_ALIASES


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    """One row the database should hold, in BRETT's vocabulary rather than HAE's.

    `units` is the CANONICAL unit, not the wire unit: the row records what it is stored in, so
    no downstream reader has to re-derive the conversion and no two readers can disagree.
    """

    metric: str
    kind: str  # 'activity' | 'nutrition' -- selects the D-03 sync_state resource
    source_name: str
    local_day: dt.date
    value: Decimal
    units: str
    sample_count: int


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """Counts only, never a value -- this object is what callers log.

    The three counters satisfy an accounting identity that a test pins:
    ``sum(row.sample_count for row in rows) == datapoints_seen - datapoints_dropped``.
    Every datapoint in the payload is either inside a row or explained by a drop, so a
    silently vanishing datapoint has nowhere to hide.
    """

    rows: tuple[NormalizedRow, ...]  # sorted by (metric, source_name, local_day)
    kinds_present: frozenset[str]  # kinds with >= 1 ACCEPTED row -- Open Question 2
    datapoints_seen: int
    datapoints_dropped: int
    metrics_unrecognized: int


@dataclass(frozen=True, slots=True)
class _MetricScan:
    """One metric's surviving datapoints plus its drop accounting. Module-private.

    `accepted` carries values, which is why this type never leaves the module and is never
    handed to a log call.
    """

    accepted: tuple[tuple[str, dt.date, Decimal], ...]
    seen: int
    dropped: int


def _scan_metric(metric: HAEMetric, spec: MetricSpec, *, tz: str) -> _MetricScan:
    """Reduce one recognised metric to ``(source_name, local_day, canonical_value)`` triples.

    Every rejection is per-DATAPOINT, deliberately. Health Auto Export has no documented retry,
    so the blast radius of one malformed element must be that element and never the window it
    arrived in (T-08-24).
    """
    accepted: list[tuple[str, dt.date, Decimal]] = []
    dropped = 0
    hevy_excluded = 0

    for point in metric.data:
        if point.qty is None or point.date is None:
            dropped += 1
            log.warning("health_ingest_datapoint_dropped", metric=metric.name, reason="incomplete")
            continue

        # HEALTH-08, before any conversion work: a Hevy datapoint is not worth converting, and
        # excluding it here means it cannot reach a bucket by any later path.
        if is_hevy_sourced(point.source):
            dropped += 1
            hevy_excluded += 1
            continue

        try:
            # `Decimal(str(...))`, never a direct binary-to-Decimal construction, which would
            # import the binary representation error into stored health data. `point.qty` is
            # already a Decimal from the wire model; this is the belt to that model's braces,
            # because Phase 9's XML path will feed this same function from a raw string.
            value = to_canonical(Decimal(str(point.qty)), metric.units, spec, metric=metric.name)
        except UnknownUnitError as exc:
            dropped += 1
            log.warning(
                "health_ingest_datapoint_dropped",
                metric=metric.name,
                unit=exc.unit,
                reason=type(exc).__name__,
            )
            continue

        try:
            ts = parse_hae_datetime(point.date)
        except HAEDateFormatError as exc:
            # Class name only. The offending string is user-controlled input reaching a log
            # sink, and the format list already says everything a reader can act on.
            dropped += 1
            log.warning(
                "health_ingest_datapoint_dropped", metric=metric.name, reason=type(exc).__name__
            )
            continue

        # Whitespace-stripped but otherwise VERBATIM: case and non-ASCII are preserved because
        # this value is stored, is part of the natural key, and is later matched against.
        source_name = (point.source or "").strip() or UNKNOWN_SOURCE_NAME
        accepted.append((source_name, local_day(ts, tz), value))

    if hevy_excluded:
        # Deliberate, and the reason this is `info` rather than silence: Pitfall N-3's stated
        # warning sign is "a source-exclusion filter that never excludes anything". One line
        # per metric with a total makes that condition observable; one line per datapoint would
        # bury it on a 189-point day. A count, never a value.
        log.info("health_ingest_hevy_source_excluded", metric=metric.name, points=hevy_excluded)

    return _MetricScan(accepted=tuple(accepted), seen=len(metric.data), dropped=dropped)


def normalize_payload(payload: HAEPayload, *, tz: str) -> NormalizeResult:
    """Collect the WHOLE payload into day-grained rows before anything is written.

    Separating the read from the write is what makes idempotency a property of the type rather
    than a discipline the caller has to remember (``hevy/events.py::drain_events`` is the same
    idea). Real payloads carry 189 datapoints for one metric-day and the table holds one row,
    so aggregation is mandatory -- and its interaction with the upsert's conflict clause is the
    sharpest correctness risk in this phase (Pitfall N-2)::

        SET qty = qty + excluded.qty  -> correct across batches, DOUBLE-COUNTS a re-sent window
        SET qty = excluded.qty        -> correct on a re-send, LOSES the first of two batches

    This function resolves the first half: within one delivery, every datapoint for a key is
    summed once, here, so plan 08-06 can use replace semantics unconditionally. The second half
    -- a day split across two batched POSTs -- is resolved at the DEVICE, by requiring Health
    Auto Export's aggregation interval to be daily, and is made OBSERVABLE by the
    ``health_ingest_multi_point_day`` warning. Under a correct device configuration that
    warning never fires; when it does, replace semantics has become lossy and the device
    setting has drifted.
    """
    buckets: dict[tuple[str, str, dt.date], list[Decimal]] = defaultdict(list)
    kinds: set[str] = set()
    seen = 0
    dropped = 0
    unrecognized = 0

    for metric in payload.data.metrics:
        spec = METRIC_REGISTRY.get(metric.name)
        if spec is None:
            # D-04: drop the metric, log ONCE, continue. Never reject the payload -- Health Auto
            # Export has no documented retry, so rejecting a batch over one unrecognised name
            # loses the entire window's activity AND nutrition, not just the unexpected part.
            unrecognized += 1
            seen += len(metric.data)
            dropped += len(metric.data)
            log.warning("health_ingest_unrecognized_metric", metric=metric.name)
            continue

        scan = _scan_metric(metric, spec, tz=tz)
        seen += scan.seen
        dropped += scan.dropped
        for source_name, day, value in scan.accepted:
            buckets[(metric.name, source_name, day)].append(value)

    rows: list[NormalizedRow] = []
    # `sorted` is part of the CONTRACT, not a convenience: plan 08-06 writes rows in this order,
    # and a nondeterministic order would make two runs over the same payload produce different
    # SAVEPOINT sequences -- a difference that only ever shows up under a partial failure.
    for (name, source_name, day), values in sorted(buckets.items()):
        row_spec = METRIC_REGISTRY[name]
        if len(values) > 1:
            # Pitfall N-2. More than one datapoint for a key means HAE's aggregation interval is
            # not daily, so a batch boundary CAN fall inside a day and replace semantics has
            # become lossy. Under a correct device configuration this never fires; when it does,
            # the device setting has drifted. Never a value -- only the shape of the problem.
            log.warning(
                "health_ingest_multi_point_day",
                metric=name,
                source_name=source_name,
                local_day=day.isoformat(),
                points=len(values),
            )
        total = sum(values, Decimal(0))
        if row_spec.aggregation == "avg":
            # The Decimal mean, for a RATE. Summing a rate makes it grow with sampling
            # frequency, so a shorter HAE interval would read as the user walking faster. No
            # `avg` metric is in the Phase 8 registry; the branch exists so Phase 13 does not
            # have to reopen this function to add one.
            total = total / Decimal(len(values))
        rows.append(
            NormalizedRow(
                metric=name,
                kind=row_spec.kind,
                source_name=source_name,
                local_day=day,
                value=total,
                units=row_spec.canonical_unit,
                sample_count=len(values),
            )
        )
        kinds.add(row_spec.kind)

    return NormalizeResult(
        rows=tuple(rows),
        kinds_present=frozenset(kinds),
        datapoints_seen=seen,
        datapoints_dropped=dropped,
        metrics_unrecognized=unrecognized,
    )

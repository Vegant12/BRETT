"""Normalized rows -> PostgreSQL, idempotently (HEALTH-09, NUTR-03, HEALTH-11, NUTR-05).

The inbound twin of ``hevy/body.py``: the same constraint-bound upsert, the same
SAVEPOINT-per-row loop, the same counts-only result type, and the same rule that bookkeeping
commits in the SAME transaction as the rows it describes.

The conflict clause is the whole design
---------------------------------------
HEALTH-09 and NUTR-03 turn on one line, and RESEARCH Pitfall N-2 shows that both obvious
choices are wrong in one direction:

* An **additive** clause -- one that adds the incoming quantity onto the stored one -- is
  correct when a single day arrives split across two batched POSTs, and **double-counts** every
  re-sent window. Health Auto Export re-sends overlapping windows routinely, so that failure is
  not hypothetical: it inflates every calorie and step figure on every delivery, silently, and
  it is exactly what ROADMAP success criterion #3 forbids.
* A **replace** clause is the mirror: a re-send is a correct no-op, and a day split across two
  batches silently **loses** the first of them.

This module takes **replace** semantics unconditionally, and it is safe to do so because
:func:`normalize.normalize_payload` aggregates the WHOLE payload before the first write. Within
one delivery ``excluded`` already carries the complete total for a
``(metric, source_name, local_day)`` key, so there is nothing left to accumulate. The remaining
risk -- a batch boundary falling inside a day -- is closed at the DEVICE, by requiring Health
Auto Export's aggregation interval to be daily, and it is made observable by the
``health_ingest_multi_point_day`` warning ``normalize.py`` already emits. Under a correct device
configuration that warning never fires; when it does, replace has become lossy and the device
setting has drifted.

The caller owns the transaction
-------------------------------
Nothing here commits except :func:`ingest_payload` itself. The two D-03 freshness timestamps are
written into the SAME transaction as the rows they describe and commit with them, so a crash can
never leave a ``sync_state`` row claiming work that rolled back. That is the same rule D-08 put
on the Hevy resume cursor, applied to a webhook that has no cursor.

D-03 / Open Question 2 -- the two resources advance INDEPENDENTLY
-----------------------------------------------------------------
``activity`` and ``nutrition`` arrive in one webhook POST, so advancing both on every successful
delivery is the tempting implementation. It is also the one that reports nutrition "fresh" while
the logging app has quietly stopped writing to HealthKit -- the exact blind spot D-03 exists to
remove. A resource advances only when the payload carried at least one ACCEPTED metric of that
kind, which is what ``NormalizeResult.kinds_present`` already counts.

The logging rule
----------------
A metric **name**, a **local_day**, a **source_name**, a **count** and an exception **class
name** are loggable. A stored quantity is not, ever (T-08-39, FOUND-05). ``str(DataError)``
renders the bound parameters, which here are this person's calorie counts, so every skip path
logs ``type(exc).__name__`` and nothing else -- and the bookkeeping error path goes through
``format_sync_error``, whose whole job is bounding that same leak.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models.health import HealthDailyMetric
from app.db.models.user import User
from app.db.repositories.sync_state import (
    PROVIDER_APPLE_HEALTH,
    RESOURCE_ACTIVITY,
    RESOURCE_NUTRITION,
    complete_sync,
    ensure_sync_state,
    record_sync_error,
)
from app.integrations.health_auto_export.normalize import (
    SOURCE_APPLE_HEALTH,
    NormalizedRow,
    normalize_payload,
)
from app.integrations.health_auto_export.schemas import HAEPayload

log = structlog.get_logger()

# The name the ON CONFLICT clause binds to. Bound BY NAME rather than by column list, mirroring
# `app.db.repositories.sync_state`: if the constraint is ever renamed this raises immediately
# instead of silently degrading into a duplicate-row insert (T-08-35).
_CONFLICT_CONSTRAINT = "uq_health_daily_metrics_user_source_metric_source_name_day"

# D-03. Table-driven and TOTAL: a kind with no entry here is a `KeyError`, which is exactly the
# failure a `.get(kind, RESOURCE_ACTIVITY)` would hide behind a plausible default -- nutrition
# silently reported under the activity resource, which is a wrong freshness answer rather than
# a missing one. `MappingProxyType` for the reason `registry.py`'s table uses it: a caller must
# not be able to retune the D-03 split at runtime.
_KIND_TO_RESOURCE: Mapping[str, str] = MappingProxyType(
    {
        "activity": RESOURCE_ACTIVITY,
        "nutrition": RESOURCE_NUTRITION,
    }
)


@dataclass(frozen=True, slots=True)
class HealthIngestResult:
    """Counts only. Never a value -- this object is what the route logs and returns."""

    rows_upserted: int
    rows_skipped: int
    datapoints_seen: int
    datapoints_dropped: int
    metrics_unrecognized: int


async def upsert_health_metric(
    session: AsyncSession, *, user_id: uuid.UUID, row: NormalizedRow
) -> None:
    """Write one day-grained row, keyed on ``(user_id, source, metric, source_name, local_day)``.

    Does not commit: the caller owns the transaction, so the payload's rows and the two D-03
    freshness timestamps land together or not at all.

    ``user_id`` is keyword-only with no default (ASVS V4): the schema is multi-user-ready, so an
    unscoped write is a cross-tenant defect a single-user suite cannot see. It is resolved
    server-side by the route and is NEVER read from the payload -- Health Auto Export cannot
    supply one and must not be able to (T-08-38).
    """
    statement = pg_insert(HealthDailyMetric).values(
        id=uuid.uuid4(),
        user_id=user_id,
        source=SOURCE_APPLE_HEALTH,
        metric=row.metric,
        source_name=row.source_name,
        local_day=row.local_day,
        value=row.value,
        units=row.units,
        sample_count=row.sample_count,
    )
    # REPLACE semantics, never additive (HEALTH-09 / NUTR-03, RESEARCH Pitfall N-2). Plan 08-05
    # aggregates the WHOLE payload before the first write, so `excluded` already carries the
    # complete total for this (metric, source_name, day) within this delivery -- accumulating it
    # onto the stored quantity would inflate every re-sent window, which is precisely what
    # ROADMAP success criterion #3 forbids.
    #
    # `units` is written on conflict because HAE units are a per-metric USER PREFERENCE inside
    # the phone app: a settings change silently alters the wire unit on the next export, and a
    # row whose stored quantity moved to the new canonical basis while its `units` string stayed
    # on the old one is a plausible number that is quietly wrong.
    #
    # `sample_count` is written on conflict too, deliberately: a sample_count that FALLS on a
    # re-sync is the cheapest available detector for a batch-split data loss, and it only works
    # if the column tracks the latest delivery.
    #
    # Bound to the constraint BY NAME rather than by column list, mirroring
    # `app.db.repositories.sync_state`: if the constraint is ever renamed this raises immediately
    # instead of silently degrading into a duplicate-row insert.
    statement = statement.on_conflict_do_update(
        constraint=_CONFLICT_CONSTRAINT,
        set_={
            "value": statement.excluded.value,
            "units": statement.excluded.units,
            "sample_count": statement.excluded.sample_count,
        },
    )
    await session.execute(statement)


async def _user_timezone(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    """The user's IANA timezone, read from ``users.timezone`` (FOUND-03).

    A deliberate SECOND copy of ``mcp/tools/_common.local_timezone`` rather than an import of
    it. An integrations package must not depend on the MCP package -- that boundary is what
    ``test_health_auto_export_isolation.py`` asserts, and it exists so the two surfaces can
    change independently. The analytics layer set the same precedent with
    ``rollup.resolve_window``; three small reads beat one shared import that inverts the layering.

    Never a module constant, never an environment variable, never a caller default. A missing
    row raises rather than falling back to a default zone: ``core/time.py`` is explicit that a
    hardcoded default is how a wrong-timezone bug passes every test, because every test would
    then read the same wrong answer the code writes. At a UTC+7 offset that bug moves every
    evening datapoint onto the wrong local day.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return tz


async def ingest_payload(
    sessionmaker: async_sessionmaker[AsyncSession], *, user_id: uuid.UUID, payload: HAEPayload
) -> HealthIngestResult:
    """Persist one validated webhook delivery and advance exactly the resources it carried.

    Deliberate divergences from ``hevy/body.py``, each of which is an absence rather than an
    omission: there is no ``running`` status phase (a webhook has no long-running fetch to
    observe -- the bookkeeping row goes straight to ``idle`` with a fresh ``last_synced_at``), no
    pagination and therefore no resume checkpoint to record, and no HTTP client, because this
    integration is INBOUND and an outbound call from this package would be an unreviewed egress
    path out of a service holding health data.
    """
    async with sessionmaker() as session:
        # Read the zone BEFORE any write and outside the try below: an unknown user is a caller
        # bug, not a failed sync, and recording it as a sync error would put a bookkeeping row
        # under a tenant that does not exist.
        tz = await _user_timezone(session, user_id=user_id)
        # Pure, no I/O, and complete before the first write -- which is what makes the replace
        # conflict clause below unconditionally correct within a delivery.
        normalized = normalize_payload(payload, tz=tz)

        rows_upserted = 0
        rows_skipped = 0
        try:
            for row in normalized.rows:
                try:
                    # SAVEPOINT per row: without it one bad row aborts the whole transaction and
                    # every later statement fails with "current transaction is aborted"
                    # (T-08-40). Health Auto Export has no documented retry, so losing the whole
                    # window to one malformed row is permanent loss of that window.
                    async with session.begin_nested():
                        await upsert_health_metric(session, user_id=user_id, row=row)
                except SQLAlchemyError as exc:
                    rows_skipped += 1
                    # Class name only: `str(DataError)` renders the bound parameters, which here
                    # are this person's calorie counts (T-08-39).
                    log.warning(
                        "health_ingest_row_skipped",
                        metric=row.metric,
                        local_day=row.local_day.isoformat(),
                        source_name=row.source_name,
                        reason=type(exc).__name__,
                    )
                else:
                    rows_upserted += 1

            # ONE instant for every resource this delivery advances, so a mixed payload cannot
            # report activity and nutrition as fractionally different ages.
            now = utc_now()
            for kind in sorted(normalized.kinds_present):
                resource = _KIND_TO_RESOURCE[kind]
                await ensure_sync_state(
                    session, user_id=user_id, provider=PROVIDER_APPLE_HEALTH, resource=resource
                )
                # In the SAME transaction as the rows above, and committed with them (T-08-36).
                # No cursor is passed: a webhook has no resume point, and `complete_sync`'s own
                # guard is what rejects a naive `last_synced_at`, so `utc_now()` is explicit.
                await complete_sync(
                    session,
                    user_id=user_id,
                    provider=PROVIDER_APPLE_HEALTH,
                    resource=resource,
                    last_synced_at=now,
                )
            await session.commit()
        except SQLAlchemyError as exc:
            # A FRESH session: the one that raised is in an aborted transaction, and the
            # bookkeeping write has to succeed precisely when the ingest did not.
            async with sessionmaker() as bookkeeping:
                for kind in sorted(normalized.kinds_present):
                    await record_sync_error(
                        bookkeeping,
                        user_id=user_id,
                        provider=PROVIDER_APPLE_HEALTH,
                        resource=_KIND_TO_RESOURCE[kind],
                        exc=exc,
                    )
                await bookkeeping.commit()
            log.warning(
                "health_ingest_failed",
                kinds=sorted(normalized.kinds_present),
                reason=type(exc).__name__,
            )
            raise

    log.info(
        "health_ingest_completed",
        rows_upserted=rows_upserted,
        rows_skipped=rows_skipped,
        datapoints_seen=normalized.datapoints_seen,
        datapoints_dropped=normalized.datapoints_dropped,
        metrics_unrecognized=normalized.metrics_unrecognized,
        kinds=sorted(normalized.kinds_present),
    )
    return HealthIngestResult(
        rows_upserted=rows_upserted,
        rows_skipped=rows_skipped,
        datapoints_seen=normalized.datapoints_seen,
        datapoints_dropped=normalized.datapoints_dropped,
        metrics_unrecognized=normalized.metrics_unrecognized,
    )

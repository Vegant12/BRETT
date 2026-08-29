"""Body-measurement sync (HEVY-07, D-05, D-06, D-07-corrected).

Three live-API facts shape everything here, and all three contradict what the blueprint
assumed:

* There is NO id field on a body measurement. The calendar DATE is the identity -- confirmed
  by the sibling endpoints `GET/PUT /v1/body_measurements/{date}` and a POST that returns 409
  if an entry already exists for that date. The natural key is therefore
  `(user_id, source, measured_on)` for the whole ROW; D-07's per-metric fallback was the wrong
  granularity.
* ONE row carries all 17 metrics. It is not one row per metric.
* `/v1/body_measurements` answers **404 "Page not found"** for an out-of-range page, where
  `/v1/workouts` answers 400. Treating that 404 as fatal would mark a run failed after it had
  already fetched everything (Pitfall 5). The client turns it into `None`; this module treats
  `None` as the terminator.

Hevy leaves seven fields without a unit suffix (`abdomen`, `waist`, `hips`, `left_thigh`,
`right_thigh`, `left_calf`, `right_calf`). They are renamed to `*_cm` on the way in, for
consistency with the other seven and with blueprint §41. Centimetres is an ASSUMPTION Hevy does
not document -- it is flagged for confirmation against the app on the first live sync.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models.body import BodyMeasurement
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_BODY_MEASUREMENTS,
    advance_cursor_page,
    complete_sync,
    ensure_sync_state,
    mark_running,
    record_sync_error,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.schemas import HevyBodyMeasurement

log = structlog.get_logger()

SOURCE_HEVY = "hevy"

# wire field name -> local column name. The seven entries whose key differs from their value
# are the unsuffixed fields Hevy sends; the rest are identity mappings, listed explicitly so
# that a field added upstream is a visible omission here rather than a silent drop.
_WIRE_TO_COLUMN: Mapping[str, str] = MappingProxyType(
    {
        "weight_kg": "weight_kg",
        "lean_mass_kg": "lean_mass_kg",
        "fat_percent": "fat_percent",
        "neck_cm": "neck_cm",
        "shoulder_cm": "shoulder_cm",
        "chest_cm": "chest_cm",
        "left_bicep_cm": "left_bicep_cm",
        "right_bicep_cm": "right_bicep_cm",
        "left_forearm_cm": "left_forearm_cm",
        "right_forearm_cm": "right_forearm_cm",
        "abdomen": "abdomen_cm",
        "waist": "waist_cm",
        "hips": "hips_cm",
        "left_thigh": "left_thigh_cm",
        "right_thigh": "right_thigh_cm",
        "left_calf": "left_calf_cm",
        "right_calf": "right_calf_cm",
    }
)


@dataclass(frozen=True, slots=True)
class BodyMeasurementSyncResult:
    """Counts only. Never a measurement -- this value is what callers log (T-03-33)."""

    pages_fetched: int
    rows_upserted: int


async def upsert_body_measurement(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    measurement: HevyBodyMeasurement,
) -> None:
    """Write one dated row, keyed on `(user_id, source, measured_on)`.

    Does not commit: the caller owns the transaction, so the page of rows and the D-08
    resume checkpoint land together or not at all.
    """
    metrics = {column: getattr(measurement, wire) for wire, column in _WIRE_TO_COLUMN.items()}
    stmt = pg_insert(BodyMeasurement).values(
        id=uuid.uuid4(),
        user_id=user_id,
        source=SOURCE_HEVY,
        # No external_id: this endpoint has no id to store. The column exists for a future
        # provider that does have one.
        external_id=None,
        measured_on=measurement.date,
        **metrics,
    )
    # EVERY metric is written on conflict, including the ones that are now None. Hevy's own
    # PUT documents "all fields are overwritten; omitted fields are set to null", so the local
    # upsert mirrors row-replacement semantics: a metric the user deleted upstream must
    # disappear locally rather than linger as a stale value in a weight trend (T-03-35).
    #
    # Bound to the constraint BY NAME rather than by column list, mirroring
    # `app.db.repositories.sync_state`: if the constraint is ever renamed this raises
    # immediately instead of silently degrading into a duplicate-row insert.
    stmt = stmt.on_conflict_do_update(
        constraint="uq_body_measurements_user_source_measured_on",
        set_={column: getattr(stmt.excluded, column) for column in _WIRE_TO_COLUMN.values()},
    )
    await session.execute(stmt)


async def sync_body_measurements(
    client: HevyClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
) -> BodyMeasurementSyncResult:
    """Walk `/v1/body_measurements` from the D-08 resume point to the end.

    Never logs a metric VALUE. `measured_on` is fine -- a calendar date is not a body
    composition figure -- but a weight, a lean mass or a body-fat percentage is personal
    health data and must not reach the log sink (T-03-33, blueprint §44).
    """
    async with sessionmaker() as session:
        state = await ensure_sync_state(
            session,
            user_id=user_id,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_BODY_MEASUREMENTS,
        )
        # `or 1` rather than `if is None`: a stored 0 is not a page Hevy accepts, so
        # treating it as "start from the beginning" is the only safe reading.
        start_page = state.cursor_page or 1
        await mark_running(
            session,
            user_id=user_id,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_BODY_MEASUREMENTS,
        )
        await session.commit()
    log.info("hevy_body_sync_started", start_page=start_page)

    pages_fetched = 0
    rows_upserted = 0
    page = start_page
    try:
        while True:
            payload = await client.get_body_measurements(page=page)
            if payload is None:
                # Pitfall 5: a 404 here means "past the last page", not a failure.
                log.info("hevy_body_pagination_terminated", page=page)
                break
            pages_fetched += 1

            async with sessionmaker() as session:
                for measurement in payload.body_measurements:
                    try:
                        # SAVEPOINT per row: without it one bad value aborts the whole
                        # transaction and every later statement fails with
                        # "current transaction is aborted" (Pitfall 11).
                        async with session.begin_nested():
                            await upsert_body_measurement(
                                session, user_id=user_id, measurement=measurement
                            )
                    except SQLAlchemyError as exc:
                        # Class name only: str(DataError) renders the bound parameters, which
                        # here are this person's body-composition numbers (T-03-34).
                        log.warning(
                            "hevy_body_measurement_skipped",
                            measured_on=measurement.date.isoformat(),
                            reason=type(exc).__name__,
                        )
                    else:
                        rows_upserted += 1

                # D-08: the checkpoint commits in the SAME transaction as the rows it
                # describes, so a crash can never leave a cursor claiming work that rolled
                # back.
                await advance_cursor_page(
                    session,
                    user_id=user_id,
                    provider=PROVIDER_HEVY,
                    resource=RESOURCE_BODY_MEASUREMENTS,
                    cursor_page=page + 1,
                )
                await session.commit()

            if not payload.body_measurements or page >= payload.page_count:
                break
            page += 1
    except Exception as exc:
        # A FRESH session: the one that raised may be in an aborted transaction, and the
        # bookkeeping write has to succeed precisely when the sync did not.
        async with sessionmaker() as session:
            await record_sync_error(
                session,
                user_id=user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_BODY_MEASUREMENTS,
                exc=exc,
            )
            await session.commit()
        # Cursors are untouched, so the next run resumes at `page` instead of re-walking
        # every 10-item page before it (HEVY-08, D-08).
        log.warning("hevy_body_sync_failed", page=page, reason=type(exc).__name__)
        raise

    async with sessionmaker() as session:
        await complete_sync(
            session,
            user_id=user_id,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_BODY_MEASUREMENTS,
            last_synced_at=utc_now(),
            # A completed full sync has no page to resume from; leaving the last page here
            # would make the NEXT run skip everything before it.
            cursor_page=None,
        )
        await session.commit()
    log.info("hevy_body_sync_completed", pages=pages_fetched, rows=rows_upserted)

    return BodyMeasurementSyncResult(pages_fetched=pages_fetched, rows_upserted=rows_upserted)

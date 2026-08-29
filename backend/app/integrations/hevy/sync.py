"""HevySyncService: the one place that decides WHAT to sync and in WHICH order (HEVY-09).

Composition only. Every transaction boundary, every checkpoint write and every retry already
lives in the four drivers this class calls; adding a second layer of transaction handling here
would make it impossible to reason about which one committed.

Order is deliberate: exercise templates first, then workouts, then body measurements. Nothing
strictly requires it -- D-03 guarantees a workout syncs whether or not its template exists --
but syncing templates first means a fresh database is never briefly in the state where every
exercise is unmapped, which is the state that makes Phase 4's output look broken.

The service borrows a sessionmaker; it never builds an engine. `app/mcp/context.py` documents
why a second engine in a second component is a bug rather than an inconvenience.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    SYNC_RESOURCES,
    get_sync_state,
)
from app.integrations.hevy.body import BodyMeasurementSyncResult, sync_body_measurements
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.events import EventSyncResult, sync_workout_events
from app.integrations.hevy.templates import TemplateSyncResult, sync_exercise_templates
from app.integrations.hevy.workouts import WorkoutSyncResult, sync_workouts

log = structlog.get_logger()

SyncMode = Literal["auto", "full", "incremental"]

# Reported for a resource with no bookkeeping row at all. Deliberately NOT one of
# `sync_state`'s own STATUS_* values: "this resource has never run" is a different statement
# from "this resource is idle", and collapsing the two would make a fresh install
# indistinguishable from a completed sync that imported nothing.
STATUS_NEVER = "never"


@dataclass(frozen=True, slots=True)
class ResourceStatus:
    """One resource's freshness answer, including the never-synced case (HEVY-09)."""

    resource: str
    last_synced_at: dt.datetime | None
    status: str
    last_error: str | None
    cursor_page: int | None
    cursor_timestamp: dt.datetime | None


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What one `sync_all` did.

    Exactly one of `workouts_full` / `workouts_incremental` is ever populated, and which one
    is the answer to "did this run re-import the history or read the delta?" -- a single
    merged field would lose that distinction, which is the one thing a caller wants to know.
    """

    mode: SyncMode
    templates: TemplateSyncResult | None = None
    workouts_full: WorkoutSyncResult | None = None
    workouts_incremental: EventSyncResult | None = None
    body: BodyMeasurementSyncResult | None = None


async def resource_status(
    sessionmaker: async_sessionmaker[AsyncSession], *, user_id: uuid.UUID
) -> list[ResourceStatus]:
    """HEVY-09, in one call and WITHOUT a transport.

    A free function rather than only a method because reading `last_synced_at` out of the
    local database must not require a Hevy API key: `HevySyncService` takes a `HevyClient`,
    and `build_hevy_client` refuses to construct one without `HEVY_API_KEY`. Asking an
    operator for a credential in order to answer "when did this last sync?" would make the
    freshness report unavailable exactly when the key is what is broken.

    Returns one entry for every member of `SYNC_RESOURCES`, including resources that have
    never run -- "never synced" is the answer to "when was this last synced", and omitting
    the row would make it indistinguishable from "the resource does not exist".

    Sorted by resource so the report is deterministic and diffable between runs.
    """
    entries: list[ResourceStatus] = []
    async with sessionmaker() as session:
        for resource in sorted(SYNC_RESOURCES):
            state = await get_sync_state(
                session, user_id=user_id, provider=PROVIDER_HEVY, resource=resource
            )
            if state is None:
                entries.append(
                    ResourceStatus(
                        resource=resource,
                        last_synced_at=None,
                        status=STATUS_NEVER,
                        last_error=None,
                        cursor_page=None,
                        cursor_timestamp=None,
                    )
                )
                continue
            entries.append(
                ResourceStatus(
                    resource=resource,
                    last_synced_at=state.last_synced_at,
                    status=state.status,
                    last_error=state.last_error,
                    cursor_page=state.cursor_page,
                    cursor_timestamp=state.cursor_timestamp,
                )
            )
    return entries


class HevySyncService:
    """The four Hevy drivers behind one call, plus the freshness report HEVY-09 asks for."""

    def __init__(
        self,
        client: HevyClient,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
    ) -> None:
        # Both collaborators are BORROWED. The caller owns the HTTP client's connection pool
        # and the engine behind the sessionmaker, and closes them; a service that closed
        # either would break the second of two calls in the same process.
        self._client = client
        self._sessionmaker = sessionmaker
        self._user_id = user_id

    async def resolve_mode(self, requested: SyncMode = "auto") -> Literal["full", "incremental"]:
        """`auto` means: incremental if a full workout sync has ever completed, else full.

        The check is `last_synced_at is not None` on the `workouts` resource, NOT
        `cursor_timestamp` -- the events cursor only exists after the FIRST incremental run,
        so keying on it would make every second run a full re-import.
        """
        if requested != "auto":
            return requested
        async with self._sessionmaker() as session:
            state = await get_sync_state(
                session,
                user_id=self._user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
            )
        if state is not None and state.last_synced_at is not None:
            return "incremental"
        return "full"

    async def sync_templates(self) -> TemplateSyncResult:
        """HEVY-06 / NORM-01: templates plus their materialised canonical muscle mapping."""
        return await sync_exercise_templates(
            self._client, self._sessionmaker, user_id=self._user_id
        )

    async def sync_workouts_full(self) -> WorkoutSyncResult:
        """HEVY-01: walk `/v1/workouts` from the D-08 resume point to the end."""
        return await sync_workouts(self._client, self._sessionmaker, user_id=self._user_id)

    async def sync_workouts_incremental(self) -> EventSyncResult:
        """HEVY-02 / HEVY-04: drain `/v1/workouts/events` and apply it oldest-first."""
        return await sync_workout_events(self._client, self._sessionmaker, user_id=self._user_id)

    async def sync_body(self) -> BodyMeasurementSyncResult:
        """HEVY-07: the date-keyed body-measurement rows."""
        return await sync_body_measurements(
            self._client, self._sessionmaker, user_id=self._user_id
        )

    async def sync_all(self, *, mode: SyncMode = "auto") -> SyncReport:
        """Templates -> workouts (full or incremental) -> body measurements.

        No exception handling here: each driver already records its own failure into
        `sync_state` before re-raising, and swallowing it would report a green sync over a
        resource that never ran. Resources completed before the failure keep their
        `last_synced_at`, which is exactly what HEVY-08 asks for.
        """
        resolved = await self.resolve_mode(mode)
        log.info("hevy_sync_all_started", mode=resolved)

        templates = await self.sync_templates()

        workouts_full: WorkoutSyncResult | None = None
        workouts_incremental: EventSyncResult | None = None
        if resolved == "full":
            workouts_full = await self.sync_workouts_full()
        else:
            workouts_incremental = await self.sync_workouts_incremental()

        body = await self.sync_body()

        if workouts_full is not None:
            workouts_touched = workouts_full.workouts_upserted
        elif workouts_incremental is not None:
            workouts_touched = workouts_incremental.events_applied
        else:  # pragma: no cover - the branch above always sets one of the two
            workouts_touched = 0

        # COUNTS and the mode, never a title, a weight or a measurement. This line is written
        # on every successful run, so anything that reached it would reach the log sink on
        # every run (T-03-46, blueprint 44).
        log.info(
            "hevy_sync_all_completed",
            mode=resolved,
            templates=templates.templates_upserted,
            workouts=workouts_touched,
            body=body.rows_upserted,
        )
        return SyncReport(
            mode=resolved,
            templates=templates,
            workouts_full=workouts_full,
            workouts_incremental=workouts_incremental,
            body=body,
        )

    async def status(self) -> list[ResourceStatus]:
        """HEVY-09, in one call.

        Delegates to `resource_status` so the never-synced rule has exactly one
        implementation; a second copy here is how the two would eventually disagree.
        """
        return await resource_status(self._sessionmaker, user_id=self._user_id)

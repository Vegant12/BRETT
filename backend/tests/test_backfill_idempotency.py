"""HEALTH-10 and ROADMAP success criterion #3 against a real Postgres container.

The backfill's whole correctness claim is that a historical row and a webhook row for the same
logical day are the SAME row. That only means anything against a database that actually enforces
the five-column unique constraint. SQLite would accept a duplicate key and every assertion in
this file would pass while production silently grew two rows per day -- which is the failure this
phase exists to prevent, and the one that is invisible from the application side.

Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share a
session-scoped container with every other integration test, and a health row that outlived its
test would make the NEXT test's "one row, not two" assertion depend on execution order. The same
discipline `test_health_ingest_idempotency.py` and `test_hevy_body.py` keep, for the same reason.

Non-ASCII source names are written as ESCAPES (`\\u2019`), never as literals. Both device names
carry U+2019 RIGHT SINGLE QUOTATION MARK, which is invisible in a diff and which one careless
editor normalising to an ASCII apostrophe would silently turn into a different assertion -- the
backfill would then write a `source_name` the webhook never sends, and criterion #3 would fail
with no test noticing. `export_sample.xml` is the one place the literal is allowed to live,
because it is data, read with an explicit `encoding="utf-8"`.

What deliberately lives ELSEWHERE: the parse itself
(`test_health_auto_export_backfill.py`, fast suite, no container) and the memory ceiling against
the user's gitignored 191 MB file (`test_backfill_real_export.py`, behind the `realfile` marker).
"""

import datetime as dt
import io
import json
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import HealthDailyMetric, SyncState
from app.db.repositories.sync_state import (
    PROVIDER_APPLE_HEALTH,
    RESOURCE_ACTIVITY,
    RESOURCE_NUTRITION,
    complete_sync,
    ensure_sync_state,
    get_sync_state,
)
from app.integrations.health_auto_export import backfill, ingest, normalize
from app.integrations.health_auto_export.backfill import BackfillSummary, run_backfill
from app.integrations.health_auto_export.ingest import ingest_payload
from app.integrations.health_auto_export.schemas import HAEPayload
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hae_fixture, hae_xml_fixture

# One stored row, as comparable DATA rather than as ORM identity:
# (metric, source_name, local_day, value, units, sample_count).
#
# `value` is read back as the `Decimal` the `NUMERIC(14,4)` column holds and compared exactly. A
# float comparison would hide precisely the corruption that matters here -- a value that survives
# the round trip in one representation and not the other.
Snapshot = tuple[str, str, dt.date, Decimal, str, int]

FIXTURE_NAME = "export_sample"

# The live-verified webhook source vocabulary. These strings sit INSIDE the natural key
# `(user_id, source, metric, source_name, local_day)`, so the backfill reproducing them
# byte-for-byte is the only reason an overlapping metric-day is ONE row rather than two.
DEVICE_CURRENT = "V\u2019s iPhone"  # device_capture.json, live-verified 2026-09-03
DEVICE_PREVIOUS = "Vegant\u2019s iPhone"  # the pre-rename name, still 86% of the real export
NUTRITION_SOURCE = "Foodvisor"

# `users.timezone` is Asia/Jakarta (+07:00) and every timestamp in both fixtures carries +0700,
# so no datapoint crosses a local-day boundary here. Pitfall N-4's boundary case has its own test
# in `test_health_ingest_idempotency.py`; this file is about the natural key, not the clock.
BUSY_DAY = dt.date(2026, 9, 2)
NEXT_DAY = dt.date(2026, 9, 3)

# What `export_sample.xml` produces: 14 rows over two local days. Pinned as a literal rather than
# read off the summary, so a fixture edit that changes the row set fails HERE rather than silently
# weakening every count assertion below.
EXPECTED_ROWS = 14

# The 2026-09-02 `step_count` values the two paths write for DEVICE_CURRENT. They are DIFFERENT on
# purpose: replace semantics means whichever path ran last wins, and equal values would make
# "replaced, not summed" unprovable.
BACKFILL_STEPS = Decimal("1500")  # 1000 + 500, two raw HealthKit samples
BACKFILL_STEP_SAMPLES = 2
WEBHOOK_STEPS = Decimal("6500")  # device_capture.json, one daily aggregate
WEBHOOK_STEP_SAMPLES = 1
SUMMED_STEPS = Decimal("8000")  # what an ADDITIVE conflict clause would leave behind

# The old phone's row for the same metric and the same day. It must survive both paths untouched:
# the collision is per `source_name`, not per day.
PREVIOUS_PHONE_STEPS = Decimal("700")

APPLE_RESOURCES = (RESOURCE_ACTIVITY, RESOURCE_NUTRITION)

# A distinct, obviously-not-now instant for pre-seeded bookkeeping rows, so "advanced" and
# "unchanged" are observable statements rather than artefacts of two NULLs comparing equal.
SEEDED_AT = dt.datetime(2026, 7, 4, 9, 15, tzinfo=dt.UTC)

# `source_name` is String(128). Longer than that is a `DataError` from PostgreSQL, which is the
# cheapest reproducible way to prove one bad row is skipped and the rest of the chunk lands.
LONG_SOURCE = "A" * 200

# The quantity on that bad row. Never asserted as a stored value -- it exists to be searched for
# in the captured log stream, where it must not appear (T-09-13).
BAD_ROW_ENERGY = "312.44"

# A minimal HealthKit export carrying exactly one row that cannot be written. Three metrics, so
# the surviving two prove the transaction is still usable; `active_energy` sorts FIRST in
# `normalize_payload`'s deterministic row order, so the failure happens before the good rows and
# not after them.
_BAD_ROW_EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_ID">
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="{long_source}" \
unit="kcal" creationDate="2026-09-02 08:06:00 +0700" startDate="2026-09-02 08:05:00 +0700" \
endDate="2026-09-02 08:35:00 +0700" value="{energy}"/>
 <Record type="HKQuantityTypeIdentifierDietaryProtein" sourceName="{nutrition}" unit="g" \
creationDate="2026-09-02 21:00:00 +0700" startDate="2026-09-02 00:00:00 +0700" \
endDate="2026-09-02 00:00:00 +0700" value="155.7"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="{device}" unit="count" \
creationDate="2026-09-02 08:01:00 +0700" startDate="2026-09-02 08:00:00 +0700" \
endDate="2026-09-02 08:30:00 +0700" value="4200"/>
</HealthData>
"""


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _payload(name: str) -> HAEPayload:
    return HAEPayload.model_validate(hae_fixture(name))


def _export(name: str = FIXTURE_NAME) -> Path:
    return hae_xml_fixture(name)


async def _run(
    maker: async_sessionmaker[AsyncSession], *, path: Path | None = None, dry_run: bool = False
) -> BackfillSummary:
    """One backfill run, with the arguments `cli.py` will pass.

    `user_id` is resolved here, server-side, and never read from the file -- `export.xml` cannot
    supply one and must not be able to (T-09-11).
    """
    return await run_backfill(
        maker, user_id=DEFAULT_USER_ID, path=path or _export(), dry_run=dry_run
    )


async def _read_all_rows(maker: async_sessionmaker[AsyncSession]) -> list[Snapshot]:
    """Every stored health row for this user, as comparable data."""
    async with maker() as session:
        rows = await session.scalars(
            sa.select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        return sorted(
            (row.metric, row.source_name, row.local_day, row.value, row.units, row.sample_count)
            for row in rows
        )


async def _read_one(
    maker: async_sessionmaker[AsyncSession], metric: str, source_name: str, day: dt.date
) -> Snapshot:
    """The single row for a full natural key, asserting there is exactly one.

    The count assertion is the load-bearing half: the failure this whole file exists to catch is
    a SECOND row appearing for a key, and a `LIMIT 1` read would report the first of two as
    though nothing were wrong.

    Keyed on `(metric, source_name, local_day)` rather than on the pair the webhook-only analog
    uses, because the backfill legitimately writes the same metric from the same source on more
    than one day.
    """
    matching = [
        row
        for row in await _read_all_rows(maker)
        if row[0] == metric and row[1] == source_name and row[2] == day
    ]
    assert len(matching) == 1, (
        f"HEALTH-10 / criterion #3 violated: expected exactly one row for {metric!r} from "
        f"{source_name!r} on {day}, found {len(matching)}. More than one means ON CONFLICT is "
        f"not firing -- the backfill is not naming the constraint the database actually "
        f"enforces, or it is not reproducing the webhook's source_name byte-for-byte"
    )
    return matching[0]


async def _duplicate_keys(
    maker: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str, dt.date, int]]:
    """Any `(metric, source_name, local_day)` holding more than one row.

    Asked of the DATABASE rather than derived from the snapshot list, so the answer comes from
    the same place the constraint does.
    """
    async with maker() as session:
        result = await session.execute(
            sa.select(
                HealthDailyMetric.metric,
                HealthDailyMetric.source_name,
                HealthDailyMetric.local_day,
                sa.func.count().label("rows"),
            )
            .where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
            .group_by(
                HealthDailyMetric.metric,
                HealthDailyMetric.source_name,
                HealthDailyMetric.local_day,
            )
            .having(sa.func.count() > 1)
        )
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]


async def _apple_state(
    maker: async_sessionmaker[AsyncSession], resource: str
) -> dt.datetime | None:
    async with maker() as session:
        state = await get_sync_state(
            session, user_id=DEFAULT_USER_ID, provider=PROVIDER_APPLE_HEALTH, resource=resource
        )
    return state.last_synced_at if state is not None else None


async def _all_apple_state(
    maker: async_sessionmaker[AsyncSession],
) -> dict[str, dt.datetime | None]:
    return {resource: await _apple_state(maker, resource) for resource in APPLE_RESOURCES}


async def _seed_apple_health(maker: async_sessionmaker[AsyncSession]) -> None:
    """Both Apple Health bookkeeping rows, already synced at a distinct PAST instant.

    They must EXIST before the run. Without that, "the timestamps advanced" would hold just as
    well because the rows were created from nothing -- and "unchanged" would hold because both
    sides were NULL. Written through the repository's own helpers, never by hand: one
    implementation of the ON CONFLICT rule.
    """
    async with maker() as session:
        for resource in APPLE_RESOURCES:
            await ensure_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_APPLE_HEALTH,
                resource=resource,
            )
            await complete_sync(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_APPLE_HEALTH,
                resource=resource,
                last_synced_at=SEEDED_AT,
            )
        await session.commit()


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove everything this module writes, pass or fail.

    EVERY `sync_state` row for this user goes, not only the two Apple Health ones: a surviving
    bookkeeping row would make the next module's "never synced reports None" assertion depend on
    execution order, which is the exact class of failure this per-test `finally` exists to
    prevent.
    """
    async with maker() as session:
        await session.execute(
            sa.delete(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        await session.execute(sa.delete(SyncState).where(SyncState.user_id == DEFAULT_USER_ID))
        await session.commit()


async def _run_capturing_logs[T](
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], Awaitable[T]]
) -> tuple[T, list[dict[str, Any]]]:
    """Run `action` with the REAL logging pipeline rendered into a buffer.

    Not `structlog.testing.capture_logs`: that replaces the configured processor chain for its
    duration, which would leave a no-values-in-logs assertion green over a pipeline that never
    ran. It also bypasses stdlib logging entirely, and the stdlib handler is where
    `backfill._MultiPointDayCounter` attaches -- so the suppression would not even run.

    ALL THREE module proxies are replaced. A backfill run emits from `backfill.py` and from
    `normalize.py`, and the same test process may drive `ingest.py` too; patching one module
    would scan part of the stream and report the rest as clean. `configure_logging` also turns
    structlog's first-use cache ON, and a proxy already cached by an earlier test keeps that
    test's configuration and writes somewhere else entirely -- an empty buffer, which is a
    capture that silently checks nothing.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")  # JSONRenderer; development is console
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_logs = {module: module.log for module in (backfill, ingest, normalize)}
    try:
        configure_logging(Settings(_env_file=None))
        structlog.configure(cache_logger_on_first_use=False)
        for module in saved_logs:
            monkeypatch.setattr(module, "log", structlog.get_logger())
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        result = await action()
        rendered = buffer.getvalue()
    finally:
        for module, saved in saved_logs.items():
            module.log = saved
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
    return result, [json.loads(line) for line in rendered.splitlines() if line.strip()]


def _events(entries: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("event") == name]


def _rendered(entries: list[dict[str, Any]]) -> str:
    """The log stream as one searchable string, with `timestamp` dropped.

    Its microsecond field is an unconstrained six-digit number that will eventually contain a
    short quantity by chance, and a suite that goes red once a fortnight teaches people to re-run
    it rather than read it.
    """
    return json.dumps(
        [{key: value for key, value in entry.items() if key != "timestamp"} for entry in entries]
    )


# ---------------------------------------------------------------------------
# HEALTH-10: the write pass itself
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_backfill_writes_one_row_per_metric_source_and_day(engine: AsyncEngine) -> None:
    """The row COUNT is the claim, and it has to hold against the real unique constraint.

    A chunked multi-row upsert is the one shape that can produce duplicates without any error:
    if the conflict clause named a constraint the database does not enforce over these five
    columns, PostgreSQL would happily INSERT every row a second time on the next run. The
    `GROUP BY ... HAVING count(*) > 1` below asks the database itself, so the answer comes from
    the same place the constraint does.
    """
    maker = _maker(engine)
    try:
        summary = await _run(maker)
        rows = await _read_all_rows(maker)

        assert summary.rows_written == len(summary.scan.normalized.rows), (
            f"the writer and the aggregate disagree: {summary.rows_written} written against "
            f"{len(summary.scan.normalized.rows)} rows produced by normalize_payload"
        )
        assert summary.rows_skipped == 0
        assert summary.rows_written == EXPECTED_ROWS
        assert len(rows) == EXPECTED_ROWS, f"expected {EXPECTED_ROWS} stored rows, got {len(rows)}"
        assert await _duplicate_keys(maker) == [], (
            "HEALTH-10 violated: a (metric, source_name, local_day) key holds more than one row. "
            "The chunked upsert is not binding to the constraint the database enforces"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_running_the_backfill_twice_changes_nothing(engine: AsyncEngine) -> None:
    """Re-running the import is a no-op. This is what makes a re-run SAFE.

    It matters concretely because D-01 expects this command to be run "once, maybe twice" -- a
    dry run, then the real one, and plausibly the real one again after an interrupted first
    attempt. An additive conflict clause would pass every single-run assertion in this file and
    double 4.5 years of history here, silently and with no rollback.
    """
    maker = _maker(engine)
    try:
        await _run(maker)
        first = await _read_all_rows(maker)
        await _run(maker)
        second = await _read_all_rows(maker)

        assert first, "the first run wrote nothing, so the equality below would hold vacuously"
        assert second == first, (
            "HEALTH-10 violated: a second identical backfill changed the stored data. Values and "
            f"sample counts are compared, not just row counts. {len(first)} row(s) before, "
            f"{len(second)} after"
        )
        assert await _duplicate_keys(maker) == []
    finally:
        await _cleanup(maker)


# ---------------------------------------------------------------------------
# Success criterion #3: backfill and webhook on the same day are ONE row
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_backfill_then_webhook_on_the_same_day_is_one_row(engine: AsyncEngine) -> None:
    """SC#3, the defining test of this phase.

    RESEARCH Pitfall 2: `source_name` sits INSIDE the natural key, so the historical path and the
    live webhook produce one row per metric-day only because they emit byte-identical source
    strings. This test fails the moment those two strings diverge by one character -- a phone
    rename, an editor folding U+2019 to an ASCII apostrophe, a well-meaning `.title()` somewhere
    in the parse -- and it is the only defence against that failure. The upsert would otherwise
    simply INSERT, silently, and the historical trend would disagree with the ongoing one.

    The value is a real discriminator, not decoration: 6500 means the webhook replaced the
    backfill's 1500, and 8000 would mean the clause accumulated across the two paths.
    """
    maker = _maker(engine)
    try:
        await _run(maker)
        seeded = await _read_one(maker, "step_count", DEVICE_CURRENT, BUSY_DAY)
        assert seeded[3] == BACKFILL_STEPS
        assert seeded[5] == BACKFILL_STEP_SAMPLES

        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=_payload("device_capture"))
        stored = await _read_one(maker, "step_count", DEVICE_CURRENT, BUSY_DAY)

        assert stored[3] == WEBHOOK_STEPS, (
            f"criterion #3 violated: the webhook delivery did not REPLACE the backfilled day. "
            f"{SUMMED_STEPS} would mean the conflict clause accumulated across the two paths, "
            f"permanently inflating every day both cover. Got {stored[3]}"
        )
        assert stored[5] == WEBHOOK_STEP_SAMPLES, (
            "sample_count must track the LATEST writer. RESEARCH Open Question 2 records that it "
            "legitimately moves between 1 and N across these two paths and is diagnostic-only; "
            f"what it must not do is keep reporting the previous writer's shape. Got {stored[5]}"
        )

        previous = await _read_one(maker, "step_count", DEVICE_PREVIOUS, BUSY_DAY)
        assert previous[3] == PREVIOUS_PHONE_STEPS, (
            "the old phone's row for the same metric and the same day was overwritten. The "
            "collision is per source_name, not per day -- a webhook delivery from one phone must "
            "not touch another phone's history"
        )
        assert len(await _read_all_rows(maker)) == EXPECTED_ROWS, (
            "the overlapping webhook delivery grew the table: every one of its twelve metrics "
            "collides with a backfilled row, so the count must not move"
        )
        assert await _duplicate_keys(maker) == []
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_webhook_then_backfill_on_the_same_day_is_one_row(engine: AsyncEngine) -> None:
    """The reverse order. ORDER decides the VALUE; it must never decide the ROW COUNT.

    Worth asserting separately because the two directions exercise different halves of the
    upsert: the previous test's second write is `ingest.py`'s per-row statement landing on a
    backfilled row, this one's is `backfill.py`'s chunked multi-row statement landing on a
    webhook row. A conflict clause that was right in one direction and wrong in the other would
    pass the previous test unchanged.

    RESEARCH Open Question 2 is why `sample_count` flips back to 2 here: backfilled days hold the
    RAW HealthKit sample count while the webhook writes 1 for its daily aggregate. That divergence
    is documented and diagnostic-only -- Phase 8's "a falling sample_count means batch-split data
    loss" detector produces a false positive on any day both paths cover.
    """
    maker = _maker(engine)
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=_payload("device_capture"))
        seeded = await _read_one(maker, "step_count", DEVICE_CURRENT, BUSY_DAY)
        assert seeded[3] == WEBHOOK_STEPS

        summary = await _run(maker)
        stored = await _read_one(maker, "step_count", DEVICE_CURRENT, BUSY_DAY)

        assert stored[3] == BACKFILL_STEPS, (
            f"the backfill did not REPLACE the webhook's day. {SUMMED_STEPS} would mean the "
            f"chunked multi-row clause accumulated onto the stored quantity. Got {stored[3]}"
        )
        assert stored[5] == BACKFILL_STEP_SAMPLES
        assert summary.rows_written == EXPECTED_ROWS
        assert summary.rows_skipped == 0
        assert len(await _read_all_rows(maker)) == EXPECTED_ROWS, (
            "row count moved: twelve of the backfill's fourteen rows collide with the webhook's, "
            "so the two extra are the old phone's day and the second local day -- nothing else"
        )
        assert await _duplicate_keys(maker) == []
    finally:
        await _cleanup(maker)


# ---------------------------------------------------------------------------
# D-03 / Open Question 4: what a run may claim about freshness
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_dry_run_writes_nothing(engine: AsyncEngine) -> None:
    """D-03: the full summary, and not one changed byte in the database.

    A real webhook delivery lands FIRST so that "unchanged" is a discriminating statement rather
    than an equality between two empty lists. The dry run then reads a file that WOULD rewrite
    every one of those rows -- `step_count` on the busy day would move from 6500 to 1500 -- so if
    the dry-run gate were missing or placed after the first `session.execute`, the snapshot
    comparison below fails on real data instead of passing vacuously.

    `sync_state` is checked too, and separately: `complete_sync` sets `last_synced_at = now`, so a
    dry run that freshened Apple Health would claim data is present that was never written
    (RESEARCH Open Question 4, T-09-15).
    """
    maker = _maker(engine)
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=_payload("device_capture"))
        before_rows = await _read_all_rows(maker)
        before_state = await _all_apple_state(maker)
        assert before_rows, "the seeding delivery wrote nothing; the comparison would be vacuous"
        assert all(value is not None for value in before_state.values())

        summary = await _run(maker, dry_run=True)

        assert await _read_all_rows(maker) == before_rows, (
            "D-03 violated: --dry-run wrote to health_daily_metrics. This is the one safety net "
            "in front of committing 4.5 years of history to production with no rollback"
        )
        assert summary.dry_run is True
        assert summary.rows_written == EXPECTED_ROWS, (
            "a dry run must still report what it WOULD write; a zero here would make the "
            "no-change assertion above true for the wrong reason"
        )
        assert summary.rows_skipped == 0
        assert summary.resources_advanced == ()
        assert await _all_apple_state(maker) == before_state, (
            "D-03 / T-09-15 violated: --dry-run advanced an Apple Health freshness timestamp. "
            "Claude would then report this history as present when nothing was written"
        )
        stored = await _read_one(maker, "step_count", DEVICE_CURRENT, BUSY_DAY)
        assert stored[3] == WEBHOOK_STEPS, (
            f"the dry run rewrote the seeded row's value to {stored[3]}"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_a_real_run_advances_both_apple_health_resources(engine: AsyncEngine) -> None:
    """D-03: both resources, at ONE instant, in the same transaction as the rows.

    Equality rather than "both are recent": two `utc_now()` calls inside the loop would make one
    run report activity and nutrition as fractionally different ages, which is a difference with
    no meaning that a future reader would eventually try to interpret.

    Pre-seeding at a distinct past instant is what makes "advanced" observable -- with no rows
    beforehand the assertion would hold no matter which timestamp the run wrote, or whether it
    wrote one at all.
    """
    maker = _maker(engine)
    try:
        await _seed_apple_health(maker)
        summary = await _run(maker)

        state = await _all_apple_state(maker)
        activity = state[RESOURCE_ACTIVITY]
        nutrition = state[RESOURCE_NUTRITION]

        assert activity is not None
        assert nutrition is not None
        assert activity > SEEDED_AT, (
            f"the run did not advance the activity resource past its seeded value {SEEDED_AT!r}"
        )
        assert activity == nutrition, (
            f"one run produced two freshness instants: {activity!r} vs {nutrition!r}"
        )
        assert activity.tzinfo is not None, "FOUND-04: freshness is stored timezone-aware"
        assert summary.resources_advanced == (RESOURCE_ACTIVITY, RESOURCE_NUTRITION), (
            f"the summary must name what it advanced, for the D-06 block. Got "
            f"{summary.resources_advanced}"
        )
    finally:
        await _cleanup(maker)


# ---------------------------------------------------------------------------
# D-07 / T-09-13: one bad row costs one row
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_one_bad_row_is_skipped_and_the_rest_of_the_chunk_lands(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-07 on the WRITE side, which is where a chunked upsert could quietly lose 500 rows.

    All three rows land in one chunk, so the multi-row statement fails as a unit. The guarantee
    is that the chunk's SAVEPOINT rolls back and the per-row path is replayed for that chunk
    alone: one row is skipped, the other two land, and the run returns normally. Without the
    fallback the whole chunk -- up to 500 rows -- would be lost to one bad value, and without the
    SAVEPOINT the transaction would abort and take all 8,077 with it.

    The offending row sorts FIRST (`active_energy` precedes `protein` and `step_count` in
    `normalize_payload`'s deterministic order), so this also proves the transaction is still
    usable AFTER the failure rather than only before it.

    The log line is asserted too: `str(DataError)` renders the bound parameters, which here are
    this person's energy figure (T-09-13).
    """
    maker = _maker(engine)
    path = tmp_path / "export_with_one_bad_row.xml"
    path.write_text(
        _BAD_ROW_EXPORT.format(
            long_source=LONG_SOURCE,
            energy=BAD_ROW_ENERGY,
            nutrition=NUTRITION_SOURCE,
            device=DEVICE_CURRENT,
        ),
        encoding="utf-8",
    )
    try:
        summary, entries = await _run_capturing_logs(monkeypatch, lambda: _run(maker, path=path))
        rows = await _read_all_rows(maker)

        assert summary.rows_skipped == 1, (
            f"expected exactly one skipped row, got {summary.rows_skipped}"
        )
        assert summary.rows_written == 2, (
            f"D-07 violated: {summary.rows_written} of the 2 good rows landed. A chunk that fails "
            f"without a per-row fallback costs every row in it, and a row failing outside a "
            f"SAVEPOINT aborts the transaction and takes the whole run with it"
        )
        assert {row[0] for row in rows} == {"protein", "step_count"}

        skipped = _events(entries, "health_backfill_row_skipped")
        assert len(skipped) == 1, f"expected one skip log line, got {len(skipped)}"
        assert skipped[0]["metric"] == "active_energy"
        assert skipped[0]["local_day"] == BUSY_DAY.isoformat()
        assert skipped[0]["source_name"] == LONG_SOURCE
        assert skipped[0]["reason"].endswith("Error"), (
            f"the skip must be logged as an exception CLASS NAME, not a rendered exception. Got "
            f"reason={skipped[0]['reason']!r}"
        )
        # Without this the assertions above could pass over a mis-wired capture.
        assert _events(entries, "health_backfill_completed"), "log capture is not wired"

        assert BAD_ROW_ENERGY not in _rendered(entries), (
            "T-09-13 / FOUND-05 violated: the skipped row's measured quantity reached the log "
            "stream. `str(DataError)` renders the bound parameters -- log the class name only"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_the_second_local_day_is_written_too(engine: AsyncEngine) -> None:
    """A guard on every count above: the backfill spans DAYS, not one day.

    Positional chunking of the parse, or an aggregation keyed on metric alone, would collapse
    2026-09-03's `step_count` into 2026-09-02's and leave a row set that still looks plausible.
    The missing day would only surface as a gap in a trend months later -- which is exactly the
    failure the record accounting identity exists to make impossible on the read side, asserted
    here on the write side.
    """
    maker = _maker(engine)
    try:
        summary = await _run(maker)
        next_day = await _read_one(maker, "step_count", DEVICE_CURRENT, NEXT_DAY)

        assert next_day[2] == NEXT_DAY
        assert summary.first_day == BUSY_DAY
        assert summary.last_day == NEXT_DAY, (
            f"the summary's date range stops at {summary.last_day}, so the D-06 block would "
            f"under-report what the run covered"
        )
    finally:
        await _cleanup(maker)

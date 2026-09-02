"""HEALTH-09 and NUTR-03 against a real Postgres container.

The day-grained upsert is the whole design, and it only means anything against a database that
actually enforces `uq_health_daily_metrics_user_source_metric_source_name_day`. SQLite would
accept a duplicate key and every assertion below would pass while production silently grew two
rows per day.

Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share a
session-scoped container with every other integration test, and a health row that outlived its
test would make the NEXT test's "one row, not two" assertion depend on execution order.

Non-ASCII source names are written as ESCAPES (`\\u30ab`), never as literals: the real nutrition
app in this user's export is spelled in katakana, and a literal in source is invisible in a diff
and one careless editor away from silently becoming a different test.
"""

import datetime as dt
import io
import json
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import HealthDailyMetric, SyncState
from app.db.repositories.sync_state import PROVIDER_APPLE_HEALTH
from app.integrations.health_auto_export import ingest, normalize
from app.integrations.health_auto_export.ingest import ingest_payload
from app.integrations.health_auto_export.schemas import HAEPayload
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hae_fixture

# One stored row, as data rather than as ORM identity:
# (metric, source_name, local_day, value, units, sample_count).
Snapshot = tuple[str, str, dt.date, Decimal, str, int]

# `users.timezone` is Asia/Jakarta (+07:00) and the fixtures are stamped +0900, so a
# midnight-anchored nutrition datapoint lands on the PREVIOUS local day. That is Pitfall N-4 and
# it is deliberate -- these two constants exist so the split is asserted rather than absorbed.
FIXTURE_ACTIVITY_DAY = dt.date(2025, 8, 15)  # 08:00 and 19:00 +0900 -> 06:00 / 17:00 Jakarta
FIXTURE_MIDNIGHT_DAY = dt.date(2025, 8, 14)  # 00:00 +0900 -> 22:00 the previous Jakarta day

MORNING = "2025-08-15 08:00:00 +0900"
LATE = "2025-08-15 21:00:00 +0900"  # 19:00 Jakarta -- still FIXTURE_ACTIVITY_DAY

# The nutrition app in this user's real export, spelled in katakana.
NUTRITION_APP = "\u30ab\u30ed\u30df\u30eb"

# `source_name` is String(128). Longer than that is a `DataError` from PostgreSQL, which is the
# cheapest reproducible way to prove ONE bad row is skipped and the rest of the batch lands.
LONG_SOURCE = "A" * 200

# The seven metrics NUTR-02 allowlists. Listed here rather than derived from the registry so a
# metric silently changing kind fails this file too, not only the normalizer's own tests.
NUTRITION_METRICS = (
    "carbohydrates",
    "dietary_energy",
    "dietary_sugar",
    "fiber",
    "protein",
    "sodium",
    "total_fat",
)


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _payload(name: str) -> HAEPayload:
    return HAEPayload.model_validate(hae_fixture(name))


def _wire(name: str, units: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "units": units, "data": points}


def _built(*metrics: dict[str, Any]) -> HAEPayload:
    """A payload assembled in code, for the cases whose point is a SHAPE the fixtures lack."""
    return HAEPayload.model_validate({"data": {"metrics": list(metrics)}})


async def _read_all_rows(maker: async_sessionmaker[AsyncSession]) -> list[Snapshot]:
    """Every stored health row, as comparable DATA.

    `value` is read back as the `Decimal` the `NUMERIC(14,4)` column holds and compared exactly.
    A float comparison here would hide precisely the corruption Finding C is about -- a prorated
    `flights_climbed` fragment that survives the round trip in one representation and not the
    other.
    """
    async with maker() as session:
        rows = await session.scalars(
            sa.select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        return sorted(
            (row.metric, row.source_name, row.local_day, row.value, row.units, row.sample_count)
            for row in rows
        )


async def _read_one(
    maker: async_sessionmaker[AsyncSession], metric: str, source_name: str
) -> Snapshot:
    """The single row for a `(metric, source_name)` pair, asserting there is exactly one.

    The count assertion is the load-bearing half: the failure mode this whole file exists to
    catch is a SECOND row appearing for a key, and a `LIMIT 1` read would report the first of
    two as though nothing were wrong.
    """
    matching = [
        row for row in await _read_all_rows(maker) if row[0] == metric and row[1] == source_name
    ]
    assert len(matching) == 1, (
        f"HEALTH-09 violated: expected exactly one row for {metric!r} from {source_name!r}, "
        f"found {len(matching)}. More than one means ON CONFLICT is not firing -- the upsert is "
        f"not naming the constraint the database actually enforces"
    )
    return matching[0]


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove everything this module writes, pass or fail."""
    async with maker() as session:
        await session.execute(
            sa.delete(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
        await session.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID,
                SyncState.provider == PROVIDER_APPLE_HEALTH,
            )
        )
        await session.commit()


async def _run_capturing_logs[T](
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], Awaitable[T]]
) -> tuple[T, list[dict[str, Any]]]:
    """Run `action` with the REAL logging pipeline rendered into a buffer.

    Not `structlog.testing.capture_logs`: that replaces the configured processor chain for its
    duration, which would leave a no-values-in-logs assertion green over a pipeline that never
    ran (`test_secret_redaction.py`'s Pitfall 6, and `test_hevy_body.py`'s note on the same).

    BOTH module proxies are replaced. An ingest emits from `ingest.py` and from `normalize.py`
    in the same call, so patching only one would scan half the log stream and report the other
    half as clean. `configure_logging` also turns structlog's first-use cache ON, and a proxy
    already cached by an earlier test keeps that test's configuration and writes somewhere else
    entirely -- an empty buffer, which is a capture that silently checks nothing.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")  # JSONRenderer; development is console
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_ingest, saved_normalize = ingest.log, normalize.log
    try:
        configure_logging(Settings(_env_file=None))
        structlog.configure(cache_logger_on_first_use=False)
        fresh = structlog.get_logger()
        monkeypatch.setattr(ingest, "log", fresh)
        monkeypatch.setattr(normalize, "log", fresh)
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        result = await action()
        rendered = buffer.getvalue()
    finally:
        ingest.log, normalize.log = saved_ingest, saved_normalize
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
    return result, [json.loads(line) for line in rendered.splitlines() if line.strip()]


def _events(entries: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("event") == name]


def _scan(entries: list[dict[str, Any]]) -> str:
    """The log stream as one searchable string, with `timestamp` dropped.

    Its microsecond field is an unconstrained six-digit number that will eventually contain a
    short quantity by chance, and a suite that goes red once a fortnight teaches people to
    re-run it rather than read it.
    """
    return json.dumps(
        [{key: value for key, value in entry.items() if key != "timestamp"} for entry in entries]
    )


# ---------------------------------------------------------------------------
# HEALTH-09 / NUTR-03: re-sending an overlapping export window is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_identical_payload_twice_changes_nothing(engine: AsyncEngine) -> None:
    """HEALTH-09 / ROADMAP criterion #3: re-sending an overlapping export window is a no-op.

    An additive conflict clause passes a single-delivery test and fails this one -- which is the
    entire reason this test exists against a real constraint rather than as a unit test on the
    statement object.
    """
    maker = _maker(engine)
    payload = _payload("activity_and_nutrition")
    try:
        first = await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        snapshot_1 = await _read_all_rows(maker)
        second = await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        snapshot_2 = await _read_all_rows(maker)

        assert snapshot_1, (
            "HEALTH-09 cannot be proven against an empty table: the first ingest wrote nothing, "
            "so the equality below would hold vacuously"
        )
        assert snapshot_2 == snapshot_1, (
            "HEALTH-09 violated: a second delivery of the identical window changed the stored "
            "data. In production Health Auto Export re-sends overlapping windows routinely, so "
            "an additive conflict clause inflates every calorie and step figure on every "
            f"delivery. {len(snapshot_1)} row(s) before, {len(snapshot_2)} after"
        )
        assert second.rows_upserted == first.rows_upserted, (
            f"the second ingest wrote a different number of rows than the first: "
            f"{first.rows_upserted} then {second.rows_upserted}"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_one_row_per_metric_source_and_local_day(engine: AsyncEngine) -> None:
    """The row COUNT is the claim, and it has to hold against the real unique constraint.

    Twelve allowlisted metrics, one source each, spread over the two local days Pitfall N-4
    produces from a +0900 payload read in Jakarta. Thirteen rows would mean the natural key is
    not the one the upsert names; eleven would mean a metric was silently dropped.
    """
    maker = _maker(engine)
    try:
        result = await ingest_payload(
            maker, user_id=DEFAULT_USER_ID, payload=_payload("activity_and_nutrition")
        )
        rows = await _read_all_rows(maker)

        assert result.rows_upserted == 12
        assert result.rows_skipped == 0
        assert result.metrics_unrecognized == 0
        assert len(rows) == 12, f"expected 12 stored rows, found {len(rows)}"
        assert {row[0] for row in rows} == set(NUTRITION_METRICS) | {
            "step_count",
            "active_energy",
            "basal_energy_burned",
            "walking_running_distance",
            "flights_climbed",
        }
        by_metric = {row[0]: row for row in rows}
        assert by_metric["step_count"][2] == FIXTURE_ACTIVITY_DAY
        assert by_metric["protein"][2] == FIXTURE_MIDNIGHT_DAY, (
            "Pitfall N-4: a midnight-anchored +0900 datapoint belongs to the PREVIOUS Jakarta "
            f"day. Got {by_metric['protein'][2]}"
        )
        # Aggregated within the delivery, which is what makes replace semantics correct.
        assert by_metric["step_count"][5] == 2
        assert by_metric["step_count"][3] == Decimal("7927.5000")
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_an_overlapping_window_replaces_rather_than_accumulates(
    engine: AsyncEngine,
) -> None:
    """HEALTH-09: an OVERLAPPING -- not identical -- re-send still leaves one row per key.

    The second payload is a strict SUPERSET of the first for the same metric-day, built by
    APPENDING a datapoint rather than by editing one, so the aggregate legitimately changes and
    the stored value is a real discriminator: it must equal the second delivery's own total, not
    the sum of both deliveries. An additive clause would store 17427.5 here and look plausible.
    """
    maker = _maker(engine)
    first_payload = _payload("activity_and_nutrition")
    raw = hae_fixture("activity_and_nutrition")
    for metric in raw["data"]["metrics"]:
        if metric["name"] == "step_count":
            metric["data"].append({"qty": 1500.0, "date": LATE, "source": "iPhone"})
    second_payload = HAEPayload.model_validate(raw)
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=first_payload)
        before = await _read_one(maker, "step_count", "iPhone")
        assert before[3] == Decimal("7927.5000")
        assert before[5] == 2

        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=second_payload)
        after = await _read_one(maker, "step_count", "iPhone")

        assert after[3] == Decimal("9427.5000"), (
            "HEALTH-09 violated: the overlapping window did not REPLACE the stored total. "
            "4821.0 + 3106.5 + 1500.0 is the second delivery's own aggregate; anything larger "
            "means the conflict clause accumulated across deliveries and every re-sent window "
            f"inflates this figure permanently. Got {after[3]}"
        )
        assert after[5] == 3, (
            "sample_count must track the LATEST delivery -- a count that stops moving is the "
            f"batch-split detector Pitfall N-2 relies on. Got {after[5]}"
        )
        assert len(await _read_all_rows(maker)) == 12, "the overlapping re-send grew the table"
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_nutrition_metrics_survive_an_identical_redelivery_unchanged(
    engine: AsyncEngine,
) -> None:
    """NUTR-03 for the seven nutrition metrics specifically, sodium included.

    Sodium is called out because it is the one metric whose canonical unit differs from its
    commonest wire unit: stored in mg, and a gram-valued sodium row is off by a factor of 1000
    while still looking like a number a person could eat.
    """
    maker = _maker(engine)
    payload = _payload("activity_and_nutrition")
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        before = {row[0]: row for row in await _read_all_rows(maker) if row[0] in NUTRITION_METRICS}
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        after = {row[0]: row for row in await _read_all_rows(maker) if row[0] in NUTRITION_METRICS}

        assert set(before) == set(NUTRITION_METRICS), (
            f"NUTR-02/NUTR-03: expected all seven nutrition metrics stored, got {sorted(before)}"
        )
        assert after == before, (
            "NUTR-03 violated: a second delivery of the identical window changed a stored "
            "nutrition figure. Health Auto Export re-sends overlapping windows routinely, so "
            "this is a daily calorie and macro total drifting upward with no error anywhere"
        )
        assert before["sodium"][4] == "mg", (
            f"NUTR-02: sodium is stored in milligrams. Got {before['sodium'][4]!r}"
        )
        assert before["sodium"][3] == Decimal("3177.1654")
        assert before["protein"][3] == Decimal("155.7000")
        assert all(row[1] == NUTRITION_APP for row in before.values()), (
            "the nutrition source name did not survive the round trip verbatim -- source_name "
            "is a KEY column, so a mangled one silently creates a second row per day"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_an_overlapping_nutrition_window_replaces_rather_than_accumulates(
    engine: AsyncEngine,
) -> None:
    """NUTR-03's half of the overlapping-window case, on a real logged day.

    Nutrition is where accumulation would be most convincing and most wrong: a nutrition app
    re-posting the same day's total is the NORMAL case, not an edge one, so an additive clause
    would double this user's recorded intake on the first ordinary re-delivery.
    """
    maker = _maker(engine)
    day = "2026-08-23 12:00:00 +0700"
    later = "2026-08-23 19:30:00 +0700"
    first_payload = _built(
        _wire("dietary_energy", "kcal", [{"qty": 1040, "date": day, "source": "Foodvisor"}])
    )
    second_payload = _built(
        _wire(
            "dietary_energy",
            "kcal",
            [
                {"qty": 1040, "date": day, "source": "Foodvisor"},
                {"qty": 504, "date": later, "source": "Foodvisor"},
            ],
        )
    )
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=first_payload)
        assert (await _read_one(maker, "dietary_energy", "Foodvisor"))[3] == Decimal("1040.0000")

        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=second_payload)
        stored = await _read_one(maker, "dietary_energy", "Foodvisor")

        assert stored[3] == Decimal("1544.0000"), (
            "NUTR-03 violated: 1040 + 504 is the second delivery's own aggregate. 2584 would "
            f"mean the first delivery was accumulated onto rather than replaced. Got {stored[3]}"
        )
        assert stored[5] == 2
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_two_sources_on_one_day_stay_two_rows_across_a_resend(
    engine: AsyncEngine,
) -> None:
    """Finding D: two nutrition apps really did write the same metric on 2026-08-23.

    Two rows, not one -- blending them is correct only if the two apps logged disjoint food, and
    nothing guarantees that. Two rows, not four -- the second delivery must upsert both, which
    is only true if `source_name` is genuinely part of the constraint the database enforces.
    """
    maker = _maker(engine)
    day = "2026-08-23 12:00:00 +0700"
    payload = _built(
        _wire(
            "dietary_energy",
            "kcal",
            [
                {"qty": 1040, "date": day, "source": "Foodvisor"},
                {"qty": 504, "date": day, "source": "Foodvisor"},
                {"qty": 670, "date": day, "source": "Foodvisor"},
                {"qty": 105, "date": day, "source": "Built With Science"},
                {"qty": 295.62, "date": day, "source": "Built With Science"},
            ],
        )
    )
    try:
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        first = await _read_all_rows(maker)
        await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload)
        second = await _read_all_rows(maker)

        assert len(first) == 2, (
            "HEALTH-08's prerequisite: `source_name` is a KEY column, so two apps writing the "
            f"same metric on one day are two addressable rows. Got {len(first)}"
        )
        assert len(second) == 2, (
            f"the re-send produced {len(second)} rows. Four would mean the constraint does not "
            f"include source_name; one would mean the two apps were blended into a single row "
            f"that can never be split apart again"
        )
        assert second == first
        assert (await _read_one(maker, "dietary_energy", "Foodvisor"))[3] == Decimal("2214.0000")
        assert (await _read_one(maker, "dietary_energy", "Built With Science"))[3] == Decimal(
            "400.6200"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_a_fractional_count_metric_survives_the_numeric_round_trip(
    engine: AsyncEngine,
) -> None:
    """Finding C: HAE prorates `count` metrics, so a real day arrives fractional.

    `flights_climbed` is 0.20163697817574894 in the captured payload. An INTEGER column -- the
    obvious choice for something called a count -- truncates that to 0 with no error anywhere,
    and 59 such fragments become a day on which the user climbed nothing.
    """
    maker = _maker(engine)
    try:
        await ingest_payload(
            maker, user_id=DEFAULT_USER_ID, payload=_payload("activity_and_nutrition")
        )
        stored = await _read_one(maker, "flights_climbed", "iPhone")

        assert stored[3] > Decimal("0"), (
            "Finding C violated: a prorated count metric truncated to zero on the way into the "
            "database. NUMERIC(14,4) is what keeps the fragment, and losing it is silent"
        )
        assert stored[3] == Decimal("0.2016"), (
            f"NUMERIC(14,4) keeps four decimal places of 0.20163697817574894. Got {stored[3]}"
        )
        assert stored[4] == "count"
    finally:
        await _cleanup(maker)


# ---------------------------------------------------------------------------
# T-08-40: one bad row costs itself and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_one_bad_row_is_skipped_and_the_rest_of_the_batch_lands(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-08-40: the SAVEPOINT is what keeps one bad row from costing the whole window.

    The offending row sorts FIRST (`active_energy` precedes `protein` and `step_count`), so this
    also proves the transaction is still usable AFTER the failure -- without `begin_nested` the
    `DataError` aborts it and every later statement dies with "current transaction is aborted",
    losing the entire window on an endpoint whose sender never retries.

    The log line is asserted too: `str(DataError)` renders the bound parameters, which here are
    this person's calorie count (T-08-39).
    """
    maker = _maker(engine)
    payload = _built(
        _wire("active_energy", "kcal", [{"qty": 312.44, "date": MORNING, "source": LONG_SOURCE}]),
        _wire("protein", "g", [{"qty": 155.7, "date": MORNING, "source": "Foodvisor"}]),
        _wire("step_count", "count", [{"qty": 4200, "date": MORNING, "source": "iPhone"}]),
    )
    try:
        result, entries = await _run_capturing_logs(
            monkeypatch,
            lambda: ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=payload),
        )
        rows = await _read_all_rows(maker)

        assert result.rows_skipped == 1, (
            f"expected exactly one skipped row, got {result.rows_skipped}"
        )
        assert result.rows_upserted == 2, (
            f"T-08-40 violated: {result.rows_upserted} of the 2 good rows landed. A row failing "
            f"outside a SAVEPOINT aborts the transaction and takes the whole window with it"
        )
        assert {row[0] for row in rows} == {"protein", "step_count"}

        skipped = _events(entries, "health_ingest_row_skipped")
        assert len(skipped) == 1, f"expected one skip log line, got {len(skipped)}"
        assert skipped[0]["metric"] == "active_energy"
        assert skipped[0]["reason"].endswith("Error"), (
            f"the skip must be logged as an exception CLASS NAME, not a rendered exception. "
            f"Got reason={skipped[0]['reason']!r}"
        )
        assert "312.44" not in _scan(entries), (
            "T-08-39 / FOUND-05 violated: the skipped row's measured quantity reached the log "
            "stream. `str(DataError)` renders the bound parameters -- log the class name only"
        )
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_an_empty_payload_commits_nothing_and_returns_zeroes(engine: AsyncEngine) -> None:
    """A delivery carrying no recognised data must be a silent, total no-op.

    Not an error: Health Auto Export has no documented retry, and a webhook that rejects an
    empty window teaches the device nothing while a webhook that half-commits one leaves a
    freshness timestamp claiming data that does not exist.
    """
    maker = _maker(engine)
    try:
        result = await ingest_payload(maker, user_id=DEFAULT_USER_ID, payload=_built())

        assert result == ingest.HealthIngestResult(
            rows_upserted=0,
            rows_skipped=0,
            datapoints_seen=0,
            datapoints_dropped=0,
            metrics_unrecognized=0,
        )
        assert await _read_all_rows(maker) == []
    finally:
        await _cleanup(maker)

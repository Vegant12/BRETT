"""ROADMAP criterion #4, asserted as row counts rather than as a rule anyone has to remember.

"Apple Health workouts and Hevy-originated body-mass rows never enter BRETT's training or body
data -- the volume, frequency, and body-weight numbers Claude reports are identical before and
after Apple Health data exists."

The exclusion is done at WRITE time (RESEARCH Open Question 1), which is what makes that
sentence provable HERE, in one test, instead of by auditing every present and future analytics
reader. That auditing burden is exactly the trap `PITFALLS.md` Pitfall 9 describes for
`_dedupe_by_day`, and this phase declines to take it on.

Against a real Postgres container: the point is what the DATABASE holds, and SQLite would not
enforce the constraint that makes `source_name` a real key column.

On the fixture dates. The three HAE fixtures are stamped 2025-08 and 2026-01, outside the
28-day analytics window the snapshot uses, and that is deliberate rather than an oversight: the
isolation claim is about TABLES, not about windows. No analytics reader touches
`health_daily_metrics` at all, so a date inside the window would prove nothing extra. The claim
that a date COULD matter -- an Apple Health row reaching `body_measurements`, which
`get_body_weight_trend` does read -- is closed structurally by
`test_no_apple_health_row_lands_in_body_measurements` instead.
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.analytics.bodyweight import get_body_weight_trend
from app.analytics.frequency import get_training_frequency
from app.analytics.volume import get_muscle_group_volume, get_weekly_volume
from app.core.time import local_day, utc_now
from app.db.models import BodyMeasurement, HealthDailyMetric, SyncState, User, Workout
from app.integrations.health_auto_export.ingest import ingest_payload
from app.integrations.health_auto_export.schemas import HAEPayload
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder, GoldenExercise, GoldenSet, hae_fixture

# Every fixture this phase captured, ingested together. `hevy_active_energy` is the Finding A
# case and the reason `test_no_hevy_sourced_row_lands_in_health_daily_metrics` exists;
# `unrecognized_and_sourceless` carries the `weight_body_mass` row D-01 keeps out of the
# registry.
ALL_FIXTURES = ("activity_and_nutrition", "hevy_active_energy", "unrecognized_and_sourceless")

# The analytics window. Four whole weeks ending today, which is long enough for the weekly
# spine to have several buckets and short enough that the seed below stays hand-checkable.
WINDOW_DAYS = 27

# `hevy_active_energy.json` carries a 666.5 kcal `active_energy` datapoint whose `source` is
# Hevy. Named here so the HEALTH-08 failure message can say what it is rather than only that a
# row exists.
HEVY_SOURCE_NAME = "Hevy"

# Days the seeded user did not step on the scale, counted back from the anchor. Inside the
# 7-day window (which needs 3 measured days of 7, so 5 is comfortably sufficient) and therefore
# inside all three. See the comment in `_seed_hevy_history`: without a gap, a stray
# 'apple_health' weigh-in is invisible to `_dedupe_by_day` and this file cannot fail.
MISSED_WEIGH_IN_DAYS = frozenset({2, 3})


@pytest.fixture(autouse=True)
async def _purge_health_rows(session: AsyncSession) -> AsyncIterator[None]:
    """Remove every ingested row before AND after each test in this module.

    `committed_history` already purges these two tables, but only the tests that request it get
    that teardown -- and half the tests here deliberately do not need a Hevy history. Without
    this, `test_no_hevy_sourced_row_lands_in_health_daily_metrics` leaves thirteen committed
    rows behind and `test_the_ingest_actually_wrote_something` then measures them as though its
    own first delivery had written them. It passed alone and failed in a full-file run, which is
    the signature of exactly this.

    Purged on the way IN as well as OUT, so a crash in an earlier module cannot make a test here
    fail for a reason that has nothing to do with it. Uses the test's OWN session rather than a
    second connection: a separate connection would block on rows the test's open transaction
    still holds.
    """
    await _purge(session)
    try:
        yield
    finally:
        await _purge(session)


async def _purge(session: AsyncSession) -> None:
    # Rollback FIRST, so a mid-test failure that left the transaction aborted does not make
    # every statement below raise `InFailedSqlTransaction` and skip the purge entirely.
    await session.rollback()
    await session.execute(
        sa.delete(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
    )
    await session.execute(sa.delete(SyncState).where(SyncState.user_id == DEFAULT_USER_ID))
    await session.commit()


async def _user_timezone(session: AsyncSession) -> str:
    """The seeded user's IANA zone, READ rather than assumed.

    A hardcoded `Asia/Jakarta` here would silently agree with a wrong value in the database:
    both the fixture and the code under test would use the same wrong zone and the window would
    still line up. `core/time.py` makes the same argument about default zones.
    """
    tz = await session.scalar(sa.select(User.timezone).where(User.id == DEFAULT_USER_ID))
    assert tz is not None, "migration 0002's default user is missing"
    return str(tz)


async def _seed_hevy_history(builder: GoldenBuilder, session: AsyncSession) -> None:
    """A compact but non-degenerate Hevy history: templates, workouts, and daily weigh-ins.

    Deliberately NOT `worst_case_history`. That fixture writes ~5,200 set rows to measure a
    payload budget; nothing here is about size, and a smaller seed means a failure message
    points at a diff a person can read.

    Anchored on `utc_now()` rather than a fixed date. A fixed anchor silently ages out of the
    window ending today, at which point every snapshot compares two empty results and the whole
    file passes for the wrong reason -- which is what `test_the_snapshot_is_not_empty` exists to
    catch.
    """
    await builder.template(
        external_id="ISO-BENCH",
        title="Isolation Bench Press",
        muscles=[(CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT)],
    )
    await builder.template(
        external_id="ISO-ROW",
        title="Isolation Barbell Row",
        muscles=[
            (CanonicalMuscleGroup.UPPER_BACK, MuscleRole.DIRECT),
            (CanonicalMuscleGroup.BICEPS, MuscleRole.INDIRECT),
        ],
    )

    # 02:00Z is 09:00 in Asia/Jakarta -- well inside the local day, so the fixture exercises the
    # arithmetic and never the local-midnight boundary, which has its own tests elsewhere.
    anchor = utc_now().replace(hour=2, minute=0, second=0, microsecond=0)
    for offset in (1, 4, 8, 11, 15, 18, 22, 25):
        await builder.workout(
            start_time=anchor - dt.timedelta(days=offset),
            title=f"Isolation Session D-{offset}",
            exercises=[
                GoldenExercise(
                    template_external_id="ISO-BENCH",
                    sets=[
                        GoldenSet(set_type="warmup", weight_kg=Decimal("40.000"), reps=10),
                        GoldenSet(weight_kg=Decimal("80.000"), reps=8),
                        GoldenSet(weight_kg=Decimal("80.000"), reps=7),
                    ],
                ),
                GoldenExercise(
                    template_external_id="ISO-ROW",
                    sets=[
                        GoldenSet(weight_kg=Decimal("60.000"), reps=10),
                        GoldenSet(weight_kg=Decimal("60.000"), reps=9),
                    ],
                ),
            ],
        )

    # Weigh-ins ending today, so `get_body_weight_trend` has a real series rather than an
    # all-None result that would compare equal to itself no matter what the ingest did. Decimal,
    # never float: these average into rolling 7/14/30-day figures and binary floating point
    # would make two arithmetically identical averages compare unequal.
    #
    # `MISSED_WEIGH_IN_DAYS` is what makes this test able to FAIL, and it was added after the
    # gapless version was mutation-checked and found insensitive. `_dedupe_by_day` does not
    # filter by source, and it orders `(measured_on, source)` -- so on a day that already has a
    # 'hevy' row, a stray 'apple_health' row sorts first and is overwritten, changing nothing.
    # It wins only on a day Hevy has NO row for. A gapless seed therefore proves that an Apple
    # Health leak is invisible, not that it is absent, and two skipped days are what turn the
    # equality below into a real assertion. This is `PITFALLS.md` Pitfall 9 in miniature.
    anchor_day = anchor.date()
    for offset in range(35):
        if offset in MISSED_WEIGH_IN_DAYS:
            continue
        await builder.body_measurement(
            measured_on=anchor_day - dt.timedelta(days=offset),
            weight_kg=Decimal("80.000") + Decimal(offset) / Decimal(20),
        )

    await session.commit()


def _comparable(result: Any) -> dict[str, Any]:
    """One analytics result as plain, exactly-comparable data, WITHOUT its freshness block.

    `mode="json"` renders every `Decimal` as a string, so two arithmetically identical answers
    compare equal and two different ones differ visibly -- a float round-trip would do neither
    reliably.

    `freshness` is EXCLUDED, and this is the one exclusion that makes the whole file work. The
    Apple Health ingest legitimately advances `sync_state` for the `activity` and `nutrition`
    resources, and `FreshnessMetadata.resources` is a dict that may carry them. Comparing it
    would make this test fail for the single reason it must not: a freshness timestamp moving is
    the ingest WORKING. What must not move is a number -- a set count, a tonnage, a rate, an
    average -- and those are everything else in the dump.

    `coverage` is deliberately NOT excluded: `sessions_in_window` and `earliest_data_at` are
    derived from workouts, so an Apple Health row changing either of them is exactly the failure
    ROADMAP criterion #4 forbids.
    """
    dumped: dict[str, Any] = result.model_dump(mode="json")
    dumped.pop("freshness", None)
    return dumped


async def _snapshot(session: AsyncSession) -> dict[str, Any]:
    """Every training and body-composition number Claude can report, in one comparable value."""
    tz = await _user_timezone(session)
    end_day = local_day(utc_now(), tz)
    start_day = end_day - dt.timedelta(days=WINDOW_DAYS)

    weekly = await get_weekly_volume(
        session, user_id=DEFAULT_USER_ID, start_day=start_day, end_day=end_day
    )
    muscle = await get_muscle_group_volume(
        session, user_id=DEFAULT_USER_ID, start_day=start_day, end_day=end_day
    )
    frequency = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=start_day, end_day=end_day
    )
    weight = await get_body_weight_trend(session, user_id=DEFAULT_USER_ID)

    return {
        "weekly_volume": _comparable(weekly),
        "muscle_group_volume": _comparable(muscle),
        "training_frequency": _comparable(frequency),
        "body_weight_trend": _comparable(weight),
    }


def _first_difference(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Name the answer that moved, rather than dumping two whole result trees at the reader."""
    for key in before:
        if before[key] != after[key]:
            return f"{key!r} changed"
    return "no top-level difference (the dicts differ in their key sets)"


async def _ingest_every_fixture(maker: async_sessionmaker[AsyncSession]) -> list[int]:
    """Ingest all three captured payloads. Returns the rows each delivery wrote."""
    written = []
    for name in ALL_FIXTURES:
        result = await ingest_payload(
            maker, user_id=DEFAULT_USER_ID, payload=HAEPayload.model_validate(hae_fixture(name))
        )
        written.append(result.rows_upserted)
    return written


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _count(session: AsyncSession, statement: sa.Select[Any]) -> int:
    return int(await session.scalar(statement) or 0)


def _rows_for(user_id: uuid.UUID, model: Any) -> sa.Select[Any]:
    return sa.select(sa.func.count()).select_from(model).where(model.user_id == user_id)


# ---------------------------------------------------------------------------
# The criterion itself
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_apple_health_ingest_changes_no_hevy_number(
    committed_history: GoldenBuilder, session: AsyncSession, engine: AsyncEngine
) -> None:
    """ROADMAP criterion #4: seed, snapshot, ingest, re-snapshot, compare.

    The comparison is EQUALITY over the whole result tree rather than a handful of spot checks,
    because the claim is universal -- "the numbers Claude reports are identical" -- and a spot
    check only covers the fields somebody thought of.
    """
    await _seed_hevy_history(committed_history, session)

    before = await _snapshot(session)
    await session.commit()

    written = await _ingest_every_fixture(_maker(engine))
    await session.commit()

    after = await _snapshot(session)

    assert sum(written) > 0, (
        f"the ingest wrote no rows at all ({written}), so the comparison below is vacuous -- it "
        f"compares a database against itself"
    )
    assert after == before, (
        f"ROADMAP criterion #4 violated: an analytics answer changed after Apple Health data was "
        f"ingested. Every number Claude reports about training must be identical before and "
        f"after, because Apple Health contributes none of them. First difference: "
        f"{_first_difference(before, after)}"
    )


@pytest.mark.integration
async def test_the_snapshot_is_not_empty(
    committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """The guard on the equality above: two empty snapshots also compare equal.

    If the seed ever ages out of the window, or `resolve_window` starts answering differently,
    the criterion test would pass while measuring nothing. This asserts the snapshot contains a
    real session count and a real weight average before anyone relies on it.
    """
    await _seed_hevy_history(committed_history, session)

    snapshot = await _snapshot(session)

    sessions = snapshot["training_frequency"]["coverage"]["sessions_in_window"]
    assert sessions > 0, (
        f"the seeded workouts fall outside the {WINDOW_DAYS + 1}-day window, so every snapshot "
        f"in this file is empty and the criterion test compares nothing. Coverage: "
        f"{snapshot['training_frequency']['coverage']}"
    )
    assert snapshot["body_weight_trend"]["average_7d_kg"] is not None, (
        "no body-weight average was computed, so the body-weight half of criterion #4 is "
        "asserted against a None that cannot change"
    )
    assert any(week["hard_sets"] > 0 for week in snapshot["weekly_volume"]["weeks"]), (
        f"no hard sets in any week: {snapshot['weekly_volume']['weeks']}"
    )


# ---------------------------------------------------------------------------
# The row-count proofs, one named test each so a failure names its own cause
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_no_apple_health_row_lands_in_body_measurements(
    committed_history: GoldenBuilder, session: AsyncSession, engine: AsyncEngine
) -> None:
    """D-01: `body_measurements` stays a TWO-source table.

    `weight_body_mass` is deliberately absent from `METRIC_REGISTRY`, so an Apple Health body
    mass is dropped as unrecognised rather than stored anywhere. That is what keeps
    `bodyweight._dedupe_by_day`'s source precedence two-valued (`hevy` and `manual`) and leaves
    Phase 11's fix un-pre-empted -- a third source would silently change which weigh-in wins on
    a day that has two.
    """
    await _seed_hevy_history(committed_history, session)
    before = await _count(session, _rows_for(DEFAULT_USER_ID, BodyMeasurement))
    await session.commit()

    await _ingest_every_fixture(_maker(engine))
    await session.commit()

    apple_rows = await _count(
        session,
        _rows_for(DEFAULT_USER_ID, BodyMeasurement).where(BodyMeasurement.source == "apple_health"),
    )
    total = await _count(session, _rows_for(DEFAULT_USER_ID, BodyMeasurement))

    assert apple_rows == 0, (
        f"D-01 violated: {apple_rows} body_measurements rows arrived with source='apple_health'. "
        f"`_dedupe_by_day`'s precedence is two-valued by construction, so a third source changes "
        f"which weigh-in wins on a day that has two -- silently, and for every historical day at "
        f"once"
    )
    assert total == before, (
        f"the ingest changed the body_measurements row count from {before} to {total}. Apple "
        f"Health contributes no body data in this phase at all"
    )


@pytest.mark.integration
async def test_workout_count_is_unchanged_by_ingest(
    committed_history: GoldenBuilder, session: AsyncSession, engine: AsyncEngine
) -> None:
    """D-02: the `workouts` array beside `metrics` is UNMODELLED, so it cannot enter.

    `schemas.HAEData` names only `metrics`, and `extra="ignore"` does the rest -- Apple Health
    workouts are structurally incapable of reaching `workouts`. That is a stronger guarantee
    than a filter, because there is no code path to forget to call.

    Hevy is the only source of training data. An Apple Health workout would double-count a
    session BRETT already holds at set-level detail, and would carry none of the sets.
    """
    await _seed_hevy_history(committed_history, session)
    before = await _count(session, _rows_for(DEFAULT_USER_ID, Workout))
    await session.commit()

    await _ingest_every_fixture(_maker(engine))
    await session.commit()

    after = await _count(session, _rows_for(DEFAULT_USER_ID, Workout))

    assert before > 0, "the seed wrote no workouts, so the equality below is vacuous"
    assert after == before, (
        f"D-02 violated: the workout count moved from {before} to {after} across an Apple Health "
        f"ingest. Hevy is the only source of training data; an Apple Health workout would "
        f"double-count a session already held at set-level detail"
    )


@pytest.mark.integration
async def test_no_hevy_sourced_row_lands_in_health_daily_metrics(
    session: AsyncSession, engine: AsyncEngine
) -> None:
    """HEALTH-08 / Finding A, asserted at the DATABASE rather than in a unit test.

    Hevy writes `ActiveEnergyBurned` into HealthKit on every training day, at 70-88% of that
    day's total active energy. A row here sourced `Hevy` therefore means BRETT is counting a
    training session it ALREADY holds at set-level detail a second time, as a calorie figure --
    and then reporting the inflated total back as if it were independent evidence.

    The exclusion happens at write time in `normalize.py`, which is what makes this one query
    sufficient instead of an audit of every reader that will ever exist.
    """
    await _ingest_every_fixture(_maker(engine))
    await session.commit()

    hevy_rows = await _count(
        session,
        _rows_for(DEFAULT_USER_ID, HealthDailyMetric).where(
            HealthDailyMetric.source_name == HEVY_SOURCE_NAME
        ),
    )
    total = await _count(session, _rows_for(DEFAULT_USER_ID, HealthDailyMetric))

    assert total > 0, (
        "no health rows were written at all, so the Hevy-exclusion assertion below is vacuously "
        "true -- it would pass against an ingest that stored nothing"
    )
    assert hevy_rows == 0, (
        f"HEALTH-08 violated: {hevy_rows} health_daily_metrics rows carry "
        f"source_name={HEVY_SOURCE_NAME!r}. Hevy writes ActiveEnergyBurned on every training day "
        f"at 70-88% of that day's total active energy, so each of these double-counts a session "
        f"BRETT already holds at set-level detail"
    )


@pytest.mark.integration
async def test_the_ingest_actually_wrote_something(
    session: AsyncSession, engine: AsyncEngine
) -> None:
    """The guard on the guards. Without it, the three tests above are vacuously true.

    Every one of them is an assertion that a count is ZERO or UNCHANGED, and an ingest that
    silently did nothing satisfies all three perfectly. This is the only test in the file that
    fails when the ingest stops working, so it is the one that gives the others their meaning.

    The FIRST delivery is measured on its own, against an empty table, because that is the only
    point at which reported writes and stored rows must be equal. Across all three they are NOT:
    `activity_and_nutrition` and `unrecognized_and_sourceless` both carry `step_count` from
    `iPhone` on the same local day, so the later delivery UPSERTS that row instead of inserting
    a second one. The gap is HEALTH-09 working -- and asserting it is bounded the right way
    round is a cheap extra check that replace semantics did not quietly become additive.
    """
    maker = _maker(engine)

    first = await ingest_payload(
        maker,
        user_id=DEFAULT_USER_ID,
        payload=HAEPayload.model_validate(hae_fixture(ALL_FIXTURES[0])),
    )
    await session.commit()
    after_first = await _count(session, _rows_for(DEFAULT_USER_ID, HealthDailyMetric))

    assert first.rows_upserted > 0, (
        f"`ingest_payload` reported writing nothing for {ALL_FIXTURES[0]!r}. Every zero-count "
        f"assertion in this file is now vacuous"
    )
    assert after_first == first.rows_upserted, (
        f"`ingest_payload` reported {first.rows_upserted} rows for the first delivery but the "
        f"database holds {after_first}. Against an empty table these must be equal -- the counts "
        f"the route returns to the phone have to describe what actually landed"
    )

    written = await _ingest_every_fixture(maker)
    await session.commit()
    stored = await _count(session, _rows_for(DEFAULT_USER_ID, HealthDailyMetric))

    assert stored >= after_first, (
        f"re-ingesting removed rows: {after_first} before, {stored} after ({written})"
    )
    assert stored <= sum(written) + after_first, (
        f"HEALTH-09 violated: {stored} rows stored is more than the {sum(written)} the three "
        f"deliveries reported plus the {after_first} already present, so an overlapping key "
        f"inserted a second row instead of replacing the first"
    )

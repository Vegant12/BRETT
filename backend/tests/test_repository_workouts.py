"""The two Phase 6 projections, against COMMITTED golden data whose answers were hand-computed.

Four rules under test are counter-intuitive, and three of them would ship a silently wrong number.

**The hard-set rule is a `case`, not a WHERE filter.** `test_a_workout_with_only_warmups_still_
appears` is the load-bearing test in this module. A WHERE-filtered implementation gets every other
assertion here right -- W1's four hard sets, its 1120 kg of tonnage, its two exercises -- and
deletes W2 from the list entirely, so "I trained on Wednesday" silently becomes false. Nothing
errors and no reviewer can see it.

**Tonnage is `None`, never `Decimal(0)`, when no set had both operands.** W2 is a warm-up-only
session, so it has no tonnage figure at all. Reporting a confident zero would tell Claude "you
moved zero kilograms" when the truth is "this session cannot produce a tonnage figure".

**`workout_detail` is the ONE place in Phase 6 that keeps warm-ups.** Every other tool reports
hard sets. This one is the raw record of what happened, with `set_type` carried per set.

**Committed, not flushed.** `test_committed_rows_are_visible_from_a_separate_session` is this
module's contract test for the `committed_history` fixture itself. If it fails, every Phase 6
integration test that follows is measuring an empty database and passing for the wrong reason.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.repositories.workouts import (
    WorkoutSummaryRow,
    recent_workout_summaries,
    workout_detail,
)
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `MCP-*` so these cannot collide with `test_analytics_volume.py`'s `VOL-*` ids,
# `test_analytics_rollup.py`'s `ROLLUP-*` ids, `test_normalization_mapping.py`'s `RESOLVER-*` ids
# or the sync tests' hevy ids: the container is session-scoped and shared.
_MCP_A = "MCP-A"
_MCP_B = "MCP-B"
_BENCH_TITLE = "Bench Press (Barbell)"
_PULLUP_TITLE = "Pull Up"

_W1 = "MCP-W1"
_W2 = "MCP-W2"
_W3 = "MCP-W3"
_OTHER_USER_WORKOUT = "MCP-WOTHER"

_TZ = "Asia/Jakarta"

# Monday 2026-08-24 at 09:00 Jakarta. Well inside the local Monday, so this fixture tests the
# arithmetic and not the boundary -- the boundary is `_W3` below.
_W1_START = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)
_W2_START = dt.datetime(2026, 8, 26, 2, 0, tzinfo=dt.UTC)

# 17:30Z is 00:30 the NEXT day in Jakarta (UTC+7). FOUND-03: at this offset every instant from
# 17:00Z belongs to tomorrow's local day, which is every evening workout.
_W3_START = dt.datetime(2026, 8, 30, 17, 30, tzinfo=dt.UTC)

# 80 x 8 + 80 x 6. The two `reps_only` sets contribute nothing -- they have no weight operand.
_W1_TONNAGE = Decimal("1120.000")


async def _seed(builder: GoldenBuilder, session: AsyncSession) -> None:
    """W1 (mixed, hand-computable) and W2 (warm-up only), COMMITTED.

    The commit is the test's own responsibility under the `committed_history` contract: making
    `GoldenBuilder` commit per statement would break it for every Phase 4/5 test that shares it.
    """
    await builder.template(
        external_id=_MCP_A, exercise_type="weight_reps", title=_BENCH_TITLE
    )
    await builder.template(external_id=_MCP_B, exercise_type="reps_only", title=_PULLUP_TITLE)

    await builder.workout(
        start_time=_W1_START,
        external_id=_W1,
        title="Push Day",
        duration_minutes=75,
        exercises=[
            GoldenExercise(
                template_external_id=_MCP_A,
                title=_BENCH_TITLE,
                sets=(
                    GoldenSet(set_type="warmup", weight_kg=Decimal("40"), reps=10),
                    GoldenSet(weight_kg=Decimal("80"), reps=8),
                    GoldenSet(weight_kg=Decimal("80"), reps=6),
                ),
            ),
            GoldenExercise(
                template_external_id=_MCP_B,
                title=_PULLUP_TITLE,
                sets=(GoldenSet(reps=10), GoldenSet(reps=8)),
            ),
        ],
    )

    # The workout a WHERE-filtered hard-set query would wrongly make disappear.
    await builder.workout(
        start_time=_W2_START,
        external_id=_W2,
        title="Aborted Session",
        duration_minutes=45,
        exercises=[
            GoldenExercise(
                template_external_id=_MCP_A,
                title=_BENCH_TITLE,
                sets=(GoldenSet(set_type="warmup", weight_kg=Decimal("40"), reps=10),),
            )
        ],
    )

    await session.commit()


def _by_id(rows: list[WorkoutSummaryRow], external_id: str) -> WorkoutSummaryRow:
    """The one summary with this id, or a failure that names what was actually returned.

    A bare `next(...)` would raise `StopIteration` and report nothing about the list it searched,
    which is the least useful failure available when the real defect is a missing row.
    """
    matches = [row for row in rows if row.external_id == external_id]
    assert matches, f"{external_id} missing from {[row.external_id for row in rows]}"
    return matches[0]


@pytest.mark.integration
async def test_recent_summaries_are_newest_first_and_capped(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """D-09/D-10: newest first, and `limit` is a hard cap, not a hint."""
    await _seed(committed_history, session)

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=1
    )

    assert len(rows) == 1, f"limit=1 returned {len(rows)} rows"
    assert rows[0].external_id == _W2, "the most recent workout must lead the list"


@pytest.mark.integration
async def test_summary_hard_sets_exclude_warmups(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """VOL-01: hard sets are an EXCLUSION of `warmup`, and this tool reuses that one definition."""
    await _seed(committed_history, session)

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=10
    )
    w1 = _by_id(rows, _W1)

    assert w1.hard_sets == 4, (
        "VOL-01: W1 has 2 working bench sets and 2 pull-up sets. A count of 5 means the warm-up "
        "was included; a count of 2 means only one exercise was counted"
    )
    assert w1.exercise_count == 2, (
        "the set join fans each exercise row out once per set -- without DISTINCT this reports 5"
    )


@pytest.mark.integration
async def test_summary_tonnage_is_gated_on_operand_presence(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """Tonnage needs BOTH operands, and its absence is `None` -- never a confident zero.

    The `is None` half is the one that matters. An implementation reporting `Decimal("0")` for W2
    passes every other assertion in this module and tells Claude "you moved zero kilograms" when
    the truth is "this session's modalities cannot produce a tonnage figure at all".
    """
    await _seed(committed_history, session)

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=10
    )
    w1 = _by_id(rows, _W1)
    w2 = _by_id(rows, _W2)

    assert w1.tonnage_sets == 2, "only the two weighted working sets have both operands"
    assert w1.tonnage_kg == _W1_TONNAGE, "80x8 + 80x6; the reps_only sets contribute nothing"

    assert w2.hard_sets == 0
    assert w2.tonnage_sets == 0
    assert w2.tonnage_kg is None, (
        "a warm-up-only session has no computable tonnage. Decimal(0) here is a different and "
        "false statement"
    )


@pytest.mark.integration
async def test_a_workout_with_only_warmups_still_appears(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """The load-bearing test: applying the hard-set rule as a WHERE deletes the whole workout.

    A WHERE filter drops every row of W2 before grouping, so W2 never reaches the result at all
    and "I trained on Wednesday" silently becomes false. A `case` inside the aggregates reports
    it honestly as a session with zero hard sets. Nothing errors either way.
    """
    await _seed(committed_history, session)

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=10
    )

    assert {row.external_id for row in rows} == {_W1, _W2}


@pytest.mark.integration
async def test_local_day_uses_the_users_timezone(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """FOUND-03: the day a session belongs to is the USER's local day, not the UTC one."""
    await _seed(committed_history, session)
    await committed_history.workout(
        start_time=_W3_START,
        external_id=_W3,
        title="Late Evening Session",
        duration_minutes=60,
        exercises=[
            GoldenExercise(
                template_external_id=_MCP_A,
                title=_BENCH_TITLE,
                sets=(GoldenSet(weight_kg=Decimal("60"), reps=5),),
            )
        ],
    )
    await session.commit()

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=10
    )

    assert _by_id(rows, _W1).local_day == dt.date(2026, 8, 24)
    assert _by_id(rows, _W3).local_day == dt.date(2026, 8, 31), (
        "FOUND-03: 2026-08-30T17:30Z is 00:30 on 2026-08-31 in Asia/Jakarta. Reporting the UTC "
        "date puts every evening workout on the wrong day"
    )


@pytest.mark.integration
async def test_workout_detail_returns_every_set_including_warmups(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """D-11: the raw record of a session, warm-ups labelled rather than removed."""
    await _seed(committed_history, session)

    detail = await workout_detail(
        session, user_id=DEFAULT_USER_ID, external_id=_W1, tz=_TZ, max_sets=120
    )

    assert detail is not None
    assert len(detail.exercises) == 2
    assert sum(len(exercise.sets) for exercise in detail.exercises) == 5
    assert detail.total_sets == 5
    assert detail.exercises[0].sets[0].set_type == "warmup", (
        "this is the ONE Phase 6 tool that keeps warm-ups; dropping them here loses the record "
        "of how the session was actually run"
    )
    assert detail.exercises[0].exercise_template_external_id == _MCP_A
    assert detail.duration_minutes == 75


@pytest.mark.integration
async def test_workout_detail_truncates_from_the_end(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """T-06-05: the cap bounds the response, and `total_sets` keeps the truncation visible.

    Sets are dropped from the END -- highest `exercise_index`, then highest `set_index` -- so the
    earliest work of the session survives. A silent truncation would be a wrong answer; a flagged
    one is a smaller answer, and `total_sets > max_sets` is what the caller sets
    `sets_truncated` from.
    """
    await _seed(committed_history, session)

    detail = await workout_detail(
        session, user_id=DEFAULT_USER_ID, external_id=_W1, tz=_TZ, max_sets=3
    )

    assert detail is not None
    assert sum(len(exercise.sets) for exercise in detail.exercises) == 3
    assert detail.total_sets == 5, "the TRUE count, reported before truncation"

    surviving = [
        (exercise.exercise_index, set_row.set_index)
        for exercise in detail.exercises
        for set_row in exercise.sets
    ]
    assert surviving == [(0, 0), (0, 1), (0, 2)]


@pytest.mark.integration
async def test_workout_detail_returns_none_for_an_unknown_id(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """A missing workout is an ANSWER, not a failure.

    A raise here reaches Claude verbatim as `Error executing tool {name}: {str(e)}` (Pitfall 3),
    which is the highest-risk disclosure surface in this phase -- and "no workout with that id"
    is an ordinary, expected outcome of an id Claude read from an older conversation.
    """
    await _seed(committed_history, session)

    detail = await workout_detail(
        session, user_id=DEFAULT_USER_ID, external_id="does-not-exist", tz=_TZ, max_sets=120
    )

    assert detail is None


@pytest.mark.integration
async def test_another_users_workout_is_never_returned(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """T-06-02 / ASVS V4: a guessed `external_id` must not cross the tenant boundary.

    A single-user suite cannot detect a missing `user_id` predicate -- every row belongs to the
    only user, so an unscoped query returns the right answer by accident. This test is the only
    thing standing between that and a cross-tenant read.
    """
    await _seed(committed_history, session)
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    await committed_history.workout(
        start_time=_W1_START,
        external_id=_OTHER_USER_WORKOUT,
        user_id=ANALYTICS_SECOND_USER_ID,
        title="Not Yours",
        duration_minutes=60,
        exercises=[
            GoldenExercise(
                template_external_id=_MCP_A,
                title=_BENCH_TITLE,
                sets=(GoldenSet(weight_kg=Decimal("100"), reps=5),),
            )
        ],
    )
    await session.commit()

    rows = await recent_workout_summaries(
        session, user_id=DEFAULT_USER_ID, tz=_TZ, limit=50
    )
    detail = await workout_detail(
        session,
        user_id=DEFAULT_USER_ID,
        external_id=_OTHER_USER_WORKOUT,
        tz=_TZ,
        max_sets=120,
    )

    assert _OTHER_USER_WORKOUT not in {row.external_id for row in rows}, (
        "ASVS V4: recent_workout_summaries leaked another user's session into the list"
    )
    assert detail is None, (
        "ASVS V4: workout_detail resolved another user's workout from a guessed external_id"
    )


@pytest.mark.integration
async def test_committed_rows_are_visible_from_a_separate_session(
    session: AsyncSession, engine: AsyncEngine, committed_history: GoldenBuilder
) -> None:
    """The `committed_history` fixture's own contract test.

    An MCP tool opens its own session from the lifespan sessionmaker -- a DIFFERENT transaction,
    which cannot see uncommitted rows at all. If this fails, every Phase 6 integration test that
    follows is querying an empty database and passing for the wrong reason.
    """
    await _seed(committed_history, session)

    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as separate:
        rows = await recent_workout_summaries(
            separate, user_id=DEFAULT_USER_ID, tz=_TZ, limit=10
        )

    assert _by_id(rows, _W1).hard_sets == 4, (
        "a separate session saw no committed rows -- committed_history is flushing, not "
        "committing, and every Phase 6 integration test built on it is vacuous"
    )

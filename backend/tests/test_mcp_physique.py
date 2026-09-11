"""PHYS-06/07/08/11's proof: the write path, its required read precursor, and the supersede
round trip, at the TOOL-BODY level.

Both tools are called DIRECTLY through a fake ``ctx``, never through ``Client(mcp)`` or the HTTP
transport, because registration lands in Plan 17-05 and the properties proven here are properties
of the TOOL BODY -- ``test_mcp_isolation.py`` already proves decorator coverage and the tool count
separately, and duplicating that here would couple this module to Plan 17-05 for no gain.

The ``_FakeCtx``/``_FakeRequestContext``/``_fake_ctx`` helpers are duplicated from
``test_mcp_program_switch.py`` rather than imported: no other test module in this suite imports
fixtures from a sibling test module (every cross-module import in ``backend/tests/`` goes through
``tests.conftest``), so duplication here follows the suite's existing convention rather than
introducing a new one.

The ``client`` fixture is taken by every test even though no HTTP request is made -- it is what
assigns ``app.state.sessionmaker``, the object the fake ``ctx`` hands the tool, wired to the real
test container.
"""

import datetime as dt
import inspect
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models.physique import (
    PHYSIQUE_RATING_ANCHORS,
    PHYSIQUE_RATING_DISCLAIMER,
    PhotoAngle,
    PhysiqueObservation,
    PhysiqueRating,
    PhysiqueRatingLevel,
    PoseState,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import local_today
from app.mcp.tools.physique import (
    fitness_get_latest_physique_observation,
    fitness_log_physique_observation,
)
from app.mcp.tools.schemas import PhysiqueLogStatus, PhysiqueRatingInput
from app.normalization.muscles import CanonicalMuscleGroup
from tests.conftest import ANALYTICS_SECOND_USER_ID, DEFAULT_USER_ID, GoldenBuilder
from tests.test_mcp_tools import LEAK_MARKERS

# Mirrors `test_mcp_program_switch.py:42`. Port 1 is reserved and never listening, so the
# connection fails immediately rather than hanging on a routable-but-silent host.
_DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"


@dataclass
class _FakeRequestContext:
    """The one attribute the tools read off ``ctx.request_context``."""

    lifespan_context: AppContext


@dataclass
class _FakeCtx:
    """The one attribute the tools read off ``ctx``.

    A hand-built stand-in rather than a real ``Context[AppContext]``: what the tools actually
    need is a sessionmaker reachable at ``ctx.request_context.lifespan_context.sessionmaker``,
    and that is exactly what this provides.
    """

    request_context: _FakeRequestContext


def _fake_ctx(sessionmaker: async_sessionmaker[AsyncSession]) -> Any:
    """Wrap a sessionmaker in the shape a tool's ``ctx`` has.

    Returns ``Any`` on purpose: the real parameter is typed ``Context[AppContext]`` and a cast
    here would be a longer way of saying the same thing while implying the fake is one.
    """
    return _FakeCtx(
        request_context=_FakeRequestContext(lifespan_context=AppContext(sessionmaker=sessionmaker))
    )


def _full_ratings(
    *,
    levels: dict[CanonicalMuscleGroup, PhysiqueRatingLevel] | None = None,
    default: PhysiqueRatingLevel = PhysiqueRatingLevel.DEVELOPED,
    not_assessable: set[CanonicalMuscleGroup] | None = None,
) -> list[PhysiqueRatingInput]:
    """All 19 groups at `default`, overridden per group by `levels`.

    Groups named in `not_assessable` carry a placeholder `not_assessable_reason` instead of a
    level. D-07's invariant is 19 rows every time, so the DEFAULT here satisfies it and each test
    overrides only the group it is actually about -- a test that hand-wrote 19 entries would be
    asserting its own fixture.
    """
    levels = levels or {}
    not_assessable = not_assessable or set()
    entries: list[PhysiqueRatingInput] = []
    for group in CanonicalMuscleGroup:
        if group in not_assessable:
            entries.append(
                PhysiqueRatingInput(
                    muscle_group=group,
                    not_assessable_reason="not visible in this photo set",
                )
            )
        else:
            entries.append(
                PhysiqueRatingInput(muscle_group=group, rating_level=levels.get(group, default))
            )
    return entries


async def _observation_count(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Row count for `user_id` in `physique_observations`, read fresh from the database."""
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(PhysiqueObservation)
        .where(PhysiqueObservation.user_id == user_id)
    )
    assert count is not None
    return count


# ---------------------------------------------------------------------------
# Task 1: the write path -- one append, and four refusal families that write nothing.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_one_call_logs_a_complete_observation(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PHYS-06. One call appends one 19-row observation with every header field intact."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT, PhotoAngle.BACK, PhotoAngle.SIDE],
        leanness_notes="lean but soft midsection",
        conditioning_notes="visible striations in quads",
        symmetry_notes="left bicep peak slightly higher",
        conditions_note="post-workout pump, good lighting",
    )

    assert result.log_status == PhysiqueLogStatus.LOGGED
    assert result.observation_id is not None
    today = await local_today(session, user_id=DEFAULT_USER_ID)
    assert result.observed_on == today

    rating_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(PhysiqueRating)
        .where(PhysiqueRating.observation_id == result.observation_id)
    )
    assert rating_count == 19

    header = (
        await session.execute(
            sa.select(PhysiqueObservation).where(PhysiqueObservation.id == result.observation_id)
        )
    ).scalar_one()
    assert header.leanness_notes == "lean but soft midsection"
    assert header.conditioning_notes == "visible striations in quads"
    assert header.symmetry_notes == "left bicep peak slightly higher"
    assert header.pose_state == PoseState.RELAXED.value
    assert header.photo_angles_present == ["front", "back", "side"]
    assert header.conditions_note == "post-workout pump, good lighting"


@pytest.mark.integration
async def test_the_write_tool_needs_no_confirmation_token(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PHYS-06's whole difference from `fitness_switch_training_program`: the first and only
    call logs, with no warn/confirm round trip."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )

    assert result.log_status == PhysiqueLogStatus.LOGGED


@pytest.mark.integration
async def test_an_incomplete_rating_set_is_refused_and_writes_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-07's 19-row invariant. 18 ratings is refused, naming the missing group, and nothing
    is written."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    before = await _observation_count(session, user_id=DEFAULT_USER_ID)

    missing_group = list(CanonicalMuscleGroup)[-1]
    ratings = _full_ratings()[:-1]

    result = await fitness_log_physique_observation(
        ctx,
        ratings=ratings,
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )

    assert result.log_status == PhysiqueLogStatus.REFUSED
    assert result.reason is not None
    assert missing_group.value in result.reason
    after = await _observation_count(session, user_id=DEFAULT_USER_ID)
    assert after == before


@pytest.mark.integration
async def test_a_duplicated_muscle_group_is_refused_and_writes_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """A 20-entry list -- all 19 groups plus one repeat -- is refused, naming the duplicated
    group, and nothing is written."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    before = await _observation_count(session, user_id=DEFAULT_USER_ID)

    ratings = _full_ratings()
    duplicate = ratings[0].model_copy()
    ratings_with_duplicate = [*ratings, duplicate]

    result = await fitness_log_physique_observation(
        ctx,
        ratings=ratings_with_duplicate,
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )

    assert result.log_status == PhysiqueLogStatus.REFUSED
    assert result.reason is not None
    assert duplicate.muscle_group.value in result.reason
    after = await _observation_count(session, user_id=DEFAULT_USER_ID)
    assert after == before


@pytest.mark.integration
async def test_a_supersede_id_without_a_reason_is_refused_and_writes_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """Both directions of the paired-argument check: an id with no reason, and a reason with
    no id, are each refused and write nothing."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    before = await _observation_count(session, user_id=DEFAULT_USER_ID)

    id_only = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=uuid.uuid4(),
    )
    assert id_only.log_status == PhysiqueLogStatus.REFUSED

    reason_only = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        superseded_reason="duplicate entry",
    )
    assert reason_only.log_status == PhysiqueLogStatus.REFUSED

    after = await _observation_count(session, user_id=DEFAULT_USER_ID)
    assert after == before


@pytest.mark.integration
async def test_an_unknown_supersede_target_is_refused_and_writes_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """A freshly generated uuid names no observation at all -- refused, writes nothing."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    before = await _observation_count(session, user_id=DEFAULT_USER_ID)

    result = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=uuid.uuid4(),
        superseded_reason="correcting a mistake",
    )

    assert result.log_status == PhysiqueLogStatus.REFUSED
    after = await _observation_count(session, user_id=DEFAULT_USER_ID)
    assert after == before


@pytest.mark.integration
async def test_another_users_observation_cannot_be_superseded(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-17-18. A real observation seeded under `ANALYTICS_SECOND_USER_ID` cannot be named as a
    supersede target -- refused, and the foreign row's `superseded_at` stays `None`."""
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    foreign_observation_id = await committed_history.physique_observation(
        observed_on=dt.date(2026, 1, 1),
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=foreign_observation_id,
        superseded_reason="trying to supersede someone else's row",
    )

    assert result.log_status == PhysiqueLogStatus.REFUSED
    foreign_superseded_at = await session.scalar(
        sa.select(PhysiqueObservation.superseded_at).where(
            PhysiqueObservation.id == foreign_observation_id
        )
    )
    assert foreign_superseded_at is None


@pytest.mark.integration
async def test_an_already_superseded_target_is_refused(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """A target that has already been superseded once cannot be superseded again."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    first = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert first.log_status == PhysiqueLogStatus.LOGGED

    second = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=first.observation_id,
        superseded_reason="correcting the first one",
    )
    assert second.log_status == PhysiqueLogStatus.LOGGED

    third = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=first.observation_id,
        superseded_reason="trying to supersede an already-superseded row",
    )

    assert third.log_status == PhysiqueLogStatus.REFUSED


@pytest.mark.integration
async def test_every_response_branch_carries_the_disclaimer(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PHYS-11. The logged branch and every in-tool refusal branch carry the disclaimer."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    logged = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert logged.log_status == PhysiqueLogStatus.LOGGED
    assert logged.disclaimer == PHYSIQUE_RATING_DISCLAIMER

    pair_refusal = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=uuid.uuid4(),
    )
    assert pair_refusal.log_status == PhysiqueLogStatus.REFUSED
    assert pair_refusal.disclaimer == PHYSIQUE_RATING_DISCLAIMER

    coverage_refusal = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings()[:-1],
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert coverage_refusal.log_status == PhysiqueLogStatus.REFUSED
    assert coverage_refusal.disclaimer == PHYSIQUE_RATING_DISCLAIMER

    target_refusal = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=uuid.uuid4(),
        superseded_reason="unknown target",
    )
    assert target_refusal.log_status == PhysiqueLogStatus.REFUSED
    assert target_refusal.disclaimer == PHYSIQUE_RATING_DISCLAIMER


# ---------------------------------------------------------------------------
# Task 2: the read path, the supersede round trip, and both degraded payloads.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_read_tool_returns_none_before_anything_is_logged(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """`data_available is True` with `observation is None` -- a real answer, not a
    degradation."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_get_latest_physique_observation(ctx)

    assert result.data_available is True
    assert result.observation is None


@pytest.mark.integration
async def test_the_read_tool_returns_the_ratings_notes_and_confounders(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PHYS-07. After one write, all 19 ratings, the three note fields and the confounder
    metadata round-trip; a `Not Assessable` group carries `rating_level is None` and its
    reason."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    not_assessable_group = CanonicalMuscleGroup.ABDUCTORS

    written = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(not_assessable={not_assessable_group}),
        pose_state=PoseState.LIGHTLY_FLEXED,
        photo_angles_present=[PhotoAngle.FRONT, PhotoAngle.BACK],
        leanness_notes="lean note",
        conditioning_notes="conditioning note",
        symmetry_notes="symmetry note",
        conditions_note="conditions note",
    )
    assert written.log_status == PhysiqueLogStatus.LOGGED

    result = await fitness_get_latest_physique_observation(ctx)

    assert result.observation is not None
    assert len(result.observation.ratings) == 19
    assert result.observation.leanness_notes == "lean note"
    assert result.observation.conditioning_notes == "conditioning note"
    assert result.observation.symmetry_notes == "symmetry note"
    assert result.observation.pose_state == PoseState.LIGHTLY_FLEXED
    assert result.observation.photo_angles_present == ["front", "back"]
    assert result.observation.conditions_note == "conditions note"

    not_assessable_view = next(
        view for view in result.observation.ratings if view.muscle_group == not_assessable_group
    )
    assert not_assessable_view.rating_level is None
    assert not_assessable_view.not_assessable_reason is not None


@pytest.mark.integration
async def test_the_read_tools_ratings_are_in_canonical_declaration_order(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """Exact equality against `list(CanonicalMuscleGroup)`, not a set comparison -- callers are
    told they may zip against it."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    written = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert written.log_status == PhysiqueLogStatus.LOGGED

    result = await fitness_get_latest_physique_observation(ctx)

    assert result.observation is not None
    assert [view.muscle_group for view in result.observation.ratings] == list(CanonicalMuscleGroup)


@pytest.mark.integration
async def test_the_read_tool_ships_the_locked_rating_scale(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PHYS-07: the locked scale travels with the prior observation, every time -- even before
    one exists."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_get_latest_physique_observation(ctx)

    assert result.rating_scale == PHYSIQUE_RATING_ANCHORS


async def test_the_read_tool_takes_no_arguments() -> None:
    """ "What is the current picture" is always a question about now -- same reasoning the
    body-weight and program tools apply. No container needed: pure signature introspection."""
    assert tuple(inspect.signature(fitness_get_latest_physique_observation).parameters) == ("ctx",)


@pytest.mark.integration
async def test_a_superseded_observation_disappears_from_the_read_but_stays_in_the_table(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-17-19. Log A, then log B superseding A: the read returns B; a direct row read shows A
    still present with its supersede columns set and all 19 rating rows intact."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    a = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert a.log_status == PhysiqueLogStatus.LOGGED

    b = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(default=PhysiqueRatingLevel.STANDOUT),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=a.observation_id,
        superseded_reason="corrected reading",
    )
    assert b.log_status == PhysiqueLogStatus.LOGGED

    result = await fitness_get_latest_physique_observation(ctx)
    assert result.observation is not None
    assert result.observation.observation_id == b.observation_id

    row = (
        await session.execute(
            sa.select(
                PhysiqueObservation.superseded_at,
                PhysiqueObservation.superseded_reason,
                PhysiqueObservation.superseded_by_id,
            ).where(PhysiqueObservation.id == a.observation_id)
        )
    ).one()
    assert row.superseded_at is not None
    assert row.superseded_reason == "corrected reading"
    assert row.superseded_by_id == b.observation_id

    a_rating_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(PhysiqueRating)
        .where(PhysiqueRating.observation_id == a.observation_id)
    )
    assert a_rating_count == 19


@pytest.mark.integration
async def test_the_supersede_response_names_the_target(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """B's response echoes back exactly which observation it superseded."""
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    a = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
    )
    assert a.log_status == PhysiqueLogStatus.LOGGED

    b = await fitness_log_physique_observation(
        ctx,
        ratings=_full_ratings(),
        pose_state=PoseState.RELAXED,
        photo_angles_present=[PhotoAngle.FRONT],
        supersedes_observation_id=a.observation_id,
        superseded_reason="duplicate",
    )

    assert b.superseded_observation_id == a.observation_id


@pytest.mark.integration
async def test_both_degraded_payloads_are_honest_and_leak_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-17-17 / PITFALLS #15. Against a dead database, the write tool reports `unknown` --
    NEVER `refused` -- with `data_available is False`; the read tool reports `data_available
    is False` with `observation is None`; both carry the disclaimer and leak nothing."""
    await session.commit()
    dead = create_async_engine(_DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    dead_sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    ctx = _fake_ctx(dead_sessionmaker)
    try:
        write_result = await fitness_log_physique_observation(
            ctx,
            ratings=_full_ratings(),
            pose_state=PoseState.RELAXED,
            photo_angles_present=[PhotoAngle.FRONT],
        )
        read_result = await fitness_get_latest_physique_observation(ctx)
    finally:
        await dead.dispose()

    # PITFALLS #15: this write has no single-use token to make a retry safe, so `refused` on an
    # append that may have landed would invite a second observation for the same day.
    assert write_result.log_status is PhysiqueLogStatus.UNKNOWN
    assert write_result.log_status is not PhysiqueLogStatus.REFUSED
    assert write_result.data_available is False

    assert read_result.data_available is False
    assert read_result.observation is None

    assert write_result.disclaimer == PHYSIQUE_RATING_DISCLAIMER
    assert read_result.disclaimer == PHYSIQUE_RATING_DISCLAIMER

    write_rendered = repr(write_result.model_dump())
    read_rendered = repr(read_result.model_dump())
    for leak in LEAK_MARKERS:
        assert leak not in write_rendered, f"{leak!r} leaked into the degraded write payload"
        assert leak not in read_rendered, f"{leak!r} leaked into the degraded read payload"


@pytest.mark.integration
async def test_the_degraded_write_reason_points_at_the_read_tool_not_a_retry(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """The degraded write's reason names the read tool and says not to retry."""
    await session.commit()
    dead = create_async_engine(_DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    dead_sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    ctx = _fake_ctx(dead_sessionmaker)
    try:
        result = await fitness_log_physique_observation(
            ctx,
            ratings=_full_ratings(),
            pose_state=PoseState.RELAXED,
            photo_angles_present=[PhotoAngle.FRONT],
        )
    finally:
        await dead.dispose()

    assert result.reason is not None
    assert "fitness_get_latest_physique_observation" in result.reason
    assert "do not retry" in result.reason

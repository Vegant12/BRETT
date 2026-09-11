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
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.physique import (
    PHYSIQUE_RATING_DISCLAIMER,
    PhotoAngle,
    PhysiqueObservation,
    PhysiqueRating,
    PhysiqueRatingLevel,
    PoseState,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import local_today
from app.mcp.tools.physique import fitness_log_physique_observation
from app.mcp.tools.schemas import PhysiqueLogStatus, PhysiqueRatingInput
from app.normalization.muscles import CanonicalMuscleGroup
from tests.conftest import ANALYTICS_SECOND_USER_ID, DEFAULT_USER_ID, GoldenBuilder

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

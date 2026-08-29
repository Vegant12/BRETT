"""HEVY-06 / NORM-01 end to end: Hevy's flat taxonomy in, canonical mapping out.

The deltoid assertions are the ones that matter. Hevy's API cannot express a front/side/rear
split and no public dataset supplies one, so these tests are the only place the project's
curated answer is checked against a real round trip through the database.

Only the HTTP transport is mocked; pagination, upsert, and the normalization call are real.
"""

import httpx  # 0.x -- required by respx for response objects
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from respx import Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import (
    ExerciseMuscle,
    ExerciseMuscleOverride,
    ExerciseTemplate,
    SyncState,
)
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    ensure_sync_state,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.templates import sync_exercise_templates
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from app.normalization.resolver import effective_muscles, set_override
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

TEMPLATES_URL = "https://api.hevyapp.com/v1/exercise_templates"

BENCH_PRESS = "05293BCA"
LATERAL_RAISE = "D04AC939"
LAT_PULLDOWN = "6A6C31A5"
SLED_PUSH = "b459cba5-cd6d-463c-abd6-54f8eafcadcb"


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. No test here exercises the retry timing."""


def _client() -> HevyClient:
    return HevyClient(SecretStr("test-key-not-a-real-credential"), sleep=_no_sleep)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _page(times: int = 1) -> list[httpx.Response]:
    """`times` identical copies of the canned template page.

    respx consumes a `side_effect` list one entry per call, so a test that syncs twice
    needs two responses; reusing one object would raise `StopIteration` on the second
    request and look like a pagination bug.
    """
    payload = hevy_fixture("exercise_templates_page1")
    return [httpx.Response(200, json=payload) for _ in range(times)]


async def _cleanup(factory: async_sessionmaker[AsyncSession]) -> None:
    """Remove every row this module could have written for the seeded user.

    The container is session-scoped and shared with every other integration test, so a
    test that leaves rows behind changes the result of the next one.
    """
    async with factory() as session:
        for statement in (
            sa.delete(ExerciseMuscle).where(ExerciseMuscle.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscleOverride).where(
                ExerciseMuscleOverride.user_id == DEFAULT_USER_ID
            ),
            sa.delete(ExerciseTemplate).where(ExerciseTemplate.user_id == DEFAULT_USER_ID),
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER_HEVY
            ),
        ):
            await session.execute(statement)
        await session.commit()


async def _template(
    factory: async_sessionmaker[AsyncSession], external_id: str
) -> ExerciseTemplate:
    async with factory() as session:
        row = await session.scalar(
            sa.select(ExerciseTemplate).where(
                ExerciseTemplate.user_id == DEFAULT_USER_ID,
                ExerciseTemplate.external_id == external_id,
            )
        )
    assert row is not None, f"no exercise_templates row for {external_id}"
    return row


async def _muscles(
    factory: async_sessionmaker[AsyncSession], external_id: str
) -> set[tuple[str, str, str]]:
    """The canonical mapping rows as comparable `(muscle, role, source)` triples."""
    async with factory() as session:
        rows = (
            await session.execute(
                sa.select(
                    ExerciseMuscle.muscle_group, ExerciseMuscle.role, ExerciseMuscle.source
                ).where(
                    ExerciseMuscle.user_id == DEFAULT_USER_ID,
                    ExerciseMuscle.exercise_template_external_id == external_id,
                )
            )
        ).all()
    return {(row[0], row[1], row[2]) for row in rows}


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with factory() as session:
        templates = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ExerciseTemplate)
            .where(ExerciseTemplate.user_id == DEFAULT_USER_ID)
        )
        muscles = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ExerciseMuscle)
            .where(ExerciseMuscle.user_id == DEFAULT_USER_ID)
        )
    assert templates is not None and muscles is not None
    return templates, muscles


@pytest.mark.integration
async def test_template_request_uses_page_size_100(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """Pitfall 6: this is the ONE endpoint that does not cap at 10.

    Asserted on the RECORDED REQUEST, not on the constant: a page size that is defined
    correctly but never reaches the query string would pass an introspection test and still
    issue ~40 requests per sync against an undocumented rate limit.
    """
    factory = _factory(engine)
    route = httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert dict(route.calls.last.request.url.params) == {"page": "1", "pageSize": "100"}
        # One page in the fixture means exactly one request; a second would mean the
        # `page >= page_count` terminator is not firing.
        assert len(route.calls) == 1
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_all_four_templates_persist(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """HEVY-06: one page in, four rows out, with `is_custom` carried through."""
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            result = await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert result.pages_fetched == 1
        assert result.templates_upserted == 4
        templates, _ = await _counts(factory)
        assert templates == 4

        async with factory() as session:
            custom = await session.scalar(
                sa.select(sa.func.count())
                .select_from(ExerciseTemplate)
                .where(
                    ExerciseTemplate.user_id == DEFAULT_USER_ID,
                    ExerciseTemplate.is_custom.is_(True),
                )
            )
        assert custom == 1
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_raw_hevy_muscle_groups_are_preserved(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """NORM-02's audit baseline. If this is ever translated in place, an override becomes
    uncheckable against anything."""
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        bench = await _template(factory, BENCH_PRESS)
        assert bench.primary_muscle_group == "chest"
        assert bench.secondary_muscle_groups == ["triceps", "shoulders"]

        # The one that proves the point: Hevy's flat bucket survives verbatim even though
        # the derived mapping below resolves it to a specific deltoid head.
        raise_row = await _template(factory, LATERAL_RAISE)
        assert raise_row.primary_muscle_group == "shoulders"
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_exercise_type_is_persisted(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """Hevy's `type` is the modality signal PROG-01 (Phase 5) needs.

    Estimated 1RM is meaningless for a `distance_duration` exercise, and the only way to
    know which is which is to have kept this column from the first sync. Dropping it now
    costs a full re-sync later.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert (await _template(factory, BENCH_PRESS)).exercise_type == "weight_reps"
        assert (await _template(factory, SLED_PUSH)).exercise_type == "distance_duration"
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_lateral_raise_maps_to_side_delts_only(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """NORM-01, the split Hevy cannot express.

    Hevy says `shoulders`. A lateral raise is frontal-plane abduction, so the side head
    is the one that works -- and reporting front or rear volume here would be a confident
    lie in every Phase 4 per-muscle answer.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert await _muscles(factory, LATERAL_RAISE) == {("side_delts", "direct", "curated")}
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_bench_press_secondary_shoulders_becomes_front_delts(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """A `shoulders` SECONDARY on a press is front-delt work, and only front-delt work."""
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        mapped = await _muscles(factory, BENCH_PRESS)
        assert mapped == {
            ("chest", "direct", "hevy"),
            ("triceps", "indirect", "hevy"),
            ("front_delts", "indirect", "curated"),
        }
        heads = {muscle for muscle, _, _ in mapped}
        assert "side_delts" not in heads
        assert "rear_delts" not in heads
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_lat_pulldown_maps_lats_upper_back_biceps(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The unambiguous majority case: 17 of Hevy's 20 values are a mechanical rename.

    Every row here is `source='hevy'`, which is the point -- curation is reserved for the
    two values that actually need a person, and this test pins that boundary.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert await _muscles(factory, LAT_PULLDOWN) == {
            ("lats", "direct", "hevy"),
            ("biceps", "indirect", "hevy"),
            ("upper_back", "indirect", "hevy"),
        }
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_custom_full_body_template_yields_no_mapping_rows(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """D-03: a curation gap is a supported state, not a failed sync.

    `full_body` is deliberately NOT fanned out to all 19 groups -- that would inflate every
    per-muscle volume figure in Phase 4 with work that never happened.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert await _muscles(factory, SLED_PUSH) == set()
        # The template itself still persisted, and the run still closed cleanly.
        assert (await _template(factory, SLED_PUSH)).title == "Sled Push (Custom)"

        async with factory() as session:
            state = await session.scalar(
                sa.select(SyncState).where(
                    SyncState.user_id == DEFAULT_USER_ID,
                    SyncState.resource == RESOURCE_EXERCISE_TEMPLATES,
                )
            )
        assert state is not None
        assert state.status == "idle"
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_unmapped_template_is_reported_in_the_result(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """A curation gap has to be VISIBLE, or it is indistinguishable from an exercise that
    is genuinely untrained.

    The result names the exact template so the gap can be closed, rather than reporting a
    bare count that tells nobody which entry to curate.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with _client() as client:
            result = await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        assert result.unmapped == (SLED_PUSH,)
        assert result.mappings_written == 7
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_template_sync_is_idempotent(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """HEVY-03 for the mapping tables: re-syncing must not accumulate.

    The mapping rows are delete-and-reinserted rather than upserted, so this also proves
    the delete half is scoped to one template and does not wipe the rest of the page.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page(times=2))
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)
            first = await _counts(factory)
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)
            second = await _counts(factory)

        assert first == second
        assert first == (4, 7)
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_resync_does_not_clear_an_override(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """NORM-02: an override that a routine sync could erase is not an override.

    `replace_exercise_muscles` deletes and reinserts the DERIVED rows, which is exactly
    the operation that would take the correction with it if the two layers shared a table.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page(times=2))
    try:
        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

            async with factory() as session:
                await set_override(
                    session,
                    user_id=DEFAULT_USER_ID,
                    template_external_id=LATERAL_RAISE,
                    assignments=[(CanonicalMuscleGroup.REAR_DELTS, MuscleRole.DIRECT)],
                    note="i cheat these into a rear-delt raise",
                )
                await session.commit()

            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        async with factory() as session:
            surviving = await session.scalar(
                sa.select(sa.func.count())
                .select_from(ExerciseMuscleOverride)
                .where(
                    ExerciseMuscleOverride.user_id == DEFAULT_USER_ID,
                    ExerciseMuscleOverride.exercise_template_external_id == LATERAL_RAISE,
                )
            )
            resolved = await effective_muscles(
                session, user_id=DEFAULT_USER_ID, template_external_id=LATERAL_RAISE
            )

        assert surviving == 1
        assert [(m.muscle_group.value, m.source.value) for m in resolved] == [
            ("rear_delts", "override")
        ]
        # And the derived row the override masks was still recomputed underneath it.
        assert await _muscles(factory, LATERAL_RAISE) == {("side_delts", "direct", "curated")}
    finally:
        await _cleanup(factory)


@pytest.mark.integration
async def test_last_synced_at_for_exercise_templates_is_independent(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-09: three resources, three answers.

    A single freshness timestamp would report the newest of the three for all of them,
    which is precisely the staleness Claude must be able to see. Syncing templates alone
    must therefore leave the workouts row untouched.
    """
    factory = _factory(engine)
    httpx2_mock.get(TEMPLATES_URL).mock(side_effect=_page())
    try:
        async with factory() as session:
            await ensure_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
            )
            await session.commit()

        async with _client() as client:
            await sync_exercise_templates(client, factory, user_id=DEFAULT_USER_ID)

        async with factory() as session:
            rows = {
                row.resource: row
                for row in (
                    await session.scalars(
                        sa.select(SyncState).where(
                            SyncState.user_id == DEFAULT_USER_ID,
                            SyncState.provider == PROVIDER_HEVY,
                        )
                    )
                ).all()
            }

        assert rows[RESOURCE_EXERCISE_TEMPLATES].last_synced_at is not None
        assert rows[RESOURCE_WORKOUTS].last_synced_at is None
        # A completed run has no page to resume from; leaving one would make the next run
        # skip the pages it already has.
        assert rows[RESOURCE_EXERCISE_TEMPLATES].cursor_page is None
    finally:
        await _cleanup(factory)

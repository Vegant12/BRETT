"""Effective muscle mapping: override-replaces-base, and the audit that proves it (NORM-02).

The rule under test is not the intuitive one. A per-row merge would let a user add a muscle or
change its role but never REMOVE one, so the single most common correction -- "this exercise
does not actually work rear delts" -- would be unexpressible. Replacement makes removal
possible AND keeps both sets intact in their own tables, which is what "auditable against the
original source mapping" actually requires.

`test_base_rows_survive_an_override_unchanged` is the load-bearing one: it asserts `created_at`
as well as the triples, so an implementation that "helpfully" rewrote the base rows to match
the override would fail even if every value happened to line up.

The two `apply_weights` tests are pure and deliberately carry no integration marker -- NORM-03
should stay verifiable when Docker is not running.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExerciseMuscle, ExerciseMuscleOverride, ExerciseTemplate, User
from app.normalization.muscles import (
    CanonicalMuscleGroup,
    MappingSource,
    MuscleRole,
)
from app.normalization.resolver import (
    EffectiveMuscle,
    apply_weights,
    clear_override,
    effective_muscles,
    effective_muscles_bulk,
    set_override,
    unmapped_template_ids,
)
from tests.conftest import DEFAULT_USER_ID

# Distinct from the ids `test_hevy_templates.py` writes: the container is session-scoped and
# shared, so overlapping ids would make one module's cleanup delete the other's fixtures.
BASE_TEMPLATE = "RESOLVER-BASE"
OTHER_TEMPLATE = "RESOLVER-OTHER"
BARE_TEMPLATE = "RESOLVER-BARE"

_CHEST = CanonicalMuscleGroup.CHEST
_TRICEPS = CanonicalMuscleGroup.TRICEPS
_FRONT_DELTS = CanonicalMuscleGroup.FRONT_DELTS
_REAR_DELTS = CanonicalMuscleGroup.REAR_DELTS

SECOND_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000009e2")


async def _seed_base(
    session: AsyncSession,
    template_external_id: str,
    rows: Sequence[tuple[CanonicalMuscleGroup, MuscleRole, MappingSource]],
    *,
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """Write `exercise_muscles` rows directly.

    Deliberately not routed through the Hevy sync: this module tests the RESOLVER, and
    going through a provider to arrange its fixtures would couple a provider-neutral unit
    to Hevy's fixture data.
    """
    for muscle, role, source in rows:
        session.add(
            ExerciseMuscle(
                id=uuid.uuid4(),
                user_id=user_id,
                exercise_template_external_id=template_external_id,
                muscle_group=muscle.value,
                role=role.value,
                source=source.value,
            )
        )
    await session.commit()


async def _cleanup(session: AsyncSession) -> None:
    """Remove every row this module could have written, for both users."""
    await session.rollback()
    users = (DEFAULT_USER_ID, SECOND_USER_ID)
    for statement in (
        sa.delete(ExerciseMuscle).where(ExerciseMuscle.user_id.in_(users)),
        sa.delete(ExerciseMuscleOverride).where(ExerciseMuscleOverride.user_id.in_(users)),
        sa.delete(ExerciseTemplate).where(ExerciseTemplate.user_id.in_(users)),
        sa.delete(User).where(User.id == SECOND_USER_ID),
    ):
        await session.execute(statement)
    await session.commit()


def _triples(muscles: Sequence[EffectiveMuscle]) -> set[tuple[str, str, str]]:
    return {(m.muscle_group.value, m.role.value, m.source.value) for m in muscles}


@pytest.mark.integration
async def test_base_mapping_is_effective_without_an_override(session: AsyncSession) -> None:
    """With nothing overridden, the curated base IS the answer, sources and all."""
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [
                (_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
                (_FRONT_DELTS, MuscleRole.INDIRECT, MappingSource.CURATED),
            ],
        )

        resolved = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )

        assert _triples(resolved) == {
            ("chest", "direct", "hevy"),
            ("front_delts", "indirect", "curated"),
        }
        # DIRECT first, so Phase 4 output and these assertions are deterministic.
        assert resolved[0].role is MuscleRole.DIRECT
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_any_override_replaces_the_entire_base_set(session: AsyncSession) -> None:
    """One override row wipes the whole base set from the effective answer.

    Not a merge. A merge would return chest+triceps+front_delts here, which is precisely
    the behaviour that makes removal impossible.
    """
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [
                (_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
                (_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
            ],
        )
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_FRONT_DELTS, MuscleRole.DIRECT)],
            note="the bar path on this one is basically an incline press",
        )
        await session.commit()

        resolved = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )

        assert _triples(resolved) == {("front_delts", "direct", "override")}
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_base_rows_survive_an_override_unchanged(session: AsyncSession) -> None:
    """NORM-02's audit, asserted rather than assumed.

    `created_at` is compared too: an implementation that deleted and rewrote the base rows
    to match the override would still produce the same triples, and this is the assertion
    that catches it.
    """
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [
                (_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
                (_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
            ],
        )

        async def _snapshot() -> set[tuple[str, str, str, object]]:
            rows = (
                await session.execute(
                    sa.select(
                        ExerciseMuscle.muscle_group,
                        ExerciseMuscle.role,
                        ExerciseMuscle.source,
                        ExerciseMuscle.created_at,
                    ).where(
                        ExerciseMuscle.user_id == DEFAULT_USER_ID,
                        ExerciseMuscle.exercise_template_external_id == BASE_TEMPLATE,
                    )
                )
            ).all()
            return {(r[0], r[1], r[2], r[3]) for r in rows}

        before = await _snapshot()
        assert len(before) == 2

        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_REAR_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        assert await _snapshot() == before
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_override_can_remove_a_muscle(session: AsyncSession) -> None:
    """The correction the whole design exists for: dropping a muscle that is not worked."""
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [
                (_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
                (_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
                (_REAR_DELTS, MuscleRole.INDIRECT, MappingSource.CURATED),
            ],
        )
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_CHEST, MuscleRole.DIRECT), (_TRICEPS, MuscleRole.INDIRECT)],
            note="does not actually work rear delts",
        )
        await session.commit()

        resolved = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )

        groups = {m.muscle_group for m in resolved}
        assert groups == {_CHEST, _TRICEPS}
        assert _REAR_DELTS not in groups
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_clear_override_restores_the_base_mapping(session: AsyncSession) -> None:
    """An override is reversible: removing it makes the curated base effective again."""
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [(_CHEST, MuscleRole.DIRECT, MappingSource.HEVY)],
        )
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_REAR_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        removed = await clear_override(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )
        await session.commit()

        assert removed == 1
        resolved = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )
        assert _triples(resolved) == {("chest", "direct", "hevy")}
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_set_override_replaces_rather_than_accumulates(session: AsyncSession) -> None:
    """An override is a complete statement of intent, not a log of past edits.

    Without the delete-first, the unique constraint would reject the second call outright
    -- or, with an upsert, quietly leave the first call's extra muscles in place.
    """
    try:
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_CHEST, MuscleRole.DIRECT), (_TRICEPS, MuscleRole.INDIRECT)],
        )
        await session.commit()

        written = await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_FRONT_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        assert written == 1
        resolved = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )
        assert _triples(resolved) == {("front_delts", "direct", "override")}
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_override_is_scoped_to_the_user(session: AsyncSession) -> None:
    """T-03-30: a shared resolver reading per-user rows must not leak across users."""
    try:
        session.add(User(id=SECOND_USER_ID))
        await session.commit()

        await _seed_base(
            session,
            BASE_TEMPLATE,
            [(_CHEST, MuscleRole.DIRECT, MappingSource.HEVY)],
        )
        await set_override(
            session,
            user_id=SECOND_USER_ID,
            template_external_id=BASE_TEMPLATE,
            assignments=[(_REAR_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        mine = await effective_muscles(
            session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
        )
        theirs = await effective_muscles(
            session, user_id=SECOND_USER_ID, template_external_id=BASE_TEMPLATE
        )

        assert _triples(mine) == {("chest", "direct", "hevy")}
        assert _triples(theirs) == {("rear_delts", "direct", "override")}
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_unmapped_template_ids_lists_only_templates_with_neither_table(
    session: AsyncSession,
) -> None:
    """D-03, computed by ABSENCE.

    A `mapping_status` column would have to be kept in sync with reality and would
    eventually drift from it; "no rows in either table" cannot be wrong.
    """
    try:
        for external_id in (BASE_TEMPLATE, OTHER_TEMPLATE, BARE_TEMPLATE):
            session.add(
                ExerciseTemplate(
                    id=uuid.uuid4(),
                    user_id=DEFAULT_USER_ID,
                    provider="test-provider",
                    external_id=external_id,
                    title=f"Fixture {external_id}",
                )
            )
        await session.commit()

        await _seed_base(
            session, BASE_TEMPLATE, [(_CHEST, MuscleRole.DIRECT, MappingSource.HEVY)]
        )
        # OTHER_TEMPLATE has only an override -- still mapped, just not from the base.
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=OTHER_TEMPLATE,
            assignments=[(_REAR_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        assert await unmapped_template_ids(session, user_id=DEFAULT_USER_ID) == [BARE_TEMPLATE]
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_effective_muscles_bulk_matches_individual_lookups(session: AsyncSession) -> None:
    """Phase 4 resolves a whole training week at once; the batch must not change the answer.

    Also pins the missing-template contract: an id with no rows anywhere maps to `[]`,
    never to a KeyError.
    """
    try:
        await _seed_base(
            session,
            BASE_TEMPLATE,
            [
                (_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
                (_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
            ],
        )
        await _seed_base(
            session, OTHER_TEMPLATE, [(_FRONT_DELTS, MuscleRole.DIRECT, MappingSource.CURATED)]
        )
        await set_override(
            session,
            user_id=DEFAULT_USER_ID,
            template_external_id=OTHER_TEMPLATE,
            assignments=[(_REAR_DELTS, MuscleRole.DIRECT)],
        )
        await session.commit()

        ids = [BASE_TEMPLATE, OTHER_TEMPLATE, BARE_TEMPLATE]
        bulk = await effective_muscles_bulk(
            session, user_id=DEFAULT_USER_ID, template_external_ids=ids
        )

        assert set(bulk) == set(ids)
        assert bulk[BARE_TEMPLATE] == []
        for external_id in ids:
            assert bulk[external_id] == await effective_muscles(
                session, user_id=DEFAULT_USER_ID, template_external_id=external_id
            )
    finally:
        await _cleanup(session)


@pytest.mark.integration
async def test_unknown_stored_muscle_value_raises(session: AsyncSession) -> None:
    """T-03-31: a stored value outside the enum fails LOUDLY.

    Silently dropping the row would shrink every Phase 4 volume figure with no error
    anywhere -- a taxonomy change shipped without a data migration would look like a
    training slump.
    """
    try:
        session.add(
            ExerciseMuscle(
                id=uuid.uuid4(),
                user_id=DEFAULT_USER_ID,
                exercise_template_external_id=BASE_TEMPLATE,
                muscle_group="kneecaps",
                role="direct",
                source="hevy",
            )
        )
        await session.commit()

        with pytest.raises(ValueError, match="kneecaps"):
            await effective_muscles(
                session, user_id=DEFAULT_USER_ID, template_external_id=BASE_TEMPLATE
            )
    finally:
        await _cleanup(session)


def test_apply_weights_uses_one_and_a_half_by_default() -> None:
    """NORM-03's default: 1.0 direct, 0.5 indirect, applied at query time."""
    weighted = apply_weights(
        [
            EffectiveMuscle(_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
            EffectiveMuscle(_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
        ]
    )

    assert weighted == {_CHEST: Decimal("1.0"), _TRICEPS: Decimal("0.5")}


def test_apply_weights_accepts_a_custom_mapping() -> None:
    """The whole point of query-time weighting: "what if indirect counted 0.3?" with no
    migration and no re-sync."""
    weighted = apply_weights(
        [
            EffectiveMuscle(_CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
            EffectiveMuscle(_TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
        ],
        {MuscleRole.DIRECT: Decimal("1.0"), MuscleRole.INDIRECT: Decimal("0.3")},
    )

    assert weighted == {_CHEST: Decimal("1.0"), _TRICEPS: Decimal("0.3")}

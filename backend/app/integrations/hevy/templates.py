"""Exercise-template sync and muscle-map materialisation (HEVY-06, NORM-01, NORM-03).

Two things happen per template, and keeping them separate is the point:

* ``exercise_templates`` stores Hevy's RAW ``primary_muscle_group`` and
  ``secondary_muscle_groups`` verbatim. That is the audit baseline NORM-02 compares an
  override against, and it is the only record of what Hevy actually said if Hevy later
  recategorises the exercise.
* ``exercise_muscles`` stores the CANONICAL result of running that raw data through
  ``app.normalization`` -- Hevy's flat ``shoulders`` expanded into the deltoid head(s) the
  movement actually trains. It is a materialised view of curated code (D-02), recomputed on
  every template sync, never hand-edited.

``/v1/exercise_templates`` caps its page size at **100**, not 10 like every other endpoint in
this integration. Using 10 here would issue roughly 40 requests instead of 5 against a rate
limit Hevy has never documented (Pitfall 6). The cap is not restated as a literal below: it
lives on ``HevyClient`` as ``PAGE_SIZE_EXERCISE_TEMPLATES`` and is only logged from there, so
there is exactly one place to be wrong.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, func, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models.exercise import ExerciseMuscle, ExerciseTemplate
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    advance_cursor_page,
    complete_sync,
    ensure_sync_state,
    mark_running,
    record_sync_error,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.schemas import HevyExerciseTemplate
from app.normalization.exercise_map import derive_assignments

log = structlog.get_logger()

# Bound to the constraint BY NAME rather than by column list, matching `sync_state`: a rename
# then raises immediately instead of silently degrading into a duplicate-row insert.
_TEMPLATE_CONSTRAINT = "uq_exercise_templates_user_provider_external_id"


@dataclass(frozen=True, slots=True)
class TemplateSyncResult:
    """What one template run did. `unmapped` is a curation report, not an error list."""

    pages_fetched: int
    templates_upserted: int
    mappings_written: int
    unmapped: tuple[str, ...]


async def upsert_exercise_template(
    session: AsyncSession, *, user_id: uuid.UUID, template: HevyExerciseTemplate
) -> None:
    """Insert or refresh one template row, storing Hevy's values UNTRANSLATED.

    `updated_at` is set explicitly. SQLAlchemy's `onupdate=func.now()` fires for an
    `update()` statement but is NOT injected into `ON CONFLICT DO UPDATE SET`, so omitting
    it would freeze the audit timestamp at row creation.
    """
    values = {
        "title": template.title,
        "exercise_type": template.type,
        "primary_muscle_group": template.primary_muscle_group,
        "secondary_muscle_groups": list(template.secondary_muscle_groups),
        "equipment_category": template.equipment,
        "is_custom": template.is_custom,
    }
    statement = pg_insert(ExerciseTemplate).values(
        id=uuid.uuid4(),
        user_id=user_id,
        provider=PROVIDER_HEVY,
        external_id=template.id,
        **values,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint=_TEMPLATE_CONSTRAINT,
            set_={**values, "updated_at": func.now()},
        )
    )


async def replace_exercise_muscles(
    session: AsyncSession, *, user_id: uuid.UUID, template: HevyExerciseTemplate
) -> int:
    """Recompute this template's canonical mapping from `app.normalization` (D-02).

    Delete-and-reinsert, exactly like workout children and for the same reason: a curated
    change that REMOVES a muscle must actually remove it. An upsert-only strategy could add
    and modify but never delete, so a correction like "this does not really work rear delts"
    would be silently ignored and the wrong row would live forever.

    Returns the number of assignment rows written -- zero is a valid, expected answer (D-03).
    """
    assignments = derive_assignments(
        template_id=template.id,
        title=template.title,
        primary_muscle_group=template.primary_muscle_group,
        secondary_muscle_groups=template.secondary_muscle_groups,
    )
    await session.execute(
        delete(ExerciseMuscle).where(
            ExerciseMuscle.user_id == user_id,
            ExerciseMuscle.exercise_template_external_id == template.id,
        )
    )
    if not assignments:
        return 0
    await session.execute(
        insert(ExerciseMuscle),
        [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "exercise_template_external_id": template.id,
                "muscle_group": assignment.muscle_group.value,
                "role": assignment.role.value,
                "source": assignment.source.value,
            }
            for assignment in assignments
        ],
    )
    return len(assignments)


async def _persist_page(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    templates: list[HevyExerciseTemplate],
) -> tuple[int, int, list[str]]:
    """Write one page's templates and mappings. Returns (upserted, mappings, unmapped ids).

    Each template's pair of writes is wrapped in its own SAVEPOINT so one malformed row
    cannot take down a page of 100. The `except` logs the exception CLASS NAME only --
    `str(exc)` on a `DataError` renders bound parameter values (T-03-32).
    """
    upserted = 0
    mappings = 0
    unmapped: list[str] = []

    for template in templates:
        try:
            async with session.begin_nested():
                await upsert_exercise_template(session, user_id=user_id, template=template)
                written = await replace_exercise_muscles(
                    session, user_id=user_id, template=template
                )
        except SQLAlchemyError as exc:
            log.warning(
                "hevy_template_skipped",
                template_id=template.id,
                reason=type(exc).__name__,
            )
            continue

        upserted += 1
        mappings += written
        # D-03: an unmapped template is a CURATION GAP, not a failure. It is counted and
        # logged so the gap is visible, and then the sync carries on. Phase 4 simply
        # excludes these templates from per-muscle volume until someone curates them.
        if written == 0:
            unmapped.append(template.id)

    return upserted, mappings, unmapped


async def sync_exercise_templates(
    client: HevyClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
) -> TemplateSyncResult:
    """Walk `/v1/exercise_templates` and materialise the canonical mapping (HEVY-06).

    Same transactional shape as the workout sync: the run is opened in its own transaction,
    each page commits together with the checkpoint that describes it (D-08), and a failure
    records the error WITHOUT resetting the cursor so the next run resumes rather than
    restarting.
    """
    async with sessionmaker() as session:
        state = await ensure_sync_state(
            session,
            user_id=user_id,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_EXERCISE_TEMPLATES,
        )
        start_page = state.cursor_page or 1
        await mark_running(
            session,
            user_id=user_id,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_EXERCISE_TEMPLATES,
        )
        await session.commit()

    log.info(
        "hevy_template_sync_started",
        start_page=start_page,
        page_size=HevyClient.PAGE_SIZE_EXERCISE_TEMPLATES,
    )

    pages_fetched = 0
    templates_upserted = 0
    mappings_written = 0
    unmapped: list[str] = []
    page = start_page

    try:
        while True:
            payload = await client.get_exercise_templates(page=page)
            pages_fetched += 1

            async with sessionmaker() as session:
                upserted, mappings, page_unmapped = await _persist_page(
                    session, user_id=user_id, templates=payload.exercise_templates
                )
                await advance_cursor_page(
                    session,
                    user_id=user_id,
                    provider=PROVIDER_HEVY,
                    resource=RESOURCE_EXERCISE_TEMPLATES,
                    cursor_page=page + 1,
                )
                await session.commit()

            templates_upserted += upserted
            mappings_written += mappings
            unmapped.extend(page_unmapped)

            log.info(
                "hevy_template_page_committed",
                page=page,
                page_count=payload.page_count,
                templates=upserted,
                mappings=mappings,
                unmapped=len(page_unmapped),
            )

            if not payload.exercise_templates or page >= payload.page_count:
                break
            page += 1

        async with sessionmaker() as session:
            await complete_sync(
                session,
                user_id=user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_EXERCISE_TEMPLATES,
                last_synced_at=utc_now(),
                cursor_page=None,
            )
            await session.commit()
    except Exception as exc:
        # A fresh session: the one that failed may be in an unusable transaction, and the
        # error record must survive regardless of what happened to it.
        async with sessionmaker() as error_session:
            await record_sync_error(
                error_session,
                user_id=user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_EXERCISE_TEMPLATES,
                exc=exc,
            )
            await error_session.commit()
        log.warning("hevy_template_sync_failed", page=page, reason=type(exc).__name__)
        raise

    log.info(
        "hevy_template_sync_completed",
        pages=pages_fetched,
        templates=templates_upserted,
        mappings=mappings_written,
        unmapped=len(unmapped),
    )
    return TemplateSyncResult(
        pages_fetched=pages_fetched,
        templates_upserted=templates_upserted,
        mappings_written=mappings_written,
        unmapped=tuple(unmapped),
    )

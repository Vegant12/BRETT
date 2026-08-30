"""Freshness and coverage, the envelope every analytics response carries (DQ-01, DQ-02).

The integration tests run against the real Postgres container because the two things under
test have no meaning outside PostgreSQL: `sync_state`'s writers go through
`INSERT ... ON CONFLICT DO UPDATE`, and the coverage count is a `TIMESTAMPTZ` half-open range
predicate whose boundary behaviour is exactly what a SQLite stand-in would get subtly wrong.

The structural test that pins `FreshnessMetadata`'s field set deliberately carries NO
integration marker. "No credential, error text or internal cursor reaches Claude" is a security
guarantee, and a security guarantee must never become skippable because Docker is not running
-- the same argument `test_sync_state.py` makes for keeping its `format_sync_error` tests in
the fast suite. The D-05 boundary test below is markerless for the cheaper reason that it
touches no database at all.

Every container-backed test takes `golden_workout` even when it only writes `sync_state` rows,
because that fixture owns the `finally: await session.rollback()` which keeps the shared
session-scoped container clean whether the test passes or fails.
"""

import datetime as dt

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import FRESHNESS_RESOURCES_MUSCLE, build_freshness
from app.analytics.schemas import FreshnessMetadata
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    complete_sync,
    get_sync_state,
    record_sync_error,
)
from tests.conftest import ANALYTICS_SECOND_USER_ID, GoldenBuilder

# `ANALYTICS_SECOND_USER_ID` and not DEFAULT_USER_ID: the container is session-scoped and
# shared, and DEFAULT_USER_ID's `sync_state` rows are written and asserted on by the Hevy sync
# tests. A distinct user id means these rows cannot collide with theirs.
#
# The two timestamps are 25 minutes apart because that is the drift observed on the live
# database between the workouts sync and the exercise_templates sync.
_SYNCED_WORKOUTS_AT = dt.datetime(2026, 8, 30, 5, 43, 18, tzinfo=dt.UTC)
_SYNCED_TEMPLATES_AT = dt.datetime(2026, 8, 30, 6, 8, 4, tzinfo=dt.UTC)

# Distinctive on purpose, so a leak is unambiguous rather than a coincidence.
_LEAK_SENTINEL = "zz-analytics-leak-canary-9f3a"


class _SentinelFailure(Exception):
    """An exception that OPTS IN to storing detail, the way the Hevy client does.

    A plain `RuntimeError(_LEAK_SENTINEL)` would not do: `format_sync_error` stores the class
    name alone unless the exception curates a `safe_message`, so the sentinel would never reach
    the column and the leak test would pass without ever having anything to leak.
    """

    safe_message = _LEAK_SENTINEL


@pytest.mark.integration
async def test_freshness_reports_each_resource_independently(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: one `last_synced_at` per resource, because they genuinely drift apart.

    A single collapsed `last_synced_at` would report the NEWER of the two for both. The muscle
    map comes from `exercise_templates`, so a stale template sync silently changes every
    per-muscle number -- and 25 minutes of drift is exactly the staleness Claude must be able
    to see in order to caveat the answer instead of asserting it.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
        last_synced_at=_SYNCED_WORKOUTS_AT,
    )
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_EXERCISE_TEMPLATES,
        last_synced_at=_SYNCED_TEMPLATES_AT,
    )
    await session.flush()

    freshness = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
    )

    assert freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }
    # Two genuinely distinct values, not one row read twice.
    assert len(set(freshness.resources.values())) == 2


@pytest.mark.integration
async def test_freshness_reports_none_for_a_never_synced_resource(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A never-synced resource reports `None`; it is NOT omitted from the map.

    "Never synced" is a legitimate answer to "when was this last synced". Dropping the key
    instead would make it indistinguishable from "the resource does not exist", which is the
    one reading that should send Claude looking for a bug rather than for a stale sync.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    freshness = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
    )

    assert set(freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
    assert all(value is None for value in freshness.resources.values())


def test_freshness_model_cannot_carry_sync_state_internals() -> None:
    """T-04-03, structurally rather than behaviourally -- and never skippable.

    `extra="forbid"` on the analytics base model means a future refactor cannot quietly widen
    `FreshnessMetadata` to carry the bookkeeping row's error text, run status or resume
    cursors. Asserting the field set as well as the rejection catches the other direction: a
    field ADDED to the model, which `extra="forbid"` would happily accept.

    No marker and no fixtures: this is the MCP-06 guarantee, and it must keep running when
    Docker does not.
    """
    assert set(FreshnessMetadata.model_fields) == {"resources"}

    with pytest.raises(ValidationError):
        FreshnessMetadata(resources={}, last_error=_LEAK_SENTINEL)  # type: ignore[call-arg]


@pytest.mark.integration
async def test_freshness_never_leaks_last_error(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """MCP-06 end to end: a real stored error never reaches the serialized response.

    The structural test above proves the model cannot DECLARE the field. This one proves the
    builder does not smuggle it in some other way -- it seeds a distinctive sentinel through
    the production writer and then scans the actual JSON Phase 6 would hand to Claude.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await record_sync_error(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
        exc=_SentinelFailure(),
    )
    await session.flush()

    state = await get_sync_state(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
    )
    assert state is not None and state.last_error is not None
    assert _LEAK_SENTINEL in state.last_error, (
        "the sentinel never reached sync_state -- test is vacuous"
    )

    payload = (
        await build_freshness(
            session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
        )
    ).model_dump_json()

    assert _LEAK_SENTINEL not in payload, (
        f"MCP-06 violated: {_LEAK_SENTINEL!r} reached an analytics return model. "
        f"sync_state's stored error text is bounded by format_sync_error precisely so it "
        f"does not travel"
    )

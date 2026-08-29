"""The Hevy quarantine boundary: wire schemas and the retryable/not split (HEVY-05).

Named `..._wire_schemas` to keep it distinct from `test_hevy_schema.py`, which is about
the DATABASE schema. This file never touches Postgres and never opens a socket: it
asserts that Hevy's JSON, exactly as the live API serves it, survives the round trip into
typed Python -- and that the failures fail in the right direction.

Three properties are load-bearing and each has a test that goes red on its own:

* **Decimals are exact.** `response.json()` yields Python floats. If `Decimal` conversion
  went through the binary float rather than its string form, `9.5` would become
  `Decimal('9.5000000000000017763568394002504646778106689453125')` and every tonnage
  figure downstream would carry the error. This is checked rather than assumed because
  the fix (a `mode="before"` validator) is cheap and the failure is silent.
* **The event union is DISCRIMINATED.** A permissive union would let an unrecognised
  event type be dropped, which is data loss that looks exactly like a successful sync.
* **A ValidationError never echoes the payload.** Workout titles and body-composition
  numbers are personal health data (FOUND-05); `hide_input_in_errors=True` is what keeps
  them out of a message that could reach a log line.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from app.integrations.hevy.errors import (
    RETRYABLE_EXCEPTIONS,
    HevyAuthError,
    HevyClientError,
    HevyError,
    HevyPageNotFound,
    HevyRateLimited,
    HevyResponseError,
    HevyServerError,
)
from app.integrations.hevy.schemas import (
    HevyDeletedWorkoutEvent,
    HevyUpdatedWorkoutEvent,
    PaginatedBodyMeasurements,
    PaginatedExerciseTemplates,
    PaginatedWorkoutEvents,
    PaginatedWorkouts,
    WorkoutCount,
    event_timestamp,
)
from tests.conftest import hevy_fixture

# Distinctive on purpose, and planted in the field that actually FAILS validation:
# pydantic only renders the offending field's input, so putting this in a valid
# neighbouring field would make the assertion pass for the wrong reason.
LEAKY_VALUE = "secret-title-9f3a-must-not-be-echoed"


# --- errors: the retryable / not-retryable split (Pitfall 7) ------------------


def test_rate_limit_and_server_error_are_retryable() -> None:
    """429 and 5xx are the two statuses where trying again can actually work."""
    assert HevyRateLimited in RETRYABLE_EXCEPTIONS
    assert HevyServerError in RETRYABLE_EXCEPTIONS
    assert httpx2.TransportError in RETRYABLE_EXCEPTIONS


def test_auth_and_client_errors_are_not_retryable() -> None:
    """Pitfall 7: retrying a 401 burns the whole backoff budget for nothing.

    A revoked key would surface as an opaque timeout a minute later instead of an
    immediate, obvious auth failure. `HevyPageNotFound` matters for the opposite reason
    (Pitfall 5): `/v1/body_measurements` uses 404 as an end-of-pages TERMINATOR, so
    retrying it would delay a run that had already fetched everything.
    """
    for not_retryable in (HevyAuthError, HevyClientError, HevyPageNotFound, HevyResponseError):
        assert not_retryable not in RETRYABLE_EXCEPTIONS
        assert not issubclass(not_retryable, tuple(RETRYABLE_EXCEPTIONS)), (
            f"{not_retryable.__name__} is retryable by INHERITANCE; "
            f"retry_if_exception_type matches subclasses"
        )


def test_page_not_found_is_a_client_error() -> None:
    """The 404 terminator is a 4xx, so a caller catching `HevyClientError` still sees it."""
    assert issubclass(HevyPageNotFound, HevyClientError)
    assert issubclass(HevyClientError, HevyError)


def test_auth_error_never_carries_the_credential() -> None:
    """T-03-16: the class is constructed from a STATUS, so there is no key to leak.

    Asserted on the constructor's arity as well as its output: an `__init__` that took a
    message would let a future caller interpolate the rejected key into it, and nothing
    else in the codebase would notice.
    """
    error = HevyAuthError(401)

    assert error.safe_message == "Hevy rejected the API key (HTTP 401)"
    for rendered in (str(error), repr(error), error.safe_message):
        assert "401" in rendered or rendered == error.safe_message
    assert error.status_code == 401


def test_response_error_names_the_endpoint_and_nothing_else() -> None:
    """T-03-18: `safe_message` is the opt-in channel, and it opts in to one string."""
    error = HevyResponseError("/v1/workouts")

    assert error.safe_message == "Hevy response did not match the expected schema for /v1/workouts"
    assert LEAKY_VALUE not in str(error)


def test_rate_limited_carries_whatever_hevy_sent() -> None:
    """D-10: Hevy documents no rate limit at all, so `retry_after` is the only evidence."""
    assert HevyRateLimited("3").retry_after == "3"
    assert HevyRateLimited().retry_after is None


# --- schemas: the fixtures, exactly as the live API serves them ---------------


def test_every_paginated_envelope_validates_its_fixture() -> None:
    """All five canned responses round-trip. This is the boundary's whole job."""
    workouts = PaginatedWorkouts.model_validate(hevy_fixture("workouts_page1"))
    templates = PaginatedExerciseTemplates.model_validate(hevy_fixture("exercise_templates_page1"))
    measurements = PaginatedBodyMeasurements.model_validate(hevy_fixture("body_measurements_page1"))
    events = PaginatedWorkoutEvents.model_validate(hevy_fixture("workout_events_page1"))
    page2 = PaginatedWorkouts.model_validate(hevy_fixture("workouts_page2"))

    assert (workouts.page, workouts.page_count) == (1, 2)
    assert len(workouts.workouts) == 1
    assert len(templates.exercise_templates) == 4
    assert len(measurements.body_measurements) == 2
    assert len(events.events) == 2
    assert page2.page == 2


def test_workout_count_is_a_plain_envelope() -> None:
    """`/v1/workouts/count` is the one endpoint with no pagination at all."""
    assert WorkoutCount.model_validate({"workout_count": 42}).workout_count == 42


def test_decimal_fields_round_trip_exactly() -> None:
    """`response.json()` gives floats; `Decimal(float)` would poison every tonnage figure.

    `40` arrives as a JSON integer and `9.5` as a JSON float, so both conversion paths are
    covered. Equality against a `Decimal` built from a STRING is the assertion -- comparing
    against another float would be true even for the broken conversion.
    """
    workouts = PaginatedWorkouts.model_validate(hevy_fixture("workouts_page1"))
    sets = workouts.workouts[0].exercises[0].sets

    assert sets[0].weight_kg == Decimal("40")
    assert sets[1].rpe == Decimal("9.5")
    assert str(sets[1].rpe) == "9.5", (
        "float->Decimal went through the binary value, not its string form; add a "
        "`mode='before'` validator returning Decimal(str(v))"
    )

    measurements = PaginatedBodyMeasurements.model_validate(hevy_fixture("body_measurements_page1"))
    assert measurements.body_measurements[1].weight_kg == Decimal("80.1")
    assert str(measurements.body_measurements[1].weight_kg) == "80.1"


def test_the_wire_shape_is_the_wire_shape_not_the_blueprint() -> None:
    """`BRETT blueprint.md` §8 is wrong in four places; the models follow the live API.

    Asserted as absent fields rather than merely present ones, because the failure mode is
    a model that carries a field Hevy never sends: it validates fine, stays `None` forever,
    and surfaces phases later as a metric that is always zero.
    """
    workout = PaginatedWorkouts.model_validate(hevy_fixture("workouts_page1")).workouts[0]
    a_set = workout.exercises[0].sets[0]

    for absent in ("rir", "weight_unit", "weight", "distance", "duration"):
        assert absent not in type(a_set).model_fields, (
            f"HEVY-05 violated: HevySet declares {absent!r}, which the live Hevy API does "
            f"not send -- that is the blueprint's schema, not Hevy's"
        )
    assert "id" not in type(a_set).model_fields
    assert "id" not in type(workout.exercises[0]).model_fields
    assert workout.exercises[0].supersets_id is None
    assert workout.exercises[1].supersets_id == 0, "supersets_id 0 is a real group, not absent"


def test_unknown_fields_are_ignored_but_a_rename_is_not() -> None:
    """`extra="ignore"` is deliberate and asymmetric.

    Hevy ADDING a field must not break a sync -- they ship whenever they like and warn that
    they may "completely change the structure". Hevy RENAMING or REMOVING one must break it
    here, loudly, rather than letting a `None` propagate into the database.
    """
    payload: dict[str, Any] = hevy_fixture("workouts_page1")
    payload["workouts"][0]["some_field_hevy_added_last_tuesday"] = True

    assert PaginatedWorkouts.model_validate(payload).workouts[0].title == "Push Day 💪"

    renamed: dict[str, Any] = hevy_fixture("workouts_page1")
    renamed["workouts"][0].pop("start_time")

    with pytest.raises(ValidationError):
        PaginatedWorkouts.model_validate(renamed)


# --- schemas: the discriminated event union ----------------------------------


def test_events_resolve_to_their_variants_in_order() -> None:
    """The fixture is newest-first, exactly as Hevy serves it (Pattern 2 depends on this)."""
    events = PaginatedWorkoutEvents.model_validate(hevy_fixture("workout_events_page1")).events

    assert isinstance(events[0], HevyDeletedWorkoutEvent)
    assert isinstance(events[1], HevyUpdatedWorkoutEvent)
    assert events[0].id == "22222222-2222-2222-2222-222222222222"
    assert events[1].workout.title == "Push Day (edited)"


def test_an_unknown_event_type_is_rejected_not_dropped() -> None:
    """T-03-17: silently skipping an unrecognised event is data loss that looks like success.

    A plain (non-discriminated) union would try each member, fail both, and -- depending on
    how the caller handled it -- could end up skipping the event. The discriminator turns
    "Hevy shipped a third event type" into a loud, immediate validation failure.
    """
    payload: dict[str, Any] = hevy_fixture("workout_events_page1")
    payload["events"].append({"type": "archived", "id": "33333333", "archived_at": "2026-08-06"})

    with pytest.raises(ValidationError) as excinfo:
        PaginatedWorkoutEvents.model_validate(payload)

    assert "archived" in str(excinfo.value) or "union_tag" in str(excinfo.value)


def test_event_timestamp_reads_a_different_field_per_variant() -> None:
    """The two variants carry their timestamp in genuinely different places.

    `UpdatedWorkout` has no top-level timestamp at all -- it is nested inside the workout
    snapshot -- so a drain that sorted on `deleted_at` would sort every update on a field
    that does not exist. Both are asserted against the fixture's literal values, so a helper
    that returned "now" for one variant could not pass.
    """
    events = PaginatedWorkoutEvents.model_validate(hevy_fixture("workout_events_page1")).events

    assert event_timestamp(events[0]) == dt.datetime(2026, 8, 5, 10, 0, tzinfo=dt.UTC)
    assert event_timestamp(events[1]) == dt.datetime(2026, 8, 4, 9, 0, tzinfo=dt.UTC)


# --- schemas: FOUND-05, the error message itself -----------------------------


def test_a_validation_error_never_echoes_the_payload() -> None:
    """FOUND-05 / T-03-18: `hide_input_in_errors=True`, asserted rather than trusted.

    Without it pydantic renders `input_value='...'` into the message, and this module's
    inputs are workout titles and body-composition numbers. A ValidationError raised here
    can reach a log line or an exception chain, so the rendering is the leak channel.
    """
    payload: dict[str, Any] = hevy_fixture("workouts_page1")
    payload["workouts"][0]["start_time"] = LEAKY_VALUE

    with pytest.raises(ValidationError) as excinfo:
        PaginatedWorkouts.model_validate(payload)

    rendered = str(excinfo.value)
    assert LEAKY_VALUE not in rendered, (
        "FOUND-05 violated: the rejected input was echoed into the ValidationError; "
        "`hide_input_in_errors=True` is missing from the model config"
    )
    assert "input_value" not in rendered
    assert "start_time" in rendered, "the message must still say WHICH field failed"

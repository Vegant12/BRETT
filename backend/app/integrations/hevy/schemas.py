"""Pydantic mirrors of Hevy's LIVE wire format (HEVY-05).

This module is the quarantine boundary. If Hevy renames a field, validation fails HERE with a
clear error, instead of a `None` propagating into the database and surfacing three phases
later as a wrong tonnage figure.

Transcribed from the live OpenAPI document parsed 2026-08-29, NOT from `BRETT blueprint.md`
§8, which is wrong in four places: it expects `rir` (Hevy sends `rpe`), `weight_unit` (Hevy
normalises to `weight_kg`), `weight`/`distance`/`duration` (actually `weight_kg`/
`distance_meters`/`duration_seconds`), and ids on exercises and sets (they have only `index`).

Every model sets `hide_input_in_errors=True`. A ValidationError from this module would
otherwise render `input_value=...` -- workout titles and body-composition numbers -- into a
message that could reach a log line (FOUND-05).
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _HevyModel(BaseModel):
    """Shared config for every wire model.

    ``extra="ignore"`` on purpose, and asymmetrically so: Hevy ADDING a field must not break
    a sync -- they ship whenever they like -- while Hevy RENAMING or REMOVING one must break
    it loudly, here, rather than letting a silent `None` reach the database.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")


class HevySet(_HevyModel):
    """One set. No `id` and no `rir`: sets are identified by `index` alone.

    Numerics are `Decimal`, never `float`. `response.json()` hands pydantic a Python float
    and pydantic converts float->Decimal via the value's STRING form, so `9.5` becomes
    `Decimal("9.5")` rather than `Decimal("9.500000000000000177635683940025...")`. Verified by
    `test_decimal_fields_round_trip_exactly`; if that test ever goes red, the fix is a
    `@field_validator(..., mode="before")` returning `Decimal(str(v))`.
    """

    index: int
    # Free-form `str`, not a Literal: Hevy documents {normal, warmup, dropset, failure}, but a
    # fifth set type must not fail a whole sync page. The normalization layer decides what an
    # unrecognised type means.
    type: str
    weight_kg: Decimal | None = None
    reps: int | None = None
    distance_meters: Decimal | None = None
    duration_seconds: int | None = None
    rpe: Decimal | None = None
    custom_metric: Decimal | None = None


class HevyExercise(_HevyModel):
    """One exercise within a workout. Also has no `id` -- only `index`.

    `supersets_id` is nullable AND meaningfully zero: `0` is a real superset group, so any
    code downstream must test `is None`, never truthiness.
    """

    index: int
    title: str
    notes: str | None = None
    exercise_template_id: str
    supersets_id: int | None = None
    sets: list[HevySet] = Field(default_factory=list)


class HevyWorkout(_HevyModel):
    """A workout as Hevy serves it. `id` is the only stable identifier in the tree."""

    id: str
    title: str = ""
    routine_id: str | None = None
    description: str | None = None
    start_time: dt.datetime
    end_time: dt.datetime
    updated_at: dt.datetime
    created_at: dt.datetime
    exercises: list[HevyExercise] = Field(default_factory=list)


class PaginatedWorkouts(_HevyModel):
    """`GET /v1/workouts` -- `pageSize` caps at 10."""

    page: int
    page_count: int
    workouts: list[HevyWorkout] = Field(default_factory=list)


class WorkoutCount(_HevyModel):
    """`GET /v1/workouts/count` -- the one endpoint with no pagination at all."""

    workout_count: int


class HevyUpdatedWorkoutEvent(_HevyModel):
    """`{type: "updated", workout: Workout}` -- carries a FULL snapshot, not a diff."""

    type: Literal["updated"]
    workout: HevyWorkout


class HevyDeletedWorkoutEvent(_HevyModel):
    """`{type: "deleted", id: str, deleted_at: str}` -- no workout body to apply."""

    type: Literal["deleted"]
    id: str
    deleted_at: dt.datetime


# A DISCRIMINATED union, not a plain one. If Hevy ever adds a third event type,
# validation must fail loudly -- a permissive union would let an unknown event be
# silently dropped, which is data loss that looks exactly like a successful sync.
HevyWorkoutEvent = Annotated[
    HevyUpdatedWorkoutEvent | HevyDeletedWorkoutEvent,
    Field(discriminator="type"),
]


class PaginatedWorkoutEvents(_HevyModel):
    """`GET /v1/workouts/events?since=` -- ordered NEWEST first, `pageSize` caps at 10."""

    page: int
    page_count: int
    events: list[HevyWorkoutEvent] = Field(default_factory=list)


class HevyExerciseTemplate(_HevyModel):
    """`id` is an 8-char hex code for built-ins and a full UUID for custom templates.

    The wire field is ``equipment``, not ``equipment_category`` -- confirmed by a live
    `/v1/exercise_templates` response during plan 03-11's real-API validation. `_HevyModel`
    declares no alias generator, so a mismatched field name here does not raise: under
    `extra="ignore"`, the real `equipment` key is silently dropped and this field would default
    to `None` for every template. See `docs/hevy-api-observations.md`.
    """

    id: str
    title: str
    type: str | None = None
    primary_muscle_group: str | None = None
    secondary_muscle_groups: list[str] = Field(default_factory=list)
    equipment: str | None = None
    is_custom: bool = False


class PaginatedExerciseTemplates(_HevyModel):
    """`GET /v1/exercise_templates` -- `pageSize` caps at **100**, not 10 (Pitfall 6)."""

    page: int
    page_count: int
    exercise_templates: list[HevyExerciseTemplate] = Field(default_factory=list)


class HevyBodyMeasurement(_HevyModel):
    """One dated measurement row. `date` is the only required field; all 17 metrics are
    independently nullable, because Hevy sends a row for any single metric the user entered.
    """

    # `date`, not `measured_on`, and no `id` field: this mirrors the WIRE. The rename to
    # `measured_on` and to `*_cm` happens in the persistence layer, not here.
    date: dt.date
    weight_kg: Decimal | None = None
    lean_mass_kg: Decimal | None = None
    fat_percent: Decimal | None = None
    neck_cm: Decimal | None = None
    shoulder_cm: Decimal | None = None
    chest_cm: Decimal | None = None
    left_bicep_cm: Decimal | None = None
    right_bicep_cm: Decimal | None = None
    left_forearm_cm: Decimal | None = None
    right_forearm_cm: Decimal | None = None
    # No `_cm` suffix on these six: Hevy does not send one. Adding it here would be a
    # rename, and a rename is exactly what this module exists to make impossible.
    abdomen: Decimal | None = None
    waist: Decimal | None = None
    hips: Decimal | None = None
    left_thigh: Decimal | None = None
    right_thigh: Decimal | None = None
    left_calf: Decimal | None = None
    right_calf: Decimal | None = None


class PaginatedBodyMeasurements(_HevyModel):
    """`GET /v1/body_measurements` -- `pageSize` caps at 10 and an over-range page 404s."""

    page: int
    page_count: int
    body_measurements: list[HevyBodyMeasurement] = Field(default_factory=list)


def event_timestamp(event: HevyWorkoutEvent) -> dt.datetime:
    """The two event variants carry their timestamp in DIFFERENT fields.

    UpdatedWorkout -> .workout.updated_at ; DeletedWorkout -> .deleted_at. Getting this
    wrong makes the drain sort on a field that does not exist for half the events.
    """
    if isinstance(event, HevyDeletedWorkoutEvent):
        return event.deleted_at
    return event.workout.updated_at

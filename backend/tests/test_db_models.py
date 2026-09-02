"""Unit tests for the declarative layer (no database required).

These assert the *shape* of ``Base.metadata`` rather than any live schema, so
they run in the fast (non-integration) suite. The corresponding live-schema
assertions live in ``test_migrations.py``.
"""

import re
import uuid

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.base import NAMING_CONVENTION, Base, TimestampMixin
from app.db.models import User
from app.db.session import make_engine, make_sessionmaker

# Same shape as the live-schema guard in `test_hevy_schema.py`, applied one layer
# earlier. A credential-shaped column caught in the FAST suite never reaches a
# migration at all.
_CREDENTIAL_SHAPED = re.compile(r"credential|password|passwd|secret|api_key|apikey|token|key")


def test_metadata_contains_expected_tables() -> None:
    """Every table is declared on purpose.

    Kept as an equality assertion, not a subset check: the value of this test is that a
    stray model or a typo'd `__tablename__` fails the FAST suite on the commit that
    introduces it. This is the complete Phase 3 schema plus Phase 8's single addition.

    `health_daily_metrics` is the ONLY table Phase 8 adds (D-02). A `health_workouts`
    appearing here would mean the Hevy-re-export exclusion had been reopened.
    """
    assert set(Base.metadata.tables) == {
        "users",
        "workouts",
        "workout_exercises",
        "workout_sets",
        "exercise_templates",
        "exercise_muscles",
        "exercise_muscle_overrides",
        "body_measurements",
        "sync_state",
        "health_daily_metrics",
    }


def test_body_measurement_key_is_a_calendar_date() -> None:
    """HEVY-07: `measured_on` is a DATE, and that is not a FOUND-04 exception.

    Hevy's field is `format: date` and its sibling endpoints key on the date itself
    (`GET/PUT /v1/body_measurements/{date}`). Storing a TIMESTAMPTZ would require
    inventing a time of day, and every comparison would then depend on the invented
    value rather than on the day the measurement was taken.
    """
    column = Base.metadata.tables["body_measurements"].c.measured_on
    assert isinstance(column.type, sa.Date)
    # `DateTime` is not a subclass of `Date` in SQLAlchemy, but assert it explicitly:
    # the failure this guards against is a model author "fixing" FOUND-04 by reaching
    # for `DateTime(timezone=True)` here.
    assert not isinstance(column.type, sa.DateTime)
    assert column.nullable is False


def test_body_measurement_carries_all_seventeen_metrics() -> None:
    """One row per date holds every metric Hevy sends, not one row per metric.

    D-07's fallback assumed per-metric keying; the live API disproves it.
    """
    columns = set(Base.metadata.tables["body_measurements"].c.keys())
    identity = {"id", "user_id", "source", "external_id", "measured_on", "created_at", "updated_at"}
    metrics = columns - identity
    assert len(metrics) == 17, sorted(metrics)
    # The seven fields Hevy sends without a unit suffix are stored as `*_cm`.
    assert {"abdomen_cm", "waist_cm", "hips_cm", "left_calf_cm"} <= metrics
    # Every metric is optional: Hevy requires only `date`.
    for name in metrics:
        assert Base.metadata.tables["body_measurements"].c[name].nullable is True, name


def test_body_measurement_unique_key_is_user_source_and_date() -> None:
    """HEVY-07 idempotency: re-syncing a date updates the row rather than adding one."""
    table = Base.metadata.tables["body_measurements"]
    unique = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique["uq_body_measurements_user_source_measured_on"] == [
        "user_id",
        "source",
        "measured_on",
    ]


def test_sync_state_unique_constraint_enables_upsert() -> None:
    """HEVY-09: one cursor row per (user, provider, resource), enforced by the DB.

    `ensure_sync_state` binds `ON CONFLICT` to this constraint by name; without it
    the get-or-create degenerates into a race.
    """
    table = Base.metadata.tables["sync_state"]
    unique = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique["uq_sync_state_user_provider_resource"] == ["user_id", "provider", "resource"]
    # D-08's resume point and HEVY-02's events cursor are separate columns on purpose:
    # one is a page number inside a run, the other survives across runs.
    assert "cursor_page" in table.c
    assert "cursor_timestamp" in table.c
    assert table.c.last_synced_at.type.timezone is True


def test_override_is_a_separate_table_from_the_base_mapping() -> None:
    """D-04/NORM-02: an override never mutates `exercise_muscles`.

    The audit NORM-02 asks for is a diff of two intact tables, which is only possible
    while both survive. A `is_override` flag on one table would destroy the baseline.
    """
    base = Base.metadata.tables["exercise_muscles"]
    override = Base.metadata.tables["exercise_muscle_overrides"]
    # The baseline records where the mapping came from; the override records why the
    # user disagreed. Neither column belongs on the other table.
    assert "source" in base.c
    assert "source" not in override.c
    assert "note" in override.c
    assert "note" not in base.c
    # NORM-03: the direct/indirect WEIGHT is a query-time parameter (blueprint §18).
    # A column here would freeze one answer into the data.
    assert "weight" not in base.c
    assert "weight" not in override.c


def test_no_model_column_stores_a_credential() -> None:
    """T-03-11: the Hevy key lives in the environment, not in a table.

    `sync_state` is deliberately not named `external_connections` (blueprint §5.2) so
    the table's own name cannot invite a credential column later. This test is the
    fast-suite half of the guarantee; `test_no_table_stores_a_credential` proves the
    same thing against the migrated database.
    """
    offenders = [
        f"{table_name}.{column.name}"
        for table_name, table in Base.metadata.tables.items()
        for column in table.c
        if _CREDENTIAL_SHAPED.search(column.name.lower())
    ]
    assert offenders == []


def test_reference_models_declare_no_relationships() -> None:
    """No `relationship()` anywhere: async lazy-load raises `MissingGreenlet`."""
    from app.db.models import (
        BodyMeasurement,
        ExerciseMuscle,
        ExerciseMuscleOverride,
        ExerciseTemplate,
        SyncState,
    )

    for model in (
        BodyMeasurement,
        ExerciseMuscle,
        ExerciseMuscleOverride,
        ExerciseTemplate,
        SyncState,
    ):
        assert list(model.__mapper__.relationships) == [], model.__name__


def test_reference_tables_are_scoped_to_a_user() -> None:
    """T-03-15: `user_id` is NOT NULL and part of every unique key on this data."""
    for table_name in (
        "exercise_templates",
        "exercise_muscles",
        "exercise_muscle_overrides",
        "body_measurements",
        "sync_state",
    ):
        table = Base.metadata.tables[table_name]
        assert table.c.user_id.nullable is False, table_name
        foreign_key = next(iter(table.c.user_id.foreign_keys))
        assert foreign_key.ondelete == "CASCADE", table_name
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                assert "user_id" in [column.name for column in constraint.columns], table_name


def test_workout_timestamps_are_timezone_aware() -> None:
    """FOUND-04 extends to the workout tables: no bare ``DateTime()`` anywhere."""
    columns = Base.metadata.tables["workouts"].c
    for name in (
        "start_time",
        "end_time",
        "provider_created_at",
        "provider_updated_at",
        "created_at",
        "updated_at",
    ):
        assert columns[name].type.timezone is True, name
    # The session boundaries are the analytics anchor; they must not be optional.
    assert columns["start_time"].nullable is False
    assert columns["end_time"].nullable is False


def test_workout_unique_constraint_enables_upsert() -> None:
    """HEVY-03 is structural: ``ON CONFLICT`` needs this exact unique index.

    Without a matching unique constraint PostgreSQL raises "there is no unique or
    exclusion constraint matching the ON CONFLICT specification" and the idempotent
    upsert of Pattern 3 cannot be expressed at all.
    """
    table = Base.metadata.tables["workouts"]
    unique = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique["uq_workouts_user_provider_external_id"] == [
        "user_id",
        "provider",
        "external_id",
    ]


def test_workout_children_cascade_on_delete() -> None:
    """HEVY-04: deletion is atomic in the database, not ordered in Python."""
    exercise_fk = next(iter(Base.metadata.tables["workout_exercises"].c.workout_id.foreign_keys))
    assert exercise_fk.ondelete == "CASCADE"
    set_fk = next(iter(Base.metadata.tables["workout_sets"].c.workout_exercise_id.foreign_keys))
    assert set_fk.ondelete == "CASCADE"


def test_workout_children_have_no_timestamps() -> None:
    """Children are replaced wholesale on re-sync, so per-row timestamps would lie."""
    for table in ("workout_exercises", "workout_sets"):
        assert "created_at" not in Base.metadata.tables[table].c


def test_workout_weight_is_exact_decimal() -> None:
    """Float would make Phase 4 tonnage sums non-deterministic."""
    column = Base.metadata.tables["workout_sets"].c.weight_kg
    assert type(column.type).__name__ == "Numeric"
    assert (column.type.precision, column.type.scale) == (7, 3)


def test_timestamps_are_timezone_aware() -> None:
    """FOUND-04: UTC is enforced by the type system, not by convention."""
    columns = Base.metadata.tables["users"].c
    assert columns.created_at.type.timezone is True
    assert columns.updated_at.type.timezone is True
    assert columns.created_at.nullable is False
    assert columns.updated_at.nullable is False
    # The mixin is what supplies them.
    assert issubclass(User, TimestampMixin)


def test_user_timezone_default_is_jakarta() -> None:
    """D-02: the default timezone is a schema default, not an env var."""
    column = Base.metadata.tables["users"].c.timezone
    assert "Asia/Jakarta" in str(column.server_default.arg)
    assert column.type.length == 64
    assert column.nullable is False


def test_user_primary_key_is_uuid() -> None:
    column = Base.metadata.tables["users"].c.id
    assert column.primary_key is True
    assert column.type.python_type is uuid.UUID


def test_naming_convention_is_applied() -> None:
    """Stable constraint names keep autogenerated downgrades reversible."""
    assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    assert Base.metadata.tables["users"].primary_key.name == "pk_users"


def test_user_has_no_relationships() -> None:
    """D-07: a `connections` relationship would fail mapper configuration."""
    assert list(User.__mapper__.relationships) == []


def test_make_engine_is_async_and_safe() -> None:
    settings = Settings(
        database_url="postgresql://u:pw@localhost:5432/brett",  # type: ignore[arg-type]
    )
    engine = make_engine(settings)
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    # FOUND-05: echo=True would write bound parameter values to the log.
    assert engine.echo is False
    # `_pre_ping` is the only place the pool records this; there is no public
    # accessor. A dropped idle connection must reconnect, not raise.
    assert engine.pool._pre_ping is True
    assert make_sessionmaker(engine).kw["expire_on_commit"] is False

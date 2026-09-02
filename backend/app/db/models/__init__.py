"""Model registry.

Importing this package is what attaches every table to ``Base.metadata``.
``migrations/env.py`` imports it for exactly that reason: without the import,
``alembic revision --autogenerate`` sees empty metadata and emits an empty
migration with no error.

Every new model must be imported here.
"""

from app.db.models.body import BodyMeasurement
from app.db.models.exercise import ExerciseMuscle, ExerciseMuscleOverride, ExerciseTemplate
from app.db.models.health import HealthDailyMetric
from app.db.models.sync_state import SyncState
from app.db.models.user import User
from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet

__all__ = [
    "BodyMeasurement",
    "ExerciseMuscle",
    "ExerciseMuscleOverride",
    "ExerciseTemplate",
    "HealthDailyMetric",
    "SyncState",
    "User",
    "Workout",
    "WorkoutExercise",
    "WorkoutSet",
]

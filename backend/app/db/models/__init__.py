"""Model registry.

Importing this package is what attaches every table to ``Base.metadata``.
``migrations/env.py`` imports it for exactly that reason: without the import,
``alembic revision --autogenerate`` sees empty metadata and emits an empty
migration with no error.

Every new model must be imported here.
"""

from app.db.models.user import User

__all__ = ["User"]

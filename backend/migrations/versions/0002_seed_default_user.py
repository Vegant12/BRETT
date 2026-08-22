"""seed the single v1 default user (D-01, D-02)

D-01: the one v1 user arrives via a data migration, not app-startup
get-or-create logic and not a CLI command, so every later phase can assume the
row exists the moment migrations have run.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A FIXED UUID, not uuid4(). Later phases, fixtures and manual queries reference
# this constant, and re-running migrations on a fresh database yields an
# identical row rather than a new random identity each time.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# D-02: hardcoded, deliberately NOT read from the environment. A migration
# describes a fixed historical transition; making it env-coupled means two
# databases at the same revision can hold different data.
DEFAULT_TIMEZONE = "Asia/Jakarta"


def upgrade() -> None:
    # A lightweight `sa.table()` construct, NOT `app.db.models.User`. A revision
    # must describe the schema as of that revision; importing the live model
    # couples this file to whatever the model looks like today and breaks
    # replay once the model changes.
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("timezone", sa.String),
    )
    op.bulk_insert(users, [{"id": DEFAULT_USER_ID, "timezone": DEFAULT_TIMEZONE}])


def downgrade() -> None:
    # Bound parameter, never an f-string (T-01-14, Ruff S608).
    #
    # The bind MUST carry an explicit UUID type. Left untyped, SQLAlchemy infers
    # VARCHAR from the Python value and asyncpg emits `id = $1::VARCHAR`, which
    # Postgres rejects outright: `operator does not exist: uuid = character
    # varying`. Passing `str(...)` does not help -- the type, not the value, is
    # what asyncpg casts on.
    op.execute(
        sa.text("DELETE FROM users WHERE id = :uid").bindparams(
            sa.bindparam("uid", DEFAULT_USER_ID, type_=postgresql.UUID(as_uuid=True))
        )
    )

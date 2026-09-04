"""training programs: effective-dated history + a switch-confirmation token (GOAL-01, D-07, D-08)

Hand-written, not pure autogenerate: ``alembic revision --autogenerate`` does not reliably
emit ``postgresql_where`` partial indexes, so the "at most one open period per user"
invariant (``uq_user_program_history_one_open_period``) is declared by hand here and on the
model, kept in lockstep so ``alembic check`` sees no drift.

D-08's seed departs from ``0002_seed_default_user.py``'s literal ``op.bulk_insert`` idiom on
purpose: the seeded period's ``started_on`` is DERIVED from live synced Hevy history
(``MIN(workouts.start_time)``) rather than a Python literal, because a hardcoded date would be
correct on exactly the one database it was written against. See the ``upgrade()`` body for the
``LEFT JOIN`` + ``COALESCE`` fallback that keeps the seed non-empty even on a database migrated
before any workout has ever synced.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_program_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("program", sa.String(length=16), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_program_history_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_program_history")),
    )
    # PITFALLS #16 / D-07: "at most one open period per user" is a DATABASE invariant, not an
    # application convention. Hand-written -- autogenerate does not reliably emit
    # `postgresql_where`, so this index is declared identically on the model and here.
    op.create_index(
        "uq_user_program_history_one_open_period",
        "user_program_history",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_on IS NULL"),
    )
    op.create_index(
        "ix_user_program_history_user_id_started_on",
        "user_program_history",
        ["user_id", "started_on"],
        unique=False,
    )

    # D-08 seed. A raw INSERT ... SELECT, NOT op.bulk_insert -- the start date must come from
    # the database rather than a Python literal, or this migration would be correct on exactly
    # one database.
    #
    # LEFT JOIN + COALESCE resolves 12-RESEARCH.md Open Question 1 explicitly: an INNER JOIN
    # would insert ZERO rows on any database whose migrations run before the first Hevy sync
    # -- every CI container and every fresh dev database -- leaving `get_active_period` return
    # None for a user who does have a program. The fallback is `users.created_at` converted to
    # the user's own local day: deterministic (a stored value, not CURRENT_DATE), so replaying
    # migrations on the same database yields the same row every time.
    #
    # `gen_random_uuid()` is a PostgreSQL 13+ builtin; the test container is postgres:18-alpine
    # and production is Neon, so no pgcrypto extension is required.
    op.execute(
        sa.text(
            """
            INSERT INTO user_program_history (id, user_id, program, started_on, ended_on)
            SELECT gen_random_uuid(),
                   u.id,
                   'lean_bulk',
                   COALESCE(
                       (MIN(w.start_time) AT TIME ZONE u.timezone)::date,
                       (u.created_at AT TIME ZONE u.timezone)::date
                   ),
                   NULL
            FROM users u
            LEFT JOIN workouts w ON w.user_id = u.id
            GROUP BY u.id, u.timezone, u.created_at
            """
        )
    )

    op.create_table(
        "program_switch_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("from_period_id", sa.UUID(), nullable=False),
        sa.Column("to_program", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_program_switch_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_period_id"],
            ["user_program_history.id"],
            name=op.f("fk_program_switch_tokens_from_period_id_user_program_history"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_switch_tokens")),
        sa.UniqueConstraint("nonce", name=op.f("uq_program_switch_tokens_nonce")),
    )


def downgrade() -> None:
    # Exact reverse of `upgrade()`, FK-child table first. `test_migrations_round_trip` asserts
    # `downgrade base` leaves ONLY `alembic_version`, so anything left behind here fails the
    # suite.
    op.drop_table("program_switch_tokens")
    op.drop_index("ix_user_program_history_user_id_started_on", table_name="user_program_history")
    op.drop_index("uq_user_program_history_one_open_period", table_name="user_program_history")
    op.drop_table("user_program_history")

"""Engine and session factories.

Factories, not module-level singletons, on purpose: a module-level
``create_async_engine(...)`` binds its pool to whichever event loop imported it,
which breaks under pytest-asyncio and leaks connections between tests. The
caller (``lifespan``, a fixture, the CLI) owns the engine's lifetime.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for this process."""
    return create_async_engine(
        settings.async_database_url,
        # A spun-down or restarted managed Postgres silently kills idle
        # connections; without pre-ping the first query after an idle period
        # fails instead of transparently reconnecting.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # NEVER True: echo logs bound parameter VALUES, which would route health
        # data and credentials through the log pipeline (FOUND-05).
        echo=False,
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory bound to ``engine``.

    ``expire_on_commit=False`` keeps ORM objects usable after commit, which
    matters for request handlers that serialize a model after committing.
    """
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

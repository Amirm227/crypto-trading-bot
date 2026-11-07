"""Database engine and session lifecycle management.

Manages AsyncEngine connection pooling, transactional session boundaries,
and connection health checks for PostgreSQL (and local test runners).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from trading_bot.domain.config import AppConfig, DatabaseConfig
from trading_bot.persistence.exceptions import DatabaseConnectionError
from trading_bot.persistence.models import Base


class DatabaseManager:
    """Encapsulates AsyncEngine lifecycle, connection pooling, and session provisioning."""

    def __init__(
        self,
        database_url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
    ) -> None:
        self._url = database_url
        engine_kwargs: dict[str, Any] = {"echo": echo}

        if database_url.startswith("sqlite"):
            if ":memory:" in database_url:
                engine_kwargs["poolclass"] = StaticPool
                engine_kwargs["connect_args"] = {"check_same_thread": False}
            else:
                engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = pool_size
            engine_kwargs["max_overflow"] = max_overflow
            engine_kwargs["pool_pre_ping"] = True

        self._engine: AsyncEngine = create_async_engine(database_url, **engine_kwargs)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """Underlying SQLAlchemy AsyncEngine instance."""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Bound session maker instance."""
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Transactional async session context manager.

        Automatically commits on successful block exit, rolls back on error,
        and guarantees session cleanup.
        """
        async with self._session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def create_all(self) -> None:
        """Create all registered database tables (for local testing and bootstrap)."""
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to create database tables: {e}") from e

    async def drop_all(self) -> None:
        """Drop all registered database tables (for test fixture teardown)."""
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to drop database tables: {e}") from e

    async def ping(self) -> bool:
        """Execute a lightweight ping query (SELECT 1) to verify database connectivity."""
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                return bool(result.scalar() == 1)
        except Exception:
            return False

    async def close(self) -> None:
        """Dispose of the engine and terminate all pooled database connections."""
        await self._engine.dispose()


def create_database_manager(
    config: AppConfig | DatabaseConfig | str,
    password: str | None = None,
    echo: bool = False,
) -> DatabaseManager:
    """Factory creating a DatabaseManager from configuration or raw URL."""
    if isinstance(config, str):
        url = config
    elif isinstance(config, AppConfig):
        env_url = config.env_settings.database_url
        url = env_url or config.base.database.get_url(password=config.env_settings.db_password)
    elif isinstance(config, DatabaseConfig):
        url = config.get_url(password=password)
    else:
        raise ValueError(f"Unsupported configuration type: {type(config).__name__}")

    return DatabaseManager(database_url=url, echo=echo)

"""Database engine and session lifecycle management.

Manages AsyncEngine connection pooling, transactional session boundaries,
and connection health checks for PostgreSQL (and local test runners).
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from trading_bot.domain.config import AppConfig, DatabaseConfig
from trading_bot.persistence.exceptions import (
    DatabaseConnectionError,
    UnsafeDatabaseTargetError,
)
from trading_bot.persistence.models import Base

TEST_TOKEN_REGEX = re.compile(r"(^|[._\-])test([._\-]|$)", re.IGNORECASE)
PROD_TOKEN_REGEX = re.compile(r"(^|[._\-])(prod|production)([._\-]|$)", re.IGNORECASE)

DANGEROUS_TARGET_DATABASES: frozenset[str] = frozenset(
    {"trading_bot", "postgres", "production", "prod", "main", "master", "default"}
)


def validate_test_database_url(database_url: str) -> None:
    """Validate that a database URL is an explicitly isolated PostgreSQL test target.

    Enforces strict safety boundaries before running destructive integration tests:
    1. Driver must be PostgreSQL (e.g. 'postgresql+asyncpg'). Every non-PostgreSQL URL
       (including SQLite memory and file URLs) is rejected.
    2. Target database name must not match known default or production databases.
    3. Target database name must not contain 'prod' or 'production' tokens.
    4. Target database name must contain 'test' as a distinct delimited token (e.g.
       'trading_bot_test', 'test_db', 'ci-test-run'). Substring collisions such as
       'contest' or 'latest' are strictly rejected.
    """
    if not database_url or not database_url.strip():
        raise UnsafeDatabaseTargetError("Database URL for integration test cannot be empty.")

    try:
        url_obj = make_url(database_url)
    except Exception as e:
        raise UnsafeDatabaseTargetError(f"Malformed database URL: {e}") from e

    # 1. Reject every non-PostgreSQL URL (including SQLite)
    driver = url_obj.drivername.lower()
    if not (driver.startswith("postgresql") or driver.startswith("postgres")):
        raise UnsafeDatabaseTargetError(
            f"Unsafe database target for PostgreSQL integration tests: unsupported driver '{url_obj.drivername}'. "
            "Only PostgreSQL connection URLs (e.g., 'postgresql+asyncpg://...') are permitted."
        )

    db_name = url_obj.database
    if not db_name or not db_name.strip():
        raise UnsafeDatabaseTargetError(
            "Unsafe database target: database name is missing from connection URL."
        )

    db_lower = db_name.strip().lower()

    if db_lower in DANGEROUS_TARGET_DATABASES or PROD_TOKEN_REGEX.search(db_lower):
        raise UnsafeDatabaseTargetError(
            f"Unsafe database target for destructive integration tests: '{db_name}'. "
            f"Target database cannot be a production or default database ({sorted(DANGEROUS_TARGET_DATABASES)})."
        )

    # 2. Require 'test' as a distinct token (separated by '.', '_', '-', or string boundaries)
    if not TEST_TOKEN_REGEX.search(db_lower):
        raise UnsafeDatabaseTargetError(
            f"Unsafe database target for destructive integration tests: '{db_name}'. "
            "The database name must contain 'test' as a distinct token (e.g., 'trading_bot_test', 'test_db'). "
            "Names with substring collisions (such as 'contest' or 'latest') are rejected."
        )


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

    @property
    def safe_url(self) -> str:
        """Database connection URL with credentials safely masked."""
        return self._engine.url.render_as_string(hide_password=True)

    def __repr__(self) -> str:
        return f"DatabaseManager(url={self.safe_url!r})"


def create_database_manager(
    config: AppConfig | DatabaseConfig | str,
    password: str | None = None,
    echo: bool = False,
) -> DatabaseManager:
    """Factory creating a DatabaseManager from configuration or raw URL.

    Maintains strict deterministic precedence:
    1. Direct URL string parameter.
    2. AppConfig: DATABASE_URL environment setting (if specified and non-empty).
    3. AppConfig: DB_* environment variables overriding base.yaml database settings.
    4. DatabaseConfig: constructed via SQLAlchemy URL.create with explicit or configured password.
    """
    if isinstance(config, str):
        url = config
    elif isinstance(config, AppConfig):
        # 1. DATABASE_URL takes highest precedence if provided
        if config.env_settings.database_url and config.env_settings.database_url.strip():
            url = config.env_settings.database_url.strip()
        else:
            # 2. DB_* environment overrides combined with base.database
            host = config.env_settings.db_host or config.base.database.host
            port = config.env_settings.db_port or config.base.database.port
            name = config.env_settings.db_name or config.base.database.name
            user = config.env_settings.db_user or config.base.database.user
            pwd = password if password is not None else config.env_settings.db_password
            if pwd is None:
                pwd = config.base.database.password

            if pwd is None or not str(pwd).strip():
                raise ValueError(
                    "Database password is required to configure a PostgreSQL connection. "
                    "Please set DB_PASSWORD or DATABASE_URL in environment."
                )

            url_obj = URL.create(
                drivername="postgresql+asyncpg",
                username=user,
                password=pwd,
                host=host,
                port=port,
                database=name,
            )
            url = url_obj.render_as_string(hide_password=False)
    elif isinstance(config, DatabaseConfig):
        url = config.get_url(password=password)
    else:
        raise ValueError(f"Unsupported configuration type: {type(config).__name__}")

    return DatabaseManager(database_url=url, echo=echo)

"""Unit tests for DatabaseManager lifecycle, session transactions, and URL construction."""

from pathlib import Path

import pytest
from sqlalchemy import text

from trading_bot.domain.config import DatabaseConfig, load_app_config
from trading_bot.persistence.database import DatabaseManager, create_database_manager


@pytest.mark.asyncio
async def test_database_manager_sqlite_lifecycle() -> None:
    """Ensure DatabaseManager connects, pings, and disposes cleanly."""
    db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    try:
        assert await db.ping() is True
        await db.create_all()
        await db.drop_all()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_manager_session_commit() -> None:
    """Ensure session context manager commits changes on normal exit."""
    db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db.create_all()

    try:
        async with db.session() as s:
            await s.execute(text("CREATE TABLE test_table (id INT, val TEXT)"))
            await s.execute(text("INSERT INTO test_table VALUES (1, 'hello')"))

        async with db.session() as s:
            res = await s.execute(text("SELECT val FROM test_table WHERE id = 1"))
            assert res.scalar() == "hello"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_manager_session_rollback_on_error() -> None:
    """Ensure session context manager rolls back changes when an exception is raised."""
    db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db.create_all()

    try:
        async with db.session() as s:
            await s.execute(text("CREATE TABLE rollback_test (id INT, val TEXT)"))
            await s.execute(text("INSERT INTO rollback_test VALUES (1, 'committed')"))

        with pytest.raises(RuntimeError):
            async with db.session() as s:
                await s.execute(text("INSERT INTO rollback_test VALUES (2, 'uncommitted')"))
                raise RuntimeError("Trigger rollback")

        async with db.session() as s:
            res = await s.execute(text("SELECT count(*) FROM rollback_test"))
            assert res.scalar() == 1
    finally:
        await db.close()


def test_database_config_url_construction() -> None:
    """Ensure DatabaseConfig builds PostgreSQL asyncpg connection URLs accurately."""
    cfg = DatabaseConfig(
        host="db.internal",
        port=5433,
        name="trading_prod",
        user="bot_user",
        password="secret_password",
    )
    url = cfg.get_url()
    assert url == "postgresql+asyncpg://bot_user:secret_password@db.internal:5433/trading_prod"

    override_url = cfg.get_url(password="custom_override")
    assert (
        override_url
        == "postgresql+asyncpg://bot_user:custom_override@db.internal:5433/trading_prod"
    )


def test_create_database_manager_from_app_config(tmp_path: Path) -> None:
    """Ensure create_database_manager constructs manager from AppConfig."""
    app_cfg = load_app_config(config_dir="configs")
    db_mgr = create_database_manager(app_cfg)
    assert isinstance(db_mgr, DatabaseManager)
    assert "postgresql+asyncpg://" in db_mgr._url

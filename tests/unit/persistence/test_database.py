"""Unit tests for DatabaseManager lifecycle, session transactions, and URL construction."""

import pytest
from sqlalchemy import text

from trading_bot.domain.config import DatabaseConfig, EnvSettings, load_app_config
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


def test_missing_password_fails_clearly() -> None:
    """Ensure missing credentials fail fast when configuring a PostgreSQL connection."""
    cfg = DatabaseConfig(
        host="localhost",
        port=5432,
        name="trading_bot",
        user="postgres",
        password=None,
    )
    with pytest.raises(ValueError) as exc:
        cfg.get_url()
    assert "Database password is required" in str(exc.value)

    app_cfg = load_app_config(config_dir="configs")
    with pytest.raises(ValueError) as exc2:
        create_database_manager(app_cfg)
    assert "Database password is required" in str(exc2.value)


def test_special_characters_in_credentials() -> None:
    """Ensure special characters in usernames and passwords are safely escaped via URL.create."""
    cfg = DatabaseConfig(
        host="localhost",
        port=5432,
        name="trading_bot",
        user="bot_user@company",
        password="p@ss:w/ord#1?&=",
    )
    url = cfg.get_url()
    assert "bot_user%40company" in url
    assert "p%40ss%3Aw%2Ford%231%3F%26%3D" in url
    # Password should NOT appear unescaped with delimiter confusion
    assert "@company:p@ss" not in url


def test_url_precedence_in_create_database_manager() -> None:
    """Ensure deterministic precedence: DATABASE_URL > DB_* env vars > base.yaml."""
    app_cfg = load_app_config(config_dir="configs")

    # 1. When database_url is provided in env_settings, it takes top precedence
    app_cfg.env_settings.database_url = (
        "postgresql+asyncpg://env_user:env_pass@remote_host:5439/env_db"
    )
    app_cfg.env_settings.db_host = "ignored_host"
    db_mgr = create_database_manager(app_cfg)
    assert db_mgr._url == "postgresql+asyncpg://env_user:env_pass@remote_host:5439/env_db"

    # 2. When database_url is None, DB_* overrides take precedence over base.yaml
    app_cfg.env_settings.database_url = None
    app_cfg.env_settings.db_host = "custom_env_host"
    app_cfg.env_settings.db_port = 5433
    app_cfg.env_settings.db_user = "custom_env_user"
    app_cfg.env_settings.db_password = "env_secret_password"
    app_cfg.env_settings.db_name = "custom_env_db"

    db_mgr2 = create_database_manager(app_cfg)
    assert "custom_env_host:5433" in db_mgr2._url
    assert "custom_env_user" in db_mgr2._url
    assert "custom_env_db" in db_mgr2._url

    # 3. Explicit password override passed to create_database_manager takes precedence
    db_mgr3 = create_database_manager(app_cfg, password="override_pwd")
    assert "override_pwd" in db_mgr3._url


def test_password_never_exposed_in_repr_or_logs() -> None:
    """Ensure passwords and credentials are never leaked in representations or logs."""
    cfg = DatabaseConfig(
        host="localhost",
        port=5432,
        name="trading_bot",
        user="postgres",
        password="super_secret_password",
    )
    cfg_repr = repr(cfg)
    assert "super_secret_password" not in cfg_repr
    assert "password='***'" in cfg_repr

    env_settings = EnvSettings(
        db_password="super_secret_env_password",
        database_url="postgresql+asyncpg://user:secret@localhost:5432/db",
    )
    env_repr = repr(env_settings)
    assert "super_secret_env_password" not in env_repr
    assert "secret@" not in env_repr

    # DatabaseManager masking
    mgr = DatabaseManager("postgresql+asyncpg://user:my_secret@localhost:5432/trading_bot")
    assert "my_secret" not in mgr.safe_url
    assert "my_secret" not in repr(mgr)
    assert "***" in mgr.safe_url


def test_legitimate_test_database_without_password() -> None:
    """Legitimate test configurations (such as SQLite) must connect without password."""
    db_mgr = create_database_manager("sqlite+aiosqlite:///:memory:")
    assert isinstance(db_mgr, DatabaseManager)
    assert db_mgr._url == "sqlite+aiosqlite:///:memory:"

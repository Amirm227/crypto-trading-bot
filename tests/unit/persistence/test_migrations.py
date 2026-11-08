"""Unit tests for database migrations, Alembic environment, and schema alignment."""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, inspect

from trading_bot.persistence.database import DatabaseManager
from trading_bot.persistence.models import CandleModel


def test_alembic_offline_sql_generation() -> None:
    """Ensure Alembic generates valid PostgreSQL DDL offline without active database."""
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        "--sql",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Alembic offline failed: {proc.stderr}"
    sql_output = proc.stdout

    # Assert table creation and exact composite constraint
    assert "CREATE TABLE candles" in sql_output
    assert "uq_candles_series_open_time" in sql_output
    assert "UNIQUE (exchange, symbol, market_type, timeframe, open_time)" in sql_output

    # ix_candles_query was removed as redundant; ix_candles_latest must be present
    assert "CREATE INDEX ix_candles_query" not in sql_output
    assert "CREATE INDEX ix_candles_latest" in sql_output


def test_candle_model_schema_matches_migration_definition() -> None:
    """Ensure CandleModel SQLAlchemy table schema matches migration table definition."""
    table = cast(Table, CandleModel.__table__)
    column_names = {c.name for c in table.columns}

    expected_columns = {
        "id",
        "exchange",
        "symbol",
        "market_type",
        "timeframe",
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_closed",
        "ingested_at",
    }
    assert column_names == expected_columns

    # Check unique constraint
    unique_constraints = [
        c for c in table.constraints if hasattr(c, "columns") and len(c.columns) > 1
    ]
    uq_names = [c.name for c in unique_constraints]
    assert "uq_candles_series_open_time" in uq_names

    uq = next(c for c in unique_constraints if c.name == "uq_candles_series_open_time")
    uq_col_names = [col.name for col in uq.columns]
    assert uq_col_names == ["exchange", "symbol", "market_type", "timeframe", "open_time"]

    # Check indexes: ix_candles_query must NOT exist; ix_candles_latest MUST exist
    index_names = {idx.name for idx in table.indexes}
    assert "ix_candles_query" not in index_names
    assert "ix_candles_latest" in index_names


def test_migration_files_exist_and_versioned() -> None:
    """Ensure Alembic migration scripts and configuration exist in the repository."""
    assert Path("alembic.ini").exists()
    assert Path("migrations/env.py").exists()
    assert Path("migrations/script.py.mako").exists()
    assert Path("migrations/versions/0001_create_candles_table.py").exists()


@pytest.mark.asyncio
async def test_alembic_upgrade_and_downgrade_execution() -> None:
    """Exercise real Alembic upgrade and downgrade lifecycle, verifying schema and constraints."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_migration_exec.db"
        sqlite_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", sqlite_url)

        # 1. Upgrade to HEAD
        command.upgrade(alembic_cfg, "head")

        # 2. Verify schema created via actual Alembic migration
        db = DatabaseManager(sqlite_url)
        async with db.engine.connect() as conn:

            def _check_tables(sync_conn):  # type: ignore[no-untyped-def]
                inspector = inspect(sync_conn)
                tables = inspector.get_table_names()
                assert "candles" in tables
                assert "alembic_version" in tables

                indexes = inspector.get_indexes("candles")
                idx_names = {idx["name"] for idx in indexes}
                assert "ix_candles_latest" in idx_names
                assert "ix_candles_query" not in idx_names

            await conn.run_sync(_check_tables)

        await db.close()

        # 3. Downgrade to BASE
        command.downgrade(alembic_cfg, "base")

        # 4. Verify candles table removed cleanly
        db2 = DatabaseManager(sqlite_url)
        async with db2.engine.connect() as conn:

            def _check_downgrade(sync_conn):  # type: ignore[no-untyped-def]
                inspector = inspect(sync_conn)
                tables = inspector.get_table_names()
                assert "candles" not in tables

            await conn.run_sync(_check_downgrade)

        await db2.close()

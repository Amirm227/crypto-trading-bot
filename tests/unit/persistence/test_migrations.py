"""Unit tests for database migrations, Alembic environment, and schema alignment."""

import subprocess
import sys
from pathlib import Path
from typing import cast

from sqlalchemy import Table

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
    assert "CREATE INDEX ix_candles_query" in sql_output
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

    # Check indexes
    index_names = {idx.name for idx in table.indexes}
    assert "ix_candles_query" in index_names
    assert "ix_candles_latest" in index_names


def test_migration_files_exist_and_versioned() -> None:
    """Ensure Alembic migration scripts and configuration exist in the repository."""
    assert Path("alembic.ini").exists()
    assert Path("migrations/env.py").exists()
    assert Path("migrations/script.py.mako").exists()
    assert Path("migrations/versions/0001_create_candles_table.py").exists()

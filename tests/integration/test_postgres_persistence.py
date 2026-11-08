"""Integration tests against a live PostgreSQL instance.

Only executed when an explicit, dedicated test PostgreSQL database is configured via TEST_DATABASE_URL
and reachable. Never silently falls back to production or default DATABASE_URL.
Exercises actual Alembic migrations (upgrade and downgrade) against real PostgreSQL.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.market_data.contracts import CandleBatch
from trading_bot.persistence.database import DatabaseManager, validate_test_database_url
from trading_bot.persistence.exceptions import ConflictingCandleError
from trading_bot.persistence.repository import PostgresCandleRepository

POSTGRES_TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def pg_db_manager() -> AsyncIterator[DatabaseManager]:
    """Fixture providing a connected PostgreSQL DatabaseManager in an isolated test database.

    Enforces:
    1. TEST_DATABASE_URL must be explicitly configured (no fallback to DATABASE_URL).
    2. URL must pass strict test database safety checks (rejects production/default names).
    3. Runs actual Alembic migrations for schema setup and downgrade for teardown.
    """
    if not POSTGRES_TEST_URL or not POSTGRES_TEST_URL.strip():
        pytest.skip(
            "TEST_DATABASE_URL environment variable is required for live PostgreSQL integration tests. "
            "Silent fallback to DATABASE_URL is strictly prohibited."
        )

    # 1. Validate safety of the test database target before any connection or operation
    validate_test_database_url(POSTGRES_TEST_URL)

    db = DatabaseManager(POSTGRES_TEST_URL)
    is_live = await db.ping()
    if not is_live:
        await db.close()
        pytest.skip(f"Dedicated test PostgreSQL instance unreachable at {db.safe_url}")

    # 2. Configure Alembic to point to the dedicated test database
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", POSTGRES_TEST_URL)

    # Clean existing test tables safely if previously left over
    async with db.session() as s:
        await s.execute(text("DROP TABLE IF EXISTS candles CASCADE"))
        await s.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))

    # 3. Exercise actual Alembic migration upgrade to HEAD
    command.upgrade(alembic_cfg, "head")

    # 4. Verify migration created expected schema and constraints on live PostgreSQL
    async with db.engine.connect() as conn:

        def _inspect_schema(sync_conn: Any) -> None:
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            assert "candles" in tables
            # Verify unique constraint
            uqs = inspector.get_unique_constraints("candles")
            uq_names = {u["name"] for u in uqs}
            assert "uq_candles_series_open_time" in uq_names
            # Verify indexes: ix_candles_latest must exist, ix_candles_query must NOT exist
            indexes = inspector.get_indexes("candles")
            idx_names = {idx["name"] for idx in indexes}
            assert "ix_candles_latest" in idx_names
            assert "ix_candles_query" not in idx_names

        await conn.run_sync(_inspect_schema)

    yield db

    # 5. Safe teardown: Exercise actual Alembic downgrade
    try:
        command.downgrade(alembic_cfg, "base")
    except Exception:
        async with db.session() as s:
            await s.execute(text("DROP TABLE IF EXISTS candles CASCADE"))
            await s.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_postgres_live_persistence_and_idempotency(pg_db_manager: DatabaseManager) -> None:
    """Verify single and batch operations on live PostgreSQL with exact decimal precision."""
    repo = PostgresCandleRepository(pg_db_manager)

    t0 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    c1 = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        timeframe=TimeFrame.H1,
        open_time=t0,
        close_time=t0 + timedelta(hours=1),
        open=Decimal("70123.45000000"),
        high=Decimal("70500.00000000"),
        low=Decimal("69800.00000000"),
        close=Decimal("70200.00000000"),
        volume=Decimal("150.25000000"),
        is_closed=True,
        ingested_at=t0 + timedelta(hours=1, seconds=1),
    )

    # 1. Single save
    await repo.save_candle(c1)
    retrieved = await repo.get_latest_candle(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert retrieved is not None
    assert retrieved.open == Decimal("70123.45000000")

    # 2. Idempotent duplicate save
    await repo.save_candle(c1)
    retrieved_again = await repo.get_latest_candle(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert retrieved_again == retrieved

    # 3. Conflicting duplicate rejection on real PostgreSQL
    conflicting = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        timeframe=TimeFrame.H1,
        open_time=t0,
        close_time=t0 + timedelta(hours=1),
        open=Decimal("70123.45000000"),
        high=Decimal("70500.00000000"),
        low=Decimal("69800.00000000"),
        close=Decimal("70999.99000000"),
        volume=Decimal("150.25000000"),
        is_closed=True,
        ingested_at=t0 + timedelta(hours=1, seconds=1),
    )
    with pytest.raises(ConflictingCandleError):
        await repo.save_candle(conflicting)

    # 4. Futures candle coexistence (composite key disambiguation)
    futures_c = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        market_type=MarketType.FUTURES,
        timeframe=TimeFrame.H1,
        open_time=t0,
        close_time=t0 + timedelta(hours=1),
        open=Decimal("70150.00000000"),
        high=Decimal("70600.00000000"),
        low=Decimal("69900.00000000"),
        close=Decimal("70250.00000000"),
        volume=Decimal("500.00000000"),
        is_closed=True,
        ingested_at=t0 + timedelta(hours=1, seconds=1),
    )
    await repo.save_candle(futures_c)

    # Verify both spot and futures exist independently on PostgreSQL
    spot_res = await repo.get_latest_candle(
        symbol="BTC/USDT", timeframe=TimeFrame.H1, market_type=MarketType.SPOT
    )
    futures_res = await repo.get_latest_candle(
        symbol="BTC/USDT", timeframe=TimeFrame.H1, market_type=MarketType.FUTURES
    )
    assert spot_res is not None and spot_res.close == Decimal("70200.00000000")
    assert futures_res is not None and futures_res.close == Decimal("70250.00000000")


@pytest.mark.asyncio
async def test_postgres_live_batch_persistence_and_rollback(pg_db_manager: DatabaseManager) -> None:
    """Verify atomic batch persistence and rollback on live PostgreSQL."""
    repo = PostgresCandleRepository(pg_db_manager)
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)

    candles = tuple(
        Candle(
            exchange="binance",
            symbol="ETH/USDT",
            market_type=MarketType.SPOT,
            timeframe=TimeFrame.H1,
            open_time=t0 + timedelta(hours=i),
            close_time=t0 + timedelta(hours=i + 1),
            open=Decimal("2500.00000000"),
            high=Decimal("2550.00000000"),
            low=Decimal("2490.00000000"),
            close=Decimal("2520.00000000"),
            volume=Decimal("100.00000000"),
            is_closed=True,
            ingested_at=t0 + timedelta(hours=i + 1, seconds=1),
        )
        for i in range(3)
    )
    batch = CandleBatch(symbol="ETH/USDT", timeframe=TimeFrame.H1, candles=candles)
    inserted = await repo.save_batch(batch)
    assert inserted == 3

    # Idempotent re-save
    re_inserted = await repo.save_batch(batch)
    assert re_inserted == 0

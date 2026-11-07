"""Integration tests against a live PostgreSQL instance.

Only executed when a real PostgreSQL database is running and reachable.
Does not substitute SQLite or mocks for live PostgreSQL verification.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.persistence.database import DatabaseManager
from trading_bot.persistence.exceptions import ConflictingCandleError
from trading_bot.persistence.repository import PostgresCandleRepository

POSTGRES_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:placeholder_db_password@localhost:5432/trading_bot",
    ),
)


@pytest.fixture
async def pg_db_manager() -> AsyncIterator[DatabaseManager]:
    """Fixture providing a connected PostgreSQL DatabaseManager, or skipping if unreachable."""
    if not POSTGRES_TEST_URL.startswith("postgresql"):
        pytest.skip("POSTGRES_TEST_URL is not configured for PostgreSQL")

    db = DatabaseManager(POSTGRES_TEST_URL)
    is_live = await db.ping()
    if not is_live:
        await db.close()
        pytest.skip(f"Live PostgreSQL instance unreachable at {POSTGRES_TEST_URL}")

    # Reset tables for clean integration test
    async with db.session() as s:
        await s.execute(text("DROP TABLE IF EXISTS candles CASCADE"))
    await db.create_all()

    yield db

    async with db.session() as s:
        await s.execute(text("DROP TABLE IF EXISTS candles CASCADE"))
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
        close=Decimal("70999.99000000"),  # Conflicting price
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

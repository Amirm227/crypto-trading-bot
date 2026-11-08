"""Unit tests for PostgresCandleRepository operations, idempotency, and transaction safety."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.market_data.contracts import CandleBatch, OHLCVRequest
from trading_bot.persistence.database import DatabaseManager
from trading_bot.persistence.exceptions import (
    BatchHomogeneityError,
    CandleRepositoryError,
    ConflictingCandleError,
)
from trading_bot.persistence.repository import PostgresCandleRepository


def make_candle(
    symbol: str = "BTC/USDT",
    market_type: MarketType = MarketType.SPOT,
    timeframe: TimeFrame = TimeFrame.H1,
    open_time: datetime | None = None,
    open_price: Decimal = Decimal("70000.00"),
    high_price: Decimal = Decimal("70500.00"),
    low_price: Decimal = Decimal("69800.00"),
    close_price: Decimal = Decimal("70200.00"),
    volume: Decimal = Decimal("100.00"),
    is_closed: bool = True,
) -> Candle:
    """Helper to manufacture a test candle with consistent defaults."""
    op_time = open_time or datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    cl_time = op_time + timedelta(hours=1 if timeframe == TimeFrame.H1 else 4)
    return Candle(
        exchange="binance",
        symbol=symbol,
        market_type=market_type,
        timeframe=timeframe,
        open_time=op_time,
        close_time=cl_time,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        is_closed=is_closed,
        ingested_at=cl_time + timedelta(seconds=1),
    )


@pytest.fixture
async def repo() -> AsyncIterator[PostgresCandleRepository]:
    """Fixture providing a fresh in-memory database and repository."""
    db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    repository = PostgresCandleRepository(db)
    yield repository
    await db.drop_all()
    await db.close()


@pytest.mark.asyncio
async def test_save_single_candle_success(repo: PostgresCandleRepository) -> None:
    """Ensure a single candle is saved and retrieved with exact equality."""
    c = make_candle(open_price=Decimal("70123.45"))
    await repo.save_candle(c)

    latest = await repo.get_latest_candle(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert latest is not None
    assert latest == c
    assert latest.open == Decimal("70123.45")


@pytest.mark.asyncio
async def test_save_batch_success(repo: PostgresCandleRepository) -> None:
    """Ensure a batch of chronological candles persists and returns newly inserted count."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    candles = tuple(
        make_candle(
            open_time=t0 + timedelta(hours=i),
            high_price=Decimal("71000.00"),
            low_price=Decimal("69000.00"),
            close_price=Decimal(f"70{i:02d}0.00"),
        )
        for i in range(5)
    )
    batch = CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=candles)

    inserted = await repo.save_batch(batch)
    assert inserted == 5

    stored = await repo.get_candles(OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1))
    assert stored is not None
    assert stored.count == 5
    assert stored.candles == candles


@pytest.mark.asyncio
async def test_save_candle_identical_duplicate_idempotent(repo: PostgresCandleRepository) -> None:
    """Ensure identical single candle writes are idempotent without error or duplicates."""
    c = make_candle()
    await repo.save_candle(c)

    # Identical write must succeed silently
    await repo.save_candle(c)

    all_candles = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(all_candles) == 1


@pytest.mark.asyncio
async def test_save_batch_identical_duplicate_idempotent(repo: PostgresCandleRepository) -> None:
    """Ensure identical batch writes return 0 newly inserted records without creating duplicate rows."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    candles = tuple(make_candle(open_time=t0 + timedelta(hours=i)) for i in range(3))
    batch = CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=candles)

    first_run = await repo.save_batch(batch)
    assert first_run == 3

    second_run = await repo.save_batch(batch)
    assert second_run == 0

    all_candles = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(all_candles) == 3


@pytest.mark.asyncio
async def test_save_batch_partial_identical_duplicates(repo: PostgresCandleRepository) -> None:
    """Ensure partial overlap inserts only newly observed candles."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    c1 = make_candle(open_time=t0)
    c2 = make_candle(open_time=t0 + timedelta(hours=1))
    c3 = make_candle(open_time=t0 + timedelta(hours=2))
    c4 = make_candle(open_time=t0 + timedelta(hours=3))

    # Persist first two
    await repo.save_batch((c1, c2))

    # Save overlapping batch of 4 (c1, c2 identical, c3, c4 new)
    inserted = await repo.save_batch((c1, c2, c3, c4))
    assert inserted == 2

    all_candles = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(all_candles) == 4


@pytest.mark.asyncio
async def test_conflicting_single_candle_raises_error(repo: PostgresCandleRepository) -> None:
    """Ensure conflicting duplicate write is explicitly rejected and preserves historical value."""
    t0 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    original = make_candle(open_time=t0, close_price=Decimal("70200.00"))
    await repo.save_candle(original)

    # Conflicting close price for same composite key (within valid low/high bounds)
    conflicting = make_candle(open_time=t0, close_price=Decimal("70400.00"))
    with pytest.raises(ConflictingCandleError) as exc:
        await repo.save_candle(conflicting)

    assert "Conflicting candle data" in str(exc.value)

    # Ensure original persisted value was NOT modified
    latest = await repo.get_latest_candle(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert latest is not None
    assert latest.close == Decimal("70200.00")


@pytest.mark.asyncio
async def test_conflicting_batch_rolls_back_entire_transaction(
    repo: PostgresCandleRepository,
) -> None:
    """Ensure a conflicting candle in a batch rolls back the entire batch atomically."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    existing_c1 = make_candle(
        open_time=t0,
        high_price=Decimal("70500.00"),
        low_price=Decimal("69500.00"),
        close_price=Decimal("70000.00"),
    )
    await repo.save_candle(existing_c1)

    # Batch with:
    # 1. Conflicting c1 (close=70300.00 != 70000.00)
    # 2. Brand new c2
    # 3. Brand new c3
    conflicting_c1 = make_candle(
        open_time=t0,
        high_price=Decimal("70500.00"),
        low_price=Decimal("69500.00"),
        close_price=Decimal("70300.00"),
    )
    new_c2 = make_candle(open_time=t0 + timedelta(hours=1))
    new_c3 = make_candle(open_time=t0 + timedelta(hours=2))

    with pytest.raises(ConflictingCandleError):
        await repo.save_batch((conflicting_c1, new_c2, new_c3))

    # Atomic rollback verification: new_c2 and new_c3 MUST NOT be persisted
    all_candles = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(all_candles) == 1
    assert all_candles[0].close == Decimal("70000.00")


@pytest.mark.asyncio
async def test_conflicting_intra_batch_duplicates_raises_error(
    repo: PostgresCandleRepository,
) -> None:
    """Ensure conflicting duplicate candles inside the input batch are detected and rejected."""
    t0 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    c_a = make_candle(open_time=t0, close_price=Decimal("70100.00"))
    c_b = make_candle(open_time=t0, close_price=Decimal("70300.00"))

    with pytest.raises(ConflictingCandleError) as exc:
        await repo.save_batch((c_a, c_b))
    assert "Conflicting duplicate candles found within input batch" in str(exc.value)


@pytest.mark.asyncio
async def test_composite_key_prevents_spot_futures_collision(
    repo: PostgresCandleRepository,
) -> None:
    """Ensure spot and futures candles sharing symbol, timeframe, and timestamp do not collide."""
    t0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    spot_candle = make_candle(
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        open_time=t0,
        close_price=Decimal("70100.00"),
    )
    futures_candle = make_candle(
        symbol="BTC/USDT",
        market_type=MarketType.FUTURES,
        open_time=t0,
        close_price=Decimal("70150.00"),  # Basis spread
    )

    await repo.save_candle(spot_candle)
    await repo.save_candle(futures_candle)

    # Both must coexist cleanly
    spot_retrieved = await repo.get_latest_candle(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        market_type=MarketType.SPOT,
    )
    futures_retrieved = await repo.get_latest_candle(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        market_type=MarketType.FUTURES,
    )

    assert spot_retrieved is not None and spot_retrieved.close == Decimal("70100.00")
    assert futures_retrieved is not None and futures_retrieved.close == Decimal("70150.00")


@pytest.mark.asyncio
async def test_retrieval_filters_and_deterministic_ordering(repo: PostgresCandleRepository) -> None:
    """Ensure candle retrieval filters strictly and returns deterministic ascending ordering."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)

    # Insert out of order
    c3 = make_candle(open_time=t0 + timedelta(hours=2))
    c1 = make_candle(open_time=t0)
    c2 = make_candle(open_time=t0 + timedelta(hours=1))

    # Different symbol and different timeframe
    other_sym = make_candle(symbol="ETH/USDT", open_time=t0)
    other_tf = make_candle(symbol="BTC/USDT", timeframe=TimeFrame.H4, open_time=t0)

    await repo.save_batch((c3, c1, c2))
    await repo.save_candle(other_sym)
    await repo.save_candle(other_tf)

    # Query with since/until filter
    req = OHLCVRequest(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        since=t0 + timedelta(hours=1),
        until=t0 + timedelta(hours=2),
    )
    result = await repo.get_candles(req)
    assert result is not None
    assert result.count == 2
    assert result.candles[0].open_time == t0 + timedelta(hours=1)
    assert result.candles[1].open_time == t0 + timedelta(hours=2)


@pytest.mark.asyncio
async def test_latest_candle_retrieval(repo: PostgresCandleRepository) -> None:
    """Ensure get_latest_candle respects closed_only and deterministic ordering."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)

    c1 = make_candle(open_time=t0, is_closed=True)
    c2 = make_candle(open_time=t0 + timedelta(hours=1), is_closed=True)
    c3_open = make_candle(open_time=t0 + timedelta(hours=2), is_closed=False)

    await repo.save_batch((c1, c2, c3_open))

    # Closed only query should return c2
    latest_closed = await repo.get_latest_candle(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        closed_only=True,
    )
    assert latest_closed is not None
    assert latest_closed.open_time == t0 + timedelta(hours=1)

    # Any candle query should return c3_open
    latest_any = await repo.get_latest_candle(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        closed_only=False,
    )
    assert latest_any is not None
    assert latest_any.open_time == t0 + timedelta(hours=2)
    assert latest_any.is_closed is False


@pytest.mark.asyncio
async def test_find_gaps_in_series(repo: PostgresCandleRepository) -> None:
    """Ensure find_gaps identifies missing hourly time segments."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    # Candle at 0h and 2h (gap at 1h)
    c0 = make_candle(open_time=t0)
    c2 = make_candle(open_time=t0 + timedelta(hours=2))
    await repo.save_batch((c0, c2))

    gaps = await repo.find_gaps(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        start=t0,
        end=t0 + timedelta(hours=3),
    )
    # Expected gap between 1h and 2h
    assert len(gaps) == 1
    assert gaps[0] == (t0 + timedelta(hours=1), t0 + timedelta(hours=2))


@pytest.mark.asyncio
async def test_repository_error_handling() -> None:
    """Ensure database errors propagate as CandleRepositoryError."""
    # Closed manager will cause operational error
    db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db.close()
    repo = PostgresCandleRepository(db)

    with pytest.raises(CandleRepositoryError):
        await repo.save_candle(make_candle())


@pytest.mark.asyncio
async def test_save_batch_rejects_mixed_series(repo: PostgresCandleRepository) -> None:
    """Ensure save_batch explicitly rejects batches containing mixed series with BatchHomogeneityError."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)

    # 1. Mixed symbols
    c_btc = make_candle(symbol="BTC/USDT", open_time=t0)
    c_eth = make_candle(symbol="ETH/USDT", open_time=t0 + timedelta(hours=1))
    with pytest.raises(BatchHomogeneityError) as exc_sym:
        await repo.save_batch((c_btc, c_eth))
    assert "Batch homogeneity violation" in str(exc_sym.value)
    assert "ETH/USDT" in str(exc_sym.value)

    # 2. Mixed market types (Spot vs Futures)
    c_spot = make_candle(market_type=MarketType.SPOT, open_time=t0)
    c_futures = make_candle(market_type=MarketType.FUTURES, open_time=t0 + timedelta(hours=1))
    with pytest.raises(BatchHomogeneityError) as exc_mkt:
        await repo.save_batch((c_spot, c_futures))
    assert "Batch homogeneity violation" in str(exc_mkt.value)

    # 3. Mixed timeframes (1H vs 4H)
    c_1h = make_candle(timeframe=TimeFrame.H1, open_time=t0)
    c_4h = make_candle(timeframe=TimeFrame.H4, open_time=t0 + timedelta(hours=4))
    with pytest.raises(BatchHomogeneityError) as exc_tf:
        await repo.save_batch((c_1h, c_4h))
    assert "Batch homogeneity violation" in str(exc_tf.value)

    # 4. Mixed exchanges
    c_binance = make_candle(open_time=t0)
    c_coinbase = Candle(
        exchange="coinbase",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        timeframe=TimeFrame.H1,
        open_time=t0 + timedelta(hours=1),
        close_time=t0 + timedelta(hours=2),
        open=Decimal("70000.00"),
        high=Decimal("70500.00"),
        low=Decimal("69800.00"),
        close=Decimal("70200.00"),
        volume=Decimal("100.00"),
        is_closed=True,
        ingested_at=t0 + timedelta(hours=2, seconds=1),
    )
    with pytest.raises(BatchHomogeneityError) as exc_ex:
        await repo.save_batch((c_binance, c_coinbase))
    assert "Batch homogeneity violation" in str(exc_ex.value)


@pytest.mark.asyncio
async def test_save_batch_intra_batch_identical_duplicates_deduplicated(
    repo: PostgresCandleRepository,
) -> None:
    """Ensure identical duplicates within a batch are deduplicated deterministically and persisted."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    c1 = make_candle(open_time=t0)
    c1_dup = make_candle(open_time=t0)  # Identical duplicate in the same batch
    c2 = make_candle(open_time=t0 + timedelta(hours=1))

    inserted = await repo.save_batch((c1, c1_dup, c2))
    assert inserted == 2

    stored = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(stored) == 2


@pytest.mark.asyncio
async def test_concurrent_identical_duplicate_insertion(repo: PostgresCandleRepository) -> None:
    """Ensure concurrent identical insertions are idempotent and do not fail with unhandled integrity error."""
    t0 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    c = make_candle(open_time=t0)

    # Execute concurrent save operations simultaneously
    results = await asyncio.gather(
        repo.save_candle(c),
        repo.save_candle(c),
        repo.save_candle(c),
        return_exceptions=True,
    )

    # All concurrent attempts must succeed without exception
    for r in results:
        assert r is None

    stored = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_concurrent_conflicting_insertion_rejected(repo: PostgresCandleRepository) -> None:
    """Ensure concurrent conflicting writes safely reject the conflict without corrupting data."""
    t0 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    original = make_candle(open_time=t0, close_price=Decimal("70100.00"))
    conflicting = make_candle(open_time=t0, close_price=Decimal("70300.00"))

    # Execute concurrent save with conflicting payloads
    results = await asyncio.gather(
        repo.save_candle(original),
        repo.save_candle(conflicting),
        return_exceptions=True,
    )

    # Exactly one must succeed (None) and one must raise ConflictingCandleError
    exceptions = [r for r in results if isinstance(r, Exception)]
    successes = [r for r in results if r is None]

    assert len(successes) == 1
    assert len(exceptions) == 1
    assert isinstance(exceptions[0], ConflictingCandleError)


@pytest.mark.asyncio
async def test_concurrent_batch_insertion_idempotent(repo: PostgresCandleRepository) -> None:
    """Ensure concurrent batch insertions are idempotent and do not fail with unhandled errors."""
    t0 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    batch = tuple(make_candle(open_time=t0 + timedelta(hours=i)) for i in range(5))

    results = await asyncio.gather(
        repo.save_batch(batch),
        repo.save_batch(batch),
        return_exceptions=True,
    )

    for r in results:
        assert isinstance(r, int)

    stored = await repo.get_candles_by_range(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert len(stored) == 5

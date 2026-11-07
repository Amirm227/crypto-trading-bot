"""Unit tests for Market Data contracts, CandleBatch invariants, and Exchange contracts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.exchanges.contracts import (
    CapabilityStatus,
    ExchangeCapabilities,
    MarketMetadata,
)
from trading_bot.market_data.contracts import (
    SUPPORTED_FUTURES_SYMBOLS,
    SUPPORTED_SPOT_SYMBOLS,
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    CandleBatch,
    CandleRepository,
    DataQualityCheckResult,
    MarketDataFeed,
    OHLCVRequest,
    RawCandle,
)


def make_valid_candle(
    open_time: datetime,
    symbol: str = "BTC/USDT",
    timeframe: TimeFrame = TimeFrame.H1,
    is_closed: bool = True,
    close_price: Decimal = Decimal("70000"),
) -> Candle:
    """Helper to create a validated test Candle."""
    duration = timedelta(hours=1 if timeframe == TimeFrame.H1 else 4)
    close_time = open_time + duration
    return Candle(
        exchange="binance",
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=Decimal("69500"),
        high=Decimal("70500"),
        low=Decimal("69000"),
        close=close_price,
        volume=Decimal("100"),
        is_closed=is_closed,
        ingested_at=close_time,
    )


def test_supported_constants() -> None:
    """Ensure supported asset and timeframe constants match specification for spot and futures."""
    for spot_sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        assert spot_sym in SUPPORTED_SPOT_SYMBOLS
        assert spot_sym in SUPPORTED_SYMBOLS

    for fut_sym in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"):
        assert fut_sym in SUPPORTED_FUTURES_SYMBOLS
        assert fut_sym in SUPPORTED_SYMBOLS

    assert TimeFrame.H1 in SUPPORTED_TIMEFRAMES
    assert TimeFrame.H4 in SUPPORTED_TIMEFRAMES


def test_ohlcv_request_valid_futures() -> None:
    """Ensure OHLCVRequest accepts linear perpetual futures symbols."""
    req = OHLCVRequest(symbol="BTC/USDT:USDT", timeframe=TimeFrame.H1)
    assert req.symbol == "BTC/USDT:USDT"
    assert req.timeframe == TimeFrame.H1


def test_ohlcv_request_valid() -> None:
    """Ensure OHLCVRequest accepts supported symbol, timeframe, and valid time bounds."""
    t1 = datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    req = OHLCVRequest(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        since=t1,
        until=t2,
        limit=500,
    )
    assert req.symbol == "BTC/USDT"
    assert req.timeframe == TimeFrame.H1
    assert req.limit == 500


def test_ohlcv_request_rejects_unsupported_symbols() -> None:
    """Ensure unsupported assets raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        OHLCVRequest(symbol="XRP/USDT", timeframe=TimeFrame.H1)
    assert "Unsupported symbol" in str(exc.value)


def test_ohlcv_request_rejects_unsupported_timeframes() -> None:
    """Ensure timeframes outside 1H and 4H raise ValidationError."""
    with pytest.raises(ValidationError) as exc:
        OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.M15)
    assert "Unsupported timeframe" in str(exc.value)


def test_ohlcv_request_rejects_inverted_time_range() -> None:
    """Ensure since >= until raises ValidationError."""
    t1 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    with pytest.raises(ValidationError) as exc:
        OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1, since=t1, until=t2)
    assert "strictly earlier than until" in str(exc.value)


def test_raw_candle_conversion_to_domain_candle() -> None:
    """Ensure RawCandle converts cleanly into a domain Candle with calculated close time."""
    # 2026-11-07 10:00:00 UTC = 1794045600000 ms
    dt = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    ts_ms = int(dt.timestamp() * 1000)

    raw = RawCandle(
        timestamp_ms=ts_ms,
        open=Decimal("70000"),
        high=Decimal("71000"),
        low=Decimal("69500"),
        close=Decimal("70500"),
        volume=Decimal("150.5"),
        is_closed=True,
    )
    candle_1h = raw.to_candle(exchange="binance", symbol="BTC/USDT", timeframe=TimeFrame.H1)
    assert candle_1h.open_time == dt
    assert candle_1h.close_time == dt + timedelta(hours=1)
    assert candle_1h.open == Decimal("70000")
    assert isinstance(candle_1h.close, Decimal)

    # 4H timeframe duration test
    candle_4h = raw.to_candle(exchange="binance", symbol="BTC/USDT", timeframe=TimeFrame.H4)
    assert candle_4h.close_time == dt + timedelta(hours=4)


def test_candle_batch_valid_and_closed_filtering() -> None:
    """Ensure CandleBatch validates chronology and correctly filters closed vs open candles."""
    t0 = datetime(2026, 11, 7, 8, 0, tzinfo=UTC)
    c1 = make_valid_candle(t0, is_closed=True)
    c2 = make_valid_candle(t0 + timedelta(hours=1), is_closed=True)
    c3 = make_valid_candle(t0 + timedelta(hours=2), is_closed=False)  # open trailing candle

    batch = CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=(c1, c2, c3))
    assert batch.count == 3
    assert batch.has_incomplete is True
    assert len(batch.closed_candles) == 2
    assert batch.latest_closed_candle == c2
    assert batch.start_time == t0
    assert batch.end_time == c3.close_time


def test_candle_batch_rejects_empty_candles() -> None:
    """Ensure CandleBatch cannot be empty."""
    with pytest.raises(ValidationError) as exc:
        CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=())
    assert "CandleBatch cannot be empty" in str(exc.value)


def test_candle_batch_rejects_mismatched_symbol_or_timeframe() -> None:
    """Ensure all candles in a batch must match batch symbol and timeframe."""
    t0 = datetime(2026, 11, 7, 8, 0, tzinfo=UTC)
    c1 = make_valid_candle(t0, symbol="BTC/USDT")
    c2 = make_valid_candle(t0 + timedelta(hours=1), symbol="ETH/USDT")

    # Mismatched symbol
    with pytest.raises(ValidationError) as exc1:
        CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=(c1, c2))
    assert "expected 'BTC/USDT'" in str(exc1.value)

    # Mismatched timeframe
    c3 = make_valid_candle(t0 + timedelta(hours=1), symbol="BTC/USDT", timeframe=TimeFrame.H4)
    with pytest.raises(ValidationError) as exc2:
        CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=(c1, c3))
    assert "expected '1h'" in str(exc2.value)


def test_candle_batch_rejects_non_ascending_timestamps() -> None:
    """Ensure non-chronological or duplicate timestamps are rejected."""
    t0 = datetime(2026, 11, 7, 8, 0, tzinfo=UTC)
    c1 = make_valid_candle(t0)
    c2 = make_valid_candle(t0)  # duplicate timestamp

    with pytest.raises(ValidationError) as exc:
        CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=(c1, c2))
    assert "strictly ascending order" in str(exc.value)


def test_candle_batch_rejects_incomplete_candle_in_middle() -> None:
    """Ensure an unclosed candle is prohibited anywhere except the trailing position."""
    t0 = datetime(2026, 11, 7, 8, 0, tzinfo=UTC)
    c1 = make_valid_candle(t0, is_closed=False)  # open candle in middle
    c2 = make_valid_candle(t0 + timedelta(hours=1), is_closed=True)

    with pytest.raises(ValidationError) as exc:
        CandleBatch(symbol="BTC/USDT", timeframe=TimeFrame.H1, candles=(c1, c2))
    assert "Only the trailing candle is permitted to be unclosed" in str(exc.value)


def test_data_quality_check_result() -> None:
    """Ensure DataQualityCheckResult instantiates and reports validity."""
    res = DataQualityCheckResult(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        total_candles=100,
        closed_candles=99,
        incomplete_candles=1,
        is_valid=True,
    )
    assert res.is_valid is True
    assert res.total_candles == 100


def test_exchange_capabilities_status_safety() -> None:
    """Ensure CapabilityStatus.is_safe_to_execute treats UNKNOWN and UNSUPPORTED as unsafe."""
    assert CapabilityStatus.SUPPORTED.is_safe_to_execute is True
    assert CapabilityStatus.UNSUPPORTED.is_safe_to_execute is False
    assert CapabilityStatus.UNKNOWN.is_safe_to_execute is False

    caps = ExchangeCapabilities()
    assert caps.isolated_margin == CapabilityStatus.SUPPORTED
    assert caps.cross_margin == CapabilityStatus.UNSUPPORTED


def test_market_metadata() -> None:
    """Ensure MarketMetadata holds Decimal lot sizes and precisions."""
    meta = MarketMetadata(
        symbol="BTC/USDT",
        base_asset="BTC",
        quote_asset="USDT",
        market_type=MarketType.SPOT,
        price_precision=2,
        quantity_precision=5,
        min_notional=Decimal("5.0"),
        min_quantity=Decimal("0.00001"),
        step_size=Decimal("0.00001"),
        tick_size=Decimal("0.01"),
        contract_size=Decimal("1.0"),
    )
    assert meta.min_notional == Decimal("5.0")
    assert meta.step_size == Decimal("0.00001")


def test_protocols_satisfiable_by_mock() -> None:
    """Ensure MarketDataFeed, CandleRepository, and MarketDataService protocols can be satisfied."""

    class MockFeed:
        async def fetch_ohlcv(self, request: OHLCVRequest) -> CandleBatch:
            c = make_valid_candle(datetime.now(UTC), symbol=request.symbol, timeframe=request.timeframe)
            return CandleBatch(symbol=request.symbol, timeframe=request.timeframe, candles=(c,))

        async def get_server_time(self) -> datetime:
            return datetime.now(UTC)

    feed: MarketDataFeed = MockFeed()
    assert isinstance(feed, MarketDataFeed)

    class MockRepo:
        async def save_candle(self, candle: Candle) -> None:
            pass

        async def save_batch(self, batch: CandleBatch) -> int:
            return batch.count

        async def get_latest_candle(
            self, symbol: str, timeframe: TimeFrame, closed_only: bool = True
        ) -> Candle | None:
            return None

        async def get_candles(self, request: OHLCVRequest) -> CandleBatch | None:
            return None

        async def find_gaps(
            self, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime
        ) -> tuple[tuple[datetime, datetime], ...]:
            return ()

    repo: CandleRepository = MockRepo()
    assert isinstance(repo, CandleRepository)

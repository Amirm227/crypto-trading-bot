"""Unit tests for CandleModel mapping, UTC timestamp handling, and numeric precision."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.persistence.models import CandleModel


def create_sample_candle(
    symbol: str = "BTC/USDT",
    market_type: MarketType = MarketType.SPOT,
    open_time: datetime | None = None,
    open_price: Decimal = Decimal("70000.00"),
    high_price: Decimal = Decimal("70500.00"),
    low_price: Decimal = Decimal("69800.00"),
    close_price: Decimal = Decimal("70200.00"),
    volume: Decimal = Decimal("150.25000000"),
    is_closed: bool = True,
) -> Candle:
    """Helper to create a validated domain Candle."""
    op_time = open_time or datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    cl_time = op_time + timedelta(hours=1)
    ingest_time = cl_time + timedelta(seconds=1)
    return Candle(
        exchange="binance",
        symbol=symbol,
        market_type=market_type,
        timeframe=TimeFrame.H1,
        open_time=op_time,
        close_time=cl_time,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        is_closed=is_closed,
        ingested_at=ingest_time,
    )


def test_candle_model_roundtrip_mapping() -> None:
    """Ensure Candle domain model maps cleanly to CandleModel and back without loss."""
    domain_candle = create_sample_candle(
        symbol="BTC/USDT:USDT",
        market_type=MarketType.FUTURES,
    )

    model = CandleModel.from_domain(domain_candle)
    assert model.exchange == "binance"
    assert model.symbol == "BTC/USDT:USDT"
    assert model.market_type == "futures"
    assert model.timeframe == "1h"
    assert model.open == Decimal("70000.00")
    assert model.high == Decimal("70500.00")
    assert model.low == Decimal("69800.00")
    assert model.close == Decimal("70200.00")
    assert model.volume == Decimal("150.25000000")
    assert model.is_closed is True

    recovered = model.to_domain()
    assert recovered == domain_candle
    assert recovered.market_type == MarketType.FUTURES
    assert isinstance(recovered.open, Decimal)
    assert recovered.open_time.tzinfo == UTC


def test_utc_timestamp_handling() -> None:
    """Ensure timestamps maintain UTC timezone awareness at the mapping boundary."""
    t0 = datetime(2026, 11, 7, 14, 30, tzinfo=UTC)
    candle = create_sample_candle(open_time=t0)
    model = CandleModel.from_domain(candle)

    assert model.open_time.tzinfo == UTC
    assert model.close_time.tzinfo == UTC
    assert model.ingested_at.tzinfo == UTC

    recovered = model.to_domain()
    assert recovered.open_time.tzinfo == UTC
    assert recovered.open_time == t0


def test_exact_numeric_precision() -> None:
    """Ensure exact fractional precisions are preserved without binary float conversion."""
    micro_price = Decimal("0.00000001")
    high_precision_volume = Decimal("1234567.89012345")

    candle = create_sample_candle(
        open_price=micro_price,
        high_price=Decimal("0.00000002"),
        low_price=micro_price,
        close_price=Decimal("0.00000002"),
        volume=high_precision_volume,
    )
    model = CandleModel.from_domain(candle)

    assert model.open == Decimal("0.00000001")
    assert model.volume == Decimal("1234567.89012345")
    assert not isinstance(model.open, float)

    recovered = model.to_domain()
    assert recovered.open == micro_price
    assert recovered.volume == high_precision_volume


def test_is_identical_matching() -> None:
    """Ensure is_identical strictly compares all payload attributes."""
    c1 = create_sample_candle()
    model = CandleModel.from_domain(c1)

    assert model.is_identical(c1) is True

    # Differing close price
    c_diff_price = create_sample_candle(close_price=Decimal("70201.00"))
    assert model.is_identical(c_diff_price) is False

    # Differing volume
    c_diff_vol = create_sample_candle(volume=Decimal("999.00"))
    assert model.is_identical(c_diff_vol) is False

    # Differing is_closed
    c_diff_closed = create_sample_candle(is_closed=False)
    assert model.is_identical(c_diff_closed) is False

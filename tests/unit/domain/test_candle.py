"""Unit tests for Candle domain model validation and serialization."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import TimeFrame


def create_valid_candle() -> Candle:
    """Helper creating a standard valid 1H candle."""
    open_time = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    close_time = open_time + timedelta(hours=1)
    ingested_at = close_time + timedelta(seconds=2)
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=TimeFrame.H1,
        open_time=open_time,
        close_time=close_time,
        open=Decimal("70000.00"),
        high=Decimal("70500.00"),
        low=Decimal("69800.00"),
        close=Decimal("70200.00"),
        volume=Decimal("150.25"),
        is_closed=True,
        ingested_at=ingested_at,
    )


def test_valid_candle_creation() -> None:
    """Ensure a correctly formatted candle initializes properly."""
    c = create_valid_candle()
    assert c.exchange == "binance"
    assert c.symbol == "BTC/USDT"
    assert c.open == Decimal("70000.00")
    assert c.high == Decimal("70500.00")
    assert c.low == Decimal("69800.00")
    assert c.close == Decimal("70200.00")
    assert c.volume == Decimal("150.25")
    assert c.is_closed is True


def test_candle_rejects_inverted_time() -> None:
    """Ensure open_time >= close_time raises ValidationError."""
    open_time = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    close_time = open_time - timedelta(hours=1)
    with pytest.raises(ValidationError) as exc:
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=TimeFrame.H1,
            open_time=open_time,
            close_time=close_time,
            open=Decimal("70000"),
            high=Decimal("70500"),
            low=Decimal("69800"),
            close=Decimal("70200"),
            volume=Decimal("100"),
            is_closed=True,
            ingested_at=open_time,
        )
    assert "earlier than close_time" in str(exc.value)


def test_candle_rejects_invalid_high_low_bounds() -> None:
    """Ensure candle prices must obey low <= open/close <= high."""
    t1 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)

    # open higher than high
    with pytest.raises(ValidationError) as exc1:
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=TimeFrame.H1,
            open_time=t1,
            close_time=t2,
            open=Decimal("71000"),
            high=Decimal("70000"),
            low=Decimal("69000"),
            close=Decimal("69500"),
            volume=Decimal("10"),
            is_closed=True,
            ingested_at=t2,
        )
    assert "open (71000) must be between low" in str(exc1.value)

    # close lower than low
    with pytest.raises(ValidationError) as exc2:
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=TimeFrame.H1,
            open_time=t1,
            close_time=t2,
            open=Decimal("70000"),
            high=Decimal("70500"),
            low=Decimal("69500"),
            close=Decimal("69000"),
            volume=Decimal("10"),
            is_closed=True,
            ingested_at=t2,
        )
    assert "close (69000) must be between low" in str(exc2.value)


def test_candle_rejects_negative_prices_and_volume() -> None:
    """Ensure non-positive prices and negative volumes are rejected."""
    t1 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)

    # Zero or negative price
    with pytest.raises(ValidationError):
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=TimeFrame.H1,
            open_time=t1,
            close_time=t2,
            open=Decimal("0"),
            high=Decimal("100"),
            low=Decimal("0"),
            close=Decimal("50"),
            volume=Decimal("10"),
            is_closed=True,
            ingested_at=t2,
        )

    # Negative volume
    with pytest.raises(ValidationError):
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=TimeFrame.H1,
            open_time=t1,
            close_time=t2,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("-1"),
            is_closed=True,
            ingested_at=t2,
        )


def test_candle_json_roundtrip_preserves_decimal_precision() -> None:
    """Ensure JSON serialization and deserialization retains exact Decimal representations."""
    c = create_valid_candle()
    json_data = c.model_dump_json()
    assert '"70000.00"' in json_data
    c_recovered = Candle.model_validate_json(json_data)
    assert c_recovered == c
    assert isinstance(c_recovered.open, Decimal)

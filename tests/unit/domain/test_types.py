"""Unit tests for domain primitive types, custom validators, and base model immutability."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.types import (
    DomainModel,
    EventSeverity,
    FinancialDecimal,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    RegimeType,
    SignalStatus,
    TimeFrame,
    UTCDateTime,
)


class DummyModel(DomainModel):
    """Test model inheriting from DomainModel."""

    price: FinancialDecimal
    timestamp: UTCDateTime


def test_financial_decimal_accepts_valid_inputs() -> None:
    """Ensure FinancialDecimal accepts Decimal, int, and numeric str via model validation."""
    now = datetime.now(UTC)
    m1 = DummyModel(price=Decimal("123.45"), timestamp=now)
    assert m1.price == Decimal("123.45")
    assert isinstance(m1.price, Decimal)

    m2 = DummyModel.model_validate({"price": "678.90", "timestamp": now})
    assert m2.price == Decimal("678.90")

    m3 = DummyModel.model_validate({"price": 100, "timestamp": now})
    assert m3.price == Decimal("100")


def test_financial_decimal_strictly_rejects_floats() -> None:
    """Ensure binary floats are rejected with TypeError/ValidationError."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        DummyModel.model_validate({"price": 123.45, "timestamp": now})
    assert "Binary floats are strictly prohibited" in str(exc.value)


def test_financial_decimal_rejects_nan_and_infinities() -> None:
    """Ensure NaN, Infinity, and invalid string inputs are rejected."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        DummyModel(price=Decimal("NaN"), timestamp=now)
    with pytest.raises(ValidationError):
        DummyModel(price=Decimal("Infinity"), timestamp=now)
    with pytest.raises(ValidationError):
        DummyModel.model_validate({"price": "not_a_number", "timestamp": now})


def test_utc_datetime_enforces_timezone_aware_utc() -> None:
    """Ensure UTC timezone-aware datetimes are enforced."""
    utc_now = datetime.now(UTC)
    m = DummyModel(price=Decimal("100"), timestamp=utc_now)
    assert m.timestamp == utc_now

    # ISO string with UTC 'Z' or '+00:00'
    m2 = DummyModel.model_validate({"price": Decimal("100"), "timestamp": "2026-11-07T12:00:00Z"})
    assert m2.timestamp.tzinfo == UTC


def test_utc_datetime_rejects_naive_and_non_utc() -> None:
    """Ensure naive datetimes and non-UTC offsets are rejected."""
    # Naive datetime
    naive_dt = datetime(2026, 11, 7, 12, 0, 0)
    with pytest.raises(ValidationError) as exc1:
        DummyModel(price=Decimal("100"), timestamp=naive_dt)
    assert "Naive datetime is prohibited" in str(exc1.value)

    # Non-UTC timezone offset
    non_utc_dt = datetime.now(timezone(timedelta(hours=3)))
    with pytest.raises(ValidationError) as exc2:
        DummyModel(price=Decimal("100"), timestamp=non_utc_dt)
    assert "Non-UTC timezone is prohibited" in str(exc2.value)


def test_domain_model_immutability() -> None:
    """Ensure DomainModel instances cannot be modified after construction."""
    now = datetime.now(UTC)
    m = DummyModel(price=Decimal("100"), timestamp=now)
    with pytest.raises(ValidationError):
        m.price = Decimal("200")


def test_domain_model_forbids_extra_fields() -> None:
    """Ensure DomainModel rejects unmodeled extra attributes."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        DummyModel.model_validate({"price": Decimal("100"), "timestamp": now, "rogue_field": "danger"})


def test_enum_definitions() -> None:
    """Verify all domain enumerations contain expected values."""
    assert TimeFrame.H1.value == "1h"
    assert TimeFrame.H4.value == "4h"
    assert MarketType.SPOT.value == "spot"
    assert MarketType.FUTURES.value == "futures"
    assert OrderSide.BUY.value == "buy"
    assert OrderSide.SELL.value == "sell"
    assert PositionSide.LONG.value == "long"
    assert PositionSide.SHORT.value == "short"
    assert OrderType.MARKET.value == "market"
    assert OrderStatus.FILLED.value == "filled"
    assert RegimeType.BULLISH_TREND.value == "bullish_trend"
    assert SignalStatus.APPROVED.value == "approved"
    assert EventSeverity.CRITICAL.value == "critical"

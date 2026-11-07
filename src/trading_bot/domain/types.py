"""Domain primitive types, custom validators, base models, and enumerations.

Enforces strict financial precision with Python Decimal and timezone-aware UTC timestamps.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer


def validate_financial_decimal(v: object) -> Decimal:
    """Validate and convert financial values to Decimal, strictly rejecting binary floats."""
    if isinstance(v, float):
        raise ValueError(
            f"Binary floats are strictly prohibited for financial values, got {v!r}. "
            "Pass Decimal or decimal string."
        )
    if isinstance(v, Decimal):
        if v.is_nan() or v.is_infinite():
            raise ValueError(f"NaN or Infinity is prohibited for financial values, got {v}")
        return v
    if isinstance(v, (str, int)):
        try:
            d = Decimal(str(v))
            if d.is_nan() or d.is_infinite():
                raise ValueError(f"NaN or Infinity is prohibited for financial values, got {d}")
            return d
        except Exception as e:
            raise ValueError(f"Invalid decimal value {v!r}: {e}") from e
    raise ValueError(f"Expected Decimal, int, or numeric str, got {type(v).__name__}")


def validate_utc_datetime(v: object) -> datetime:
    """Validate and enforce timezone-aware UTC datetimes."""
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if not isinstance(v, datetime):
        raise ValueError(f"Expected datetime or ISO datetime string, got {type(v).__name__}")
    if v.tzinfo is None:
        raise ValueError("Naive datetime is prohibited; timestamp must be timezone-aware UTC.")
    if v.utcoffset() != UTC.utcoffset(None):
        raise ValueError("Non-UTC timezone is prohibited; convert timestamp to UTC explicitly.")
    return v


# Annotated types for domain safety
FinancialDecimal = Annotated[
    Decimal,
    BeforeValidator(validate_financial_decimal),
    PlainSerializer(lambda d: str(d), return_type=str, when_used="json"),
]

UTCDateTime = Annotated[
    datetime,
    BeforeValidator(validate_utc_datetime),
    PlainSerializer(lambda dt: dt.isoformat(), return_type=str, when_used="json"),
]


class DomainModel(BaseModel):
    """Base immutable domain model with strict validation and forbidden extra attributes."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=False,
        validate_default=True,
    )


class TimeFrame(StrEnum):
    """Supported candle timeframes."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class MarketType(StrEnum):
    """Trading market type."""

    SPOT = "spot"
    FUTURES = "futures"


class OrderSide(StrEnum):
    """Order transaction side."""

    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    """Position direction."""

    LONG = "long"
    SHORT = "short"


class OrderType(StrEnum):
    """Order execution type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    TAKE_PROFIT_MARKET = "take_profit_market"


class OrderStatus(StrEnum):
    """Order lifecycle state machine statuses."""

    CREATED = "created"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class RegimeType(StrEnum):
    """Market regime classification categories."""

    BULLISH_TREND = "bullish_trend"
    BEARISH_TREND = "bearish_trend"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    TRANSITIONAL = "transitional"


class SignalStatus(StrEnum):
    """Signal lifecycle statuses."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class EventSeverity(StrEnum):
    """System event severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

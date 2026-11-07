"""Candle domain model with strict mathematical OHLCV integrity checks."""

from decimal import Decimal
from typing import Any

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
    TimeFrame,
    UTCDateTime,
)


class Candle(DomainModel):
    """Immutable, validated OHLCV candlestick representation."""

    exchange: str
    symbol: str
    market_type: MarketType = MarketType.SPOT
    timeframe: TimeFrame
    open_time: UTCDateTime
    close_time: UTCDateTime
    open: FinancialDecimal
    high: FinancialDecimal
    low: FinancialDecimal
    close: FinancialDecimal
    volume: FinancialDecimal
    is_closed: bool
    ingested_at: UTCDateTime

    @model_validator(mode="before")
    @classmethod
    def set_market_type_default(cls, data: Any) -> Any:
        """Infer or default market_type if omitted, preserving backwards compatibility."""
        if isinstance(data, dict) and "market_type" not in data:
            symbol = data.get("symbol", "")
            if symbol and (":" in symbol or symbol.endswith(":USDT")):
                data["market_type"] = MarketType.FUTURES
            else:
                data["market_type"] = MarketType.SPOT
        return data

    @model_validator(mode="after")
    def validate_ohlcv_integrity(self) -> "Candle":
        """Verify candlestick time sequence and price invariants."""
        if self.open_time >= self.close_time:
            raise ValueError(
                f"open_time ({self.open_time}) must be strictly earlier than close_time ({self.close_time})"
            )

        zero = Decimal("0")
        if self.open <= zero or self.high <= zero or self.low <= zero or self.close <= zero:
            raise ValueError("OHLC prices must be strictly positive (> 0)")

        if self.volume < zero:
            raise ValueError("Volume must be non-negative (>= 0)")

        if not (self.low <= self.open <= self.high):
            raise ValueError(
                f"Invalid candle open: open ({self.open}) must be between low ({self.low}) and high ({self.high})"
            )

        if not (self.low <= self.close <= self.high):
            raise ValueError(
                f"Invalid candle close: close ({self.close}) must be between low ({self.low}) and high ({self.high})"
            )

        return self

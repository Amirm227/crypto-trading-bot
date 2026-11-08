"""SQLAlchemy declarative ORM models and mapping boundaries.

Ensures strict financial precision via Numeric(asdecimal=True), timezone-aware UTC timestamps,
and composite uniqueness across (exchange, symbol, market_type, timeframe, open_time).
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import MarketType, TimeFrame


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base class for persistence entities."""


class CandleModel(Base):
    """PostgreSQL persistence model for OHLCV candlestick records."""

    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(asdecimal=True), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(asdecimal=True), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(asdecimal=True), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(asdecimal=True), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(asdecimal=True), nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "exchange",
            "symbol",
            "market_type",
            "timeframe",
            "open_time",
            name="uq_candles_series_open_time",
        ),
        Index(
            "ix_candles_latest",
            "exchange",
            "symbol",
            "market_type",
            "timeframe",
            "is_closed",
            "open_time",
        ),
    )

    def to_domain(self) -> Candle:
        """Map persistence record to immutable, validated domain Candle entity."""
        return Candle(
            exchange=self.exchange,
            symbol=self.symbol,
            market_type=MarketType(self.market_type),
            timeframe=TimeFrame(self.timeframe),
            open_time=_ensure_utc(self.open_time),
            close_time=_ensure_utc(self.close_time),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            is_closed=self.is_closed,
            ingested_at=_ensure_utc(self.ingested_at),
        )

    @classmethod
    def from_domain(cls, candle: Candle) -> "CandleModel":
        """Construct persistence entity from validated domain Candle."""
        return cls(
            exchange=candle.exchange,
            symbol=candle.symbol,
            market_type=candle.market_type.value,
            timeframe=candle.timeframe.value,
            open_time=_ensure_utc(candle.open_time),
            close_time=_ensure_utc(candle.close_time),
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            is_closed=candle.is_closed,
            ingested_at=_ensure_utc(candle.ingested_at),
        )

    def is_identical(self, candle: Candle) -> bool:
        """Check if an incoming domain candle matches this record's payload identically."""
        return (
            self.exchange == candle.exchange
            and self.symbol == candle.symbol
            and self.market_type == candle.market_type.value
            and self.timeframe == candle.timeframe.value
            and _ensure_utc(self.open_time) == _ensure_utc(candle.open_time)
            and _ensure_utc(self.close_time) == _ensure_utc(candle.close_time)
            and self.open == candle.open
            and self.high == candle.high
            and self.low == candle.low
            and self.close == candle.close
            and self.volume == candle.volume
            and self.is_closed == candle.is_closed
        )

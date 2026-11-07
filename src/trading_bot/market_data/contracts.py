"""Market data domain contracts, protocols, and strongly typed OHLCV data structures.

Enforces supported assets (BTC, ETH, SOL), supported timeframes (1H, 4H),
strict timestamp sequencing, and separation of closed vs incomplete candles.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    TimeFrame,
    UTCDateTime,
)

SUPPORTED_BASE_ASSETS: frozenset[str] = frozenset({"BTC", "ETH", "SOL"})
SUPPORTED_SPOT_SYMBOLS: frozenset[str] = frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT"})
SUPPORTED_FUTURES_SYMBOLS: frozenset[str] = frozenset({
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
})
SUPPORTED_SYMBOLS: frozenset[str] = frozenset(SUPPORTED_SPOT_SYMBOLS | SUPPORTED_FUTURES_SYMBOLS)
SUPPORTED_TIMEFRAMES: frozenset[TimeFrame] = frozenset({TimeFrame.H1, TimeFrame.H4})

TIMEFRAME_DURATIONS: dict[TimeFrame, timedelta] = {
    TimeFrame.M1: timedelta(minutes=1),
    TimeFrame.M5: timedelta(minutes=5),
    TimeFrame.M15: timedelta(minutes=15),
    TimeFrame.H1: timedelta(hours=1),
    TimeFrame.H4: timedelta(hours=4),
    TimeFrame.D1: timedelta(days=1),
}


class OHLCVRequest(DomainModel):
    """Normalized request for historical or incremental OHLCV market data."""

    symbol: str
    timeframe: TimeFrame
    since: UTCDateTime | None = None
    until: UTCDateTime | None = None
    limit: int = Field(default=500, gt=0, le=1000)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        normalized_symbol = self.symbol.strip().upper()
        if normalized_symbol not in SUPPORTED_SYMBOLS:
            raise ValueError(
                f"Unsupported symbol '{self.symbol}'. Must be one of {sorted(SUPPORTED_SYMBOLS)}"
            )

        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{self.timeframe}'. Must be 1h or 4h for MVP"
            )

        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError(
                f"since ({self.since}) must be strictly earlier than until ({self.until})"
            )

        return self


class RawCandle(DomainModel):
    """Raw OHLCV entry received from exchange before domain validation and normalization."""

    timestamp_ms: int = Field(gt=0)
    open: FinancialDecimal
    high: FinancialDecimal
    low: FinancialDecimal
    close: FinancialDecimal
    volume: FinancialDecimal
    is_closed: bool = True

    @property
    def open_time(self) -> datetime:
        """Convert millisecond timestamp to timezone-aware UTC datetime."""
        return datetime.fromtimestamp(self.timestamp_ms / 1000.0, tz=UTC)

    def to_candle(
        self,
        exchange: str,
        symbol: str,
        timeframe: TimeFrame,
        ingested_at: datetime | None = None,
    ) -> Candle:
        """Transform raw candle DTO into fully validated domain Candle."""
        duration = TIMEFRAME_DURATIONS[timeframe]
        op_time = self.open_time
        cl_time = op_time + duration
        ingest_time = ingested_at or datetime.now(UTC)

        return Candle(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            open_time=op_time,
            close_time=cl_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            is_closed=self.is_closed,
            ingested_at=ingest_time,
        )


class CandleBatch(DomainModel):
    """Immutable, chronological collection of validated candles for a single asset and timeframe."""

    symbol: str
    timeframe: TimeFrame
    candles: tuple[Candle, ...]

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if not self.candles:
            raise ValueError("CandleBatch cannot be empty")

        symbol = self.symbol
        timeframe = self.timeframe

        for i, c in enumerate(self.candles):
            if c.symbol != symbol:
                raise ValueError(
                    f"Candle at index {i} has symbol '{c.symbol}', expected '{symbol}'"
                )
            if c.timeframe != timeframe:
                raise ValueError(
                    f"Candle at index {i} has timeframe '{c.timeframe}', expected '{timeframe}'"
                )

            # Check timestamp ordering
            if i > 0:
                prev_c = self.candles[i - 1]
                if c.open_time <= prev_c.open_time:
                    raise ValueError(
                        f"Candles not in strictly ascending order: index {i} ({c.open_time}) "
                        f"<= index {i-1} ({prev_c.open_time})"
                    )

            # Incomplete candle check: only the very last candle can be incomplete
            if not c.is_closed and i < len(self.candles) - 1:
                raise ValueError(
                    f"Incomplete candle found at index {i} ({c.open_time}). "
                    "Only the trailing candle is permitted to be unclosed."
                )

        return self

    @property
    def count(self) -> int:
        return len(self.candles)

    @property
    def start_time(self) -> datetime:
        return self.candles[0].open_time

    @property
    def end_time(self) -> datetime:
        return self.candles[-1].close_time

    @property
    def has_incomplete(self) -> bool:
        """True if the trailing candle in the batch is open (unclosed)."""
        return not self.candles[-1].is_closed

    @property
    def closed_candles(self) -> tuple[Candle, ...]:
        """Return strictly closed candles; filters out any unclosed trailing candle."""
        return tuple(c for c in self.candles if c.is_closed)

    @property
    def latest_closed_candle(self) -> Candle | None:
        """Return the most recent closed candle, or None if no closed candle exists."""
        closed = self.closed_candles
        return closed[-1] if closed else None


class DataQualityCheckResult(DomainModel):
    """Result of validation and gap detection across a candle sequence."""

    symbol: str
    timeframe: TimeFrame
    total_candles: int
    closed_candles: int
    incomplete_candles: int
    is_valid: bool
    gaps_detected: tuple[tuple[UTCDateTime, UTCDateTime], ...] = ()
    rejection_reasons: tuple[str, ...] = ()


@runtime_checkable
class MarketDataFeed(Protocol):
    """Protocol for external market data sources (exchange APIs or historical adapters)."""

    async def fetch_ohlcv(self, request: OHLCVRequest) -> CandleBatch:
        """Retrieve OHLCV candles matching request criteria."""
        ...

    async def get_server_time(self) -> datetime:
        """Retrieve current exchange/provider timestamp in UTC."""
        ...


@runtime_checkable
class CandleRepository(Protocol):
    """Protocol for persistent storage and retrieval of candlestick data."""

    async def save_candle(self, candle: Candle) -> None:
        """Persist a single candle idempotently."""
        ...

    async def save_batch(self, batch: CandleBatch) -> int:
        """Persist a batch of candles, returning count of newly inserted records."""
        ...

    async def get_latest_candle(
        self,
        symbol: str,
        timeframe: TimeFrame,
        closed_only: bool = True,
    ) -> Candle | None:
        """Retrieve the most recent candle for symbol and timeframe."""
        ...

    async def get_candles(self, request: OHLCVRequest) -> CandleBatch | None:
        """Query candles from storage matching request."""
        ...

    async def find_gaps(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
    ) -> tuple[tuple[datetime, datetime], ...]:
        """Detect missing timestamp intervals in stored historical data."""
        ...


@runtime_checkable
class MarketDataService(Protocol):
    """Application service coordinating market data ingestion, validation, and strategy feeds."""

    async def sync_candles(self, symbol: str, timeframe: TimeFrame) -> CandleBatch:
        """Synchronize stored data with exchange feed and validate continuity."""
        ...

    async def get_regime_candles(self, symbol: str) -> CandleBatch:
        """Retrieve closed 4H candles strictly required for Regime classification."""
        ...

    async def get_entry_candles(self, symbol: str) -> CandleBatch:
        """Retrieve closed 1H candles strictly required for strategy entry evaluations."""
        ...

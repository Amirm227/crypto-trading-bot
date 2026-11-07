"""Market data retrieval, validation, gap detection, and storage interfaces."""

from trading_bot.market_data.contracts import (
    SUPPORTED_BASE_ASSETS,
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_DURATIONS,
    CandleBatch,
    CandleRepository,
    DataQualityCheckResult,
    MarketDataFeed,
    MarketDataService,
    OHLCVRequest,
    RawCandle,
)

__all__ = [
    "SUPPORTED_BASE_ASSETS",
    "SUPPORTED_SYMBOLS",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_DURATIONS",
    "CandleBatch",
    "CandleRepository",
    "DataQualityCheckResult",
    "MarketDataFeed",
    "MarketDataService",
    "OHLCVRequest",
    "RawCandle",
]

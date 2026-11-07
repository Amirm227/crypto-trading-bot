"""Exchange adapter abstraction layer and protocol definitions."""

from trading_bot.exchanges.ccxt_adapter import ReadOnlyCCXTAdapter
from trading_bot.exchanges.contracts import (
    CapabilityStatus,
    ExchangeAdapter,
    ExchangeCapabilities,
    MarketMetadata,
)
from trading_bot.exchanges.exceptions import (
    ExchangeAdapterError,
    ExchangeDataError,
    ExchangeNetworkError,
    ExchangePermissionError,
    ExchangeRateLimitError,
    ExchangeTimeoutError,
)

__all__ = [
    "CapabilityStatus",
    "ExchangeAdapter",
    "ExchangeAdapterError",
    "ExchangeCapabilities",
    "ExchangeDataError",
    "ExchangeNetworkError",
    "ExchangePermissionError",
    "ExchangeRateLimitError",
    "ExchangeTimeoutError",
    "MarketMetadata",
    "ReadOnlyCCXTAdapter",
]

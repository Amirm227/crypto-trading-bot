"""Exchange adapter abstraction layer and protocol definitions."""

from trading_bot.exchanges.contracts import (
    CapabilityStatus,
    ExchangeAdapter,
    ExchangeCapabilities,
    MarketMetadata,
)

__all__ = [
    "CapabilityStatus",
    "ExchangeAdapter",
    "ExchangeCapabilities",
    "MarketMetadata",
]

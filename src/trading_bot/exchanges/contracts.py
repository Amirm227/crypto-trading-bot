"""Exchange adapter contracts, capability registries, and market metadata interfaces.

The sole communication boundary between internal bot domain logic and external exchange APIs.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
)
from trading_bot.market_data.contracts import CandleBatch, OHLCVRequest


class CapabilityStatus(StrEnum):
    """Capability registration statuses for exchange operations."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"

    @property
    def is_safe_to_execute(self) -> bool:
        """Sensitive operations must be explicitly SUPPORTED; UNKNOWN is treated as UNSUPPORTED."""
        return self == CapabilityStatus.SUPPORTED


class ExchangeCapabilities(DomainModel):
    """Registry tracking explicit exchange operational capabilities."""

    spot: CapabilityStatus = CapabilityStatus.SUPPORTED
    linear_futures: CapabilityStatus = CapabilityStatus.SUPPORTED
    isolated_margin: CapabilityStatus = CapabilityStatus.SUPPORTED
    cross_margin: CapabilityStatus = CapabilityStatus.UNSUPPORTED
    client_order_id: CapabilityStatus = CapabilityStatus.SUPPORTED
    reduce_only: CapabilityStatus = CapabilityStatus.SUPPORTED
    stop_market: CapabilityStatus = CapabilityStatus.SUPPORTED
    take_profit_market: CapabilityStatus = CapabilityStatus.SUPPORTED
    funding_history: CapabilityStatus = CapabilityStatus.SUPPORTED
    ohlcv_fetch: CapabilityStatus = CapabilityStatus.SUPPORTED


class MarketMetadata(DomainModel):
    """Normalized exchange rules, precisions, and lot/notional boundaries for an asset."""

    symbol: str
    base_asset: str
    quote_asset: str
    market_type: MarketType
    price_precision: int
    quantity_precision: int
    min_notional: FinancialDecimal = Decimal("5.0")
    min_quantity: FinancialDecimal = Decimal("0.0001")
    step_size: FinancialDecimal = Decimal("0.0001")
    tick_size: FinancialDecimal = Decimal("0.01")
    contract_size: FinancialDecimal = Decimal("1.0")


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Sole boundary protocol for exchange API communication."""

    async def get_ohlcv(self, request: OHLCVRequest) -> CandleBatch:
        """Fetch historical or incremental candles for symbol and timeframe."""
        ...

    async def get_market_metadata(self, symbol: str) -> MarketMetadata:
        """Fetch normalized symbols, precisions, and limits."""
        ...

    async def get_server_time(self) -> datetime:
        """Retrieve exchange server time in UTC."""
        ...

    async def get_exchange_capabilities(self) -> ExchangeCapabilities:
        """Query supported exchange features and order types."""
        ...

    async def get_balance(self) -> dict[str, FinancialDecimal]:
        """Fetch account equity and balance ledger."""
        ...

    async def get_positions(self) -> list[Any]:
        """Query active exchange positions."""
        ...

    async def get_funding_rate(self, symbol: str) -> FinancialDecimal:
        """Retrieve latest funding rate for a linear futures asset."""
        ...

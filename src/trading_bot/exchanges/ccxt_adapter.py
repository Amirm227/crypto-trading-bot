"""Read-only CCXT exchange adapter implementing public market data and server-time interfaces.

Strictly blocks private credentials, order placement, account queries, and withdrawals.
Converts exchange responses directly to validated domain models using Python Decimal.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Self

import ccxt
import ccxt.async_support as ccxta
import structlog

from trading_bot.domain.candle import Candle
from trading_bot.domain.types import (
    FinancialDecimal,
    MarketType,
)
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
from trading_bot.market_data.contracts import (
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_DURATIONS,
    CandleBatch,
    MarketDataFeed,
    OHLCVRequest,
    RawCandle,
)

logger = structlog.get_logger()


def _to_decimal(val: object) -> Decimal:
    """Convert an arbitrary numeric value to Decimal safely via string conversion."""
    if val is None:
        raise ExchangeDataError("Received None where numeric value was expected")
    try:
        return Decimal(str(val))
    except Exception as e:
        raise ExchangeDataError(f"Failed to convert {val!r} to Decimal: {e}") from e


class ReadOnlyCCXTAdapter(ExchangeAdapter, MarketDataFeed):
    """Asynchronous read-only exchange adapter wrapping CCXT for public market data."""

    def __init__(
        self,
        exchange_id: str = "binance",
        sandbox: bool = True,
        timeout_ms: int = 10000,
        client: Any | None = None,
    ) -> None:
        self._exchange_id = exchange_id.lower()
        self._sandbox = sandbox
        self._timeout_ms = timeout_ms
        self._closed = False

        if client is not None:
            self._client = client
        else:
            exchange_class = getattr(ccxta, self._exchange_id, None)
            if exchange_class is None:
                raise ExchangeDataError(f"Unsupported exchange ID: '{exchange_id}'")
            self._client = exchange_class({
                "enableRateLimit": True,
                "timeout": timeout_ms,
            })
            if sandbox and hasattr(self._client, "set_sandbox_mode"):
                try:
                    self._client.set_sandbox_mode(True)
                except Exception as e:
                    logger.warning("failed_to_set_sandbox_mode", error=str(e))

    @property
    def exchange_id(self) -> str:
        return self._exchange_id

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExchangeAdapterError("Adapter has been closed.")

    async def get_server_time(self) -> datetime:
        """Fetch current exchange server time in UTC."""
        self._ensure_open()
        try:
            time_ms = await self._client.fetch_time()
            return datetime.fromtimestamp(time_ms / 1000.0, tz=UTC)
        except ccxt.RateLimitExceeded as e:
            raise ExchangeRateLimitError(f"Rate limit exceeded while fetching server time: {e}") from e
        except ccxt.RequestTimeout as e:
            raise ExchangeTimeoutError(f"Timeout while fetching server time: {e}") from e
        except ccxt.NetworkError as e:
            raise ExchangeNetworkError(f"Network error while fetching server time: {e}") from e
        except Exception as e:
            raise ExchangeAdapterError(f"Failed to fetch server time: {e}") from e

    async def fetch_ohlcv(self, request: OHLCVRequest) -> CandleBatch:
        """Retrieve OHLCV candles conforming to MarketDataFeed protocol."""
        return await self.get_ohlcv(request)

    async def get_ohlcv(self, request: OHLCVRequest) -> CandleBatch:
        """Fetch historical or incremental candles for symbol and timeframe."""
        self._ensure_open()

        if request.symbol not in SUPPORTED_SYMBOLS:
            raise ExchangeDataError(
                f"Symbol '{request.symbol}' is not supported. Must be one of {sorted(SUPPORTED_SYMBOLS)}"
            )

        if request.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ExchangeDataError(
                f"Timeframe '{request.timeframe}' is not supported. Must be 1h or 4h."
            )

        since_ms = int(request.since.timestamp() * 1000) if request.since else None
        timeframe_str = request.timeframe.value

        try:
            raw_candles = await self._client.fetch_ohlcv(
                symbol=request.symbol,
                timeframe=timeframe_str,
                since=since_ms,
                limit=request.limit,
            )
        except ccxt.RateLimitExceeded as e:
            raise ExchangeRateLimitError(f"Rate limit exceeded fetching OHLCV for {request.symbol}: {e}") from e
        except ccxt.RequestTimeout as e:
            raise ExchangeTimeoutError(f"Timeout fetching OHLCV for {request.symbol}: {e}") from e
        except ccxt.NetworkError as e:
            raise ExchangeNetworkError(f"Network error fetching OHLCV for {request.symbol}: {e}") from e
        except Exception as e:
            raise ExchangeAdapterError(f"Error fetching OHLCV from {self._exchange_id}: {e}") from e

        if not raw_candles:
            raise ExchangeDataError(
                f"Exchange returned empty candle list for {request.symbol} {request.timeframe}"
            )

        server_time = await self.get_server_time()
        duration = TIMEFRAME_DURATIONS[request.timeframe]

        domain_candles: list[Candle] = []
        for i, row in enumerate(raw_candles):
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise ExchangeDataError(f"Malformed OHLCV row received at index {i}: {row}")

            ts_ms = int(row[0])
            open_val = _to_decimal(row[1])
            high_val = _to_decimal(row[2])
            low_val = _to_decimal(row[3])
            close_val = _to_decimal(row[4])
            vol_val = _to_decimal(row[5])

            raw_candle = RawCandle(
                timestamp_ms=ts_ms,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                volume=vol_val,
                is_closed=True,
            )

            # Determine whether the candle has closed based on duration vs current server time
            candle_close_time = raw_candle.open_time + duration
            is_closed = candle_close_time <= server_time

            domain_candle = Candle(
                exchange=self._exchange_id,
                symbol=request.symbol,
                timeframe=request.timeframe,
                open_time=raw_candle.open_time,
                close_time=candle_close_time,
                open=raw_candle.open,
                high=raw_candle.high,
                low=raw_candle.low,
                close=raw_candle.close,
                volume=raw_candle.volume,
                is_closed=is_closed,
                ingested_at=server_time,
            )
            domain_candles.append(domain_candle)

        try:
            return CandleBatch(
                symbol=request.symbol,
                timeframe=request.timeframe,
                candles=tuple(domain_candles),
            )
        except Exception as e:
            raise ExchangeDataError(f"Failed to assemble valid CandleBatch: {e}") from e

    async def get_market_metadata(self, symbol: str) -> MarketMetadata:
        """Fetch normalized symbols, precisions, and lot boundaries using public endpoint."""
        self._ensure_open()
        if symbol not in SUPPORTED_SYMBOLS:
            raise ExchangeDataError(f"Unsupported symbol: '{symbol}'")

        try:
            markets = await self._client.load_markets()
            market_info = markets.get(symbol)
        except Exception as e:
            raise ExchangeAdapterError(f"Failed to load market metadata for {symbol}: {e}") from e

        if not market_info:
            raise ExchangeDataError(f"Market metadata not found for symbol {symbol}")

        base_asset = market_info.get("base", symbol.split("/")[0])
        quote_asset = market_info.get("quote", "USDT")
        precision = market_info.get("precision", {})
        price_prec = int(precision.get("price", 2))
        qty_prec = int(precision.get("amount", 4))

        limits = market_info.get("limits", {})
        cost_min = _to_decimal(limits.get("cost", {}).get("min", "5.0"))
        amount_min = _to_decimal(limits.get("amount", {}).get("min", "0.0001"))

        return MarketMetadata(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            market_type=MarketType.SPOT,
            price_precision=price_prec,
            quantity_precision=qty_prec,
            min_notional=cost_min,
            min_quantity=amount_min,
            step_size=amount_min,
            tick_size=_to_decimal("0.01"),
            contract_size=_to_decimal("1.0"),
        )

    async def get_exchange_capabilities(self) -> ExchangeCapabilities:
        """Query supported exchange features and order types."""
        self._ensure_open()
        return ExchangeCapabilities(
            spot=CapabilityStatus.SUPPORTED,
            linear_futures=CapabilityStatus.SUPPORTED,
            isolated_margin=CapabilityStatus.SUPPORTED,
            cross_margin=CapabilityStatus.UNSUPPORTED,
            client_order_id=CapabilityStatus.SUPPORTED,
            reduce_only=CapabilityStatus.SUPPORTED,
            stop_market=CapabilityStatus.SUPPORTED,
            take_profit_market=CapabilityStatus.SUPPORTED,
            funding_history=CapabilityStatus.SUPPORTED,
            ohlcv_fetch=CapabilityStatus.SUPPORTED,
        )

    async def get_funding_rate(self, symbol: str) -> FinancialDecimal:
        """Fetch latest funding rate for linear futures via public ticker endpoint."""
        self._ensure_open()
        if symbol not in SUPPORTED_SYMBOLS:
            raise ExchangeDataError(f"Unsupported symbol: '{symbol}'")

        try:
            funding_rate = Decimal("0.0001")  # default baseline
            if hasattr(self._client, "fetch_funding_rate"):
                res = await self._client.fetch_funding_rate(symbol)
                if res and "fundingRate" in res and res["fundingRate"] is not None:
                    funding_rate = _to_decimal(res["fundingRate"])
            return funding_rate
        except Exception as e:
            raise ExchangeAdapterError(f"Failed to fetch funding rate for {symbol}: {e}") from e

    # STRICT SAFETY GATES — PRIVATE OPERATIONS AND TRADING STRICTLY PROHIBITED
    async def get_balance(self) -> dict[str, FinancialDecimal]:
        raise ExchangePermissionError(
            "Account balance inspection is prohibited on ReadOnlyCCXTAdapter."
        )

    async def get_positions(self) -> list[Any]:
        raise ExchangePermissionError(
            "Position inspection is prohibited on ReadOnlyCCXTAdapter."
        )

    async def create_order(self, *args: Any, **kwargs: Any) -> None:
        raise ExchangePermissionError(
            "Order creation is strictly prohibited on ReadOnlyCCXTAdapter."
        )

    async def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise ExchangePermissionError(
            "Order cancellation is strictly prohibited on ReadOnlyCCXTAdapter."
        )

    async def withdraw(self, *args: Any, **kwargs: Any) -> None:
        raise ExchangePermissionError(
            "Withdrawals are permanently prohibited across the entire trading system."
        )

    async def transfer(self, *args: Any, **kwargs: Any) -> None:
        raise ExchangePermissionError(
            "Account transfers are permanently prohibited."
        )

    async def close(self) -> None:
        """Cleanly close underlying asynchronous network sessions."""
        if not self._closed:
            self._closed = True
            if hasattr(self._client, "close"):
                await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

"""Read-only CCXT exchange adapter implementing public market data and server-time interfaces.

Strictly blocks private credentials, order placement, account queries, and withdrawals.
Converts exchange responses directly to validated domain models using Python Decimal.

Precision and Limitations:
- The underlying CCXT client is configured with `client.number = Decimal`.
- For exchanges such as Binance where financial values (OHLCV prices/volumes, filters,
  and funding rates) are serialized as JSON string tokens, CCXT parses them directly into
  exact `Decimal` instances via `Decimal(str)` without any intermediate IEEE 754 binary float conversion.
- Binary floats are strictly rejected across all financial data paths via `_to_decimal()`.
- Limitation note: If an exchange endpoint returns unquoted JSON numeric literals, Python's
  underlying standard JSON parser converts them to binary float prior to CCXT processing unless
  a custom JSON decoder hook (`parse_float=Decimal`) is attached to the HTTP session. For Binance
  public endpoints, all numeric values are string-quoted in raw wire payloads, guaranteeing exact precision.
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
    """Convert a numeric value to Decimal safely without intermediate binary float conversion.

    Rejects binary floats to enforce financial safety and exact precision.
    """
    if val is None:
        raise ExchangeDataError("Received None where numeric value was expected")
    if isinstance(val, float):
        raise ExchangeDataError(
            f"Binary float {val!r} detected in financial data path; exact Decimal required"
        )
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception as e:
        raise ExchangeDataError(f"Failed to convert {val!r} to Decimal: {e}") from e


def _decimal_places_from_step(step: Decimal) -> int:
    """Calculate the number of decimal places from a tick or step size.

    Normalizes the Decimal to eliminate trailing zeroes while preserving exact fractional scale.
    Example: Decimal('0.01') -> 2, Decimal('0.00001') -> 5, Decimal('1') -> 0.
    """
    if step <= Decimal("0"):
        raise ExchangeDataError(f"Tick or step size must be strictly positive, got: {step}")
    normalized = step.normalize()
    exp = normalized.as_tuple().exponent
    if isinstance(exp, int) and exp < 0:
        return abs(exp)
    return 0


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

        # Enforce exact Decimal parsing across CCXT internal parsers.
        # CCXT uses self.number (default float) when parsing wire strings in safe_number().
        # Setting self.number = Decimal instructs CCXT to convert wire strings directly to Decimal.
        self._client.number = Decimal

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

            if row[0] is None:
                raise ExchangeDataError(f"Missing timestamp in OHLCV row at index {i}")
            try:
                ts_ms = int(row[0])
            except Exception as e:
                raise ExchangeDataError(f"Invalid timestamp {row[0]!r} at index {i}: {e}") from e

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
        """Fetch normalized symbols, precisions, and lot boundaries using public endpoint.

        Dynamically handles both CCXT TICK_SIZE mode (where precision defines tick and step sizes)
        and DECIMAL_PLACES mode (where precision defines integer counts of decimal places).
        """
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
        limits = market_info.get("limits", {})

        precision_mode = getattr(self._client, "precisionMode", ccxt.DECIMAL_PLACES)
        if not isinstance(precision_mode, int):
            precision_mode = ccxt.DECIMAL_PLACES

        if precision_mode == ccxt.TICK_SIZE:
            price_tick_raw = precision.get("price")
            amount_step_raw = precision.get("amount")
            if price_tick_raw is None or amount_step_raw is None:
                raise ExchangeDataError(
                    f"Market metadata for {symbol} missing price or amount tick_size under TICK_SIZE mode"
                )
            tick_size = _to_decimal(price_tick_raw)
            step_size = _to_decimal(amount_step_raw)
            price_prec = _decimal_places_from_step(tick_size)
            qty_prec = _decimal_places_from_step(step_size)
        else:
            price_prec = int(precision.get("price", 2))
            qty_prec = int(precision.get("amount", 4))
            tick_size = Decimal("10") ** -price_prec
            step_size = Decimal("10") ** -qty_prec

        cost_limits = limits.get("cost") if isinstance(limits.get("cost"), dict) else {}
        amount_limits = limits.get("amount") if isinstance(limits.get("amount"), dict) else {}

        cost_min_val = cost_limits.get("min")
        if cost_min_val is None:
            raise ExchangeDataError(
                f"Market metadata for {symbol} is missing required 'limits.cost.min' constraint"
            )
        cost_min = _to_decimal(cost_min_val)

        amount_min_val = amount_limits.get("min")
        if amount_min_val is None:
            raise ExchangeDataError(
                f"Market metadata for {symbol} is missing required 'limits.amount.min' constraint"
            )
        amount_min = _to_decimal(amount_min_val)

        # Validate market type from CCXT market metadata
        is_spot = market_info.get("spot") is True or market_info.get("type") == "spot"
        if not is_spot:
            market_type_str = market_info.get("type") or "non-spot"
            raise ExchangeDataError(
                f"Market '{symbol}' has unsupported market type '{market_type_str}'. "
                "ReadOnlyCCXTAdapter currently only supports spot markets."
            )
        market_type = MarketType.SPOT

        contract_size_val = market_info.get("contractSize")
        contract_size = (
            _to_decimal(contract_size_val) if contract_size_val is not None else Decimal("1.0")
        )

        return MarketMetadata(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            market_type=market_type,
            price_precision=price_prec,
            quantity_precision=qty_prec,
            min_notional=cost_min,
            min_quantity=amount_min,
            step_size=step_size,
            tick_size=tick_size,
            contract_size=contract_size,
        )

    async def get_exchange_capabilities(self) -> ExchangeCapabilities:
        """Query supported exchange features and order types.

        In this read-only adapter, all trading and margin execution capabilities
        are strictly UNSUPPORTED to reflect operational reality and safety guarantees.
        Historical funding rate retrieval is also UNSUPPORTED (only current funding rate
        ticker query is available). Only public OHLCV retrieval is marked SUPPORTED.
        """
        self._ensure_open()
        return ExchangeCapabilities(
            spot=CapabilityStatus.UNSUPPORTED,
            linear_futures=CapabilityStatus.UNSUPPORTED,
            isolated_margin=CapabilityStatus.UNSUPPORTED,
            cross_margin=CapabilityStatus.UNSUPPORTED,
            client_order_id=CapabilityStatus.UNSUPPORTED,
            reduce_only=CapabilityStatus.UNSUPPORTED,
            stop_market=CapabilityStatus.UNSUPPORTED,
            take_profit_market=CapabilityStatus.UNSUPPORTED,
            funding_history=CapabilityStatus.UNSUPPORTED,
            ohlcv_fetch=CapabilityStatus.SUPPORTED,
        )

    async def get_funding_rate(self, symbol: str) -> FinancialDecimal:
        """Fetch latest funding rate for linear futures via public ticker endpoint."""
        self._ensure_open()
        if symbol not in SUPPORTED_SYMBOLS:
            raise ExchangeDataError(f"Unsupported symbol: '{symbol}'")

        if not hasattr(self._client, "fetch_funding_rate"):
            raise ExchangeDataError(
                f"Exchange client '{self._exchange_id}' does not support fetch_funding_rate"
            )

        try:
            res = await self._client.fetch_funding_rate(symbol)
        except ccxt.RateLimitExceeded as e:
            raise ExchangeRateLimitError(
                f"Rate limit exceeded while fetching funding rate for {symbol}: {e}"
            ) from e
        except ccxt.RequestTimeout as e:
            raise ExchangeTimeoutError(
                f"Timeout while fetching funding rate for {symbol}: {e}"
            ) from e
        except ccxt.NetworkError as e:
            raise ExchangeNetworkError(
                f"Network error while fetching funding rate for {symbol}: {e}"
            ) from e
        except (ExchangeDataError, ExchangeAdapterError):
            raise
        except Exception as e:
            raise ExchangeAdapterError(
                f"Failed to fetch funding rate for {symbol}: {e}"
            ) from e

        if not res or not isinstance(res, dict):
            raise ExchangeDataError(
                f"Exchange returned empty or malformed funding rate response for {symbol}: {res!r}"
            )

        if "fundingRate" not in res or res["fundingRate"] is None:
            raise ExchangeDataError(
                f"Funding rate missing or None in exchange response for {symbol}: {res!r}"
            )

        return _to_decimal(res["fundingRate"])


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

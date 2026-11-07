"""Unit tests for ReadOnlyCCXTAdapter verifying protocol conformance, public endpoints, and security gates."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import ccxt
import pytest

from trading_bot.domain.types import MarketType, TimeFrame
from trading_bot.exchanges.ccxt_adapter import (
    ReadOnlyCCXTAdapter,
    _decimal_places_from_step,
    _to_decimal,
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
    CandleBatch,
    MarketDataFeed,
    OHLCVRequest,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    """Fixture providing a mocked CCXT async exchange client configured with Decimal parser."""
    client = AsyncMock()
    client.precisionMode = ccxt.DECIMAL_PLACES
    client.number = Decimal
    # Mock server time: 2026-11-07 12:00:00 UTC
    client.fetch_time.return_value = 1794052800000
    # Mock markets (default BTC spot)
    client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {"price": 2, "amount": 5},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.00001")}},
        },
        "BTC/USDT:USDT": {
            "symbol": "BTC/USDT:USDT",
            "base": "BTC",
            "quote": "USDT",
            "settle": "USDT",
            "spot": False,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
            "contract": True,
            "contractSize": Decimal("1.0"),
            "precision": {"price": 1, "amount": 3},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.001")}},
        },
    }
    client.fetch_funding_rate.return_value = {"fundingRate": Decimal("0.0001")}
    return client


def test_protocol_conformance(mock_client: AsyncMock) -> None:
    """Ensure ReadOnlyCCXTAdapter conforms to ExchangeAdapter and MarketDataFeed protocols."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    assert isinstance(adapter, ExchangeAdapter)
    assert isinstance(adapter, MarketDataFeed)


@pytest.mark.asyncio
async def test_get_server_time_returns_utc_datetime(mock_client: AsyncMock) -> None:
    """Ensure get_server_time converts millisecond timestamps to timezone-aware UTC datetime."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    server_time = await adapter.get_server_time()
    assert server_time.tzinfo == UTC
    assert server_time == datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    mock_client.fetch_time.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_ohlcv_normalizes_to_decimal_candle_batch(mock_client: AsyncMock) -> None:
    """Ensure fetch_ohlcv preserves Decimal precision and correctly sets is_closed flag for spot."""
    # Server time is 12:00:00 UTC
    # Candle 1: 10:00:00 to 11:00:00 (Closed)
    # Candle 2: 11:00:00 to 12:00:00 (Closed)
    # Candle 3: 12:00:00 to 13:00:00 (Open / Incomplete)
    ts1 = int(datetime(2026, 11, 7, 10, 0, tzinfo=UTC).timestamp() * 1000)
    ts2 = int(datetime(2026, 11, 7, 11, 0, tzinfo=UTC).timestamp() * 1000)
    ts3 = int(datetime(2026, 11, 7, 12, 0, tzinfo=UTC).timestamp() * 1000)

    mock_client.fetch_ohlcv.return_value = [
        [ts1, Decimal("69500.25"), Decimal("70100.50"), Decimal("69200.00"), Decimal("69800.75"), Decimal("120.45")],
        [ts2, Decimal("69800.75"), Decimal("70500.00"), Decimal("69700.00"), Decimal("70200.00"), Decimal("150.10")],
        [ts3, Decimal("70200.00"), Decimal("70600.00"), Decimal("70100.00"), Decimal("70400.00"), Decimal("45.20")],
    ]

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1, limit=100)
    batch = await adapter.fetch_ohlcv(req)

    assert isinstance(batch, CandleBatch)
    assert batch.count == 3
    assert batch.has_incomplete is True
    assert len(batch.closed_candles) == 2

    c1 = batch.candles[0]
    assert c1.open == Decimal("69500.25")
    assert isinstance(c1.open, Decimal)
    assert isinstance(c1.high, Decimal)
    assert isinstance(c1.low, Decimal)
    assert isinstance(c1.close, Decimal)
    assert isinstance(c1.volume, Decimal)
    assert c1.is_closed is True

    c3 = batch.candles[2]
    assert c3.is_closed is False


@pytest.mark.asyncio
async def test_fetch_ohlcv_linear_perpetual(mock_client: AsyncMock) -> None:
    """Ensure fetch_ohlcv retrieves and normalizes linear perpetual futures candles."""
    ts = int(datetime(2026, 11, 7, 10, 0, tzinfo=UTC).timestamp() * 1000)
    mock_client.fetch_ohlcv.return_value = [
        [ts, Decimal("70100.0"), Decimal("70500.0"), Decimal("69800.0"), Decimal("70250.0"), Decimal("500.0")]
    ]
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT:USDT", timeframe=TimeFrame.H1)
    batch = await adapter.fetch_ohlcv(req)

    assert batch.symbol == "BTC/USDT:USDT"
    assert batch.candles[0].open == Decimal("70100.0")
    assert isinstance(batch.candles[0].open, Decimal)


@pytest.mark.asyncio
async def test_get_market_metadata_spot(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata extracts spot lot sizes, precisions, and market type."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("BTC/USDT")

    assert isinstance(meta, MarketMetadata)
    assert meta.symbol == "BTC/USDT"
    assert meta.market_type == MarketType.SPOT
    assert meta.base_asset == "BTC"
    assert meta.quote_asset == "USDT"
    assert meta.price_precision == 2
    assert meta.quantity_precision == 5
    assert meta.min_notional == Decimal("5.0")
    assert isinstance(meta.min_notional, Decimal)
    assert meta.min_quantity == Decimal("0.00001")
    assert isinstance(meta.min_quantity, Decimal)
    assert meta.step_size == Decimal("0.00001")
    assert meta.tick_size == Decimal("0.01")


@pytest.mark.asyncio
async def test_get_market_metadata_linear_perpetual(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata normalizes USDT-M linear perpetual contracts."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("BTC/USDT:USDT")

    assert isinstance(meta, MarketMetadata)
    assert meta.symbol == "BTC/USDT:USDT"
    assert meta.market_type == MarketType.FUTURES
    assert meta.base_asset == "BTC"
    assert meta.quote_asset == "USDT"
    assert meta.price_precision == 1
    assert meta.quantity_precision == 3
    assert meta.min_notional == Decimal("5.0")
    assert meta.min_quantity == Decimal("0.001")
    assert meta.step_size == Decimal("0.001")
    assert meta.contract_size == Decimal("1.0")


@pytest.mark.asyncio
async def test_get_exchange_capabilities(mock_client: AsyncMock) -> None:
    """Ensure capabilities strictly mark all execution/margin operations and funding history as UNSUPPORTED for safety."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    caps = await adapter.get_exchange_capabilities()

    assert isinstance(caps, ExchangeCapabilities)
    assert caps.spot == CapabilityStatus.UNSUPPORTED
    assert caps.linear_futures == CapabilityStatus.UNSUPPORTED
    assert caps.isolated_margin == CapabilityStatus.UNSUPPORTED
    assert caps.cross_margin == CapabilityStatus.UNSUPPORTED
    assert caps.client_order_id == CapabilityStatus.UNSUPPORTED
    assert caps.reduce_only == CapabilityStatus.UNSUPPORTED
    assert caps.stop_market == CapabilityStatus.UNSUPPORTED
    assert caps.take_profit_market == CapabilityStatus.UNSUPPORTED
    assert caps.funding_history == CapabilityStatus.UNSUPPORTED
    assert caps.ohlcv_fetch == CapabilityStatus.SUPPORTED


@pytest.mark.asyncio
async def test_get_funding_rate_returns_decimal_for_perpetual(mock_client: AsyncMock) -> None:
    """Ensure funding rate query returns exact Decimal for perpetual futures symbol."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    rate = await adapter.get_funding_rate("BTC/USDT:USDT")
    assert rate == Decimal("0.0001")
    assert isinstance(rate, Decimal)


@pytest.mark.asyncio
async def test_get_funding_rate_rejects_spot_symbol(mock_client: AsyncMock) -> None:
    """Ensure funding rate query on a spot symbol is strictly rejected with ExchangeDataError."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc:
        await adapter.get_funding_rate("BTC/USDT")
    assert "only applicable to perpetual futures markets" in str(exc.value)


@pytest.mark.asyncio
async def test_network_and_rate_limit_error_handling(mock_client: AsyncMock) -> None:
    """Ensure CCXT exceptions are normalized into domain-safe exception hierarchy."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1)

    # RateLimitExceeded
    mock_client.fetch_ohlcv.side_effect = ccxt.RateLimitExceeded("Too many requests")
    with pytest.raises(ExchangeRateLimitError):
        await adapter.fetch_ohlcv(req)

    # RequestTimeout
    mock_client.fetch_ohlcv.side_effect = ccxt.RequestTimeout("Socket timeout")
    with pytest.raises(ExchangeTimeoutError):
        await adapter.fetch_ohlcv(req)

    # NetworkError
    mock_client.fetch_ohlcv.side_effect = ccxt.NetworkError("Host unreachable")
    with pytest.raises(ExchangeNetworkError):
        await adapter.fetch_ohlcv(req)

    # Empty candle list returned
    mock_client.fetch_ohlcv.side_effect = None
    mock_client.fetch_ohlcv.return_value = []
    with pytest.raises(ExchangeDataError) as exc_empty:
        await adapter.fetch_ohlcv(req)
    assert "empty candle list" in str(exc_empty.value)

    # Malformed row returned
    mock_client.fetch_ohlcv.return_value = [[123456789, Decimal("70000")]]  # only 2 elements instead of 6
    with pytest.raises(ExchangeDataError) as exc_malformed:
        await adapter.fetch_ohlcv(req)
    assert "Malformed OHLCV row" in str(exc_malformed.value)


@pytest.mark.asyncio
async def test_deterministic_cleanup_and_closed_guard(mock_client: AsyncMock) -> None:
    """Ensure adapter closes underlying connection and guards against post-close calls."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    assert adapter.is_closed is False

    await adapter.close()
    assert adapter.is_closed is True
    mock_client.close.assert_awaited_once()

    # Calling methods after close raises ExchangeAdapterError
    with pytest.raises(ExchangeAdapterError) as exc:
        await adapter.get_server_time()
    assert "Adapter has been closed" in str(exc.value)


@pytest.mark.asyncio
async def test_async_context_manager(mock_client: AsyncMock) -> None:
    """Ensure async context manager enters and closes cleanly."""
    async with ReadOnlyCCXTAdapter(client=mock_client) as adapter:
        assert adapter.is_closed is False
    assert adapter.is_closed is True
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_security_gates_private_operations_strictly_prohibited(mock_client: AsyncMock) -> None:
    """Verify that order creation, cancellation, withdrawals, transfers, and account queries are blocked."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    with pytest.raises(ExchangePermissionError) as exc1:
        await adapter.create_order()
    assert "Order creation is strictly prohibited" in str(exc1.value)

    with pytest.raises(ExchangePermissionError) as exc2:
        await adapter.cancel_order()
    assert "Order cancellation is strictly prohibited" in str(exc2.value)

    with pytest.raises(ExchangePermissionError) as exc3:
        await adapter.withdraw()
    assert "Withdrawals are permanently prohibited" in str(exc3.value)

    with pytest.raises(ExchangePermissionError) as exc4:
        await adapter.transfer()
    assert "Account transfers are permanently prohibited" in str(exc4.value)

    with pytest.raises(ExchangePermissionError) as exc5:
        await adapter.get_balance()
    assert "Account balance inspection is prohibited" in str(exc5.value)

    with pytest.raises(ExchangePermissionError) as exc6:
        await adapter.get_positions()
    assert "Position inspection is prohibited" in str(exc6.value)


@pytest.mark.asyncio
async def test_adapter_initialization_unsupported_exchange() -> None:
    """Ensure initializing with an unrecognized exchange ID raises ExchangeDataError."""
    with pytest.raises(ExchangeDataError) as exc:
        ReadOnlyCCXTAdapter(exchange_id="nonexistent_exchange_999")
    assert "Unsupported exchange ID" in str(exc.value)


@pytest.mark.asyncio
async def test_get_server_time_exceptions(mock_client: AsyncMock) -> None:
    """Ensure get_server_time maps CCXT exceptions to adapter errors."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    # RateLimitExceeded
    mock_client.fetch_time.side_effect = ccxt.RateLimitExceeded("Rate limit")
    with pytest.raises(ExchangeRateLimitError):
        await adapter.get_server_time()

    # RequestTimeout
    mock_client.fetch_time.side_effect = ccxt.RequestTimeout("Timeout")
    with pytest.raises(ExchangeTimeoutError):
        await adapter.get_server_time()

    # NetworkError
    mock_client.fetch_time.side_effect = ccxt.NetworkError("Network")
    with pytest.raises(ExchangeNetworkError):
        await adapter.get_server_time()

    # Generic Exception
    mock_client.fetch_time.side_effect = RuntimeError("Generic crash")
    with pytest.raises(ExchangeAdapterError):
        await adapter.get_server_time()


@pytest.mark.asyncio
async def test_get_market_metadata_error_handling(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata handles missing market and exceptions."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    # Unsupported symbol
    with pytest.raises(ExchangeDataError) as exc1:
        await adapter.get_market_metadata("XRP/USDT")
    assert "Unsupported symbol" in str(exc1.value)

    # Exception loading markets
    mock_client.load_markets.side_effect = ccxt.NetworkError("Failed to reach API")
    with pytest.raises(ExchangeAdapterError):
        await adapter.get_market_metadata("BTC/USDT")

    # Missing symbol in markets dict
    mock_client.load_markets.side_effect = None
    mock_client.load_markets.return_value = {}
    with pytest.raises(ExchangeDataError) as exc2:
        await adapter.get_market_metadata("BTC/USDT")
    assert "Market metadata not found" in str(exc2.value)


@pytest.mark.asyncio
async def test_get_funding_rate_error_handling(mock_client: AsyncMock) -> None:
    """Ensure get_funding_rate validates symbol and catches network errors."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    # Unsupported symbol
    with pytest.raises(ExchangeDataError):
        await adapter.get_funding_rate("DOGE/USDT")

    # Network error on valid perpetual
    mock_client.fetch_funding_rate.side_effect = ccxt.NetworkError("Error")
    with pytest.raises(ExchangeNetworkError):
        await adapter.get_funding_rate("BTC/USDT:USDT")

    # Rate limit error on valid perpetual
    mock_client.fetch_funding_rate.side_effect = ccxt.RateLimitExceeded("Rate limit")
    with pytest.raises(ExchangeRateLimitError):
        await adapter.get_funding_rate("BTC/USDT:USDT")

    # Timeout error on valid perpetual
    mock_client.fetch_funding_rate.side_effect = ccxt.RequestTimeout("Timeout")
    with pytest.raises(ExchangeTimeoutError):
        await adapter.get_funding_rate("BTC/USDT:USDT")


def test_to_decimal_handling_and_float_rejection() -> None:
    """Ensure _to_decimal converts safe types and strictly rejects binary floats."""
    # None raises
    with pytest.raises(ExchangeDataError) as exc_none:
        _to_decimal(None)
    assert "Received None" in str(exc_none.value)

    # Binary float raises
    with pytest.raises(ExchangeDataError) as exc_float:
        _to_decimal(69500.25)
    assert "Binary float" in str(exc_float.value)

    # Invalid string raises
    with pytest.raises(ExchangeDataError) as exc_str:
        _to_decimal("not_a_valid_decimal")
    assert "Failed to convert" in str(exc_str.value)

    # Valid Decimal returns exact instance
    dec_val = Decimal("69500.123456789")
    assert _to_decimal(dec_val) is dec_val

    # Valid string converted to Decimal
    assert _to_decimal("69500.25") == Decimal("69500.25")

    # Valid int converted to Decimal
    assert _to_decimal(100) == Decimal("100")


def test_decimal_places_from_step() -> None:
    """Ensure _decimal_places_from_step derives exact precision and rejects non-positive values."""
    assert _decimal_places_from_step(Decimal("0.01")) == 2
    assert _decimal_places_from_step(Decimal("0.00001")) == 5
    assert _decimal_places_from_step(Decimal("0.00000001")) == 8
    assert _decimal_places_from_step(Decimal("1")) == 0
    assert _decimal_places_from_step(Decimal("1.0")) == 0
    assert _decimal_places_from_step(Decimal("100")) == 0
    assert _decimal_places_from_step(Decimal("0.05")) == 2
    assert _decimal_places_from_step(Decimal("0.25")) == 2
    assert _decimal_places_from_step(Decimal("0.00100")) == 3

    # Non-positive values raise ExchangeDataError
    with pytest.raises(ExchangeDataError):
        _decimal_places_from_step(Decimal("0"))

    with pytest.raises(ExchangeDataError):
        _decimal_places_from_step(Decimal("-0.01"))


@pytest.mark.asyncio
async def test_client_number_configured_to_decimal(mock_client: AsyncMock) -> None:
    """Verify underlying CCXT client is configured with number=Decimal upon adapter initialization."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    assert mock_client.number == Decimal
    assert adapter._client.number == Decimal

    # Test fresh client instantiation sets number = Decimal
    fresh_adapter = ReadOnlyCCXTAdapter(exchange_id="binance")
    assert fresh_adapter._client.number == Decimal
    await fresh_adapter.close()


@pytest.mark.asyncio
async def test_high_precision_ohlcv_preserved_without_float_degradation(mock_client: AsyncMock) -> None:
    """Ensure high-precision OHLCV values (e.g. 18 decimal places) are preserved exactly without float truncation."""
    ts = int(datetime(2026, 11, 7, 10, 0, tzinfo=UTC).timestamp() * 1000)
    p_open = Decimal("69500.123456789012345678")
    p_high = Decimal("70100.987654321098765432")
    p_low = Decimal("69200.000000000000000001")
    p_close = Decimal("69800.555555555555555555")
    p_vol = Decimal("120.123456789012345678")

    mock_client.fetch_ohlcv.return_value = [[ts, p_open, p_high, p_low, p_close, p_vol]]

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1)
    batch = await adapter.fetch_ohlcv(req)

    candle = batch.candles[0]
    assert candle.open == p_open
    assert str(candle.open) == "69500.123456789012345678"
    assert candle.high == p_high
    assert str(candle.high) == "70100.987654321098765432"
    assert candle.low == p_low
    assert str(candle.low) == "69200.000000000000000001"
    assert candle.close == p_close
    assert str(candle.close) == "69800.555555555555555555"
    assert candle.volume == p_vol
    assert str(candle.volume) == "120.123456789012345678"


@pytest.mark.asyncio
async def test_fetch_ohlcv_rejects_binary_float(mock_client: AsyncMock) -> None:
    """Ensure receiving binary float values in raw OHLCV rows triggers ExchangeDataError."""
    ts = int(datetime(2026, 11, 7, 10, 0, tzinfo=UTC).timestamp() * 1000)
    mock_client.fetch_ohlcv.return_value = [[ts, 69500.25, 70100.50, 69200.00, 69800.75, 120.45]]

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1)

    with pytest.raises(ExchangeDataError) as exc:
        await adapter.fetch_ohlcv(req)
    assert "Binary float" in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_ohlcv_invalid_or_missing_timestamp(mock_client: AsyncMock) -> None:
    """Ensure fetch_ohlcv validates raw timestamp before processing."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    req = OHLCVRequest(symbol="BTC/USDT", timeframe=TimeFrame.H1)

    # Missing None timestamp
    mock_client.fetch_ohlcv.return_value = [
        [None, Decimal("69000"), Decimal("69100"), Decimal("68900"), Decimal("69050"), Decimal("10")]
    ]
    with pytest.raises(ExchangeDataError) as exc_none:
        await adapter.fetch_ohlcv(req)
    assert "Missing timestamp" in str(exc_none.value)

    # Invalid timestamp
    mock_client.fetch_ohlcv.return_value = [
        ["invalid_ts", Decimal("69000"), Decimal("69100"), Decimal("68900"), Decimal("69050"), Decimal("10")]
    ]
    with pytest.raises(ExchangeDataError) as exc_inv:
        await adapter.fetch_ohlcv(req)
    assert "Invalid timestamp" in str(exc_inv.value)


@pytest.mark.asyncio
async def test_get_market_metadata_tick_size_mode(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata correctly parses TICK_SIZE mode and separates min_qty from step_size."""
    mock_client.precisionMode = ccxt.TICK_SIZE
    mock_client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {
                "price": Decimal("0.01"),
                "amount": Decimal("0.00001"),
            },
            "limits": {
                "cost": {"min": Decimal("10.0")},
                "amount": {"min": Decimal("0.001")},
            },
        }
    }

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("BTC/USDT")

    assert meta.price_precision == 2
    assert meta.quantity_precision == 5
    assert meta.tick_size == Decimal("0.01")
    assert meta.step_size == Decimal("0.00001")
    # min_quantity separated from step_size
    assert meta.min_quantity == Decimal("0.001")
    assert meta.min_notional == Decimal("10.0")


@pytest.mark.asyncio
async def test_get_market_metadata_tick_size_high_precision(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata correctly calculates high precision in TICK_SIZE mode."""
    mock_client.precisionMode = ccxt.TICK_SIZE
    mock_client.load_markets.return_value = {
        "SOL/USDT": {
            "symbol": "SOL/USDT",
            "base": "SOL",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {
                "price": Decimal("0.00001"),
                "amount": Decimal("0.00000001"),
            },
            "limits": {
                "cost": {"min": Decimal("5.0")},
                "amount": {"min": Decimal("0.00000001")},
            },
        }
    }

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("SOL/USDT")

    assert meta.price_precision == 5
    assert meta.quantity_precision == 8
    assert meta.tick_size == Decimal("0.00001")
    assert meta.step_size == Decimal("0.00000001")


@pytest.mark.asyncio
async def test_get_market_metadata_tick_size_missing_precision_raises(mock_client: AsyncMock) -> None:
    """Ensure missing price or amount in TICK_SIZE mode raises ExchangeDataError."""
    mock_client.precisionMode = ccxt.TICK_SIZE
    mock_client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {
                "price": None,
                "amount": Decimal("0.00001"),
            },
            "limits": {
                "cost": {"min": Decimal("5.0")},
                "amount": {"min": Decimal("0.00001")},
            },
        }
    }

    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc:
        await adapter.get_market_metadata("BTC/USDT")
    assert "missing price or amount tick_size" in str(exc.value)


@pytest.mark.asyncio
async def test_get_market_metadata_missing_amount_min_raises(mock_client: AsyncMock) -> None:
    """Ensure missing or None limits.amount.min raises ExchangeDataError without fallback to step_size."""
    # amount min is None
    mock_client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {"price": 2, "amount": 5},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": None}},
        }
    }
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc1:
        await adapter.get_market_metadata("BTC/USDT")
    assert "missing required 'limits.amount.min'" in str(exc1.value)

    # amount dict missing entirely
    mock_client.load_markets.return_value["BTC/USDT"]["limits"] = {"cost": {"min": Decimal("5.0")}}
    with pytest.raises(ExchangeDataError) as exc2:
        await adapter.get_market_metadata("BTC/USDT")
    assert "missing required 'limits.amount.min'" in str(exc2.value)


@pytest.mark.asyncio
async def test_get_market_metadata_missing_cost_min_raises(mock_client: AsyncMock) -> None:
    """Ensure missing or None limits.cost.min raises ExchangeDataError without fallback to 5.0."""
    # cost min is None
    mock_client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "type": "spot",
            "precision": {"price": 2, "amount": 5},
            "limits": {"cost": {"min": None}, "amount": {"min": Decimal("0.00001")}},
        }
    }
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc1:
        await adapter.get_market_metadata("BTC/USDT")
    assert "missing required 'limits.cost.min'" in str(exc1.value)

    # cost dict missing entirely
    mock_client.load_markets.return_value["BTC/USDT"]["limits"] = {"amount": {"min": Decimal("0.00001")}}
    with pytest.raises(ExchangeDataError) as exc2:
        await adapter.get_market_metadata("BTC/USDT")
    assert "missing required 'limits.cost.min'" in str(exc2.value)


@pytest.mark.asyncio
async def test_get_market_metadata_market_type_validation(mock_client: AsyncMock) -> None:
    """Ensure spot market type is validated and non-spot markets raise ExchangeDataError."""
    # Spot succeeds
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("BTC/USDT")
    assert meta.market_type == MarketType.SPOT

    # Delivery Future raises
    mock_client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "spot": False,
            "type": "future",
            "future": True,
            "precision": {"price": 2, "amount": 5},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.00001")}},
        }
    }
    with pytest.raises(ExchangeDataError) as exc_future:
        await adapter.get_market_metadata("BTC/USDT")
    assert "unsupported or mismatched market structure" in str(exc_future.value)

    # Option raises
    mock_client.load_markets.return_value["BTC/USDT"] = {
        "symbol": "BTC/USDT",
        "base": "BTC",
        "quote": "USDT",
        "spot": False,
        "type": "option",
        "option": True,
        "precision": {"price": 2, "amount": 5},
        "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.00001")}},
    }
    with pytest.raises(ExchangeDataError) as exc_opt:
        await adapter.get_market_metadata("BTC/USDT")
    assert "unsupported or mismatched market structure" in str(exc_opt.value)


@pytest.mark.asyncio
async def test_get_market_metadata_rejects_inverse_contracts(mock_client: AsyncMock) -> None:
    """Ensure inverse contracts are strictly rejected."""
    mock_client.load_markets.return_value = {
        "BTC/USDT:USDT": {
            "symbol": "BTC/USDT:USDT",
            "base": "BTC",
            "quote": "USD",
            "settle": "BTC",
            "spot": False,
            "swap": True,
            "linear": False,
            "inverse": True,
            "type": "swap",
            "precision": {"price": 1, "amount": 3},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.001")}},
        }
    }
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc:
        await adapter.get_market_metadata("BTC/USDT:USDT")
    assert "inverse contract" in str(exc.value)


@pytest.mark.asyncio
async def test_get_market_metadata_rejects_non_usdt_settle(mock_client: AsyncMock) -> None:
    """Ensure linear perpetual with non-USDT settle asset is rejected."""
    mock_client.load_markets.return_value = {
        "BTC/USDT:USDT": {
            "symbol": "BTC/USDT:USDT",
            "base": "BTC",
            "quote": "USDT",
            "settle": "USDC",  # mismatch: settle is USDC instead of USDT
            "spot": False,
            "swap": True,
            "linear": True,
            "inverse": False,
            "type": "swap",
            "precision": {"price": 1, "amount": 3},
            "limits": {"cost": {"min": Decimal("5.0")}, "amount": {"min": Decimal("0.001")}},
        }
    }
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc:
        await adapter.get_market_metadata("BTC/USDT:USDT")
    assert "unsupported or mismatched market structure" in str(exc.value)


@pytest.mark.asyncio
async def test_get_funding_rate_none_and_malformed_responses(mock_client: AsyncMock) -> None:
    """Ensure missing, None, or malformed funding rate response raises ExchangeDataError without fallbacks."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    # Return None
    mock_client.fetch_funding_rate.side_effect = None
    mock_client.fetch_funding_rate.return_value = None
    with pytest.raises(ExchangeDataError) as exc1:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "empty or malformed" in str(exc1.value)

    # Empty dict response
    mock_client.fetch_funding_rate.return_value = {}
    with pytest.raises(ExchangeDataError) as exc2:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "empty or malformed" in str(exc2.value)

    # Non-empty dict missing fundingRate key
    mock_client.fetch_funding_rate.return_value = {"symbol": "BTCUSDT"}
    with pytest.raises(ExchangeDataError) as exc_missing:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "missing or None" in str(exc_missing.value)

    # fundingRate is None
    mock_client.fetch_funding_rate.return_value = {"fundingRate": None}
    with pytest.raises(ExchangeDataError) as exc3:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "missing or None" in str(exc3.value)

    # Malformed non-dict response
    mock_client.fetch_funding_rate.return_value = "invalid_string"
    with pytest.raises(ExchangeDataError) as exc4:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "empty or malformed" in str(exc4.value)

    # Binary float response raises float rejection error
    mock_client.fetch_funding_rate.return_value = {"fundingRate": 0.0001}
    with pytest.raises(ExchangeDataError) as exc5:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "Binary float" in str(exc5.value)


@pytest.mark.asyncio
async def test_get_funding_rate_high_precision_preservation(mock_client: AsyncMock) -> None:
    """Ensure high-precision funding rate Decimal is preserved without degradation."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    precise_rate = Decimal("0.000123456789012345")
    mock_client.fetch_funding_rate.return_value = {"fundingRate": precise_rate}

    rate = await adapter.get_funding_rate("BTC/USDT:USDT")
    assert rate == precise_rate
    assert str(rate) == "0.000123456789012345"
    assert isinstance(rate, Decimal)


@pytest.mark.asyncio
async def test_get_funding_rate_client_missing_method(mock_client: AsyncMock) -> None:
    """Ensure exchange client lacking fetch_funding_rate raises ExchangeDataError."""
    del mock_client.fetch_funding_rate
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    with pytest.raises(ExchangeDataError) as exc:
        await adapter.get_funding_rate("BTC/USDT:USDT")
    assert "does not support fetch_funding_rate" in str(exc.value)

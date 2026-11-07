"""Unit tests for ReadOnlyCCXTAdapter verifying protocol conformance, public endpoints, and security gates."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import ccxt
import pytest

from trading_bot.domain.types import TimeFrame
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
from trading_bot.market_data.contracts import (
    CandleBatch,
    MarketDataFeed,
    OHLCVRequest,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    """Fixture providing a mocked CCXT async exchange client."""
    client = AsyncMock()
    # Mock server time: 2026-11-07 12:00:00 UTC
    client.fetch_time.return_value = 1794052800000
    # Mock markets
    client.load_markets.return_value = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "precision": {"price": 2, "amount": 5},
            "limits": {"cost": {"min": 5.0}, "amount": {"min": 0.00001}},
        }
    }
    client.fetch_funding_rate.return_value = {"fundingRate": 0.0001}
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
    """Ensure fetch_ohlcv preserves Decimal precision and correctly sets is_closed flag."""
    # Server time is 12:00:00 UTC
    # Candle 1: 10:00:00 to 11:00:00 (Closed)
    # Candle 2: 11:00:00 to 12:00:00 (Closed)
    # Candle 3: 12:00:00 to 13:00:00 (Open / Incomplete)
    ts1 = int(datetime(2026, 11, 7, 10, 0, tzinfo=UTC).timestamp() * 1000)
    ts2 = int(datetime(2026, 11, 7, 11, 0, tzinfo=UTC).timestamp() * 1000)
    ts3 = int(datetime(2026, 11, 7, 12, 0, tzinfo=UTC).timestamp() * 1000)

    mock_client.fetch_ohlcv.return_value = [
        [ts1, 69500.25, 70100.50, 69200.00, 69800.75, 120.45],
        [ts2, 69800.75, 70500.00, 69700.00, 70200.00, 150.10],
        [ts3, 70200.00, 70600.00, 70100.00, 70400.00, 45.20],
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
    assert c1.is_closed is True

    c3 = batch.candles[2]
    assert c3.is_closed is False


@pytest.mark.asyncio
async def test_get_market_metadata_normalized(mock_client: AsyncMock) -> None:
    """Ensure get_market_metadata extracts lot sizes and precisions using Decimal."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    meta = await adapter.get_market_metadata("BTC/USDT")

    assert isinstance(meta, MarketMetadata)
    assert meta.symbol == "BTC/USDT"
    assert meta.price_precision == 2
    assert meta.quantity_precision == 5
    assert meta.min_notional == Decimal("5.0")
    assert isinstance(meta.min_notional, Decimal)


@pytest.mark.asyncio
async def test_get_exchange_capabilities(mock_client: AsyncMock) -> None:
    """Ensure capabilities explicitly forbid cross margin and support isolated margin."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    caps = await adapter.get_exchange_capabilities()

    assert isinstance(caps, ExchangeCapabilities)
    assert caps.isolated_margin == CapabilityStatus.SUPPORTED
    assert caps.cross_margin == CapabilityStatus.UNSUPPORTED


@pytest.mark.asyncio
async def test_get_funding_rate_returns_decimal(mock_client: AsyncMock) -> None:
    """Ensure funding rate query returns Decimal."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)
    rate = await adapter.get_funding_rate("BTC/USDT")
    assert rate == Decimal("0.0001")
    assert isinstance(rate, Decimal)


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
    mock_client.fetch_ohlcv.return_value = [[123456789, 70000]]  # only 2 elements instead of 6
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
    """Ensure get_funding_rate validates symbol and catches errors."""
    adapter = ReadOnlyCCXTAdapter(client=mock_client)

    # Unsupported symbol
    with pytest.raises(ExchangeDataError):
        await adapter.get_funding_rate("DOGE/USDT")

    # Client exception
    mock_client.fetch_funding_rate.side_effect = ccxt.NetworkError("Error")
    with pytest.raises(ExchangeAdapterError):
        await adapter.get_funding_rate("BTC/USDT")


def test_to_decimal_error_handling() -> None:
    """Ensure _to_decimal handles None and invalid formats."""
    from trading_bot.exchanges.ccxt_adapter import _to_decimal

    with pytest.raises(ExchangeDataError) as exc1:
        _to_decimal(None)
    assert "Received None" in str(exc1.value)

    with pytest.raises(ExchangeDataError) as exc2:
        _to_decimal("not_a_valid_decimal")
    assert "Failed to convert" in str(exc2.value)

"""Unit tests for Order, Fill, Position, Trade, PortfolioSnapshot, and Regime models."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.fill import Fill
from trading_bot.domain.order import Order
from trading_bot.domain.portfolio import PortfolioSnapshot
from trading_bot.domain.position import Position
from trading_bot.domain.regime import MarketRegime
from trading_bot.domain.trade import Trade
from trading_bot.domain.types import (
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    RegimeType,
    TimeFrame,
)


def test_valid_market_order() -> None:
    """Ensure standard market entry order initializes with valid defaults."""
    now = datetime.now(UTC)
    order = Order(
        internal_id="ord-int-001",
        client_order_id="cl-ord-001",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        status=OrderStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    assert order.filled_quantity == Decimal("0")
    assert order.status == OrderStatus.CREATED


def test_limit_order_requires_price() -> None:
    """Ensure LIMIT order without price is rejected."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        Order(
            internal_id="ord-lim-001",
            client_order_id="cl-lim-001",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.01"),
            price=None,  # missing limit price
            status=OrderStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
    assert "Limit orders require a positive price" in str(exc.value)


def test_order_fill_accounting_consistency() -> None:
    """Ensure filled order has filled_quantity == quantity and positive average_fill_price."""
    now = datetime.now(UTC)
    # Status FILLED but quantity not fully filled
    with pytest.raises(ValidationError) as exc:
        Order(
            internal_id="ord-fill-bad",
            client_order_id="cl-fill-bad",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0.005"),  # partially filled, not completely
            average_fill_price=Decimal("70000"),
            status=OrderStatus.FILLED,
            created_at=now,
            updated_at=now,
        )
    assert "filled_quantity (0.005) != quantity (0.01)" in str(exc.value)


def test_valid_fill() -> None:
    """Ensure valid trade fill constructs properly."""
    now = datetime.now(UTC)
    fill = Fill(
        fill_id="fill-001",
        client_order_id="cl-001",
        exchange_trade_id="ex-tr-001",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        price=Decimal("70050.25"),
        quantity=Decimal("0.01"),
        fee=Decimal("0.07005"),
        fee_asset="USDT",
        timestamp=now,
    )
    assert fill.fee >= Decimal("0")


def test_position_invariants() -> None:
    """Ensure position validates spot constraints and positive quantities."""
    now = datetime.now(UTC)
    pos = Position(
        position_id="pos-001",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        average_entry_price=Decimal("70000.00"),
        mark_price=Decimal("70500.00"),
        unrealized_pnl=Decimal("5.00"),
        created_at=now,
        updated_at=now,
    )
    assert pos.side == PositionSide.LONG

    # Spot short rejected
    with pytest.raises(ValidationError) as exc:
        Position(
            position_id="pos-spot-short",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=PositionSide.SHORT,
            quantity=Decimal("0.01"),
            average_entry_price=Decimal("70000.00"),
            mark_price=Decimal("69500.00"),
            unrealized_pnl=Decimal("5.00"),
            created_at=now,
            updated_at=now,
        )
    assert "SHORT positions are strictly prohibited on Spot" in str(exc.value)


def test_trade_lifecycle_and_pnl_math() -> None:
    """Ensure completed Trade enforces exact mathematical gross and net PnL."""
    t_entry = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    t_exit = datetime(2026, 11, 7, 14, 0, tzinfo=UTC)

    # LONG: Entry=70000, Exit=72000, Qty=0.01
    # gross_pnl = (72000 - 70000) * 0.01 = 20.00
    # fees_total = 0.50, funding = 0.00 -> net_pnl = 19.50
    trade = Trade(
        trade_id="tr-001",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        side=PositionSide.LONG,
        entry_time=t_entry,
        exit_time=t_exit,
        entry_price=Decimal("70000"),
        exit_price=Decimal("72000"),
        quantity=Decimal("0.01"),
        fees_total=Decimal("0.50"),
        funding_total=Decimal("0.00"),
        gross_pnl=Decimal("20.00"),
        net_pnl=Decimal("19.50"),
        exit_reason="TAKE_PROFIT_TRIGGERED",
    )
    assert trade.net_pnl == Decimal("19.50")

    # Inconsistent net PnL math rejected
    with pytest.raises(ValidationError) as exc:
        Trade(
            trade_id="tr-bad-pnl",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=PositionSide.LONG,
            entry_time=t_entry,
            exit_time=t_exit,
            entry_price=Decimal("70000"),
            exit_price=Decimal("72000"),
            quantity=Decimal("0.01"),
            fees_total=Decimal("0.50"),
            funding_total=Decimal("0.00"),
            gross_pnl=Decimal("20.00"),
            net_pnl=Decimal("25.00"),  # mathematically wrong
            exit_reason="TAKE_PROFIT_TRIGGERED",
        )
    assert "does not match expected gross_pnl - fees_total + funding_total" in str(exc.value)


def test_portfolio_snapshot_drawdown_bounds() -> None:
    """Ensure PortfolioSnapshot enforces peak equity and drawdown bounds."""
    now = datetime.now(UTC)
    snap = PortfolioSnapshot(
        snapshot_id="snap-001",
        timestamp=now,
        total_equity=Decimal("950.00"),
        available_balance=Decimal("950.00"),
        margin_used=Decimal("0"),
        open_risk_amount=Decimal("0"),
        open_risk_pct=Decimal("0"),
        current_drawdown_pct=Decimal("5.00"),
        peak_equity=Decimal("1000.00"),
        open_positions_count=0,
    )
    assert snap.total_equity == Decimal("950.00")

    # peak equity lower than total equity is rejected
    with pytest.raises(ValidationError) as exc:
        PortfolioSnapshot(
            snapshot_id="snap-bad",
            timestamp=now,
            total_equity=Decimal("1200.00"),
            available_balance=Decimal("1200.00"),
            margin_used=Decimal("0"),
            open_risk_amount=Decimal("0"),
            open_risk_pct=Decimal("0"),
            current_drawdown_pct=Decimal("0"),
            peak_equity=Decimal("1000.00"),  # peak < total
            open_positions_count=0,
        )
    assert "cannot be lower than total_equity" in str(exc.value)


def test_market_regime_confidence_bounds() -> None:
    """Ensure MarketRegime enforces 0 to 1 confidence."""
    now = datetime.now(UTC)
    regime = MarketRegime(
        symbol="BTC/USDT",
        timeframe=TimeFrame.H4,
        regime=RegimeType.BULLISH_TREND,
        confidence=Decimal("0.85"),
        features={"adx_14": Decimal("28.5"), "ema_slope": Decimal("1.2")},
        detected_at=now,
        detector_version="regime_v1.0",
        reason_codes=("EMA200_POSITIVE_SLOPE", "ADX_GT_25"),
    )
    assert regime.confidence == Decimal("0.85")

    # confidence > 1.0 rejected
    with pytest.raises(ValidationError) as exc:
        MarketRegime(
            symbol="BTC/USDT",
            timeframe=TimeFrame.H4,
            regime=RegimeType.BULLISH_TREND,
            confidence=Decimal("1.50"),  # out of bounds
            features={},
            detected_at=now,
            detector_version="regime_v1.0",
            reason_codes=(),
        )
    assert "Confidence must be between 0.0 and 1.0" in str(exc.value)

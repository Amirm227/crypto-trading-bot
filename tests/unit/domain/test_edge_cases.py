"""Comprehensive edge-case and boundary tests for all domain models and invariants."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from trading_bot.domain.events import BotEvent, RiskEvent
from trading_bot.domain.fill import Fill
from trading_bot.domain.order import Order
from trading_bot.domain.portfolio import PortfolioSnapshot
from trading_bot.domain.position import Position
from trading_bot.domain.regime import MarketRegime
from trading_bot.domain.risk import RiskDecision
from trading_bot.domain.signal import Signal
from trading_bot.domain.trade import Trade
from trading_bot.domain.types import (
    EventSeverity,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    RegimeType,
    TimeFrame,
)


def test_fill_boundary_validations() -> None:
    """Ensure all Fill validation rules trigger appropriately."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "fill_id": "f-1",
        "client_order_id": "c-1",
        "exchange_trade_id": "e-1",
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "price": Decimal("70000"),
        "quantity": Decimal("1.0"),
        "fee": Decimal("5.0"),
        "fee_asset": "USDT",
        "timestamp": now,
    }

    # Zero price
    with pytest.raises(ValidationError):
        Fill.model_validate({**base_dict, "price": Decimal("0")})

    # Zero quantity
    with pytest.raises(ValidationError):
        Fill.model_validate({**base_dict, "quantity": Decimal("0")})

    # Negative fee
    with pytest.raises(ValidationError):
        Fill.model_validate({**base_dict, "fee": Decimal("-0.01")})

    # Empty identifiers
    for empty_key in ("fill_id", "client_order_id", "exchange_trade_id", "fee_asset"):
        with pytest.raises(ValidationError):
            Fill.model_validate({**base_dict, empty_key: "  "})


def test_order_boundary_validations() -> None:
    """Ensure all Order state transitions and pricing rules trigger appropriately."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "internal_id": "ord-1",
        "client_order_id": "cl-1",
        "symbol": "BTC/USDT",
        "market_type": MarketType.SPOT,
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1.0"),
        "created_at": now,
        "updated_at": now,
    }

    # created_at > updated_at
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "created_at": now + timedelta(seconds=10)})

    # Quantity <= 0
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "quantity": Decimal("0")})

    # Empty IDs
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "internal_id": ""})
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "client_order_id": ""})

    # STOP_MARKET requires stop_price
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "order_type": OrderType.STOP_MARKET, "stop_price": None})

    # Filled quantity > 0 requires average_fill_price
    with pytest.raises(ValidationError):
        Order.model_validate({**base_dict, "filled_quantity": Decimal("0.5"), "average_fill_price": None})

    # Filled quantity == 0 forbids average_fill_price
    with pytest.raises(ValidationError):
        Order.model_validate(
            {**base_dict, "filled_quantity": Decimal("0"), "average_fill_price": Decimal("100")}
        )

    # Status CREATED requires filled_quantity == 0
    with pytest.raises(ValidationError):
        Order.model_validate(
            {
                **base_dict,
                "status": OrderStatus.CREATED,
                "filled_quantity": Decimal("0.1"),
                "average_fill_price": Decimal("100"),
            }
        )


def test_position_boundary_validations() -> None:
    """Ensure Position boundaries for timestamps and pricing trigger properly."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "position_id": "p-1",
        "symbol": "BTC/USDT",
        "market_type": MarketType.FUTURES,
        "side": PositionSide.SHORT,
        "quantity": Decimal("1.0"),
        "average_entry_price": Decimal("70000"),
        "mark_price": Decimal("69000"),
        "unrealized_pnl": Decimal("1000"),
        "created_at": now,
        "updated_at": now,
    }

    # Inverted timestamps
    with pytest.raises(ValidationError):
        Position.model_validate({**base_dict, "created_at": now + timedelta(seconds=5)})

    # Quantity <= 0
    with pytest.raises(ValidationError):
        Position.model_validate({**base_dict, "quantity": Decimal("0")})

    # Entry price <= 0
    with pytest.raises(ValidationError):
        Position.model_validate({**base_dict, "average_entry_price": Decimal("0")})

    # Mark price <= 0
    with pytest.raises(ValidationError):
        Position.model_validate({**base_dict, "mark_price": Decimal("0")})

    # Empty position_id
    with pytest.raises(ValidationError):
        Position.model_validate({**base_dict, "position_id": "  "})


def test_portfolio_boundary_validations() -> None:
    """Ensure PortfolioSnapshot capital balance boundaries trigger properly."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "snapshot_id": "snap-1",
        "timestamp": now,
        "total_equity": Decimal("1000"),
        "available_balance": Decimal("1000"),
        "margin_used": Decimal("0"),
        "open_risk_amount": Decimal("0"),
        "open_risk_pct": Decimal("0"),
        "current_drawdown_pct": Decimal("0"),
        "peak_equity": Decimal("1000"),
        "open_positions_count": 0,
    }

    # Total equity <= 0
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "total_equity": Decimal("0")})

    # Negative available balance
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "available_balance": Decimal("-10")})

    # Negative margin used
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "margin_used": Decimal("-10")})

    # Negative open risk amount
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "open_risk_amount": Decimal("-1")})

    # open_risk_pct > 100% or < 0%
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "open_risk_pct": Decimal("105")})
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "open_risk_pct": Decimal("-1")})

    # current_drawdown_pct > 100% or < 0%
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "current_drawdown_pct": Decimal("101")})
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "current_drawdown_pct": Decimal("-5")})

    # Negative open_positions_count
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "open_positions_count": -1})

    # Empty snapshot_id
    with pytest.raises(ValidationError):
        PortfolioSnapshot.model_validate({**base_dict, "snapshot_id": " "})


def test_regime_boundary_validations() -> None:
    """Ensure MarketRegime fields enforce non-empty version and symbol."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "symbol": "BTC/USDT",
        "timeframe": TimeFrame.H4,
        "regime": RegimeType.SIDEWAYS,
        "confidence": Decimal("0.5"),
        "features": {},
        "detected_at": now,
        "detector_version": "v1",
        "reason_codes": (),
    }

    # Empty detector_version
    with pytest.raises(ValidationError):
        MarketRegime.model_validate({**base_dict, "detector_version": "  "})

    # Empty symbol
    with pytest.raises(ValidationError):
        MarketRegime.model_validate({**base_dict, "symbol": ""})


def test_risk_decision_boundary_validations() -> None:
    """Ensure RiskDecision enforces equity, ID, and allocation consistency."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "decision_id": "dec-1",
        "signal_id": "sig-1",
        "approved": True,
        "rejection_codes": (),
        "equity_snapshot": Decimal("1000"),
        "risk_amount": Decimal("2.0"),
        "quantity": Decimal("0.01"),
        "notional": Decimal("100"),
        "margin": Decimal("100"),
        "config_version": "v1",
        "decided_at": now,
    }

    # Equity <= 0
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "equity_snapshot": Decimal("0")})

    # Empty decision_id or signal_id
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "decision_id": ""})
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "signal_id": "  "})

    # Approved with risk_amount <= 0
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "risk_amount": Decimal("0")})

    # Approved with quantity <= 0
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "quantity": Decimal("0")})

    # Approved with notional <= 0
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "notional": Decimal("0")})

    # Approved with margin <= 0
    with pytest.raises(ValidationError):
        RiskDecision.model_validate({**base_dict, "margin": Decimal("0")})

    # Rejected with non-zero notional or margin
    with pytest.raises(ValidationError):
        RiskDecision.model_validate(
            {
                **base_dict,
                "approved": False,
                "rejection_codes": ("ERR",),
                "quantity": Decimal("0"),
                "risk_amount": Decimal("0"),
                "notional": Decimal("50"),
            }
        )
    with pytest.raises(ValidationError):
        RiskDecision.model_validate(
            {
                **base_dict,
                "approved": False,
                "rejection_codes": ("ERR",),
                "quantity": Decimal("0"),
                "risk_amount": Decimal("0"),
                "notional": Decimal("0"),
                "margin": Decimal("50"),
            }
        )


def test_signal_boundary_validations() -> None:
    """Ensure Signal pricing, expiration, and ID constraints trigger properly."""
    now = datetime.now(UTC)
    base_dict: dict[str, Any] = {
        "signal_id": "s-1",
        "strategy_id": "tf",
        "strategy_version": "1.0",
        "symbol": "BTC/USDT",
        "market_type": MarketType.FUTURES,
        "side": OrderSide.SELL,
        "entry_type": OrderType.MARKET,
        "entry_price": Decimal("70000"),
        "stop_loss": Decimal("71000"),
        "take_profit": Decimal("68000"),
        "risk_reward_ratio": Decimal("2.0"),
        "reason_codes": ("TREND_SHORT",),
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
    }

    # Empty signal_id or strategy_id
    with pytest.raises(ValidationError):
        Signal.model_validate({**base_dict, "signal_id": ""})
    with pytest.raises(ValidationError):
        Signal.model_validate({**base_dict, "strategy_id": "  "})

    # Non-positive entry_price, stop_loss, take_profit
    with pytest.raises(ValidationError):
        Signal.model_validate({**base_dict, "entry_price": Decimal("0")})
    with pytest.raises(ValidationError):
        Signal.model_validate({**base_dict, "stop_loss": Decimal("0")})
    with pytest.raises(ValidationError):
        Signal.model_validate({**base_dict, "take_profit": Decimal("0")})

    # Invalid SELL structure (take_profit above entry)
    with pytest.raises(ValidationError):
        Signal.model_validate(
            {
                **base_dict,
                "take_profit": Decimal("72000"),
                "stop_loss": Decimal("69000"),
            }
        )


def test_trade_boundary_validations() -> None:
    """Ensure Trade timing, pricing, and short math triggers properly."""
    t1 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=2)
    base_dict: dict[str, Any] = {
        "trade_id": "t-1",
        "symbol": "ETH/USDT",
        "market_type": MarketType.FUTURES,
        "side": PositionSide.SHORT,
        "entry_time": t1,
        "exit_time": t2,
        "entry_price": Decimal("3000"),
        "exit_price": Decimal("2800"),  # drop of 200 * 1 = 200 gross
        "quantity": Decimal("1.0"),
        "fees_total": Decimal("2.0"),
        "funding_total": Decimal("0.5"),
        "gross_pnl": Decimal("200.0"),
        "net_pnl": Decimal("198.5"),
        "exit_reason": "TAKE_PROFIT",
    }

    # Valid short trade
    tr = Trade.model_validate(base_dict)
    assert tr.gross_pnl == Decimal("200.0")

    # Inverted time
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "entry_time": t2, "exit_time": t1})

    # Non-positive prices or quantity
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "entry_price": Decimal("0")})
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "exit_price": Decimal("0")})
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "quantity": Decimal("0")})

    # Negative fees
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "fees_total": Decimal("-1")})

    # Empty IDs
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "trade_id": " "})
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "exit_reason": ""})

    # Short trade on SPOT market prohibited
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "market_type": MarketType.SPOT})

    # Gross PnL mismatch on short trade
    with pytest.raises(ValidationError):
        Trade.model_validate({**base_dict, "gross_pnl": Decimal("300.0")})


def test_events_models() -> None:
    """Ensure RiskEvent and BotEvent models instantiate and serialize cleanly."""
    now = datetime.now(UTC)
    rev = RiskEvent(
        event_id="rev-1",
        timestamp=now,
        component="risk_engine",
        event_type="CIRCUIT_BREAKER_TRIGGERED",
        severity=EventSeverity.CRITICAL,
        context={"daily_loss_pct": Decimal("0.85"), "limit": Decimal("0.75")},
        action_taken="ENTRY_HALT",
    )
    assert rev.severity == EventSeverity.CRITICAL
    json_str = rev.model_dump_json()
    assert '"ENTRY_HALT"' in json_str

    bev = BotEvent(
        event_id="bev-1",
        timestamp=now,
        component="market_data",
        event_type="BACKFILL_STARTED",
        severity=EventSeverity.INFO,
        context={"symbol": "BTC/USDT", "candles_fetched": 500},
        action_taken="CONTINUE",
    )
    assert bev.event_type == "BACKFILL_STARTED"

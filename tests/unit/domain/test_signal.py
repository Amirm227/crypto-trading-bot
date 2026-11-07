"""Unit tests for Signal domain model pricing, directions, and risk-reward validation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.signal import Signal
from trading_bot.domain.types import (
    MarketType,
    OrderSide,
    OrderType,
    SignalStatus,
)


def test_valid_buy_signal() -> None:
    """Ensure a valid BUY signal with R:R >= 2.0 constructs cleanly."""
    now = datetime.now(UTC)
    sig = Signal(
        signal_id="sig-001",
        strategy_id="trend_following",
        strategy_version="1.0.0",
        symbol="BTC/USDT",
        market_type=MarketType.SPOT,
        side=OrderSide.BUY,
        entry_type=OrderType.MARKET,
        entry_price=Decimal("70000"),
        stop_loss=Decimal("69000"),   # stop distance = 1000
        take_profit=Decimal("72000"),  # target distance = 2000, R:R = 2.0
        risk_reward_ratio=Decimal("2.0"),
        reason_codes=("PULLBACK_CONFIRMED", "RSI_HEALTHY"),
        created_at=now,
        expires_at=now + timedelta(hours=2),
        status=SignalStatus.PENDING,
    )
    assert sig.signal_id == "sig-001"
    assert sig.risk_reward_ratio == Decimal("2.0")


def test_valid_sell_futures_signal() -> None:
    """Ensure a valid SELL signal on Futures with R:R >= 2.0 constructs cleanly."""
    now = datetime.now(UTC)
    sig = Signal(
        signal_id="sig-002",
        strategy_id="trend_following",
        strategy_version="1.0.0",
        symbol="ETH/USDT",
        market_type=MarketType.FUTURES,
        side=OrderSide.SELL,
        entry_type=OrderType.MARKET,
        entry_price=Decimal("3000"),
        stop_loss=Decimal("3100"),   # stop distance = 100
        take_profit=Decimal("2750"),  # target distance = 250, R:R = 2.5
        risk_reward_ratio=Decimal("2.5"),
        reason_codes=("BEARISH_BREAKDOWN",),
        created_at=now,
        expires_at=now + timedelta(hours=2),
    )
    assert sig.side == OrderSide.SELL
    assert sig.risk_reward_ratio == Decimal("2.5")


def test_signal_rejects_spot_short() -> None:
    """Ensure Short selling is strictly rejected on Spot market."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        Signal(
            signal_id="sig-spot-short",
            strategy_id="trend_following",
            strategy_version="1.0.0",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.SELL,
            entry_type=OrderType.MARKET,
            entry_price=Decimal("70000"),
            stop_loss=Decimal("71000"),
            take_profit=Decimal("68000"),
            risk_reward_ratio=Decimal("2.0"),
            reason_codes=("INVALID_SPOT_SHORT",),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    assert "Short selling (OrderSide.SELL) is strictly prohibited on Spot" in str(exc.value)


def test_signal_rejects_sub_minimum_risk_reward() -> None:
    """Ensure risk_reward_ratio < 2.0 is rejected."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        Signal(
            signal_id="sig-low-rr",
            strategy_id="trend_following",
            strategy_version="1.0.0",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.BUY,
            entry_type=OrderType.MARKET,
            entry_price=Decimal("70000"),
            stop_loss=Decimal("69000"),   # distance = 1000
            take_profit=Decimal("71500"),  # distance = 1500, R:R = 1.5
            risk_reward_ratio=Decimal("1.5"),
            reason_codes=("LOW_RR",),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    assert "below the required 1:2 minimum" in str(exc.value)


def test_signal_rejects_inverted_price_structure() -> None:
    """Ensure stop loss on the wrong side of entry is rejected."""
    now = datetime.now(UTC)
    # BUY where stop loss is above entry price
    with pytest.raises(ValidationError) as exc:
        Signal(
            signal_id="sig-inv",
            strategy_id="trend_following",
            strategy_version="1.0.0",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.BUY,
            entry_type=OrderType.MARKET,
            entry_price=Decimal("70000"),
            stop_loss=Decimal("71000"),  # invalid: stop above entry for buy
            take_profit=Decimal("73000"),
            risk_reward_ratio=Decimal("2.0"),
            reason_codes=("BAD_STOP",),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    assert "Invalid BUY structure" in str(exc.value)


def test_signal_rejects_declared_rr_mismatch() -> None:
    """Ensure declared risk_reward_ratio must match actual price distances."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        Signal(
            signal_id="sig-mismatch",
            strategy_id="trend_following",
            strategy_version="1.0.0",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            side=OrderSide.BUY,
            entry_type=OrderType.MARKET,
            entry_price=Decimal("70000"),
            stop_loss=Decimal("69000"),   # distance = 1000
            take_profit=Decimal("72000"),  # distance = 2000, actual R:R = 2.0
            risk_reward_ratio=Decimal("3.5"),  # fabricated R:R
            reason_codes=("TEST",),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    assert "does not match calculated ratio" in str(exc.value)

"""Signal domain model representing validated trading candidate intents."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
    OrderSide,
    OrderType,
    SignalStatus,
    UTCDateTime,
)


class Signal(DomainModel):
    """Immutable standardized trading signal."""

    signal_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    market_type: MarketType
    side: OrderSide
    entry_type: OrderType
    entry_price: FinancialDecimal
    stop_loss: FinancialDecimal
    take_profit: FinancialDecimal
    risk_reward_ratio: FinancialDecimal
    reason_codes: tuple[str, ...]
    created_at: UTCDateTime
    expires_at: UTCDateTime
    status: SignalStatus = SignalStatus.PENDING

    @model_validator(mode="after")
    def validate_signal_integrity(self) -> "Signal":
        """Verify signal pricing structure, direction rules, and risk-reward constraints."""
        if self.created_at >= self.expires_at:
            raise ValueError(
                f"created_at ({self.created_at}) must precede expires_at ({self.expires_at})"
            )

        zero = Decimal("0")
        if self.entry_price <= zero or self.stop_loss <= zero or self.take_profit <= zero:
            raise ValueError("entry_price, stop_loss, and take_profit must be strictly positive (> 0)")

        if not self.signal_id.strip():
            raise ValueError("signal_id must not be empty")

        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")

        # Spot market restriction: Short entries are prohibited on spot
        if self.market_type == MarketType.SPOT and self.side == OrderSide.SELL:
            raise ValueError("Short selling (OrderSide.SELL) is strictly prohibited on Spot markets")

        min_rr = Decimal("2.0")
        if self.risk_reward_ratio < min_rr:
            raise ValueError(
                f"Signal risk_reward_ratio ({self.risk_reward_ratio}) is below the required 1:2 minimum ({min_rr})"
            )

        # Directional structure validation
        if self.side == OrderSide.BUY:
            if not (self.stop_loss < self.entry_price < self.take_profit):
                raise ValueError(
                    f"Invalid BUY structure: requires stop_loss ({self.stop_loss}) < "
                    f"entry_price ({self.entry_price}) < take_profit ({self.take_profit})"
                )
            stop_distance = self.entry_price - self.stop_loss
            target_distance = self.take_profit - self.entry_price
            calculated_rr = target_distance / stop_distance
        else:  # OrderSide.SELL
            if not (self.take_profit < self.entry_price < self.stop_loss):
                raise ValueError(
                    f"Invalid SELL structure: requires take_profit ({self.take_profit}) < "
                    f"entry_price ({self.entry_price}) < stop_loss ({self.stop_loss})"
                )
            stop_distance = self.stop_loss - self.entry_price
            target_distance = self.entry_price - self.take_profit
            calculated_rr = target_distance / stop_distance

        # Ensure declared risk_reward_ratio matches mathematical ratio within precision tolerance (0.01)
        if abs(self.risk_reward_ratio - calculated_rr) > Decimal("0.02"):
            raise ValueError(
                f"Declared risk_reward_ratio ({self.risk_reward_ratio}) does not match "
                f"calculated ratio ({calculated_rr:.4f})"
            )

        return self

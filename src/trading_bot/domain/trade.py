"""Trade domain model representing completed trade lifecycle from entry to exit."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
    PositionSide,
    UTCDateTime,
)


class Trade(DomainModel):
    """Immutable closed trade lifecycle record with complete PnL and fee accounting."""

    trade_id: str
    symbol: str
    market_type: MarketType
    side: PositionSide
    entry_time: UTCDateTime
    exit_time: UTCDateTime
    entry_price: FinancialDecimal
    exit_price: FinancialDecimal
    quantity: FinancialDecimal
    fees_total: FinancialDecimal
    funding_total: FinancialDecimal = Decimal("0")
    gross_pnl: FinancialDecimal
    net_pnl: FinancialDecimal
    exit_reason: str

    @model_validator(mode="after")
    def validate_trade_integrity(self) -> "Trade":
        """Verify trade duration, mathematical PnL, and spot constraints."""
        if self.entry_time >= self.exit_time:
            raise ValueError(
                f"entry_time ({self.entry_time}) must be earlier than exit_time ({self.exit_time})"
            )

        zero = Decimal("0")
        if self.entry_price <= zero or self.exit_price <= zero:
            raise ValueError("entry_price and exit_price must be strictly positive (> 0)")

        if self.quantity <= zero:
            raise ValueError(f"Trade quantity must be strictly positive (> 0), got {self.quantity}")

        if self.fees_total < zero:
            raise ValueError(f"fees_total must be non-negative (>= 0), got {self.fees_total}")

        if self.market_type == MarketType.SPOT and self.side == PositionSide.SHORT:
            raise ValueError("SHORT trades are prohibited on Spot markets")

        if not self.trade_id.strip():
            raise ValueError("trade_id must not be empty")

        if not self.exit_reason.strip():
            raise ValueError("exit_reason must not be empty")

        # Mathematical PnL verification
        if self.side == PositionSide.LONG:
            expected_gross = (self.exit_price - self.entry_price) * self.quantity
        else:  # PositionSide.SHORT
            expected_gross = (self.entry_price - self.exit_price) * self.quantity

        if abs(self.gross_pnl - expected_gross) > Decimal("0.001"):
            raise ValueError(
                f"Declared gross_pnl ({self.gross_pnl}) does not match "
                f"expected calculation ({expected_gross:.4f})"
            )

        expected_net = self.gross_pnl - self.fees_total + self.funding_total
        if abs(self.net_pnl - expected_net) > Decimal("0.001"):
            raise ValueError(
                f"Declared net_pnl ({self.net_pnl}) does not match "
                f"expected gross_pnl - fees_total + funding_total ({expected_net:.4f})"
            )

        return self

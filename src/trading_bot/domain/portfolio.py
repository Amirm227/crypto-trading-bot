"""Portfolio snapshot domain model representing point-in-time equity, risk, and drawdowns."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    UTCDateTime,
)


class PortfolioSnapshot(DomainModel):
    """Immutable point-in-time snapshot of portfolio capital and aggregate risk."""

    snapshot_id: str
    timestamp: UTCDateTime
    total_equity: FinancialDecimal
    available_balance: FinancialDecimal
    margin_used: FinancialDecimal
    open_risk_amount: FinancialDecimal
    open_risk_pct: FinancialDecimal
    current_drawdown_pct: FinancialDecimal
    peak_equity: FinancialDecimal
    open_positions_count: int

    @model_validator(mode="after")
    def validate_portfolio_integrity(self) -> "PortfolioSnapshot":
        """Verify capital balance consistency, drawdown boundaries, and risk limits."""
        zero = Decimal("0")
        hundred = Decimal("100")

        if self.total_equity <= zero:
            raise ValueError(f"total_equity must be strictly positive (> 0), got {self.total_equity}")

        if self.available_balance < zero:
            raise ValueError(f"available_balance cannot be negative, got {self.available_balance}")

        if self.margin_used < zero:
            raise ValueError(f"margin_used cannot be negative, got {self.margin_used}")

        if self.open_risk_amount < zero:
            raise ValueError(f"open_risk_amount cannot be negative, got {self.open_risk_amount}")

        if not (zero <= self.open_risk_pct <= hundred):
            raise ValueError(f"open_risk_pct must be between 0 and 100%, got {self.open_risk_pct}")

        if not (zero <= self.current_drawdown_pct <= hundred):
            raise ValueError(
                f"current_drawdown_pct must be between 0 and 100%, got {self.current_drawdown_pct}"
            )

        if self.peak_equity < self.total_equity:
            raise ValueError(
                f"peak_equity ({self.peak_equity}) cannot be lower than total_equity ({self.total_equity})"
            )

        if self.open_positions_count < 0:
            raise ValueError(
                f"open_positions_count cannot be negative, got {self.open_positions_count}"
            )

        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")

        return self

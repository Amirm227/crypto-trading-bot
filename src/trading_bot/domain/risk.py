"""Risk decision domain model representing the mandatory risk evaluation gate."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    UTCDateTime,
)


class RiskDecision(DomainModel):
    """Immutable audit record of a risk evaluation for a candidate signal."""

    decision_id: str
    signal_id: str
    approved: bool
    rejection_codes: tuple[str, ...]
    equity_snapshot: FinancialDecimal
    risk_amount: FinancialDecimal
    quantity: FinancialDecimal
    notional: FinancialDecimal
    margin: FinancialDecimal
    config_version: str
    decided_at: UTCDateTime

    @model_validator(mode="after")
    def validate_risk_decision_integrity(self) -> "RiskDecision":
        """Enforce strict gate invariants: approved vs rejected state requirements."""
        zero = Decimal("0")
        if self.equity_snapshot <= zero:
            raise ValueError(f"equity_snapshot must be strictly positive (> 0), got {self.equity_snapshot}")

        if not self.decision_id.strip():
            raise ValueError("decision_id must not be empty")

        if not self.signal_id.strip():
            raise ValueError("signal_id must not be empty")

        if self.approved:
            if len(self.rejection_codes) > 0:
                raise ValueError(
                    f"Approved risk decision cannot contain rejection codes: {self.rejection_codes}"
                )
            if self.risk_amount <= zero:
                raise ValueError("Approved decision must have risk_amount > 0")
            if self.quantity <= zero:
                raise ValueError("Approved decision must have quantity > 0")
            if self.notional <= zero:
                raise ValueError("Approved decision must have notional > 0")
            if self.margin <= zero:
                raise ValueError("Approved decision must have margin > 0")

            # Hard risk cap: trade-level risk cannot exceed 0.25% of equity (with minimal 0.001% rounding tolerance)
            max_allowed_risk = self.equity_snapshot * Decimal("0.0025") * Decimal("1.0001")
            if self.risk_amount > max_allowed_risk:
                raise ValueError(
                    f"Risk amount ({self.risk_amount}) exceeds the 0.25% equity cap ({max_allowed_risk:.4f})"
                )
        else:
            if len(self.rejection_codes) == 0:
                raise ValueError("Rejected risk decision must specify at least one rejection code")
            if self.quantity != zero:
                raise ValueError(f"Rejected decision must have quantity == 0, got {self.quantity}")
            if self.notional != zero:
                raise ValueError(f"Rejected decision must have notional == 0, got {self.notional}")
            if self.margin != zero:
                raise ValueError(f"Rejected decision must have margin == 0, got {self.margin}")
            if self.risk_amount != zero:
                raise ValueError(f"Rejected decision must have risk_amount == 0, got {self.risk_amount}")

        return self

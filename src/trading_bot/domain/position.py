"""Position domain model representing active portfolio holdings and risk exposure."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
    PositionSide,
    UTCDateTime,
)


class Position(DomainModel):
    """Immutable representation of an active open position."""

    position_id: str
    symbol: str
    market_type: MarketType
    side: PositionSide
    quantity: FinancialDecimal
    average_entry_price: FinancialDecimal
    mark_price: FinancialDecimal
    stop_order_id: str | None = None
    target_order_id: str | None = None
    unrealized_pnl: FinancialDecimal
    realized_pnl: FinancialDecimal = Decimal("0")
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_position_integrity(self) -> "Position":
        """Verify position parameters and spot/futures constraints."""
        if self.created_at > self.updated_at:
            raise ValueError(
                f"created_at ({self.created_at}) cannot be later than updated_at ({self.updated_at})"
            )

        zero = Decimal("0")
        if self.quantity <= zero:
            raise ValueError(f"Position quantity must be strictly positive (> 0), got {self.quantity}")

        if self.average_entry_price <= zero:
            raise ValueError(
                f"average_entry_price must be strictly positive (> 0), got {self.average_entry_price}"
            )

        if self.mark_price <= zero:
            raise ValueError(f"mark_price must be strictly positive (> 0), got {self.mark_price}")

        # Spot market constraint: Short positions are prohibited on spot
        if self.market_type == MarketType.SPOT and self.side == PositionSide.SHORT:
            raise ValueError("SHORT positions are strictly prohibited on Spot markets")

        if not self.position_id.strip():
            raise ValueError("position_id must not be empty")

        return self

"""Fill domain model representing individual executed trade transactions."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    OrderSide,
    UTCDateTime,
)


class Fill(DomainModel):
    """Immutable execution fill record."""

    fill_id: str
    client_order_id: str
    exchange_trade_id: str
    symbol: str
    side: OrderSide
    price: FinancialDecimal
    quantity: FinancialDecimal
    fee: FinancialDecimal
    fee_asset: str
    timestamp: UTCDateTime

    @model_validator(mode="after")
    def validate_fill_integrity(self) -> "Fill":
        """Verify fill price, quantity, fee, and identification constraints."""
        zero = Decimal("0")
        if self.price <= zero:
            raise ValueError(f"Fill price must be strictly positive (> 0), got {self.price}")

        if self.quantity <= zero:
            raise ValueError(f"Fill quantity must be strictly positive (> 0), got {self.quantity}")

        if self.fee < zero:
            raise ValueError(f"Fill fee must be non-negative (>= 0), got {self.fee}")

        if not self.fill_id.strip():
            raise ValueError("fill_id must not be empty")

        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")

        if not self.exchange_trade_id.strip():
            raise ValueError("exchange_trade_id must not be empty")

        if not self.fee_asset.strip():
            raise ValueError("fee_asset must not be empty")

        return self

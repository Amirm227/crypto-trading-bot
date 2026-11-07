"""Order domain model representing execution intents and exchange state."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    UTCDateTime,
)


class Order(DomainModel):
    """Immutable order entity tracking lifecycle, fills, and idempotency."""

    internal_id: str
    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    market_type: MarketType
    side: OrderSide
    order_type: OrderType
    quantity: FinancialDecimal
    filled_quantity: FinancialDecimal = Decimal("0")
    price: FinancialDecimal | None = None
    stop_price: FinancialDecimal | None = None
    average_fill_price: FinancialDecimal | None = None
    status: OrderStatus = OrderStatus.CREATED
    reduce_only: bool = False
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_order_integrity(self) -> "Order":
        """Verify order quantity, pricing, status, and fill constraints."""
        if self.created_at > self.updated_at:
            raise ValueError(
                f"created_at ({self.created_at}) cannot be later than updated_at ({self.updated_at})"
            )

        zero = Decimal("0")
        if self.quantity <= zero:
            raise ValueError(f"quantity must be strictly positive (> 0), got {self.quantity}")

        if not (zero <= self.filled_quantity <= self.quantity):
            raise ValueError(
                f"filled_quantity ({self.filled_quantity}) must be between 0 and quantity ({self.quantity})"
            )

        if not self.internal_id.strip():
            raise ValueError("internal_id must not be empty")

        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")

        # Type-specific pricing requirements
        if self.order_type == OrderType.LIMIT and (self.price is None or self.price <= zero):
            raise ValueError("Limit orders require a positive price (> 0)")

        if self.order_type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET) and (
            self.stop_price is None or self.stop_price <= zero
        ):
            raise ValueError(
                f"{self.order_type} orders require a positive stop_price (> 0)"
            )

        # Fill accounting
        if self.filled_quantity > zero:
            if self.average_fill_price is None or self.average_fill_price <= zero:
                raise ValueError("Orders with filled_quantity > 0 require positive average_fill_price")
        elif self.average_fill_price is not None:
            raise ValueError("Unfilled orders cannot have an average_fill_price")

        # Status consistency
        if self.status == OrderStatus.FILLED and self.filled_quantity != self.quantity:
            raise ValueError(
                f"Order marked FILLED but filled_quantity ({self.filled_quantity}) != quantity ({self.quantity})"
            )

        if self.status in (OrderStatus.CREATED, OrderStatus.SUBMITTED) and self.filled_quantity != zero:
            raise ValueError(
                f"Order in {self.status} status must have filled_quantity == 0, got {self.filled_quantity}"
            )

        return self

"""Market regime domain model for 4H classification state."""

from decimal import Decimal

from pydantic import model_validator

from trading_bot.domain.types import (
    DomainModel,
    FinancialDecimal,
    RegimeType,
    TimeFrame,
    UTCDateTime,
)


class MarketRegime(DomainModel):
    """Immutable market regime snapshot for an asset."""

    symbol: str
    timeframe: TimeFrame
    regime: RegimeType
    confidence: FinancialDecimal
    features: dict[str, FinancialDecimal]
    detected_at: UTCDateTime
    detector_version: str
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_regime_integrity(self) -> "MarketRegime":
        """Verify regime confidence bounds and metadata."""
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not self.detector_version.strip():
            raise ValueError("detector_version must not be empty")
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        return self

"""System and risk event models for structured auditing and telemetry."""

from trading_bot.domain.types import (
    DomainModel,
    EventSeverity,
    FinancialDecimal,
    UTCDateTime,
)


class RiskEvent(DomainModel):
    """Immutable audit record of a risk-related event or circuit breaker trigger."""

    event_id: str
    timestamp: UTCDateTime
    component: str
    event_type: str
    severity: EventSeverity
    context: dict[str, str | int | FinancialDecimal | bool]
    action_taken: str


class BotEvent(DomainModel):
    """Immutable audit record of an operational system or lifecycle event."""

    event_id: str
    timestamp: UTCDateTime
    component: str
    event_type: str
    severity: EventSeverity
    context: dict[str, str | int | FinancialDecimal | bool]
    action_taken: str

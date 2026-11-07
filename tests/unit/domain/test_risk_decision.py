"""Unit tests for RiskDecision domain model and gate invariants."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_bot.domain.risk import RiskDecision


def test_valid_approved_risk_decision() -> None:
    """Ensure a compliant approved decision is constructed within the 0.25% risk cap."""
    now = datetime.now(UTC)
    # Equity = $1000 -> 0.25% risk cap = $2.50
    dec = RiskDecision(
        decision_id="risk-001",
        signal_id="sig-001",
        approved=True,
        rejection_codes=(),
        equity_snapshot=Decimal("1000.00"),
        risk_amount=Decimal("2.50"),   # exactly 0.25%
        quantity=Decimal("0.0025"),
        notional=Decimal("175.00"),
        margin=Decimal("175.00"),
        config_version="risk_v1.0",
        decided_at=now,
    )
    assert dec.approved is True
    assert dec.risk_amount == Decimal("2.50")


def test_valid_rejected_risk_decision() -> None:
    """Ensure a rejected decision has zero allocation and documented rejection codes."""
    now = datetime.now(UTC)
    dec = RiskDecision(
        decision_id="risk-002",
        signal_id="sig-002",
        approved=False,
        rejection_codes=("DAILY_LOSS_LIMIT_EXCEEDED",),
        equity_snapshot=Decimal("1000.00"),
        risk_amount=Decimal("0"),
        quantity=Decimal("0"),
        notional=Decimal("0"),
        margin=Decimal("0"),
        config_version="risk_v1.0",
        decided_at=now,
    )
    assert dec.approved is False
    assert "DAILY_LOSS_LIMIT_EXCEEDED" in dec.rejection_codes


def test_risk_decision_rejects_over_cap_risk() -> None:
    """Ensure risk_amount exceeding 0.25% of equity is rejected."""
    now = datetime.now(UTC)
    # Equity = $1000, 0.25% cap = $2.50, attempted risk = $5.00 (0.5%)
    with pytest.raises(ValidationError) as exc:
        RiskDecision(
            decision_id="risk-over-cap",
            signal_id="sig-001",
            approved=True,
            rejection_codes=(),
            equity_snapshot=Decimal("1000.00"),
            risk_amount=Decimal("5.00"),  # Exceeds 0.25% limit
            quantity=Decimal("0.005"),
            notional=Decimal("350.00"),
            margin=Decimal("350.00"),
            config_version="risk_v1.0",
            decided_at=now,
        )
    assert "exceeds the 0.25% equity cap" in str(exc.value)


def test_approved_decision_cannot_have_rejection_codes() -> None:
    """Ensure approved decisions cannot carry rejection codes."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        RiskDecision(
            decision_id="risk-invalid-approved",
            signal_id="sig-001",
            approved=True,
            rejection_codes=("SOME_WARNING",),
            equity_snapshot=Decimal("1000.00"),
            risk_amount=Decimal("2.00"),
            quantity=Decimal("0.002"),
            notional=Decimal("140.00"),
            margin=Decimal("140.00"),
            config_version="risk_v1.0",
            decided_at=now,
        )
    assert "cannot contain rejection codes" in str(exc.value)


def test_rejected_decision_must_have_rejection_codes() -> None:
    """Ensure rejected decisions without an audit reason are rejected."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        RiskDecision(
            decision_id="risk-empty-rejection",
            signal_id="sig-001",
            approved=False,
            rejection_codes=(),
            equity_snapshot=Decimal("1000.00"),
            risk_amount=Decimal("0"),
            quantity=Decimal("0"),
            notional=Decimal("0"),
            margin=Decimal("0"),
            config_version="risk_v1.0",
            decided_at=now,
        )
    assert "specify at least one rejection code" in str(exc.value)


def test_rejected_decision_must_have_zero_allocations() -> None:
    """Ensure rejected decisions cannot hold non-zero quantity or risk."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc:
        RiskDecision(
            decision_id="risk-nonzero-alloc",
            signal_id="sig-001",
            approved=False,
            rejection_codes=("TEST_REASON",),
            equity_snapshot=Decimal("1000.00"),
            risk_amount=Decimal("0"),
            quantity=Decimal("0.05"),  # Invalid for rejected
            notional=Decimal("0"),
            margin=Decimal("0"),
            config_version="risk_v1.0",
            decided_at=now,
        )
    assert "quantity == 0" in str(exc.value)

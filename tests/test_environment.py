"""Baseline environment and packaging verification tests."""

import sys
from decimal import Decimal
from pathlib import Path

import trading_bot


def test_python_version() -> None:
    """Ensure running on Python 3.11+."""
    assert sys.version_info >= (3, 11), f"Requires Python 3.11+, got {sys.version}"


def test_package_installed() -> None:
    """Ensure trading_bot package is importable and versioned."""
    assert trading_bot.__version__ == "0.1.0"


def test_decimal_precision() -> None:
    """Ensure Decimal arithmetic functions strictly without float rounding errors."""
    val1 = Decimal("0.1")
    val2 = Decimal("0.2")
    expected = Decimal("0.3")
    assert val1 + val2 == expected
    assert val1 + val2 != 0.30000000000000004  # float behavior rejected


def test_env_example_safety() -> None:
    """Ensure .env.example exists, is uncommitted to actual secrets, and has safe defaults."""
    env_example = Path(".env.example")
    assert env_example.exists(), ".env.example must exist"
    content = env_example.read_text(encoding="utf-8")
    assert "ENABLE_LIVE_TRADING=false" in content
    assert "ALLOW_WITHDRAWALS=false" in content
    assert "FUTURES_LEVERAGE=1" in content
    assert "MARGIN_MODE=isolated" in content
    assert "ALLOW_CROSS_MARGIN=false" in content
    assert "placeholder" in content

"""Unit tests ensuring dangerous and unsafe database targets are strictly rejected.

Guarantees tests will never execute destructive SQL against default, production,
or ambiguous databases.
"""

import pytest

from trading_bot.persistence.database import (
    DANGEROUS_TARGET_DATABASES,
    validate_test_database_url,
)
from trading_bot.persistence.exceptions import UnsafeDatabaseTargetError


def test_validate_test_database_url_rejects_empty() -> None:
    """Empty database URL must fail validation immediately."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url("")
    assert "cannot be empty" in str(exc.value)


@pytest.mark.parametrize("db_name", sorted(DANGEROUS_TARGET_DATABASES))
def test_validate_test_database_url_rejects_dangerous_names(db_name: str) -> None:
    """Known dangerous, production, and default database names must be rejected."""
    url = f"postgresql+asyncpg://user:password@localhost:5432/{db_name}"
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url(url)
    assert "Unsafe database target for destructive integration tests" in str(exc.value)
    assert db_name in str(exc.value)


@pytest.mark.parametrize(
    "ambiguous_url",
    [
        "postgresql+asyncpg://user:password@localhost:5432/crypto_data",
        "postgresql+asyncpg://user:password@localhost:5432/app_development",
        "postgresql+asyncpg://user:password@localhost:5432/staging_db",
    ],
)
def test_validate_test_database_url_rejects_missing_test_token(ambiguous_url: str) -> None:
    """URLs lacking 'test' token must be rejected even if not in explicitly banned list."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url(ambiguous_url)
    assert "must explicitly contain 'test'" in str(exc.value)


@pytest.mark.parametrize(
    "valid_test_url",
    [
        "postgresql+asyncpg://user:password@localhost:5432/trading_bot_test",
        "postgresql+asyncpg://user:password@localhost:5432/test_db",
        "postgresql+asyncpg://user:password@localhost:5432/ci_test_run",
        "sqlite+aiosqlite:///:memory:",
        "sqlite+aiosqlite:///file_test.db",
    ],
)
def test_validate_test_database_url_accepts_valid_test_targets(valid_test_url: str) -> None:
    """Explicitly isolated test database names are permitted."""
    # Should not raise
    validate_test_database_url(valid_test_url)


def test_malformed_url_rejected() -> None:
    """Malformed URL string must raise UnsafeDatabaseTargetError."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url("invalid-scheme://")
    assert "Malformed database URL" in str(exc.value) or "missing" in str(exc.value)

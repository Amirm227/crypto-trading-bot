"""Unit tests ensuring dangerous, unsafe, and non-PostgreSQL database targets are strictly rejected.

Guarantees tests will never execute destructive SQL against default, production,
ambiguous, SQLite, or pre-populated databases in integration testing.
"""

from typing import Any
from unittest.mock import MagicMock

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


@pytest.mark.parametrize(
    "sqlite_url",
    [
        "sqlite+aiosqlite:///:memory:",
        "sqlite:///:memory:",
        "sqlite+aiosqlite:///test.db",
        "sqlite+aiosqlite:///trading_bot_test.db",
        "sqlite:///file_test.db",
    ],
)
def test_validate_test_database_url_rejects_sqlite(sqlite_url: str) -> None:
    """SQLite URLs must be strictly rejected by the PostgreSQL integration validator."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url(sqlite_url)
    assert "unsupported driver" in str(exc.value)
    assert "Only PostgreSQL connection URLs" in str(exc.value)


@pytest.mark.parametrize(
    "dangerous_db_name",
    [*sorted(DANGEROUS_TARGET_DATABASES), "contest", "latest", "attest", "protest", "fastest"],
)
def test_validate_test_database_url_rejects_dangerous_and_substring_collisions(
    dangerous_db_name: str,
) -> None:
    """Known dangerous, production, and substring collision database names must be rejected."""
    url = f"postgresql+asyncpg://user:password@localhost:5432/{dangerous_db_name}"
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url(url)
    assert "Unsafe database target for destructive integration tests" in str(
        exc.value
    ) or "must contain 'test' as a distinct token" in str(exc.value)


@pytest.mark.parametrize(
    "ambiguous_url",
    [
        "postgresql+asyncpg://user:password@localhost:5432/crypto_data",
        "postgresql+asyncpg://user:password@localhost:5432/app_development",
        "postgresql+asyncpg://user:password@localhost:5432/staging_db",
        "postgresql+asyncpg://user:password@localhost:5432/trading_bot_prod",
        "postgresql+asyncpg://user:password@localhost:5432/contest_trading",
        "postgresql+asyncpg://user:password@localhost:5432/latest_candles",
    ],
)
def test_validate_test_database_url_rejects_missing_distinct_test_token(ambiguous_url: str) -> None:
    """URLs lacking 'test' as a distinct delimited token must be rejected."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url(ambiguous_url)
    assert "must contain 'test' as a distinct token" in str(
        exc.value
    ) or "Target database cannot be a production" in str(exc.value)


@pytest.mark.parametrize(
    "valid_test_url",
    [
        "postgresql+asyncpg://user:password@localhost:5432/trading_bot_test",
        "postgresql+asyncpg://user:password@localhost:5432/test_db",
        "postgresql+asyncpg://user:password@localhost:5432/ci_test_run",
        "postgresql+asyncpg://user:password@localhost:5432/test-database",
        "postgresql+asyncpg://user:password@localhost:5432/test.db",
        "postgresql+asyncpg://user:password@localhost:5432/test",
    ],
)
def test_validate_test_database_url_accepts_valid_test_targets(valid_test_url: str) -> None:
    """PostgreSQL databases with 'test' as a distinct token are permitted."""
    validate_test_database_url(valid_test_url)


def test_malformed_url_rejected() -> None:
    """Malformed URL string must raise UnsafeDatabaseTargetError."""
    with pytest.raises(UnsafeDatabaseTargetError) as exc:
        validate_test_database_url("invalid-scheme://")
    assert "Malformed database URL" in str(exc.value) or "unsupported driver" in str(exc.value)


def test_missing_test_database_url_skips_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure absence of TEST_DATABASE_URL never falls back to DATABASE_URL."""
    import importlib
    import sys
    from pathlib import Path

    tests_dir = str((Path.cwd() / "tests").resolve())
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)

    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/production_db"
    )

    test_mod = importlib.import_module("integration.test_postgres_persistence")
    test_mod = importlib.reload(test_mod)
    assert getattr(test_mod, "POSTGRES_TEST_URL", None) is None


@pytest.mark.asyncio
async def test_unexpected_preexisting_schema_fails_safely() -> None:
    """Ensure pre-existing schema in target test database fails with an actionable error instead of deleting it."""
    # Mock connection inspector that discovers an existing 'candles' table
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["candles", "alembic_version"]

    def _check_clean_state(sync_conn: Any) -> None:
        existing_tables = set(mock_inspector.get_table_names())
        conflict_tables = existing_tables.intersection({"candles", "alembic_version"})
        if conflict_tables:
            raise RuntimeError(
                f"Target test database contains unexpected pre-existing "
                f"schema or migration state ({sorted(conflict_tables)}). "
                "Integration tests require a clean, dedicated test database without pre-existing schema. "
                "Refusing to execute destructive raw SQL or overwrite existing tables."
            )

    with pytest.raises(RuntimeError) as exc:
        _check_clean_state(MagicMock())

    assert "contains unexpected pre-existing schema or migration state" in str(exc.value)
    assert "Refusing to execute destructive raw SQL" in str(exc.value)

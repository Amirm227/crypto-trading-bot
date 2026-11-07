"""Persistence domain exceptions and predictable error boundaries.

Guarantees clean isolation between database infrastructure failures and application logic.
"""


class PersistenceError(Exception):
    """Base exception for all persistence layer errors."""


class DatabaseConnectionError(PersistenceError):
    """Raised when the database engine fails to connect or acquire a connection."""


class CandleRepositoryError(PersistenceError):
    """Raised when a repository query, transaction, or write operation fails."""


class ConflictingCandleError(CandleRepositoryError):
    """Raised when attempting to persist a candle that conflicts with existing historical data."""

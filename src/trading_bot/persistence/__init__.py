"""Data storage layer, repositories, and PostgreSQL interactions."""

from trading_bot.persistence.database import DatabaseManager, create_database_manager
from trading_bot.persistence.exceptions import (
    CandleRepositoryError,
    ConflictingCandleError,
    DatabaseConnectionError,
    PersistenceError,
)
from trading_bot.persistence.models import Base, CandleModel
from trading_bot.persistence.repository import PostgresCandleRepository

__all__ = [
    "Base",
    "CandleModel",
    "CandleRepositoryError",
    "ConflictingCandleError",
    "DatabaseConnectionError",
    "DatabaseManager",
    "PersistenceError",
    "PostgresCandleRepository",
    "create_database_manager",
]

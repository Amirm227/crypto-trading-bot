"""Create candles table with composite uniqueness constraint and indexes.

Revision ID: 0001
Revises: None
Create Date: 2026-11-07 20:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create candles table, composite unique constraint, and performance indexes."""
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market_type", sa.String(length=16), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "exchange",
            "symbol",
            "market_type",
            "timeframe",
            "open_time",
            name="uq_candles_series_open_time",
        ),
    )
    op.create_index(
        "ix_candles_query",
        "candles",
        ["exchange", "symbol", "market_type", "timeframe", "open_time"],
        unique=False,
    )
    op.create_index(
        "ix_candles_latest",
        "candles",
        ["exchange", "symbol", "market_type", "timeframe", "is_closed", "open_time"],
        unique=False,
    )


def downgrade() -> None:
    """Drop indexes, constraints, and candles table."""
    op.drop_index("ix_candles_latest", table_name="candles")
    op.drop_index("ix_candles_query", table_name="candles")
    op.drop_constraint("uq_candles_series_open_time", "candles", type_="unique")
    op.drop_table("candles")

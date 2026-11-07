# ADR-003: PostgreSQL for Primary Persistence and Audit Trail

## Status
Accepted

## Date
2026-11-07

## Context
The bot requires durable, auditable, and queryable storage for historical candles, indicator snapshots, regime classifications, candidate signals, risk decisions, orders, fills, positions, trades, and risk events. Data integrity, relational foreign keys, and auditability are non-negotiable.

## Decision
We adopt **PostgreSQL** as the primary relational database for the trading system, using SQLAlchemy (asyncio) and Alembic for schema migrations.

## Alternatives Considered
1. **SQLite:** Simple embedded database. While SQLite is suitable for lightweight local storage or in-memory unit test mocks, it lacks native concurrent write performance, robust network access, advanced window functions, and timeseries partitioning needed for production analytics.
2. **NoSQL / MongoDB:** Document-oriented database. Rejected due to lack of strict ACID relational guarantees across financial ledgers, risk decisions, orders, and fills.
3. **Pure Timeseries DB (InfluxDB / TimescaleDB extension alone):** Rejected as a standalone solution because relational entities (trades, orders, fills, risk decisions) require strong relational constraints and foreign keys.

## Rationale
PostgreSQL provides ACID compliance, rock-solid reliability, powerful indexing, JSONB support for flexible metadata, and full relational integrity across all trading entities. TimescaleDB extension can be added in the future if timeseries volume demands hypertable partitioning.

## Consequences
### Positive
- Strict referential integrity between signals, risk decisions, orders, fills, and trades.
- Immutable audit log of all system decisions and rejected signals.
- Familiar SQL querying for post-trade analysis, reconciliation, and compliance reporting.

### Negative / Trade-offs
- Requires running a PostgreSQL server (e.g. via Docker or managed service).
- Slightly more setup complexity compared to file-based or SQLite storage.

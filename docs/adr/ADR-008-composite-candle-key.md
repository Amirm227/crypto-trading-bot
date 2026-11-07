# ADR-008: Composite Unique Key Refinement for OHLCV Candle Storage

## Status
Accepted

## Date
2026-11-07

## Context
In ADR-003 and the initial architectural specification (`docs/ARCHITECTURE.md`), the unique candlestick constraint was defined as:

`(exchange, symbol, timeframe, open_time)`

In Task 1.2, the system introduced support for both Spot and USDT-M Linear Perpetual Futures public market data. On centralized cryptocurrency exchanges (such as Binance), spot and derivative markets frequently share identical base and quote assets (e.g., BTC/USDT), timeframe resolutions (e.g., 1h), and candle timestamp boundaries (e.g., 2026-11-07 10:00:00 UTC).

Under the original 4-part unique key, a 1h BTC/USDT spot candle and a 1h BTC/USDT perpetual futures candle sharing the same open timestamp would collide at the database level. Depending on insertion mechanics, this collision would either result in duplicate key violation errors, prevent storage of one market's candles, or silently overwrite historical spot data with futures data (or vice versa).

## Decision
We refine the unique key and persistence schema for candlesticks by including the `market_type` discriminator, establishing the composite unique key:

`(exchange, symbol, market_type, timeframe, open_time)`

To ensure end-to-end consistency and type safety across domain and persistence layers:
1. The domain `Candle` model is extended with `market_type: MarketType = MarketType.SPOT`. Callers may explicitly pass `MarketType.FUTURES` or `MarketType.SPOT`. For backwards compatibility, if omitted, `market_type` defaults to `MarketType.SPOT` unless a futures symbol convention is detected.
2. The database table `candles` enforces a unique constraint on `(exchange, symbol, market_type, timeframe, open_time)`.
3. Range queries and latest-candle queries filter by `market_type` in addition to `exchange`, `symbol`, and `timeframe`.

## Alternatives Considered
1. **Relying solely on symbol string conventions (e.g. `:USDT` suffix):**
   Relying on symbol formatting alone is brittle across different exchanges and normalization adapters. Some exchanges use identical tickers for spot and contracts, or normalize them differently across data feeds.
2. **Partitioning into separate tables (`candles_spot`, `candles_futures`):**
   Rejected as premature and overly complex. It doubles table migrations, duplicates repository query logic, and complicates cross-market analytics and backtesting engines that correlate spot and perpetual prices.

## Rationale
Explicitly including `market_type` in the composite unique key provides guaranteed uniqueness at the database engine level, prevents cross-instrument data collisions, ensures transactional idempotency during concurrent ingestion, and cleanly aligns the relational model with the domain contracts.

## Consequences
### Positive
- Prevents collision and silent overwrite between Spot and Perpetual Futures instruments.
- Enables clean, independent queries for spot vs futures candles for the same asset.
- Retains backwards compatibility with existing domain constructors.
- Preserves referential integrity for downstream indicator calculation, regime detection, and backtesting.

### Negative / Trade-offs
- The composite unique index includes 5 columns instead of 4, incurring minimal additional index storage overhead.

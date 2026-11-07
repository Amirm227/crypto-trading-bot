# ADR-002: CCXT-Based Exchange Adapter Abstraction Layer

## Status
Accepted

## Date
2026-11-07

## Context
The bot must interact with crypto exchanges for market data retrieval, account balance queries, order creation, order cancellation, and fill synchronization across Spot and Linear Futures markets for BTC, ETH, and SOL. Direct exchange API coupling tightly binds business logic to proprietary REST/WebSocket schemas.

## Decision
We define an explicit `ExchangeAdapter` protocol interface in `src/trading_bot/exchanges/` and implement the primary exchange integration using `CCXT` behind this interface. All domain models and execution modules communicate solely through the abstract `ExchangeAdapter` contract.

## Alternatives Considered
1. **Direct Native REST/WebSocket Client per Exchange:** Implementing custom HTTP/WebSocket clients for each exchange from scratch. Rejected due to high development overhead, maintenance burden with frequent exchange API updates, and slow iteration.
2. **Direct Direct In-line CCXT Usage in Strategies/Execution:** Calling CCXT functions directly from strategies or execution engine. Rejected because CCXT does not fully normalize complex exchange behaviors (such as hedge mode, reduce-only flags, conditional stops, fee structures, and exchange-specific error codes), which violates domain separation.

## Rationale
Wrapping CCXT within a strictly typed adapter protocol gives us access to a mature, maintained connectivity layer for exchange APIs while allowing us to enforce domain-level normalization, capability tracking (`SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`), client order ID idempotency, and protective order handling.

## Consequences
### Positive
- Strategy and execution engines are exchange-agnostic.
- Mock adapters can be cleanly substituted in unit and integration tests.
- Normalized data models (Symbols, Precisions, Order Statuses).

### Negative / Trade-offs
- CCXT adds an external dependency that must be monitored for updates and regressions.
- Nuanced exchange features (e.g., custom trigger types or exchange-specific margin modes) require explicit adapter-level normalization.

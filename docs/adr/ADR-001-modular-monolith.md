# ADR-001: Modular Monolith Architecture

## Status
Accepted

## Date
2026-11-07

## Context
The system needs to ingest market data, compute indicators, classify market regimes, run three trading strategies, evaluate risk, manage orders, and support both historical backtesting and paper trading. We need an architectural design that ensures clear boundaries, maintainability, low operational complexity, and future scalability.

## Decision
We adopt a **Modular Monolith** architecture implemented as a single Python codebase with strict logical boundaries between components (Domain, Market Data, Indicators, Regime, Strategy, Risk, Portfolio, Execution, Adapter, Backtesting, Persistence, and Monitoring).

## Alternatives Considered
1. **Microservices Architecture:** Splitting the bot into independent services (Data Service, Strategy Service, Risk Service, Order Service) communicating over gRPC or message queues. Rejected due to high operational complexity, distributed state synchronization overhead, network latency, and premature optimization for an MVP managing 3 assets.
2. **Monolithic Script / Sprawl:** Single flat script or loosely structured repository. Rejected due to lack of testability, tight coupling between data and execution, and inability to cleanly share strategy code between backtest and live execution.

## Rationale
A modular monolith gives the organizational benefits of microservices (clean boundaries, decoupled business logic, independent testability) while running within a single runtime process. This eliminates distributed failure modes, network serialization overhead, and deployment friction. If future scale requires microservices (e.g. distributed backtesting clusters), the well-defined module boundaries make extraction straightforward.

## Consequences
### Positive
- Zero network latency between strategy evaluation and risk checks.
- Atomic in-process state consistency.
- Simplified local development, testing, and debugging.
- Minimal operational infrastructure requirements.

### Negative / Trade-offs
- Process crashes take down all components together (mitigated by external supervisor / restart mechanisms and crash-recovery state machines).
- Long-running computational tasks (like heavy backtests) must be run via separate scripts rather than inside the real-time bot process.

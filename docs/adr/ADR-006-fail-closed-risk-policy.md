# ADR-006: Fail-Closed Risk Policy and Mandatory Circuit Breakers

## Status
Accepted

## Date
2026-11-07

## Context
In financial automation, system failures (network timeouts, unhandled exceptions, database disconnects, API rate-limiting, stale data, unexpected market regimes, or missing protective stops) can lead to catastrophic losses if the system attempts to continue trading or makes optimistic assumptions.

## Decision
The system adopts a strict, non-negotiable **Fail-Closed** design philosophy:
1. Every candidate order requires affirmative, recorded approval from the Risk Engine. Absence of approval or an exception during evaluation defaults to an immediate rejection.
2. Incomplete candles, stale market data, or timestamp gaps immediately halt candidate signal generation (`Entry Halt`).
3. An unknown order state (`UNKNOWN`) or unconfirmed protective stop halts all new entries until explicit reconciliation occurs.
4. If Daily Loss (0.75%), Weekly Loss (2.00%), or Max Drawdown (8.00%) is breached, circuit breakers immediately trigger an Entry Halt or Emergency Halt.
5. In no circumstances does the system increase position sizes to recover past losses (Martingale is strictly prohibited).

## Alternatives Considered
1. **Fail-Open / Best-Effort Execution:** Continuing to process trades during degraded states to maximize trading opportunities. Rejected as unacceptable; capital preservation is the primary directive.
2. **Optimistic Order Retry:** Resubmitting orders upon network timeouts without querying exchange order state first. Rejected because blind retries cause duplicate fills and unhedged overexposure.

## Rationale
In algorithmic trading, preventing catastrophic drawdown is far more critical than capturing every market move. Trading bots survive long-term by prioritizing downside protection over aggressive availability.

## Consequences
### Positive
- Strict capital protection under operational anomalies and market turbulence.
- Audit trail explicitly records reasons for all trade rejections and halts.
- Predictable and bounded downside risk.

### Negative / Trade-offs
- The system may miss valid market opportunities during brief transient network blips or backfill cycles.
- Requires operator intervention to clear emergency halts after manual inspection.

# ADR-005: Shared Strategy and Risk Core Across Backtesting and Execution

## Status
Accepted

## Date
2026-11-07

## Context
A major failure mode in algorithmic trading systems is code divergence between backtesting research scripts and production execution bots. When strategy or risk algorithms are reimplemented separately for backtesting versus live trading, subtle discrepancy bugs (e.g., look-ahead bias, off-by-one candle indexing, differing fee calculations, uncoordinated slippage) create false expectations and live capital loss.

## Decision
The core domain engines—specifically the Indicator Engine, Regime Detector, Strategy Manager, Signal Engine, and Risk Engine—must be single, unified, pure implementations shared identically across Historical Backtesting, Out-of-Sample Walk-Forward testing, Paper Trading, and Live execution. Only the Market Data Source (Historical vs. Live) and the Order Execution Layer (Simulator vs. Exchange Adapter) differ.

## Alternatives Considered
1. **Third-Party Backtesting Framework (Backtrader / VectorBT / Lean):** Writing strategies using framework-specific DSLs for backtesting and rewriting them in custom code for production execution. Rejected because dual-implementation introduces translation bugs and discrepancies.
2. **Post-Hoc Live Porting:** Developing strategies in standalone notebooks and manually porting logic to the bot runtime. Rejected due to poor auditability, versioning drift, and high bug risk.

## Rationale
By writing strategies as pure functions taking typed domain candles/indicators and emitting typed signals, and risk checks as deterministic gates taking typed account snapshots, the exact same tested code paths run against historical data and live streams. This ensures what was tested is what executes.

## Consequences
### Positive
- Zero logic divergence between backtest simulation and real-world execution.
- Single source of truth for strategy and risk parameters.
- Comprehensive unit and scenario tests validate both backtesting and production behaviors simultaneously.

### Negative / Trade-offs
- Backtesting performance is bound to the discrete event model rather than highly vectorized matrix calculations, but runtime for 1H/4H timeframes over multi-year periods remains very fast (seconds to minutes).

# ADR-004: Python Decimal for All Financial and Risk Calculations

## Status
Accepted

## Date
2026-11-07

## Context
Financial calculations involving prices, quantities, notional values, risk budgets, stop distances, exchange fees, funding rates, and realized/unrealized PnL are vulnerable to IEEE 754 floating-point inaccuracies (e.g., `0.1 + 0.2 != 0.3`). Accumulating floating-point inaccuracies can lead to incorrect position sizing, violated risk limits, or invalid order submissions rejected by exchange precision rules.

## Decision
All monetary values, prices, asset amounts, fee calculations, risk percentages, and PnL metrics must be represented and computed using Python's `Decimal` type. Standard IEEE 754 `float` is strictly prohibited for financial state and risk evaluations.

## Alternatives Considered
1. **IEEE 754 Floats:** Native Python `float`. Rejected due to non-deterministic precision loss, representation errors, and potential boundary violations in risk caps.
2. **Integer Arithmetic (Fixed-Point / Satoshis / Cents):** Storing all amounts as integers scaled by `10^8` or `10^18`. Rejected due to added cognitive complexity across varying decimal precisions for BTC (8), ETH (18/8), SOL (9), and USD quotes (2/4/6), increasing conversion bug risk.

## Rationale
Python's built-in `Decimal` module provides exact decimal arithmetic with configurable rounding modes (e.g., `ROUND_DOWN` for lot sizing to prevent exceeding risk budgets). It eliminates subtle float rounding bugs entirely and aligns directly with database `NUMERIC` / `DECIMAL` types.

## Consequences
### Positive
- Absolute precision in risk sizing, cash ledgers, fee tracking, and PnL.
- Complete deterministic reproducibility between backtest, paper, and audit logs.
- Safe conservative rounding enforcement (e.g. truncation toward zero for position sizes).

### Negative / Trade-offs
- Slight performance overhead compared to native C-level float operations (negligible for 1H/4H candle-based trading systems).
- Explicit casting required when interfacing with numerical libraries (e.g., converting numpy arrays to Decimal at the indicator-to-domain boundary).

# Backtesting and Validation Specification

See [docs/ARCHITECTURE.md](ARCHITECTURE.md#12-backtesting-and-validation) for the complete backtesting specification.

## Core Rules

1. **Shared Core:** Backtester uses the exact same Strategy and Risk Engine modules as Live/Paper trading.
2. **Zero Look-Ahead Bias:** Closed candles only. Indicator calculations use historical windows strictly.
3. **Execution Realism:**
   - Explicit fee schedule (Maker/Taker).
   - Conservative slippage model.
   - Funding rate impact for futures.
   - Conservative collision rule: if both stop and target are touched in the same candle without verifiable sub-candle sequence, assume the Stop was triggered first.
4. **Data Separation:**
   - In-Sample (training/initial parameter evaluation).
   - Validation (limited hyperparameter check).
   - Out-of-Sample (unseen test period).
   - Walk-Forward (rolling window validation).

# Strategy Specifications

See [docs/ARCHITECTURE.md](ARCHITECTURE.md#8-strategy-rules) for the complete strategy specifications.

## Overview

The trading system employs three distinct strategy families activated selectively by Market Regime (detected on the 4H timeframe):

1. **Trend Following (4H Regime, 1H Entry):**
   - Active in Bullish Trend (Long) and Bearish Trend (Short, Futures-only).
   - EMA20/50 pullback within EMA200 trend, ADX > 25, RSI filtering.
   - Entry on confirmed close; minimum R:R = 1:2.

2. **Mean Reversion (1H Timeframe):**
   - Active exclusively in Sideways Regime (ADX < 20).
   - Bollinger Band (20,2) penetration and re-entry with RSI overextension.
   - Prohibited during active trends; minimum R:R = 1:2.

3. **Breakout (1H Timeframe):**
   - Active in Bullish Trend (Long) and Bearish Trend (Short, Futures-only).
   - 20-period Donchian channel breakout confirmed by Volume > 1.5x Volume SMA(20).
   - Anti-chase ATR filters; minimum R:R = 1:2.

## Conflict Resolution

- Single strategy ownership per symbol.
- Same-direction signals share the risk budget; risk is never doubled.
- Opposing candidate signals for the same symbol are both rejected by default.
- Signals enforce a strict Time-to-Live (TTL).

# ADR-007: Mandatory Paper Trading Verification Before Live Trading

## Status
Accepted

## Date
2026-11-07

## Context
Deploying an algorithmic trading system directly to live financial markets based solely on backtested metrics exposes capital to unseen real-world risks: exchange order queue latency, slippage discrepancies, WebSocket disconnects, partial fill nuances, API rate limits, and market impact.

## Decision
No live capital trading is permitted until the system has successfully completed and passed all preceding testing gates:
1. **Gate 1:** Unit, integration, and scenario tests pass 100%.
2. **Gate 2:** Historical backtest across full market cycles shows positive net expectancy after all fees, realistic slippage, and funding costs.
3. **Gate 3:** Out-of-sample and walk-forward evaluations confirm robustness without significant degradation.
4. **Gate 4:** A minimum of 4 to 8 weeks (or statistically significant trade count) of continuous Paper Trading is completed on live market feeds with zero unhandled exceptions, zero duplicate orders, valid reconciliation, and acceptable tracking against simulated performance.
5. **Gate 5:** Explicit human operator sign-off and API credentials configured with trade-only permissions (withdrawals disabled).

## Alternatives Considered
1. **Immediate Live Trading with Small Capital:** Skipping Paper Trading and deploying directly with minimal capital (e.g. $100). Rejected because real-money micro-testing can still incur unnecessary losses and fails to validate exchange idiosyncrasies systematically under stress without risk.
2. **Backtest-Only Deployment:** Moving straight from backtest to live. Rejected as irresponsible quant engineering due to high likelihood of unmodeled execution biases.

## Rationale
Mandatory paper trading on real-time market data serves as an essential flight simulator. It exposes subtle timing bugs, edge-case market states, and exchange API edge cases in a zero-risk environment before real capital is committed.

## Consequences
### Positive
- Thorough validation of the entire execution stack and exchange connectivity under real-world conditions.
- Zero risk to capital during the stabilization and burn-in period.
- Builds operational confidence and empirical performance baselines.

### Negative / Trade-offs
- Delays live deployment by several weeks to accumulate statistically significant forward testing data.

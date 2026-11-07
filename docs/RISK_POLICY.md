# Risk Policy Specification

See [docs/ARCHITECTURE.md](ARCHITECTURE.md#9-risk-management) for the complete risk policy.

## Non-Negotiable Limits

| Parameter | Limit | Enforcement Mechanism |
|---|---|---|
| Per-Trade Risk | 0.25% of Equity | Hard rejection in Risk Engine |
| Total Open Risk | 0.50% of Equity | Sum of stop distances across all positions |
| Daily Loss Limit | 0.75% of UTC day start equity | Entry Halt triggered on breach |
| Weekly Loss Limit | 2.00% of UTC week start equity | Entry Halt triggered on breach |
| Max Drawdown | 8.00% from Peak Equity | Emergency Halt triggered on breach |
| Max New Trades / Day | 3 trades | Daily counter enforced |
| Minimum R:R | 1:2 (after fees and slippage) | Discard signal if < 2.0 |
| Leverage | 1x Isolated | Cross-margin strictly prohibited |
| Martingale | Prohibited | Never scale up on losing positions |
| Fail-Closed | Mandatory | Reject entries on stale data or ambiguous state |

## Position Sizing Formula

```text
risk_budget = equity * risk_per_trade
stop_distance = abs(entry_price - stop_price)
raw_quantity = risk_budget / stop_distance
```

If rounding up to meet exchange minimum notional or lot size pushes risk above `risk_budget`, the order is rejected. Never increase risk to meet exchange minimums.

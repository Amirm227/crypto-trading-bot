# Operational Runbook

See [docs/ARCHITECTURE.md](ARCHITECTURE.md#14-infrastructure-security-and-observability) for security and observability details.

## Emergency Procedures

### 1. Kill Switch Activation
- **Entry Halt:** Halts all new candidate signal generation and entry order creation. Active positions continue to be monitored for stop/target exits.
- **Emergency Halt:** Immediately cancels all pending orders, places protective market stops or executes emergency de-risking as specified by safety policies.

### 2. Reconciliation Discrepancy
- If internal position/balance state deviates from exchange state:
  1. System triggers immediate `Entry Halt`.
  2. High-severity alert is emitted.
  3. Operator inspects logs and runs `scripts/reconcile.py`.
  4. System does NOT resume until manual verification is completed.

### 3. Stale Market Data
- If no closed candle arrives within permitted tolerance:
  1. New signal generation is disabled.
  2. System initiates backfill and gap check.
  3. Signal generation resumes only once continuity is restored.

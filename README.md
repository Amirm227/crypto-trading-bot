# Cryptocurrency Trading Bot

A testable, auditable, and fault-tolerant algorithmic trading system for BTC, ETH, and SOL built with Python 3.11+.

> **IMPORTANT DISCLAIMER:**
> This software does not guarantee any profit. Algorithmic trading involves substantial risk of loss. Live trading is strictly disabled by default. The system operates under a strict **Fail-Closed** policy: if any data, model, or account state is ambiguous or inconsistent, all new order entries are halted immediately. API withdrawal permissions must always remain disabled.

---

## 1. Governing Principles

1. **No Forced Trading:** The system trades only when strict strategy and regime conditions are met.
2. **No Guaranteed Return:** Returns are an objective, never a guarantee.
3. **Risk Before Signal:** Every candidate signal must pass the mandatory Risk Engine evaluation before reaching execution.
4. **Fail-Closed:** When data quality, connection state, or position reconciliation is uncertain, new entries halt.
5. **No Martingale:** Position sizes are never increased to chase or recover losses.
6. **Isolated 1x Futures Only:** Cross-margin and leverage above 1x are prohibited.
7. **Unified Core:** Strategy and risk logic are identical across Backtesting, Paper Trading, and Live execution.
8. **Strict Idempotency:** Unique `client_order_id` for all intents; blind retries are prohibited.
9. **Financial Precision:** All prices, quantities, fees, and PnL values are computed using Python `Decimal`.
10. **Zero Real Capital Without Formal Gate Clearance:** Sequence is strictly: Backtest → Out-of-Sample → Paper Trading (4-8 weeks) → Limited Live (Human Approval Required).

---

## 2. Architecture Overview

The system is designed as a **Modular Monolith**:

```text
[Exchange / Market Data]
        │
        ▼
 [Indicator Engine] ────► [Regime Detector (4H)]
                                │
                                ▼
                       [Strategy Manager]
                                │
                                ▼
                         [Signal Engine]
                                │
                                ▼
                          [Risk Engine]  ◄─── [Portfolio / Limits]
                                │
                       (Approved Signals Only)
                                │
                                ▼
                       [Execution Engine]
                                │
                                ▼
                       [Exchange Adapter]
```

---

## 3. Implementation Status

- [x] **Task 0.1:** Git repository initialized, `.gitignore` configured, documentation persisted.
- [x] **Task 0.2:** Project environment and dependencies (`pyproject.toml`, `.env.example`, `.venv`).
- [ ] **Task 0.3:** Directory scaffolding and ADRs.
- [ ] **Task 0.4:** Core domain models (`Decimal` precision, immutable).
- [ ] **Task 0.5:** Typed configuration schemas and validation.

---

## 4. Documentation Reference

- **Full Architecture Specification:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Architectural Decision Records:** `docs/adr/`

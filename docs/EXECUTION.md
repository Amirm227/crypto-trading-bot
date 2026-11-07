# Execution and Order Lifecycle Specification

See [docs/ARCHITECTURE.md](ARCHITECTURE.md#10-execution-and-order-lifecycle) for the complete execution specification.

## Order Lifecycle State Machine

- `CREATED`: Internal order intent initialized.
- `SUBMITTED`: Dispatched to exchange adapter with unique `client_order_id`.
- `ACKNOWLEDGED`: Confirmed by exchange.
- `UNKNOWN`: Communication timeout; requires mandatory query/reconciliation before any retry.
- `PARTIALLY_FILLED`: Managed with actual filled quantity; stops placed proportionally.
- `FILLED`: Completely filled; protective stop immediately placed.
- `CANCEL_PENDING`: In flight cancellation.
- `CANCELED`: Canceled.
- `REJECTED`: Rejected by exchange or adapter validation.

## Idempotency Rules

1. Every order intent has an immutable, unique `client_order_id`.
2. Blind resubmissions are strictly prohibited.
3. Upon timeout or communication drop, the system queries order state via `client_order_id` before taking action.
4. Partial fills recalculate risk based solely on filled quantity; stops are placed for the partial position.

# Architecture Decision Records

## ADR-001: PostgreSQL over SQLite

PostgreSQL is used for both local development and production. SQLite differs in locking behaviour, transaction isolation, type handling, and concurrency semantics. The concurrency protection in this project (SELECT ... FOR UPDATE) relies on PostgreSQL-specific row-level locking. Running the same engine locally and in production means tests exercise the same database behaviour as the deployed system.

## ADR-002: Decimal over float

All monetary values use Python's `Decimal` and PostgreSQL's `Numeric(12,2)`. Floating-point arithmetic introduces rounding errors that accumulate over repeated operations. For financial software this is a correctness requirement, not a preference.

## ADR-003: Append-only ledger

Ledger entries are never updated or deleted. Corrections are recorded as compensating entries. This preserves a complete audit trail and makes balances reproducible from history at any point in time.

## ADR-004: FastAPI

Selected for Python alignment, built-in Pydantic validation, automatic OpenAPI documentation generation, and async support if needed later. Lightweight enough for a six-day project, capable enough to demonstrate production patterns.

## ADR-005: Row-level locking for concurrency

Account rows are locked with SELECT ... FOR UPDATE before balance checks. Without this, concurrent withdrawals can both read the same balance and both succeed, resulting in negative balances. Transfers lock both accounts in deterministic UUID order to minimise deadlock risk.

## ADR-006: External Clearing account

Deposits and withdrawals use an internal system account as the counterparty to maintain double-entry invariants. This is a demonstration of the accounting pattern, not a model of how a production bank's chart of accounts works. The alternative (single-sided entries for deposits/withdrawals) would break the global ledger invariant.

## ADR-007: Request hashing for idempotency conflicts

Idempotency keys are paired with a SHA-256 hash of the canonical request parameters. This detects the case where a client reuses a key with different parameters, which would otherwise silently return the wrong transaction. Same key with same parameters is a safe retry. Same key with different parameters is a 409 Conflict.

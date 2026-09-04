# Design

## Architecture

```
Client
  |
FastAPI / Pydantic (validation, routing, OpenAPI)
  |
Service layer (transaction logic, locking, idempotency)
  |
SQLAlchemy + Alembic (ORM, migrations)
  |
PostgreSQL (local: Docker Compose, prod: Azure Database for PostgreSQL)
```

Deployment: Azure App Service (API runtime), GitHub Actions (CI/CD).

## Data Model

Three tables. Every financial event produces balanced ledger entries. Balances are derived, never stored.

### Account

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key, generated server-side |
| name | String | Unique, required |
| is_system | Boolean | True for internal accounts (External Clearing) |
| created_at | DateTime | Server default |

### Transaction

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| idempotency_key | String | Unique, client-supplied |
| type | Enum | deposit, withdrawal, transfer |
| amount | Numeric(12,2) | Decimal, never float |
| request_hash | String(64) | SHA-256 of canonical request body |
| reference | String | Optional description |
| created_at | DateTime | Server default |

### LedgerEntry

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| transaction_id | FK -> Transaction | Required |
| account_id | FK -> Account | Required |
| amount | Numeric(12,2) | Signed: positive = credit, negative = debit |

## Double-Entry Model

Every transaction type produces exactly two ledger entries that sum to zero.

### External Clearing

An internal system account acts as the counterparty for deposits and withdrawals. This is a balancing account used to maintain double-entry invariants for cash entering or leaving the system. It is not modelling a production bank's chart of accounts.

**Deposit (50.00 into Customer):**
```
External Clearing   -50.00
Customer            +50.00
```

**Withdrawal (20.00 from Customer):**
```
Customer            -20.00
External Clearing   +20.00
```

**Transfer (50.00 from A to B):**
```
A   -50.00
B   +50.00
```

Global invariant: the sum of all ledger entries across all accounts is always zero.
Per-transaction invariant: the sum of entries for any single transaction is always zero.

## Transaction Lifecycle

```
Client: POST /transactions
  -> Pydantic validates request (type, amount > 0, required fields)
  -> Check idempotency key
     -> Key exists + same request_hash: return original transaction
     -> Key exists + different request_hash: 409 Conflict
     -> Key is new: continue
  -> Lock affected account rows (SELECT ... FOR UPDATE)
  -> Validate balance (for withdrawals and transfers)
  -> Create Transaction row
  -> Create LedgerEntry rows (debit + credit)
  -> Commit (atomic, all-or-nothing)
  -> Return transaction response
```

## Idempotency

Every POST /transactions requires an `idempotency_key`. The service computes a SHA-256 hash of all semantically relevant request fields (type, amount, account IDs, reference) and stores it as `request_hash`.

- Same key, same hash: return the original transaction (safe retry).
- Same key, different hash: 409 Conflict. The caller reused a key with different parameters.

This prevents silent data corruption from mismatched retries.

## Concurrency

Account-affecting operations acquire row-level locks using `SELECT ... FOR UPDATE` before reading balances. This prevents the classic double-spend race:

```
Thread A: reads balance = 100
Thread B: reads balance = 100
Thread A: withdraws 80 -> balance = 20
Thread B: withdraws 80 -> balance = -60  (BUG)
```

With locking, Thread B blocks until Thread A commits, then reads the updated balance (20) and correctly rejects the withdrawal.

Transfers lock both accounts in deterministic UUID order to minimise deadlock risk. The lower UUID is always locked first.

## Decimal Money

All monetary values use `Numeric(12,2)` in PostgreSQL and `Decimal` in Python. Floats introduce rounding errors that accumulate over repeated operations. A banking engineer reviewing this repo will check for this immediately.

## Configuration and Secrets

`DATABASE_URL` is injected via environment variable. Local development uses Docker Compose with a local PostgreSQL instance. Azure deployment uses Azure App Service environment variables pointing to Azure Database for PostgreSQL.

No credentials are committed to source control. The `.gitignore` excludes `.env`.

## CI/CD

GitHub Actions runs on every push to main:
1. Install dependencies
2. Run ruff (linting)
3. Run pytest against a PostgreSQL service container
4. On green main: deploy to Azure App Service

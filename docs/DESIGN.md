# Design

## Architecture

```
Client
  |
FastAPI / Pydantic (validation, routing, OpenAPI)
  |
Service layer (transaction logic, locking, idempotency, outbox)
  |
SQLAlchemy + Alembic (ORM, migrations)
  |
PostgreSQL (local: Docker Compose, prod: Cloud SQL)
  |
Transactional outbox -> Pub/Sub (event publishing)
```

Deployment: GCP Cloud Run (europe-west2), GitHub Actions (CI/CD).
Infrastructure: Terraform.

## Data Model

Four tables. Every financial event produces balanced ledger entries. Balances are derived, never stored.

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

### OutboxEvent

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| aggregate_type | String(50) | Always "transaction" |
| aggregate_id | UUID | Transaction ID |
| event_type | String(100) | e.g. "transaction.deposit" |
| payload | Text | JSON event data |
| created_at | DateTime | Server default |
| published_at | DateTime | Null until relay publishes |

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
  -> Write OutboxEvent (same transaction)
  -> Commit (atomic, all-or-nothing)
  -> Return transaction response
```

## Transactional Outbox

Every transaction writes an event to the `outbox_events` table inside the same database transaction as the ledger entries. This guarantees exactly-once event delivery: if the transaction commits, the event exists. If it rolls back, neither ledger entries nor the event are persisted.

A relay endpoint (`POST /outbox/publish`) marks pending events as published. In production, a Cloud Scheduler job or background worker calls the relay, which publishes events to Pub/Sub and marks them as delivered.

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

## Observability

Structured JSON logging with request ID correlation. Every HTTP request gets a unique `X-Request-ID` (client-supplied or auto-generated) that propagates through all log entries for that request. Transaction events (creation, idempotent replays, conflicts) log the transaction ID for traceability.

Log output is JSON to stdout, which Cloud Run forwards directly to Google Cloud Logging as structured log entries.

## Configuration and Secrets

`DATABASE_URL` is injected via environment variable. Local development uses Docker Compose with a local PostgreSQL instance. GCP deployment uses Cloud Run environment variables pointing to Cloud SQL.

No credentials are committed to source control. The `.gitignore` excludes `.env` and `gcp-key.json`.

## CI/CD

GitHub Actions runs on every push to main:
1. Ruff lint
2. Pytest against a PostgreSQL service container (34 tests)
3. On green main: build Docker image, push to Artifact Registry, deploy to Cloud Run

## Infrastructure as Code

All GCP resources are defined in Terraform (`terraform/`): Cloud SQL, Artifact Registry, Cloud Run, Pub/Sub topic and subscription, Secret Manager, IAM roles, service accounts.

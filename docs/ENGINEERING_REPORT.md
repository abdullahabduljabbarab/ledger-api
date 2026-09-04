# Engineering Report

## What this is

An append-only double-entry ledger API. Every financial event produces balanced debit/credit entries that sum to zero. Balances are derived from entry sums, never stored. The system is designed around correctness guarantees that a banking engineer would expect: idempotency, crash recovery, decimal precision, and tamper evidence.

## Architecture

```
Client (authenticated via JWT)
  |
FastAPI + Pydantic (validation, routing, OpenAPI docs)
  |
Service layer (double-entry logic, row-level locking, idempotency, hash chain)
  |
SQLAlchemy + Alembic (ORM, schema migrations)
  |
PostgreSQL 16 (Cloud SQL, europe-west2)
  |
Transactional outbox --> Pub/Sub topic (event publishing)
```

Deployed on GCP Cloud Run with auto-scaling (0-3 instances). CI/CD via GitHub Actions: lint, test against PostgreSQL service container, auto-deploy on green main.

Infrastructure defined in Terraform: Cloud SQL, Artifact Registry, Cloud Run, Pub/Sub, Secret Manager, IAM roles.

## Key engineering decisions

**Derived balances, not stored balances.** Balances are computed as `SUM(ledger_entries.amount) WHERE account_id = ?` at query time. This eliminates the entire category of bugs where a stored balance drifts from the actual entry history. The trade-off is query cost, which is acceptable at this scale.

**External Clearing counterparty.** Deposits and withdrawals create entries against an internal system account so every transaction produces exactly two entries summing to zero. This makes the global invariant (`SUM(all entries) = 0`) hold unconditionally.

**Deterministic lock ordering.** Transfers lock both accounts using `SELECT ... FOR UPDATE` in UUID sort order. This prevents deadlocks when two concurrent transfers affect the same pair of accounts.

**SHA-256 idempotency conflict detection.** The idempotency key is paired with a hash of the full request body. Same key, same body returns the original transaction. Same key, different body returns 409. This catches accidental key reuse.

**Tamper-evident hash chain.** Each transaction stores `prev_hash` (the previous transaction's `chain_hash`) and its own `chain_hash` (SHA-256 of `id|key|type|amount|request_hash|prev_hash`). The chain verifier recomputes every hash and detects any modification.

**Transactional outbox.** Events are written to an `outbox_events` table inside the same database transaction as ledger entries. This guarantees that if entries exist, the event exists. A relay endpoint marks events as published for downstream consumers.

## Numbers

| Metric | Value |
|--------|-------|
| Test count | 50 |
| Property-based test examples (Hypothesis) | 190+ per run |
| Alembic migrations | 3 (initial schema, outbox table, hash chain columns) |
| API endpoints | 15 |
| Roles (RBAC) | 3 (customer, auditor, admin) |
| STRIDE threat categories covered | 6/6 |
| Requirement-to-test traceability entries | 7 |

## Test categories

| Category | Tests | What they prove |
|----------|-------|-----------------|
| Transaction lifecycle | 9 | Deposits, withdrawals, transfers, validation, edge cases |
| Concurrency | 1 | Parallel withdrawals cannot overspend (row-level locking) |
| Idempotency | 2 | Duplicate keys return original, mismatched keys return 409 |
| Decimal precision | 1 | 100 x 0.01 = 1.00 exactly (not 0.999...98) |
| Ledger invariants | 2 | Per-transaction and global sum = 0 |
| Entry immutability | 2 | No PUT or DELETE on ledger entries |
| Account lifecycle | 2 | Create, retrieve, duplicate name rejected |
| Property-based (Hypothesis) | 5 | Random operation sequences preserve invariants |
| Resilience / failure injection | 4 | Commit crash rolls back, rapid-fire idempotency, failed transfers leave no partial state |
| Transactional outbox | 3 | Events created atomically, relay publishes, no duplicates on replay |
| Audit / reconciliation | 2 | Independent balance recomputation, invariant checks |
| Hash chain | 2 | Chain intact after operations, tamper detected on modification |
| Auth / RBAC | 11 | Login, token validation, role enforcement, privilege escalation prevention |
| Schema evolution | 1 | Migrations apply incrementally, data survives upgrade/downgrade |

## Injected failures tested

- Database commit crash mid-transaction (balance unchanged)
- 10 rapid-fire identical idempotency keys (only 1 transaction created)
- Insufficient-funds transfer (no partial entries left behind)
- 20 consecutive overdraw attempts (balance unchanged)
- Hash chain tampering (detected by verifier)

## Cloud architecture

| Component | Service | Region |
|-----------|---------|--------|
| API runtime | Cloud Run | europe-west2 (London) |
| Database | Cloud SQL PostgreSQL 16 | europe-west2 |
| Container registry | Artifact Registry | europe-west2 |
| Event bus | Pub/Sub | europe-west2 |
| Secrets | Secret Manager | europe-west2 |
| CI/CD | GitHub Actions | Ubuntu runners |
| IaC | Terraform | All resources declared |

## V&V matrix

| Requirement | Verification method | Test/evidence |
|-------------|-------------------|---------------|
| Double-entry invariant | Automated test + audit endpoint | `test_audit_verify_clean_ledger`, `GET /audit/verify` |
| Idempotent transactions | Automated test + property test | `test_idempotent_deposits_never_duplicate`, Hypothesis |
| Overdraw prevention | Automated test + property test | `test_overdraw_never_permitted`, concurrent withdrawal test |
| Crash recovery | Failure injection test | `test_commit_failure_rolls_back` |
| Tamper detection | Automated test + audit endpoint | `test_hash_chain_detects_tamper`, `GET /audit/chain` |
| Role-based access | Automated test | 11 auth tests covering all role/endpoint combinations |
| Schema evolution | Migration test | `test_migrations_apply_incrementally` |
| Decimal precision | Automated test | `test_decimal_precision` (100 x 0.01 = 1.00) |
| API correctness | OpenAPI spec + automated tests | `/docs` serves auto-generated spec, 50 tests validate behaviour |

## Design trade-offs

**In-memory user store vs. database users.** The auth system uses a hardcoded user dictionary. In production this would be a users table with registration. For a portfolio project, the RBAC enforcement logic is the engineering point, not the user management CRUD.

**Outbox relay as an API endpoint vs. background worker.** The relay is triggered via `POST /outbox/publish` rather than a continuously running worker. This is simpler to deploy on Cloud Run (no persistent process needed) and can be called by Cloud Scheduler on a cron. The trade-off is slightly higher event delivery latency.

**Hash chain with nullable columns vs. mandatory columns.** The `prev_hash` and `chain_hash` columns are nullable to support migration from existing unchained transactions. New transactions always have both values set.

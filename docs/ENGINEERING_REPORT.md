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

**Serialised chain appends.** Chain linking takes a transaction-scoped PostgreSQL advisory lock, so concurrent writers cannot read the same tip and fork the chain. Append order is recorded in a `chain_seq` column rather than inferred from `created_at`, because `now()` returns transaction start time and therefore does not match commit order. The column is unique, so a failure of the lock surfaces as a database error rather than a silently forked chain. This design came directly out of load testing, which is described below.

**Transactional outbox.** Events are written to an `outbox_events` table inside the same database transaction as ledger entries. This guarantees that if entries exist, the event exists, with no dual write to a broker that could succeed while the database rolls back.

**At-least-once delivery, stated honestly.** The relay publishes to Pub/Sub and only marks a row published once the transport accepts it. A failure leaves that row and everything after it pending, preserving order for the retry. A crash between a successful publish and the commit will republish, so delivery is at-least-once rather than exactly-once and consumers deduplicate on `event_id`. The relay reports which transport handled each batch, so it is never ambiguous whether a real publish occurred.

## Numbers

| Metric | Value |
|--------|-------|
| Test count | 58 |
| Property-based test examples (Hypothesis) | 190+ per run |
| Alembic migrations | 4 (initial schema, outbox table, hash chain columns, chain sequence) |
| API endpoints | 17 |
| Roles (RBAC) | 3 (customer, auditor, admin) |
| STRIDE threat categories covered | 6/6 |
| Requirement-to-test traceability entries | 7 |

## Test categories

| Category | Tests | What they prove |
|----------|-------|-----------------|
| Transaction lifecycle | 9 | Deposits, withdrawals, transfers, validation, edge cases |
| Auth / RBAC | 11 | Login, token validation, role enforcement, privilege escalation prevention |
| Property-based (Hypothesis) | 5 | Random operation sequences preserve invariants |
| Audit / hash chain | 5 | Independent recomputation, chain intact, tamper detected, amounts normalised |
| Account lifecycle | 4 | Create, retrieve, duplicate name rejected, listing |
| Resilience / failure injection | 4 | Commit crash rolls back, rapid-fire idempotency, failed transfers leave no partial state |
| Transactional outbox | 5 | Events created atomically, relay publishes, no duplicates on replay, transport reported, failed publish leaves rows pending |
| Event consumer | 4 | Deduplication on event_id: first delivery, redelivery, independent events, idempotent marking |
| Concurrency | 2 | Parallel withdrawals cannot overspend, concurrent transfers cannot fork the chain |
| Idempotency | 2 | Duplicate keys return original, mismatched keys return 409 |
| Ledger invariants | 2 | Per-transaction and global sum = 0 |
| Entry immutability | 2 | No PUT or DELETE on ledger entries |
| Decimal precision | 1 | 100 x 0.01 = 1.00 exactly (not 0.999...98) |
| Schema evolution | 1 | Migrations apply incrementally, data survives upgrade/downgrade |
| Health | 1 | Database connectivity probe reports status and latency |

## Injected failures tested

- Database commit crash mid-transaction (balance unchanged)
- 10 rapid-fire identical idempotency keys (only 1 transaction created)
- Insufficient-funds transfer (no partial entries left behind)
- 20 consecutive overdraw attempts (balance unchanged)
- Hash chain tampering (detected by verifier)
- Concurrent transfers across disjoint account pairs (chain stays linear)
- Container that fails to start deployed to Cloud Run (traffic never shifted, live service unaffected)
- Full database restored from backup into a separate instance (reconciliation and hash chain both pass)

## What load testing found

Load testing the live deployment produced no failed requests and met every latency target, but the hash chain verifier failed afterwards. The reconciliation engine passed, so the ledger itself was correct; the fault was in the audit layer's own linking and ordering logic.

Two defects were responsible, and neither was reachable from the unit tests because both require real parallelism. Chain appends were not serialised, so transfers between disjoint account pairs could link to the same predecessor. Deposits and withdrawals happened to be safe only because they all lock the shared External Clearing account. Separately, verification walked the chain by `created_at`, which is transaction start time rather than commit time, so correctly linked transactions could still be reported as broken.

Writing the regression test then exposed a third defect: on a cold database, concurrent writers all miss the External Clearing lookup and race to insert the same unique name.

All three are fixed and covered by tests. The wider point is that the correctness invariants held throughout, the independent audit layer caught the fault rather than a user noticing a wrong balance, and the bug only appeared once the system was put under genuine concurrent load.

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
| Chain integrity under concurrency | Automated test + load test | `test_concurrent_transfers_keep_chain_linear`, Locust run |
| Backup is restorable | Restore drill | Cloud SQL export restored to a separate database, 417 transactions and 834 entries matching live, reconciliation and chain both pass |
| Bad deploy cannot take the service down | Failure injection on live infrastructure | Broken image deployed to Cloud Run, revision failed health check, traffic stayed 100% on the healthy revision |
| Event delivery | Automated test + live verification | `test_publish_failure_leaves_events_pending`, 415 events drained to Pub/Sub and confirmed by independent pull |
| Role-based access | Automated test | 11 auth tests covering all role/endpoint combinations |
| Schema evolution | Migration test | `test_migrations_apply_incrementally` |
| Decimal precision | Automated test | `test_decimal_precision` (100 x 0.01 = 1.00) |
| API correctness | OpenAPI spec + automated tests | `/docs` serves auto-generated spec, 58 tests validate behaviour |
| Event consumer deduplication | Automated test | `test_consumer` covers first delivery, redelivery, and independent events |
| Secret is never the repo default in production | Startup guard + Secret Manager | Service refuses to boot in production without `JWT_SECRET_KEY`; supplied from Secret Manager |

## Design trade-offs

**In-memory user store vs. database users.** The auth system uses a hardcoded user dictionary. In production this would be a users table with registration. For a portfolio project, the RBAC enforcement logic is the engineering point, not the user management CRUD.

**Log transport alongside Pub/Sub.** Rather than stubbing the relay when no topic is configured, there are two real transports selected by the `PUBSUB_TOPIC` environment variable. Local runs and tests exercise the identical relay code path, including the failure handling, without needing cloud credentials. The alternative, skipping the publish and marking rows delivered anyway, would have made the endpoint lie about what it did.

**Outbox relay as an API endpoint vs. background worker.** The relay is triggered via `POST /outbox/publish` rather than a continuously running worker. This is simpler to deploy on Cloud Run (no persistent process needed) and can be called by Cloud Scheduler on a cron. The trade-off is slightly higher event delivery latency.

**Hash chain with nullable columns vs. mandatory columns.** The `prev_hash` and `chain_hash` columns are nullable to support migration from existing unchained transactions. New transactions always have both values set.

# Ledger API

[![CI](https://github.com/abdullahabduljabbarab/ledger-api/actions/workflows/ci.yml/badge.svg)](https://github.com/abdullahabduljabbarab/ledger-api/actions/workflows/ci.yml)
[![Terraform](https://github.com/abdullahabduljabbarab/ledger-api/actions/workflows/terraform.yml/badge.svg)](https://github.com/abdullahabduljabbarab/ledger-api/actions/workflows/terraform.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An append-only, double-entry financial ledger. Every transaction produces balanced debit and credit entries that sum to zero, balances are derived from those entries rather than stored, and the whole history is chained with SHA-256 so tampering is detectable. It is deployed on Google Cloud Run with Cloud SQL, its infrastructure is defined as code in Terraform, and it is shipped by a CI pipeline that lints, tests, validates the Terraform and deploys on every push to main.

**Live service**

- Product page: https://ledger-api-465847189589.europe-west2.run.app/
- Interactive API reference: https://ledger-api-465847189589.europe-west2.run.app/reference
- OpenAPI / Swagger UI: https://ledger-api-465847189589.europe-west2.run.app/docs

![Ledger portal](docs/images/14-portal-hero.png)

---

## Contents

- [What it does](#what-it-does)
- [Correctness guarantees](#correctness-guarantees)
- [Event delivery](#event-delivery)
- [Architecture](#architecture)
- [Verification and evidence](#verification-and-evidence)
- [Running it locally](#running-it-locally)
- [Design decisions](#design-decisions)
- [Project layout](#project-layout)

---

## What it does

The core is double-entry bookkeeping done properly. A deposit does not just add a number to an account. It writes two ledger entries: a credit to the target account and a matching debit to an internal "External Clearing" account. The two always sum to zero, which is what makes the global invariant `SUM(all entries) = 0` hold unconditionally.

**Deposit 500 into an account:**

![Deposit](docs/images/03-deposit.png)

**The two entries it produced.** The account receives +500.00; the mirror -500.00 sits on External Clearing:

![Double-entry ledger entries](docs/images/04-entries-double-entry.png)

**The balance is derived, never stored.** It is computed as `SUM(entries)` at query time, so it can never drift from the history that produced it:

![Derived balance](docs/images/05-balance.png)

**Transfers** move value between two accounts, locking both in a deterministic order to avoid deadlocks:

![Transfer](docs/images/06-transfer.png)

The API also serves account statements with running balances, cursor-paginated entry and transaction listings, and a deep health check that probes the database.

---

## Correctness guarantees

**Idempotency.** Every transaction carries a client-supplied `idempotency_key`. Replaying the exact same request returns the original transaction rather than creating a second one. The response below is the *same* transaction id and creation time as the first deposit, even though it was sent again minutes later:

![Idempotent replay](docs/images/07-idempotency.png)

Reusing a key with *different* parameters is a conflict, not a silent overwrite. The ledger rejects it with a 409 so a bug in a caller cannot quietly change a recorded transaction:

![Idempotency conflict](docs/images/08-conflict-409.png)

**Independent reconciliation.** A verification engine recomputes ledger state through a path that shares no code with the write path. It re-derives every account balance from raw entries and runs six checks: the global invariant, per-transaction balance, independent balance recomputation, referential integrity, idempotency-key uniqueness, and entry count per transaction.

![Reconciliation passing](docs/images/09-audit-verify.png)

**Tamper evidence.** Each transaction stores the previous transaction's hash and its own SHA-256 over `id | key | type | amount | request_hash | prev_hash`. The chain verifier re-hashes the entire history and reports any broken link or modified row.

![Hash chain passing](docs/images/10-audit-chain.png)

**Concurrency.** Transfers take row locks in UUID order to prevent deadlocks, and chain appends serialise on a transaction-scoped advisory lock so concurrent writers cannot fork the chain. This last property came directly out of load testing; see [Verification and evidence](#verification-and-evidence).

**Authentication and access control.** JWT bearer tokens carry one of three roles. Customers can transact, auditors can inspect, admins can provision. The signing secret is injected from Secret Manager at deploy time and the service refuses to start in production without it, so it can never fall back to a value visible in source control.

---

## Event delivery

Transactions are published to downstream consumers using the transactional outbox pattern. The event row is written in the *same database transaction* as the ledger entries, so if the transaction commits the event exists, and if it rolls back neither persists. There is no dual write to a broker that could succeed while the database rolls back.

A relay reads unpublished events oldest-first and marks each published only once the transport has accepted it. Delivery is at-least-once, and consumers deduplicate on `event_id`.

**Pending events after a deposit and a transfer:**

![Outbox pending](docs/images/11-outbox-pending.png)

**Publishing them to Pub/Sub.** The response names the transport, so the endpoint can never claim success for work it did not do:

![Outbox publish](docs/images/12-outbox-publish.png)

**Proof they arrived,** pulled straight off the Pub/Sub subscription in the Cloud Console, independent of the API. The bottom two rows are the deposit and transfer above, carrying matching transaction ids and idempotency keys:

![Pub/Sub messages](docs/images/13-pubsub.png)

The consumer lives in [`scripts/consumer.py`](scripts/consumer.py).

---

## Architecture

```mermaid
flowchart TD
    C[Clients] -->|JWT over HTTPS| A[FastAPI: validation, RBAC, routing]
    A --> S[Service layer: double-entry, row locks, idempotency, hash chain]
    S --> DB[(PostgreSQL 16 / Cloud SQL)]
    DB -->|same transaction| OB[outbox_events]
    OB --> R[Relay: POST /outbox/publish]
    R --> PS[Pub/Sub topic]
    PS --> K[Idempotent consumer]

    A -.structured JSON logs.-> L[Cloud Logging]

    subgraph GCP [Google Cloud, europe-west2]
        A
        S
        DB
        OB
        R
        PS
    end
```

FastAPI and Pydantic handle validation, routing and the OpenAPI spec. SQLAlchemy and Alembic own the schema and migrations. The full GCP stack (Cloud SQL, Cloud Run, Artifact Registry, Pub/Sub, Secret Manager, IAM, and the backups bucket) is defined as code in Terraform under [`terraform/`](terraform/), and the configuration is validated on every push by the CI pipeline.

**Deployment.** GitHub Actions lints, runs the full test suite against a PostgreSQL service container, and validates the Terraform. On green it builds the image, pushes to Artifact Registry and deploys to Cloud Run. Database credentials and the JWT signing key are injected from Secret Manager. Alembic migrations run automatically on container start.

![Cloud Run revisions](docs/images/17-cloud-run.png)

---

## Verification and evidence

58 automated tests cover the ledger, concurrency, idempotency, decimal precision, the audit engine, the hash chain, auth, the outbox, the consumer and schema migrations. On top of unit tests the system was exercised against the live deployment.

**Load test (Locust, live Cloud Run, 5 concurrent users, 60 seconds):**

| Metric | Target | Measured |
|--------|--------|----------|
| Requests | | 828 |
| Failures | 0 | 0 |
| p50 latency | < 200 ms | 72 ms |
| p95 latency | < 500 ms | 110 ms |
| p99 latency | < 1000 ms | 260 ms |
| Throughput | > 10 req/s | 13.9 req/s |

**A defect the load test found.** The reconciliation engine passed under load but the hash-chain verifier failed with forked links. Two causes: chain appends were not serialised, so concurrent transfers could link to the same predecessor; and verification ordered by `created_at`, which in PostgreSQL is transaction start time, not commit time. Both are fixed (advisory lock plus an explicit `chain_seq` column) and covered by a regression test that reproduces the fork and fails reliably without the lock. The ledger invariants held throughout; the independent audit layer is what caught the fault. Full write-up in [`docs/SLO.md`](docs/SLO.md) and [`docs/PRODUCTION_LOG.md`](docs/PRODUCTION_LOG.md).

**Backup and restore.** The live database was exported from Cloud SQL, restored into a separate PostgreSQL instance, and verified there directly: 417 transactions and 834 entries matching live exactly, reconciliation passing all six checks, hash chain intact.

**Deployment failure safety.** A container that fails on startup was deployed to Cloud Run; the revision failed its health check and traffic stayed entirely on the healthy revision.

**Requirement to evidence:**

| Requirement | How it is verified |
|-------------|--------------------|
| Double-entry invariant holds | `test_audit_verify_clean_ledger`, `GET /audit/verify` |
| Balances never drift | derived at query time, `test_balance_equals_sum_of_entries` |
| Idempotent retries | `test_idempotent_deposits_never_duplicate`, 409 on conflict |
| Overdraw prevention | `test_overdraw_never_permitted`, concurrent withdrawal test |
| Tamper detection | `test_hash_chain_detects_tamper`, `GET /audit/chain` |
| Chain integrity under concurrency | `test_concurrent_transfers_keep_chain_linear`, load test |
| Crash recovery | `test_commit_failure_rolls_back` |
| Role-based access | 11 auth tests across every role and endpoint |
| Schema evolution | `test_migrations_apply_incrementally` |
| Event delivery | `test_publish_failure_leaves_events_pending`, live Pub/Sub pull |

A more detailed matrix lives in [`docs/ENGINEERING_REPORT.md`](docs/ENGINEERING_REPORT.md) and the STRIDE threat model in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

---

## Running it locally

Requires Docker and Python 3.12.

```bash
# 1. start PostgreSQL
docker compose up -d

# 2. install dependencies
pip install -r requirements.txt

# 3. point the app at the database and apply migrations
export DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger
alembic upgrade head

# 4. run the service
uvicorn app.main:app --reload
```

Then open http://localhost:8000/ for the portal, or http://localhost:8000/docs for Swagger.

**Running the tests** (needs a separate test database):

```bash
docker compose exec db psql -U ledger -d postgres -c "CREATE DATABASE ledger_test;"
export TEST_DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger_test
pytest
```

**Load test** against a running instance:

```bash
locust -f scripts/loadtest.py --host http://localhost:8000
```

Demo credentials for the deployed service are available on request; the deployed signing secret is not the repository default.

---

## Design decisions

**Derived balances, not stored balances.** Computing `SUM(entries)` at query time eliminates the entire class of bugs where a cached balance drifts from the entry history. The cost is query time, which is acceptable at this scale and is the safer default for money.

**External Clearing counterparty.** Deposits and withdrawals post against an internal system account so every transaction produces two entries summing to zero, which lets the global invariant hold without special-casing.

**At-least-once, stated honestly.** The outbox makes event capture atomic with the ledger write, but a crash between a successful publish and the commit that marks the row will republish. Rather than claim exactly-once, delivery is at-least-once and consumers deduplicate on `event_id`.

**Two transports, no stubs.** The relay publishes to Pub/Sub in the cloud and to the structured log locally, selected by an environment variable. Local runs and tests exercise the identical relay path, including the failure handling, without cloud credentials.

More decisions and their trade-offs are recorded in [`docs/ENGINEERING_REPORT.md`](docs/ENGINEERING_REPORT.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## Project layout

```
app/            FastAPI application, service layer, auth, audit, chain, outbox
migrations/     Alembic migrations (schema, outbox table, hash chain, chain sequence)
terraform/      All GCP infrastructure as code
scripts/        Load test harness and the Pub/Sub consumer
tests/          58 tests: unit, property-based, resilience, concurrency, migrations
docs/           Design, engineering report, threat model, SLOs, production log
```

---

Built by Abdullah Ameed Abduljabbar.

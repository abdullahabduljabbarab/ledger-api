# Production Log

## Day 1

### Goal
Scaffold FastAPI service, data model, PostgreSQL, health endpoint, test suite, engineering docs.

### Completed
- Created Account, Transaction, LedgerEntry SQLAlchemy models (Numeric(12,2), UUID PKs)
- Pydantic schemas with Decimal validation, gt=0 amount constraint
- Service layer with External Clearing counterparty, SELECT FOR UPDATE locking, deterministic UUID lock ordering, idempotency with SHA-256 request hash conflict detection
- All API endpoints: POST/GET accounts, POST/GET transactions, GET balance, GET entries, GET health
- Docker Compose for local PostgreSQL 16
- Alembic initial migration seeding External Clearing system account
- 22 tests passing: accounts, deposits, withdrawals, transfers, concurrency (parallel withdrawals), idempotency + 409 conflict, decimal precision (100x 0.01 = 1.00), per-transaction + global ledger invariants, entry immutability
- Engineering docs: MVP scope, requirements (14 functional + 8 non-functional), design, V&V plan with requirement-to-test traceability, security boundaries, 7 ADRs
- ruff lint passing

### Problems / Decisions
- Rejected SQLite for local dev because row-level locking (SELECT FOR UPDATE) is PostgreSQL-specific and the concurrency tests need it
- Added External Clearing system account so deposits/withdrawals produce balanced entries and the global SUM=0 invariant genuinely holds
- Idempotency hash includes all business-relevant fields (type, amount, account IDs, reference) to catch mismatched retries

### Evidence
- /health returns 200 at localhost:8000
- Swagger docs live at localhost:8000/docs
- 22/22 tests green (pytest, 1.77s)
- ruff: all checks passed

### Next
Cloud deployment and CI/CD.

## Day 2

### Goal
Deploy to Google Cloud Platform, set up CI/CD, expand test coverage with property-based and resilience testing.

### Completed
- Deployed to GCP Cloud Run (europe-west2) with Cloud SQL PostgreSQL 16
- Live API at https://ledger-api-465847189589.europe-west2.run.app
- Swagger docs at https://ledger-api-465847189589.europe-west2.run.app/docs
- GitHub Actions CI/CD: ruff lint, pytest against PostgreSQL service container, auto-deploy to Cloud Run on green main
- Dockerfile + start.sh for containerised deployment with Alembic migration on startup
- Deep health check: GET /health pings database, returns connection latency
- Request tracing middleware: X-Request-ID and X-Response-Time-Ms on every response
- Cursor-based pagination on GET /transactions and GET /entries
- Account statement endpoint: GET /accounts/{id}/statement with date range filtering and running balance
- Property-based testing with Hypothesis (5 tests): random deposit/withdrawal/transfer sequences preserving ledger invariants, balance matching entry sums, idempotent duplicates never creating extra transactions, 409 conflicts never changing state, overdraw prevention across random amounts
- Resilience testing (4 tests): commit failure rollback verification, rapid-fire idempotency key hammering, failed transfer leaving no partial entries, repeated overdraw attempts preserving balance
- Locust load test harness for live GCP deployment
- Test count: 22 to 31

### Problems / Decisions
- Azure signup blocked entirely (household-level ban, likely from a shared account). Switched to GCP instead. No engineering impact, same PostgreSQL, same containerised deployment model.
- gcloud CLI had SSL certificate errors in VS Code terminal. Ran commands from Google Cloud SDK Shell instead.
- Cloud SQL db-f1-micro tier no longer exists for PostgreSQL. Used db-custom-1-3840 (Enterprise edition, covered by $300 free trial credit).
- Pagination changed the response shape of list endpoints from flat arrays to {items, next_cursor}. Updated all existing tests that read entries.
- Crash injection test (monkeypatching Session.add mid-transaction) revealed SQLAlchemy autoflush behaviour. Replaced with commit-level failure injection which correctly verifies rollback.

### Evidence
- /health returns {"status": "ok", "database": "connected", "db_latency_ms": ...} on live URL
- POST /accounts returns 201 on live GCP endpoint
- GitHub Actions: lint, test, deploy all green
- 31/31 tests green locally (pytest, 31.63s)
- ruff: all checks passed
- Hypothesis explored 50 random transaction sequences per property test without invariant violations

### Next
Full README with architecture overview, API examples, deployment instructions, live link, build badge. Load testing against live deployment.

## Day 3

### Goal
Structured observability, transactional outbox pattern, infrastructure as code, documentation updates.

### Completed
- Structured JSON logging: all HTTP requests emit JSON log lines to stdout with timestamp, level, request_id, method, path, status_code, duration_ms. Transaction events log creation, idempotent replays, and 409 conflicts with transaction_id correlation. Cloud Run forwards these directly to Google Cloud Logging as structured entries.
- Request ID propagation: the X-Request-ID header (client-supplied or auto-generated) is stored in a contextvars.ContextVar and attached to every log entry within that request's lifecycle.
- Transactional outbox: every transaction writes an OutboxEvent row in the same database transaction as the ledger entries. Guarantees exactly-once delivery semantics. New migration (002_outbox) adds the outbox_events table with an index on published_at.
- Outbox relay endpoints: GET /outbox/pending lists unpublished events, POST /outbox/publish marks them as delivered. In production, a scheduler or background worker calls the relay to push events to Pub/Sub.
- Terraform infrastructure as code: all GCP resources defined in terraform/ directory. Cloud SQL instance, database, user. Artifact Registry repository. Cloud Run service with Cloud SQL connection. Pub/Sub topic (transaction-events) and subscription. Secret Manager secret for DB password. IAM roles for Cloud Run service account and GitHub deploy service account. Service accounts for both runtime and CI/CD.
- Documentation updates: DESIGN.md rewritten for GCP, added outbox table to data model, added transactional outbox and observability sections. SECURITY.md updated all Azure references to GCP, added Secret Manager and structured logging mentions.
- Test count: 31 to 34. Three new outbox tests: event creation on transaction, publish marks events as delivered, idempotent replay does not create duplicate events.
- Fixed concurrency test: was importing SessionLocal at module level, bypassing the test database fixture. Patched to use the test engine via database_module reference.

### Problems / Decisions
- Outbox events are written inside the same database transaction as ledger entries. This is the transactional outbox pattern: if the transaction commits, the event is guaranteed to exist. If it rolls back, neither entries nor event persist. No distributed transaction needed.
- The relay endpoint marks events as published but does not actually push to Pub/Sub yet. The Pub/Sub topic and subscription are provisioned in Terraform. Wiring the actual publish call is straightforward once the infrastructure is applied.
- Terraform files are declarative config in the repo. They do not affect the running infrastructure until `terraform apply` is run. The current deployment was set up manually via gcloud CLI, so Terraform serves as documentation and reproducibility for now.

### Evidence
- /health returns 200 with db_latency_ms on live URL
- POST /transactions creates outbox event (verified via GET /outbox/pending on live)
- POST /outbox/publish returns {"published": 1} on live, GET /outbox/pending returns 0 after
- 34/34 tests green locally and in CI
- ruff: all checks passed
- GitHub Actions: lint, test, deploy all green

### Next
Full README. Locust load test against live GCP deployment.

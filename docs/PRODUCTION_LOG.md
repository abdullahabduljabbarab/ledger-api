# Production Log

## Milestone 1

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

## Milestone 2

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

## Milestone 3

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

## Milestone 4

### Goal
Authentication and access control, independent verification of the ledger, tamper evidence, threat modelling, then load test the live deployment and fix whatever it finds.

### Completed
- JWT authentication with three roles (customer, auditor, admin). POST /auth/token issues HS256 tokens carrying the role claim, expiring after 60 minutes. Passwords hashed with bcrypt.
- Role-based access control across every endpoint. Account provisioning is admin only. Transactions are admin or customer. Audit endpoints are auditor or admin. Outbox relay is admin only. Health is the only public route.
- Reconciliation engine at GET /audit/verify. Independently recomputes every account balance from raw entry sums and runs six checks: global invariant, per-transaction invariant, balance recomputation, referential integrity, idempotency key uniqueness, and entry count per transaction. It shares no code with the write path, so it genuinely re-derives rather than re-reading what the service already believes.
- Tamper-evident hash chain at GET /audit/chain. Each transaction stores the previous transaction's hash alongside its own SHA-256 of id, key, type, amount, request hash and predecessor. The verifier recomputes the entire chain and reports broken links and modified rows separately.
- STRIDE threat model covering all six categories, each threat mapped to its mitigation and the test that proves it, plus an honest list of gaps not yet closed.
- Service level objectives defined up front, before measuring, so the targets were not written to match the results.
- Schema evolution test applying migrations one at a time, asserting the schema at each step, then downgrading and confirming data survives.
- Engineering report covering architecture, key decisions, test categories, injected failures and design trade-offs.
- Load test executed against live Cloud Run: 828 requests over 60 seconds at 5 concurrent users, zero failures, p50 72ms, p95 110ms, p99 260ms, 13.9 req/s. Every SLO met.
- Migration 004 fixing two hash chain concurrency defects found by that load test, with a regression test that reproduces the fault.
- Test count: 34 to 52.

### Problems / Decisions
- Replaced passlib with the bcrypt library directly. Passlib reads `bcrypt.__about__` for version detection, which modern bcrypt no longer exposes, and it also rejected passwords over 72 bytes rather than truncating.
- The load test found a real bug that the unit tests could not reach. The reconciliation engine passed, but the hash chain verifier failed with forked links. Two separate causes.
- First cause: `link_transaction` read the chain tip without serialising, so concurrent writers could link to the same predecessor. Deposits and withdrawals were protected by accident, since both lock the shared External Clearing account, but transfers between disjoint account pairs share no row lock and forked the chain. Fixed with a transaction-scoped advisory lock, held until commit, so the tip that is read is final.
- Second cause: the verifier walked the chain ordered by `created_at`. In PostgreSQL `now()` returns transaction start time rather than commit time, so a transaction that began earlier but committed later was verified out of order and reported broken even when correctly linked. Fixed with an explicit `chain_seq` column recording true append order. It carries a unique constraint, so if the lock ever fails the database rejects the fork rather than silently accepting it.
- Writing the regression test surfaced a third defect. Sixteen cold-start writers all miss the External Clearing lookup and race to insert the same unique name, which returns 500 on a fresh database. Fixed with a second advisory lock on the creation path only, so the common case where the account already exists takes no lock at all.
- Also fixed a latent hash bug: an amount supplied as "10" was hashed before the database normalised it to 10.00, so verification on read-back would report a false tamper. Amounts are now quantised to the column precision before hashing.
- Migration 004 re-anchors the existing chain in one deterministic pass. This repairs rows damaged by the old behaviour rather than leaving a permanently failing audit endpoint.
- Locust could not reach the live API from this machine at first. Norton antivirus intercepts TLS and re-signs certificates with its own root, which is trusted by Windows but absent from Python's certifi bundle, and Locust sets `trust_env = False` so REQUESTS_CA_BUNDLE is ignored. Worked around outside the repo so no test code trusts a weaker certificate path.

### Evidence
- Auth verified on live: admin creates accounts (201), customer denied (403), auditor reaches /audit/verify (200) but denied on transactions (403)
- GET /audit/verify returns pass on live with all six checks holding across 416 transactions and 9 accounts
- Load test: 828 requests, 0 failures, 13.9 req/s sustained
- Regression test fails 3 times out of 3 with the advisory lock removed, passes with it restored
- 52/52 tests green locally
- ruff: all checks passed

### Next
Full README.

## Milestone 5

### Goal
Close the gap between what the documentation claimed about event publishing and what the code actually did.

### Completed
- Real Pub/Sub publishing. The relay now hands each event to a transport and only marks the row published once the transport accepts it. Previously it marked events delivered without sending them anywhere.
- Two transports selected by the `PUBSUB_TOPIC` environment variable. Cloud Run publishes to Pub/Sub. Local runs and tests use a log transport, so the same relay path including failure handling is exercised without cloud credentials. The relay response reports which transport handled the batch.
- Downstream consumer in `scripts/consumer.py`. Subscribes to `transaction-events-sub`, deduplicates on the `event_id` attribute, keeps a running count per transaction type, and nacks malformed messages rather than acking them away.
- Created the Pub/Sub topic and subscription in the live project, matching the existing Terraform definitions, and granted the Cloud Run service account the publisher role on the topic.
- Added `PUBSUB_TOPIC` to the Cloud Run deploy step so the deployed service uses the real transport.
- Corrected the design document, which claimed exactly-once delivery. The outbox makes event capture atomic with the ledger write, but delivery is at-least-once and consumers must deduplicate.
- Test count: 52 to 54. Two new outbox tests: the relay reports its transport, and a failing transport leaves events pending rather than marking them delivered.

### Problems / Decisions
- The topic and subscription did not exist. Terraform declared them but had never been applied, since the original infrastructure was created by hand with gcloud. Created them directly to match the Terraform definitions rather than running `terraform apply`, which would have tried to take over the manually created Cloud SQL and Cloud Run resources.
- Chose a log transport over a stub for the no-topic case. A stub that marks rows delivered without sending them is exactly the behaviour being fixed, and it would leave the endpoint reporting success for work it did not do.
- On a publish failure the relay stops at the first failed row rather than skipping ahead. Events stay in order and the next call retries from the same point.
- gcloud could not reach the API from this machine for the same reason Locust could not: Norton intercepts TLS and its root is absent from the bundles these tools ship with. Pointed `CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE` at a combined bundle for the session.
- Confirmed the service account key used during setup is listed in .gitignore and untracked, so it has never entered the repository.

### Evidence
- Pub/Sub topic `transaction-events` and subscription `transaction-events-sub` exist in the live project
- Cloud Run service account holds `roles/pubsub.publisher` on the topic
- `POST /outbox/publish` on the live service returns `{"published": 200, "failed": 0, "transport": "pubsub"}`
- Messages confirmed on the subscription by an independent pull, carrying `event_id` and `event_type` attributes with the full transaction payload as the body
- Relay drained the full backlog of 415 events to Pub/Sub across three batches, ending at 0 pending
- 54/54 tests green locally
- ruff: all checks passed

### Next
Backup and restore evidence. Deployment rollback evidence. Full README.

## Milestone 6

### Goal
Prove two operational claims rather than assert them: that the database can actually be restored from a backup, and that a bad deployment cannot take the service down.

### Completed
- Backup and restore proven end to end. Created a Cloud Storage bucket, granted the Cloud SQL service agent write access, exported the live `ledger` database, downloaded the dump, and restored it into a separate local PostgreSQL database.
- Verified the restored copy independently. The reconciliation engine and the hash chain verifier were run directly against the restored database, not through the live service, and the row counts were compared against the live API.
- Deployment failure safety proven. Built an image that starts and then exits with a configuration error, pushed it to Artifact Registry, and deployed it to Cloud Run.
- Confirmed the failed revision never received traffic and the live service was unaffected throughout.

### Problems / Decisions
- Restored into a local PostgreSQL database rather than back into Cloud SQL. Restoring into a second cloud database would have needed IP allowlisting or a proxy to verify, and would have cost more, without proving anything extra. What matters is that the dump is complete and the restored ledger passes verification, and a local restore shows that just as well.
- The dump contained one statement that does not apply outside Cloud SQL, a grant to `cloudsqlsuperuser`. Created that role locally before restoring so the restore could run under `ON_ERROR_STOP=1` and any real error would surface rather than being skipped.
- Deployed the broken image with `--no-traffic` and a revision tag. The point is to show Cloud Run refuses to shift traffic to a revision that fails its health check, and that can be demonstrated without ever putting the live API at risk. Deliberately breaking production to prove it survives would be the wrong trade.
- Reused the deployed image and replaced only the entrypoint, so the failure is a startup fault rather than a build fault. A build failure would have been caught by CI and would not have exercised the Cloud Run health check at all.
- The failed revision cannot be deleted while it is the most recently created one. It holds no traffic and is superseded automatically by the next deploy. Its image tag was removed from Artifact Registry.

### Evidence
- Export produced a 376,687 byte dump in `gs://ledger-api-507618-backups/`
- Restore ran under `ON_ERROR_STOP=1` and exited 0, so no statement failed
- Restored copy: 417 transactions, 834 ledger entries, entry sum exactly 0.00
- Restored copy reconciliation: pass on all six checks (global invariant, per-transaction invariant, account balances, referential integrity, idempotency uniqueness, entry count)
- Restored copy hash chain: pass, 417 links, 0 broken
- Restored counts match the live service exactly: 417 transactions and 834 entries on both
- Bad deploy: revision `ledger-api-00009-faw` failed its health check and gcloud exited 1
- Traffic stayed 100% on `ledger-api-00008-ssn` throughout, and the failed revision was allocated none
- Live service during and after the failed deploy: `/health` 200, `/audit/verify` pass, `/audit/chain` pass with 417 links and 0 broken

### Next
Full README.

## Milestone 7

### Goal
Turn the root URL into a product surface rather than a raw Swagger page, and close a JWT configuration hole found while reviewing what the page should advertise.

### Completed
- Product portal at `/`: hero, live status read from `/status`, an evidence strip, the architecture path, correctness guarantees, the six-check integrity panel, the load benchmark, the concurrency-defect story, an illustrative write-path animation, and links into the API surfaces. Static HTML, CSS and vanilla JS, no framework.
- Public `/status` endpoint: a cheap unauthenticated summary (counts and a connectivity probe) that the portal polls. The full reconciliation stays authenticated because it recomputes every balance, which is not something an anonymous caller should be able to trigger.
- Scalar API reference at `/reference`, with every endpoint grouped under real tags (System, Authentication, Accounts, Transactions, Statements, Audit and Reconciliation, Event Delivery) and given summaries. Swagger stays at `/docs`.
- Consumer deduplication extracted into a testable object with four unit tests. Test count 54 to 58.

### Problems / Decisions
- Found while deciding what the page should show: the deployed service had no `JWT_SECRET_KEY` set, so it was signing tokens with the fallback default that is visible in the public repository. Anyone could forge an admin token without a password. This was the real issue behind the demo credentials, not the credentials themselves.
- Fixed at three layers. The secret is now stored in Secret Manager and injected at deploy time, the CI deploy references it with `--set-secrets` so it survives redeploys, and the application refuses to start in production when the variable is absent rather than falling back to a value from source control.
- Removed the demo credentials from the public portal and from the API description. They belong in the repository README for reviewers, not advertised on the live marketing surface.
- Kept the "Pub/Sub to idempotent consumer" path on the architecture diagram because it is genuinely wired: publishing is verified live and the consumer's deduplication is now unit-tested. Every claim on the page is evidence-backed.
- Latency of `0 ms` was displayed as `<1 ms`, since a sub-millisecond probe rounding to zero read as fake rather than fast.

### Evidence
- `/`, `/reference`, `/status`, `/docs`, `/openapi.json` all serve correctly
- Portal renders cleanly at desktop and tablet widths; the responsive rules cover phone widths
- 58/58 tests green locally
- ruff: all checks passed

### Next
Full README.

# Service Level Objectives

## Defined SLOs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.5% | Percentage of non-5xx responses during load test |
| p50 latency | < 200ms | Median response time across all endpoints |
| p95 latency | < 500ms | 95th percentile response time |
| p99 latency | < 1000ms | 99th percentile response time |
| Transaction correctness | 100% | Zero ledger invariant violations after load test (`GET /audit/verify` status = pass) |
| Error rate | < 1% | Percentage of requests returning 5xx (excluding expected 4xx like 422 insufficient funds) |
| Throughput | > 10 req/s sustained | Measured under 5 concurrent users |

## Load Test Configuration

- Tool: Locust
- Target: `https://ledger-api-465847189589.europe-west2.run.app`
- Users: 5 concurrent
- Duration: 60 seconds
- Workload mix: deposits (27%), withdrawals (18%), balance checks (27%), entry listings (9%), idempotent retries (9%), health checks (9%)

## Load Test Results

Run on 2026-09-04 against the live Cloud Run deployment. 828 requests over 60 seconds at 5 concurrent users, of which 487 were transaction writes.

| Metric | Target | Measured | Status |
|--------|--------|----------|--------|
| Availability | 99.5% | 100% (0 of 828 failed) | pass |
| p50 latency | < 200ms | 72ms | pass |
| p95 latency | < 500ms | 110ms | pass |
| p99 latency | < 1000ms | 260ms | pass |
| Error rate (5xx) | < 1% | 0% | pass |
| Throughput | > 10 req/s | 13.9 req/s | pass |
| Reconciliation (`/audit/verify`) | pass | pass | pass |
| Hash chain (`/audit/chain`) | pass | fail, see below | fixed in 004 |

Mean response time was 74.5ms and the slowest single request was 580ms. Per-endpoint medians: health 43ms, balance reads 47ms, entry listings 48ms, transaction writes 80ms.

The slowest endpoint is `POST /auth/token` at 570ms. That is expected rather than a regression: bcrypt is deliberately expensive to make password brute-forcing costly, and login happens once per session rather than per request.

## What the load test found

The reconciliation engine passed cleanly, but the hash chain verifier failed with forked links. Two defects were responsible, neither of which the unit tests could reach because both require genuine parallelism:

1. `link_transaction` read the chain tip without serialising, so two concurrent writers could link to the same predecessor. Deposits and withdrawals were accidentally protected because they all lock the shared External Clearing account, but transfers between disjoint account pairs share no row lock and forked the chain.
2. The verifier walked the chain in `created_at` order. In PostgreSQL `now()` returns transaction start time, not commit time, so a transaction that began earlier but committed later was verified out of order and reported as broken even when correctly linked.

Both are fixed in migration 004: a transaction-scoped advisory lock serialises chain appends, and an explicit `chain_seq` column records true append order. A regression test reproduces the fork with concurrent transfers and fails reliably without the lock.

This is the value of load testing stated plainly. The correctness invariants held throughout, the audit layer detected the fault, and the defect was only reachable under real concurrency.

## Post-Load Verification

After the load test completes, the reconciliation engine (`GET /audit/verify`) is run against the live database. It independently recomputes every account balance, checks every transaction sums to zero, checks the global ledger invariant, verifies referential integrity, and confirms idempotency key uniqueness. A passing result proves the ledger maintained correctness under concurrent load.

The hash chain verifier (`GET /audit/chain`) is also run to confirm no transactions were corrupted during the load test.

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

*To be filled after running Locust against the live deployment.*

| Metric | Target | Measured | Status |
|--------|--------|----------|--------|
| Availability | 99.5% | | |
| p50 latency | < 200ms | | |
| p95 latency | < 500ms | | |
| p99 latency | < 1000ms | | |
| Error rate (5xx) | < 1% | | |
| Throughput | > 10 req/s | | |
| Ledger integrity | pass | | |

## Post-Load Verification

After the load test completes, the reconciliation engine (`GET /audit/verify`) is run against the live database. It independently recomputes every account balance, checks every transaction sums to zero, checks the global ledger invariant, verifies referential integrity, and confirms idempotency key uniqueness. A passing result proves the ledger maintained correctness under concurrent load.

The hash chain verifier (`GET /audit/chain`) is also run to confirm no transactions were corrupted during the load test.

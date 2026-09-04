# Threat Model (STRIDE)

## Scope

This threat model covers the ledger-api service: a double-entry financial ledger API deployed on GCP Cloud Run with Cloud SQL PostgreSQL. It does not cover network-level DDoS or physical security of cloud infrastructure.

## Assets

| Asset | Sensitivity | Location |
|-------|-------------|----------|
| Ledger entries | High (financial records) | Cloud SQL |
| Account balances | High (derived from entries) | Computed at query time |
| Transaction history | High (tamper-evident chain) | Cloud SQL |
| JWT signing key | Critical (controls all access) | Environment variable |
| Database credentials | Critical | Environment variable / Secret Manager |
| GCP service account key | Critical | GitHub Secrets |

## Threat Analysis

### S: Spoofing

| Threat | Mitigation | Test |
|--------|------------|------|
| Attacker forges JWT to impersonate admin | JWTs signed with HS256 secret. Secret rotated via environment variable, not hardcoded. | `test_unauthenticated_request_rejected`, `test_login_invalid_credentials` |
| Attacker replays a valid JWT after expiration | Tokens expire after 60 minutes (`exp` claim enforced by jose). | Token expiry validated in `get_current_user` |
| Attacker guesses user credentials | Passwords hashed with bcrypt (cost factor 12). Brute force mitigated by bcrypt's computational cost. | `test_login_invalid_credentials` |

### T: Tampering

| Threat | Mitigation | Test |
|--------|------------|------|
| Direct database modification of ledger entries | Tamper-evident hash chain: each transaction includes `prev_hash` and `chain_hash`. Any modification breaks the chain. | `test_hash_chain_detects_tamper` |
| Modification of transaction amounts after recording | Append-only ledger design. No UPDATE or DELETE endpoints for entries. Corrections require compensating entries. | `test_no_put_on_entries`, `test_no_delete_on_entries` |
| SQL injection via API parameters | All queries use SQLAlchemy ORM with parameterised queries. Pydantic validates and coerces all input before it reaches the service layer. | Type-safe UUID/Decimal parsing rejects injection strings |

### R: Repudiation

| Threat | Mitigation | Test |
|--------|------------|------|
| User denies making a transaction | Every transaction has a unique `idempotency_key` supplied by the caller and a `request_hash` of the full request body. Structured JSON logs include `transaction_id` and `request_id` for correlation. | `test_idempotent_deposits_never_duplicate` |
| Operator denies altering the ledger | Hash chain provides cryptographic proof of transaction ordering. `GET /audit/chain` independently verifies the full chain. | `test_hash_chain_intact` |

### I: Information Disclosure

| Threat | Mitigation | Test |
|--------|------------|------|
| Unauthenticated access to account data | All account/transaction endpoints require valid JWT. Health endpoint is the only public route. | `test_unauthenticated_request_rejected` |
| Customer accessing another customer's data | Role-based access control: customers can transact, auditors can inspect, admins can provision. (Per-account ownership not yet implemented.) | `test_customer_cannot_create_account`, `test_auditor_cannot_transact` |
| Stack traces in error responses | FastAPI returns structured JSON errors. No stack traces or internal state in production responses. | Validated by manual inspection |
| Credential leakage in logs | Structured JSON logging excludes request bodies and credentials. Only metadata (path, status, timing) is logged. | Log format defined in `app/logging.py` |

### D: Denial of Service

| Threat | Mitigation | Test |
|--------|------------|------|
| Resource exhaustion via large queries | Cursor-based pagination with configurable limits (max 100 items per page). | Pagination enforced on all list endpoints |
| Database connection exhaustion | Cloud Run scales 0-3 instances. Cloud SQL connection pooling limits concurrent connections. | Scaling config in Terraform |
| Malicious transaction payloads | Pydantic enforces `amount > 0`, valid enum types, valid UUIDs. Invalid requests rejected at the validation layer before reaching the database. | `test_negative_amount_rejected`, `test_zero_amount_rejected` |

### E: Elevation of Privilege

| Threat | Mitigation | Test |
|--------|------------|------|
| Customer escalates to admin role | Roles embedded in JWT at token creation time. No endpoint allows role modification. Token must be re-issued by the auth endpoint with valid credentials. | `test_customer_cannot_create_account` |
| Auditor creates transactions | Auditors are explicitly excluded from the transaction creation role check (`admin` and `customer` only). | `test_auditor_cannot_transact` |
| Customer accesses audit endpoints | Audit endpoints restricted to `auditor` and `admin` roles. | `test_customer_cannot_verify_ledger` |
| Customer accesses outbox/admin endpoints | Outbox endpoints restricted to `admin` role. | `test_customer_cannot_access_outbox` |

## Mitigations Not Yet Implemented

| Gap | Risk | Priority |
|-----|------|----------|
| Per-account ownership (customer A sees only their accounts) | Medium: any authenticated customer can see any account | Would add in production |
| Rate limiting | Medium: authenticated brute force, API abuse | Would add via Cloud Armor or middleware |
| Refresh tokens | Low: 60-minute access tokens are sufficient for a portfolio project | Would add for long-lived sessions |
| Audit log of authentication events | Low: login attempts not persisted | Would add for compliance |

## Requirement-to-Test Traceability

| Requirement | Tests |
|-------------|-------|
| Idempotency prevents duplicate transactions | `test_idempotent_deposits_never_duplicate`, `test_idempotency_conflict_never_creates_transaction`, `test_duplicate_idempotency_key_under_rapid_fire` |
| Double-entry invariant holds under all operations | `test_audit_verify_clean_ledger`, `test_balance_equals_sum_of_entries`, `test_ledger_invariants_under_random_operations` |
| Hash chain detects tampering | `test_hash_chain_intact`, `test_hash_chain_detects_tamper` |
| Role-based access control | `test_customer_cannot_create_account`, `test_auditor_cannot_transact`, `test_customer_cannot_verify_ledger`, `test_customer_cannot_access_outbox` |
| Authentication required | `test_unauthenticated_request_rejected`, `test_login_invalid_credentials` |
| Overdraw prevention | `test_overdraw_never_permitted`, `test_withdrawal_overdraw_preserves_ledger_integrity` |
| Crash recovery | `test_commit_failure_rolls_back`, `test_transfer_failure_leaves_no_partial_entries` |

# Verification and Validation Plan

## Approach

All functional and non-functional requirements are verified through automated tests running against a PostgreSQL test database. CI evidence is provided by the GitHub Actions workflow.

## Requirement-to-Test Mapping

| Requirement | Verification | Test / Evidence |
|-------------|-------------|-----------------|
| REQ-F-001 | Automated | test_create_account, test_duplicate_account_name |
| REQ-F-002 | Automated | test_deposit, test_deposit_creates_clearing_entries |
| REQ-F-003 | Automated | test_withdrawal |
| REQ-F-004 | Automated | test_transfer |
| REQ-F-005 | Automated | test_deposit (balance check), test_withdrawal (balance check) |
| REQ-F-006 | Automated | test_duplicate_key_same_params_returns_original |
| REQ-F-007 | Automated | test_duplicate_key_different_params_returns_409 |
| REQ-F-008 | Automated + Inspection | No ledger mutation/delete API exposed; test that unsupported methods return 405 |
| REQ-F-009 | Automated | test_withdrawal_insufficient_balance, test_transfer_insufficient_funds |
| REQ-F-010 | Automated | test_self_transfer_rejected |
| REQ-F-011 | Automated | test_negative_amount_rejected, test_zero_amount_rejected |
| REQ-F-012 | Automated | test_health |
| REQ-F-013 | Automated | test_list_transactions (to be added) |
| REQ-F-014 | Automated | test_list_entries (to be added) |
| REQ-NF-001 | Automated + Inspection | test_decimal_precision_no_drift; Numeric(12,2) in models, Decimal in schemas |
| REQ-NF-002 | Automated | test_concurrent_withdrawals_cannot_overspend |
| REQ-NF-003 | By design | .gitignore excludes .env, DATABASE_URL from environment |
| REQ-NF-004 | CI evidence | GitHub Actions workflow (ruff + pytest on push) |
| REQ-NF-005 | Automated | test_global_ledger_invariant |
| REQ-NF-006 | Automated | test_per_transaction_invariant |
| REQ-NF-007 | By design | docker-compose.yml provides local PostgreSQL |
| REQ-NF-008 | CI evidence | Alembic upgrade runs in CI before tests (clean PG to current schema) |

## Acceptance Criteria

The project passes V&V when:
- All requirements have either an automated test or a by-design justification.
- CI is green against PostgreSQL.
- The live Azure endpoint returns 200 on /health.

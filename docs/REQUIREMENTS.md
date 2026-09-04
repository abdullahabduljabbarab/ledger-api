# Requirements

## Functional

| ID | Requirement |
|----|-------------|
| REQ-F-001 | The system shall allow creation of a uniquely named account. |
| REQ-F-002 | The system shall record deposits as balanced ledger entries against an internal clearing account. |
| REQ-F-003 | The system shall record withdrawals as balanced ledger entries against an internal clearing account. |
| REQ-F-004 | The system shall execute transfers atomically, debiting one account and crediting another in a single database transaction. |
| REQ-F-005 | The system shall derive account balances from the sum of ledger entries, never from a stored balance field. |
| REQ-F-006 | The system shall return the original transaction when a duplicate idempotency key is submitted with matching parameters. |
| REQ-F-007 | The system shall reject a duplicate idempotency key submitted with different parameters (409 Conflict). |
| REQ-F-008 | The application shall not expose operations that modify or delete ledger entries. Corrections use compensating entries. |
| REQ-F-009 | The system shall reject withdrawals and transfers where the source account has insufficient balance. |
| REQ-F-010 | The system shall reject self-transfers (from and to the same account). |
| REQ-F-011 | The system shall reject negative and zero transaction amounts. |
| REQ-F-012 | The system shall expose a health endpoint for liveness checks. |
| REQ-F-013 | The system shall provide queryable transaction history with optional filters (account, type). |
| REQ-F-014 | The system shall provide a per-account ledger entry audit trail. |

## Non-Functional

| ID | Requirement |
|----|-------------|
| REQ-NF-001 | All monetary values shall use Decimal (Python) and Numeric(12,2) (PostgreSQL). No floats. |
| REQ-NF-002 | Concurrent transactions against the same account shall not cause double-spending. Row-level locking (SELECT ... FOR UPDATE) with deterministic lock ordering. |
| REQ-NF-003 | Database credentials and secrets shall be stored in environment variables, never in source control. |
| REQ-NF-004 | The CI pipeline shall run linting (ruff) and automated tests (pytest) before deployment. |
| REQ-NF-005 | After every committed transaction, the sum of all ledger entries across the system shall equal zero. |
| REQ-NF-006 | Every committed transaction shall have ledger entries whose sum equals zero. |
| REQ-NF-007 | Local development shall use PostgreSQL (via Docker Compose), matching the production database engine. |
| REQ-NF-008 | Schema changes shall be managed through versioned Alembic migrations. |

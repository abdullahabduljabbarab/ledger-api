# MVP Scope

## Objective

Build and deploy a cloud-hosted double-entry ledger API demonstrating modern backend and cloud engineering.

## Must-have

- Create accounts
- Deposit, withdraw, transfer
- Immutable balanced ledger entries (double-entry, External Clearing counterparty)
- Derived balances (never stored, always computed from entries)
- Idempotent writes with payload conflict detection
- Atomic transactions
- Concurrency protection (row-level locking)
- PostgreSQL (local and production)
- Azure deployment (App Service + PostgreSQL Flexible Server)
- CI/CD (GitHub Actions)
- Automated test suite
- OpenAPI documentation (/docs)

## Not in scope

- Frontend
- OAuth / authentication
- Kubernetes
- Kafka / message queues
- Microservices
- Redis
- Terraform
- Production banking compliance
- Real payment rails
- Real personal or financial data

## Definition of Done

- Live Azure endpoint returning 200 on /health
- PostgreSQL production database with migrated schema
- All tests green against PostgreSQL
- CI/CD pipeline deploying on green main
- /docs (Swagger) accessible on the live endpoint
- README complete with architecture, examples, and live link

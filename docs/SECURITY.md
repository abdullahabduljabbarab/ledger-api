# Security

## What this project is

A portfolio demonstration of backend and cloud engineering. It is not a production banking system and does not handle real personal or financial data.

## Boundaries

**Secrets management.** Database credentials are stored in environment variables (Azure App Service configuration for production, .env for local development). No credentials are committed to source control. `.gitignore` excludes `.env`.

**Input validation.** All requests are validated through Pydantic models before reaching the service layer. Invalid types, negative amounts, missing fields, and malformed UUIDs are rejected with structured error responses.

**SQL injection.** All database queries go through SQLAlchemy's ORM and parameterised queries. No raw string interpolation in SQL.

**Identifiers.** Accounts and transactions use UUIDs. No sequential integer IDs exposed.

**Error responses.** Structured JSON errors. No stack traces or internal state leaked in responses.

**HTTPS.** Handled by Azure App Service at the infrastructure level. The application itself does not terminate TLS.

## Authentication

None. This is a deliberate scope decision for a portfolio project. Adding token-based auth would be straightforward but is not the engineering point this project is making.

## Known limitations

- No rate limiting
- No role-based access control
- No audit logging beyond the immutable ledger entries themselves
- Encryption at rest relies on the managed encryption provided by Azure Database for PostgreSQL. Customer-managed keys are outside project scope.

# ledger-api

Append-only double-entry ledger API deployed on Azure. FastAPI, PostgreSQL, CI/CD.

## Quick start

```bash
docker compose up -d
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

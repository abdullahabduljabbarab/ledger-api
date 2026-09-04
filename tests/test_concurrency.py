import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

import app.database as database_module
from app.database import get_db
from app.main import app


def test_concurrent_withdrawals_cannot_overspend(setup_db):
    run_id = uuid.uuid4().hex[:8]

    def fresh_client():
        def override():
            db = database_module.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        return TestClient(app)

    c = fresh_client()
    acc = c.post("/accounts", json={"name": f"ConcUser-{run_id}"}).json()["id"]
    c.post("/transactions", json={
        "idempotency_key": f"conc-fund-{run_id}",
        "type": "deposit",
        "amount": "100.00",
        "account_id": acc,
    })

    def withdraw(key):
        cl = fresh_client()
        return cl.post("/transactions", json={
            "idempotency_key": key,
            "type": "withdrawal",
            "amount": "80.00",
            "account_id": acc,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(withdraw, f"conc-wd-1-{run_id}")
        f2 = pool.submit(withdraw, f"conc-wd-2-{run_id}")
        r1, r2 = f1.result(), f2.result()

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 422], (
        f"Expected one success and one failure, got {r1.status_code} and {r2.status_code}"
    )

    c2 = fresh_client()
    bal = c2.get(f"/accounts/{acc}/balance").json()
    assert Decimal(bal["balance"]) == Decimal("20.00")

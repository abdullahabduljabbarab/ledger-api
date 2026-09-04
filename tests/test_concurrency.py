from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import SessionLocal, get_db
from app.main import app


def test_concurrent_withdrawals_cannot_overspend(setup_db):
    def fresh_client():
        def override():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        return TestClient(app)

    c = fresh_client()
    acc = c.post("/accounts", json={"name": "ConcUser"}).json()["id"]
    c.post("/transactions", json={
        "idempotency_key": "conc-fund",
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
        f1 = pool.submit(withdraw, "conc-wd-1")
        f2 = pool.submit(withdraw, "conc-wd-2")
        r1, r2 = f1.result(), f2.result()

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 422], (
        f"Expected one success and one failure, got {r1.status_code} and {r2.status_code}"
    )

    c2 = fresh_client()
    bal = c2.get(f"/accounts/{acc}/balance").json()
    assert Decimal(bal["balance"]) == Decimal("20.00")

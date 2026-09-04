from decimal import Decimal


def _create_account(client, name="DecimalUser"):
    return client.post("/accounts", json={"name": name}).json()["id"]


def test_decimal_precision_no_drift(client):
    acc = _create_account(client)

    for i in range(100):
        client.post("/transactions", json={
            "idempotency_key": f"drift-dep-{i}",
            "type": "deposit",
            "amount": "0.01",
            "account_id": acc,
        })

    bal = client.get(f"/accounts/{acc}/balance").json()
    assert Decimal(bal["balance"]) == Decimal("1.00")

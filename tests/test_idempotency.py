def _create_account(client, name="IdempUser"):
    return client.post("/accounts", json={"name": name}).json()["id"]


def test_duplicate_key_same_params_returns_original(client):
    acc = _create_account(client)
    payload = {
        "idempotency_key": "idem-1",
        "type": "deposit",
        "amount": "75.00",
        "account_id": acc,
    }
    r1 = client.post("/transactions", json=payload)
    r2 = client.post("/transactions", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_duplicate_key_different_params_returns_409(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "idem-conflict",
        "type": "deposit",
        "amount": "50.00",
        "account_id": acc,
    })
    resp = client.post("/transactions", json={
        "idempotency_key": "idem-conflict",
        "type": "deposit",
        "amount": "500.00",
        "account_id": acc,
    })
    assert resp.status_code == 409

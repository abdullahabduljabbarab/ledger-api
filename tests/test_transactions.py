from decimal import Decimal


def _create_account(client, name="TestUser"):
    resp = client.post("/accounts", json={"name": name})
    return resp.json()["id"]


def test_deposit(client):
    acc = _create_account(client)
    resp = client.post("/transactions", json={
        "idempotency_key": "dep-1",
        "type": "deposit",
        "amount": "100.00",
        "account_id": acc,
    })
    assert resp.status_code == 201

    bal = client.get(f"/accounts/{acc}/balance").json()
    assert Decimal(bal["balance"]) == Decimal("100.00")


def test_deposit_creates_clearing_entries(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "dep-2",
        "type": "deposit",
        "amount": "50.00",
        "account_id": acc,
    })
    entries = client.get(f"/accounts/{acc}/entries").json()
    assert len(entries) == 1
    assert Decimal(entries[0]["amount"]) == Decimal("50.00")


def test_withdrawal(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "dep-w",
        "type": "deposit",
        "amount": "200.00",
        "account_id": acc,
    })
    resp = client.post("/transactions", json={
        "idempotency_key": "wd-1",
        "type": "withdrawal",
        "amount": "80.00",
        "account_id": acc,
    })
    assert resp.status_code == 201

    bal = client.get(f"/accounts/{acc}/balance").json()
    assert Decimal(bal["balance"]) == Decimal("120.00")


def test_withdrawal_insufficient_balance(client):
    acc = _create_account(client)
    resp = client.post("/transactions", json={
        "idempotency_key": "wd-fail",
        "type": "withdrawal",
        "amount": "50.00",
        "account_id": acc,
    })
    assert resp.status_code == 422


def test_negative_amount_rejected(client):
    acc = _create_account(client)
    resp = client.post("/transactions", json={
        "idempotency_key": "neg-1",
        "type": "deposit",
        "amount": "-10.00",
        "account_id": acc,
    })
    assert resp.status_code == 422


def test_zero_amount_rejected(client):
    acc = _create_account(client)
    resp = client.post("/transactions", json={
        "idempotency_key": "zero-1",
        "type": "deposit",
        "amount": "0.00",
        "account_id": acc,
    })
    assert resp.status_code == 422


def test_transfer(client):
    a = _create_account(client, "Alice")
    b = _create_account(client, "Bob")
    client.post("/transactions", json={
        "idempotency_key": "fund-a",
        "type": "deposit",
        "amount": "500.00",
        "account_id": a,
    })
    resp = client.post("/transactions", json={
        "idempotency_key": "xfer-1",
        "type": "transfer",
        "amount": "200.00",
        "from_account_id": a,
        "to_account_id": b,
    })
    assert resp.status_code == 201

    assert Decimal(client.get(f"/accounts/{a}/balance").json()["balance"]) == Decimal("300.00")
    assert Decimal(client.get(f"/accounts/{b}/balance").json()["balance"]) == Decimal("200.00")


def test_transfer_insufficient_funds(client):
    a = _create_account(client, "A_poor")
    b = _create_account(client, "B_rich")
    resp = client.post("/transactions", json={
        "idempotency_key": "xfer-fail",
        "type": "transfer",
        "amount": "100.00",
        "from_account_id": a,
        "to_account_id": b,
    })
    assert resp.status_code == 422


def test_self_transfer_rejected(client):
    a = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "fund-self",
        "type": "deposit",
        "amount": "100.00",
        "account_id": a,
    })
    resp = client.post("/transactions", json={
        "idempotency_key": "self-xfer",
        "type": "transfer",
        "amount": "10.00",
        "from_account_id": a,
        "to_account_id": a,
    })
    assert resp.status_code == 422

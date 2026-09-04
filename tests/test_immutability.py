def _create_account(client, name="ImmUser"):
    return client.post("/accounts", json={"name": name}).json()["id"]


def test_no_put_on_entries(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "imm-dep",
        "type": "deposit",
        "amount": "50.00",
        "account_id": acc,
    })
    entries = client.get(f"/accounts/{acc}/entries").json()
    entry_id = entries[0]["id"]

    resp = client.put(f"/accounts/{acc}/entries/{entry_id}", json={"amount": "999.00"})
    assert resp.status_code == 405


def test_no_delete_on_entries(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": "imm-dep-2",
        "type": "deposit",
        "amount": "50.00",
        "account_id": acc,
    })
    entries = client.get(f"/accounts/{acc}/entries").json()
    entry_id = entries[0]["id"]

    resp = client.delete(f"/accounts/{acc}/entries/{entry_id}")
    assert resp.status_code == 405

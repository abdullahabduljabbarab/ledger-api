import uuid


def test_create_account(client):
    resp = client.post("/accounts", json={"name": "Alice"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alice"
    assert data["is_system"] is False


def test_get_account(client):
    resp = client.post("/accounts", json={"name": "Bob"})
    account_id = resp.json()["id"]

    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Bob"


def test_get_nonexistent_account(client):
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/accounts/{fake_id}")
    assert resp.status_code == 404


def test_duplicate_account_name(client):
    client.post("/accounts", json={"name": "Charlie"})
    resp = client.post("/accounts", json={"name": "Charlie"})
    assert resp.status_code == 409

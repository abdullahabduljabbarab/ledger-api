import uuid


def _create_account(client, name=None):
    name = name or f"outbox-{uuid.uuid4().hex[:8]}"
    return client.post("/accounts", json={"name": name}).json()["id"]


def test_transaction_creates_outbox_event(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "100.00",
        "account_id": acc,
    })

    resp = client.get("/outbox/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pending_count"] >= 1
    assert data["events"][0]["event_type"] == "transaction.deposit"


def test_outbox_publish_marks_events(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "50.00",
        "account_id": acc,
    })

    before = client.get("/outbox/pending").json()
    assert before["pending_count"] >= 1

    pub_resp = client.post("/outbox/publish")
    assert pub_resp.status_code == 200
    assert pub_resp.json()["published"] >= 1

    after = client.get("/outbox/pending").json()
    assert after["pending_count"] == 0


def test_publish_reports_transport(client):
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "10.00",
        "account_id": acc,
    })

    body = client.post("/outbox/publish").json()
    assert body["transport"] == "log"
    assert body["published"] >= 1
    assert body["failed"] == 0


def test_publish_failure_leaves_events_pending(client, monkeypatch):
    """A transport failure must never mark an event as delivered."""
    acc = _create_account(client)
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "10.00",
        "account_id": acc,
    })

    class BrokenTransport:
        name = "broken"

        def publish(self, event_id, event_type, payload):
            raise RuntimeError("transport unavailable")

    monkeypatch.setattr("app.main.get_transport", lambda: BrokenTransport())

    body = client.post("/outbox/publish").json()
    assert body["published"] == 0
    assert body["failed"] >= 1

    after = client.get("/outbox/pending").json()
    assert after["pending_count"] >= 1


def test_idempotent_replay_does_not_create_outbox_event(client):
    acc = _create_account(client)
    key = uuid.uuid4().hex

    client.post("/transactions", json={
        "idempotency_key": key,
        "type": "deposit",
        "amount": "25.00",
        "account_id": acc,
    })

    client.post("/outbox/publish")

    client.post("/transactions", json={
        "idempotency_key": key,
        "type": "deposit",
        "amount": "25.00",
        "account_id": acc,
    })

    after = client.get("/outbox/pending").json()
    assert after["pending_count"] == 0

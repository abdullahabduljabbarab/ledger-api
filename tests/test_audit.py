import uuid


def _create_account(client, name=None):
    name = name or f"audit-{uuid.uuid4().hex[:8]}"
    return client.post("/accounts", json={"name": name}).json()["id"]


def _deposit(client, account_id, amount="100.00"):
    return client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": amount,
        "account_id": account_id,
    })


def test_audit_verify_clean_ledger(client):
    acc = _create_account(client)
    _deposit(client, acc, "500.00")
    _deposit(client, acc, "250.00")

    resp = client.get("/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pass"
    assert data["checks"]["global_invariant"]["pass"] is True
    assert data["checks"]["per_transaction_invariant"]["pass"] is True
    assert data["checks"]["referential_integrity"]["pass"] is True
    assert data["checks"]["idempotency_uniqueness"]["pass"] is True
    assert data["checks"]["entry_count"]["pass"] is True
    assert len(data["discrepancies"]) == 0


def test_audit_verify_after_transfer(client):
    a = _create_account(client, f"audit-a-{uuid.uuid4().hex[:6]}")
    b = _create_account(client, f"audit-b-{uuid.uuid4().hex[:6]}")
    _deposit(client, a, "1000.00")
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "transfer",
        "amount": "300.00",
        "from_account_id": a,
        "to_account_id": b,
    })

    resp = client.get("/audit/verify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pass"


def test_hash_chain_intact(client):
    acc = _create_account(client)
    _deposit(client, acc, "100.00")
    _deposit(client, acc, "200.00")
    _deposit(client, acc, "300.00")

    resp = client.get("/audit/chain")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pass"
    assert data["chain_length"] == 3
    assert len(data["broken_links"]) == 0


def test_hash_chain_detects_tamper(client, db):
    acc = _create_account(client)
    _deposit(client, acc, "100.00")
    _deposit(client, acc, "200.00")

    from sqlalchemy import select

    from app.models import Transaction

    txn = db.execute(
        select(Transaction)
        .where(Transaction.chain_hash.isnot(None))
        .order_by(Transaction.created_at.asc())
        .limit(1)
    ).scalar_one()
    txn.chain_hash = "tampered" + txn.chain_hash[8:]
    db.commit()

    resp = client.get("/audit/chain")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "fail"
    assert any(
        link.get("tamper_detected") for link in data["broken_links"]
    )

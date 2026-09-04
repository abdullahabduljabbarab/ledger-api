import uuid

from app.auth import Role, TokenData, create_access_token


def _token(role: Role) -> dict:
    token = create_access_token(TokenData(username="test", role=role))
    return {"Authorization": f"Bearer {token}"}


def test_login_valid_credentials(raw_client):
    resp = raw_client.post("/auth/token", data={
        "username": "admin",
        "password": "admin123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert resp.json()["token_type"] == "bearer"


def test_login_invalid_credentials(raw_client):
    resp = raw_client.post("/auth/token", data={
        "username": "admin",
        "password": "wrong",
    })
    assert resp.status_code == 401


def test_unauthenticated_request_rejected(raw_client):
    resp = raw_client.post("/accounts", json={"name": "NoAuth"})
    assert resp.status_code == 401


def test_customer_cannot_create_account(raw_client):
    resp = raw_client.post(
        "/accounts",
        json={"name": "Forbidden"},
        headers=_token(Role.customer),
    )
    assert resp.status_code == 403


def test_auditor_cannot_create_account(raw_client):
    resp = raw_client.post(
        "/accounts",
        json={"name": "Forbidden"},
        headers=_token(Role.auditor),
    )
    assert resp.status_code == 403


def test_admin_can_create_account(raw_client):
    resp = raw_client.post(
        "/accounts",
        json={"name": f"AdminAcc-{uuid.uuid4().hex[:6]}"},
        headers=_token(Role.admin),
    )
    assert resp.status_code == 201


def test_customer_can_transact(raw_client):
    headers = _token(Role.admin)
    acc = raw_client.post(
        "/accounts",
        json={"name": f"CustTxn-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    ).json()["id"]

    cust_headers = _token(Role.customer)
    resp = raw_client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "100.00",
        "account_id": acc,
    }, headers=cust_headers)
    assert resp.status_code == 201


def test_auditor_cannot_transact(raw_client):
    headers = _token(Role.admin)
    acc = raw_client.post(
        "/accounts",
        json={"name": f"AudTxn-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    ).json()["id"]

    aud_headers = _token(Role.auditor)
    resp = raw_client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": "100.00",
        "account_id": acc,
    }, headers=aud_headers)
    assert resp.status_code == 403


def test_auditor_can_verify_ledger(raw_client):
    resp = raw_client.get("/audit/verify", headers=_token(Role.auditor))
    assert resp.status_code == 200


def test_customer_cannot_verify_ledger(raw_client):
    resp = raw_client.get("/audit/verify", headers=_token(Role.customer))
    assert resp.status_code == 403


def test_customer_cannot_access_outbox(raw_client):
    resp = raw_client.get("/outbox/pending", headers=_token(Role.customer))
    assert resp.status_code == 403

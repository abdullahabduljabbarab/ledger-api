import uuid
from decimal import Decimal
from unittest.mock import patch


def _create_funded_account(client, balance="500.00"):
    name = f"res-{uuid.uuid4().hex[:8]}"
    acc = client.post("/accounts", json={"name": name}).json()
    client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "deposit",
        "amount": balance,
        "account_id": acc["id"],
    })
    return acc["id"]


def _balance(client, account_id):
    return Decimal(client.get(f"/accounts/{account_id}/balance").json()["balance"])


def test_commit_failure_rolls_back(client, db):
    """Force an exception during commit. The database transaction should
    roll back entirely, leaving no partial entries or transactions."""
    acc = _create_funded_account(client)
    original_balance = _balance(client, acc)

    from sqlalchemy.orm import Session as SASession

    def exploding_commit(self):
        self.rollback()
        raise RuntimeError("Simulated database failure during commit")

    crashed = False
    with patch.object(SASession, "commit", exploding_commit):
        try:
            client.post("/transactions", json={
                "idempotency_key": uuid.uuid4().hex,
                "type": "withdrawal",
                "amount": "100.00",
                "account_id": acc,
            })
        except Exception:
            crashed = True

    assert crashed, "Expected crash did not occur"

    final_balance = _balance(client, acc)
    assert final_balance == original_balance, (
        f"Failed commit changed balance: {final_balance} != {original_balance}"
    )


def test_duplicate_idempotency_key_under_rapid_fire(client):
    """Hammer the same idempotency key rapidly. Only one transaction should exist."""
    acc = _create_funded_account(client)
    key = uuid.uuid4().hex

    results = []
    for _ in range(10):
        resp = client.post("/transactions", json={
            "idempotency_key": key,
            "type": "deposit",
            "amount": "50.00",
            "account_id": acc,
        })
        results.append(resp.status_code)

    assert results.count(201) == 10, (
        "Idempotent replays should all return 201 with the original transaction"
    )

    bal = _balance(client, acc)
    assert bal == Decimal("550.00"), (
        f"Rapid-fire idempotent deposits created duplicates: {bal} != 550.00"
    )

    txn_ids = set()
    for _ in range(10):
        resp = client.post("/transactions", json={
            "idempotency_key": key,
            "type": "deposit",
            "amount": "50.00",
            "account_id": acc,
        })
        txn_ids.add(resp.json()["id"])

    assert len(txn_ids) == 1, f"Multiple transaction IDs for same key: {txn_ids}"


def test_transfer_failure_leaves_no_partial_entries(client):
    """A transfer that fails validation should not create any ledger entries."""
    acc_a = _create_funded_account(client, "100.00")
    acc_b = _create_funded_account(client)

    resp = client.post("/transactions", json={
        "idempotency_key": uuid.uuid4().hex,
        "type": "transfer",
        "amount": "999.00",
        "from_account_id": acc_a,
        "to_account_id": acc_b,
    })
    assert resp.status_code == 422

    bal_a = _balance(client, acc_a)
    bal_b = _balance(client, acc_b)
    assert bal_a == Decimal("100.00"), f"Source account changed: {bal_a}"
    assert bal_b == Decimal("500.00"), f"Dest account changed: {bal_b}"


def test_withdrawal_overdraw_preserves_ledger_integrity(client):
    """Many failed overdraw attempts should never corrupt the ledger."""
    acc = _create_funded_account(client, "10.00")

    for i in range(20):
        client.post("/transactions", json={
            "idempotency_key": uuid.uuid4().hex,
            "type": "withdrawal",
            "amount": "10.01",
            "account_id": acc,
        })

    bal = _balance(client, acc)
    assert bal == Decimal("10.00"), f"Failed withdrawals changed balance: {bal}"

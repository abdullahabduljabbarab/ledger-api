from decimal import Decimal

from sqlalchemy import func, select

from app.models import LedgerEntry, Transaction


def _create_account(client, name):
    return client.post("/accounts", json={"name": name}).json()["id"]


def test_global_ledger_invariant(client, db):
    a = _create_account(client, "Inv_A")
    b = _create_account(client, "Inv_B")

    client.post("/transactions", json={
        "idempotency_key": "inv-dep",
        "type": "deposit",
        "amount": "1000.00",
        "account_id": a,
    })
    client.post("/transactions", json={
        "idempotency_key": "inv-xfer",
        "type": "transfer",
        "amount": "300.00",
        "from_account_id": a,
        "to_account_id": b,
    })
    client.post("/transactions", json={
        "idempotency_key": "inv-wd",
        "type": "withdrawal",
        "amount": "50.00",
        "account_id": b,
    })

    total = db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0))
    ).scalar()
    assert Decimal(str(total)) == Decimal("0.00")


def test_per_transaction_invariant(client, db):
    a = _create_account(client, "TxnInv_A")
    b = _create_account(client, "TxnInv_B")

    client.post("/transactions", json={
        "idempotency_key": "txn-inv-dep",
        "type": "deposit",
        "amount": "500.00",
        "account_id": a,
    })
    client.post("/transactions", json={
        "idempotency_key": "txn-inv-xfer",
        "type": "transfer",
        "amount": "100.00",
        "from_account_id": a,
        "to_account_id": b,
    })
    client.post("/transactions", json={
        "idempotency_key": "txn-inv-wd",
        "type": "withdrawal",
        "amount": "25.00",
        "account_id": b,
    })

    txns = db.execute(select(Transaction)).scalars().all()
    for txn in txns:
        entry_sum = db.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.transaction_id == txn.id
            )
        ).scalar()
        assert Decimal(str(entry_sum)) == Decimal("0.00"), (
            f"Transaction {txn.id} ({txn.type}) entries do not balance: {entry_sum}"
        )

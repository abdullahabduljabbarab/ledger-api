import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

logger = logging.getLogger("ledger.chain")

GENESIS_HASH = "0" * 64


def compute_chain_hash(txn: Transaction, prev_hash: str) -> str:
    payload = (
        f"{txn.id}|{txn.idempotency_key}|{txn.type.value}|"
        f"{txn.amount}|{txn.request_hash}|{prev_hash}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def link_transaction(db: Session, txn: Transaction) -> None:
    prev = db.execute(
        select(Transaction)
        .where(Transaction.id != txn.id)
        .where(Transaction.chain_hash.isnot(None))
        .order_by(Transaction.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    prev_hash = prev.chain_hash if prev else GENESIS_HASH
    txn.prev_hash = prev_hash
    txn.chain_hash = compute_chain_hash(txn, prev_hash)


def verify_hash_chain(db: Session) -> dict:
    transactions = list(
        db.execute(
            select(Transaction)
            .where(Transaction.chain_hash.isnot(None))
            .order_by(Transaction.created_at.asc())
        ).scalars().all()
    )

    if not transactions:
        return {
            "status": "pass",
            "chain_length": 0,
            "message": "No chained transactions found",
        }

    broken_links = []
    expected_prev = GENESIS_HASH

    for txn in transactions:
        if txn.prev_hash != expected_prev:
            broken_links.append({
                "transaction_id": str(txn.id),
                "expected_prev": expected_prev,
                "actual_prev": txn.prev_hash,
            })

        recomputed = compute_chain_hash(txn, txn.prev_hash)
        if recomputed != txn.chain_hash:
            broken_links.append({
                "transaction_id": str(txn.id),
                "stored_hash": txn.chain_hash,
                "recomputed_hash": recomputed,
                "tamper_detected": True,
            })

        expected_prev = txn.chain_hash

    status = "pass" if not broken_links else "fail"
    logger.info(
        f"Hash chain verification: {status}",
        extra={"chain_length": len(transactions)},
    )

    return {
        "status": status,
        "chain_length": len(transactions),
        "broken_links": broken_links,
    }

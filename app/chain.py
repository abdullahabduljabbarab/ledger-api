import hashlib
import logging
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Transaction

logger = logging.getLogger("ledger.chain")

GENESIS_HASH = "0" * 64

AMOUNT_PRECISION = Decimal("0.01")

# Every writer contends on this one key, so chain appends serialise against
# each other without blocking any other work.
CHAIN_LOCK_KEY = 8891274


def compute_chain_hash(txn: Transaction, prev_hash: str) -> str:
    # Match the column precision. An amount supplied as "10" is stored as 10.00,
    # so hashing the unnormalised value would fail verification on read-back.
    amount = Decimal(txn.amount).quantize(AMOUNT_PRECISION)
    payload = (
        f"{txn.id}|{txn.idempotency_key}|{txn.type.value}|"
        f"{amount}|{txn.request_hash}|{prev_hash}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def link_transaction(db: Session, txn: Transaction) -> None:
    # Without this lock two concurrent writers read the same tip and both link
    # to it, forking the chain. The lock is transaction scoped, so it is held
    # until commit and the tip we read is guaranteed to be the final one.
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})

    prev = db.execute(
        select(Transaction)
        .where(Transaction.chain_seq.isnot(None))
        .order_by(Transaction.chain_seq.desc())
        .limit(1)
    ).scalar_one_or_none()

    prev_hash = prev.chain_hash if prev else GENESIS_HASH
    txn.chain_seq = prev.chain_seq + 1 if prev else 1
    txn.prev_hash = prev_hash
    txn.chain_hash = compute_chain_hash(txn, prev_hash)


def verify_hash_chain(db: Session) -> dict:
    transactions = list(
        db.execute(
            select(Transaction)
            .where(Transaction.chain_seq.isnot(None))
            .order_by(Transaction.chain_seq.asc())
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

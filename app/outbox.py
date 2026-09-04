import json
import logging

from sqlalchemy.orm import Session

from app.models import OutboxEvent, Transaction

logger = logging.getLogger("ledger.outbox")


def write_transaction_event(db: Session, txn: Transaction) -> OutboxEvent:
    payload = json.dumps({
        "transaction_id": str(txn.id),
        "type": txn.type.value,
        "amount": str(txn.amount),
        "idempotency_key": txn.idempotency_key,
        "reference": txn.reference,
    })

    event = OutboxEvent(
        aggregate_type="transaction",
        aggregate_id=txn.id,
        event_type=f"transaction.{txn.type.value}",
        payload=payload,
    )
    db.add(event)
    logger.info(
        "Outbox event queued",
        extra={
            "transaction_id": str(txn.id),
            "event_type": event.event_type,
        },
    )
    return event

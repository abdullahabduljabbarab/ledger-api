import logging
import time
import uuid as uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging import request_id_var, setup_logging
from app.models import (
    Account,
    LedgerEntry,
    OutboxEvent,
    Transaction,
    TransactionType,
)
from app.schemas import (
    AccountCreate,
    AccountResponse,
    BalanceResponse,
    LedgerEntryResponse,
    PaginatedResponse,
    StatementEntry,
    StatementResponse,
    TransactionCreate,
    TransactionResponse,
)
from app.service import compute_balance, create_transaction

setup_logging()
logger = logging.getLogger("ledger.api")

app = FastAPI(title="Ledger API", version="0.1.0")


@app.middleware("http")
async def request_tracing(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid_mod.uuid4()))
    request_id_var.set(request_id)
    start = time.monotonic()
    response: Response = await call_next(request)
    duration = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration:.1f}"
    logger.info(
        "Request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration, 1),
        },
    )
    return response


@app.get("/health")
def health(db: Session = Depends(get_db)):
    start = time.monotonic()
    db.execute(text("SELECT 1"))
    db_ms = (time.monotonic() - start) * 1000
    return {"status": "ok", "database": "connected", "db_latency_ms": round(db_ms, 1)}


@app.post("/accounts", response_model=AccountResponse, status_code=201)
def post_account(data: AccountCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        select(Account).where(Account.name == data.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Account name already exists")

    account = Account(name=data.name)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@app.get("/accounts/{account_id}", response_model=AccountResponse)
def get_account(account_id: UUID, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
def get_balance(account_id: UUID, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    balance = compute_balance(db, account_id)
    return BalanceResponse(account_id=account_id, balance=balance)


@app.post("/transactions", response_model=TransactionResponse, status_code=201)
def post_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    txn = create_transaction(db, data)
    return txn


@app.get("/transactions", response_model=PaginatedResponse[TransactionResponse])
def list_transactions(
    account_id: UUID | None = Query(None),
    type: TransactionType | None = Query(None),
    cursor: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Transaction)

    if account_id is not None:
        entry_ids = select(LedgerEntry.transaction_id).where(
            LedgerEntry.account_id == account_id
        )
        stmt = stmt.where(Transaction.id.in_(entry_ids))

    if type is not None:
        stmt = stmt.where(Transaction.type == type)

    if cursor is not None:
        cursor_txn = db.get(Transaction, cursor)
        if cursor_txn is not None:
            stmt = stmt.where(Transaction.created_at < cursor_txn.created_at)

    stmt = stmt.order_by(Transaction.created_at.desc()).limit(limit + 1)
    items = list(db.execute(stmt).scalars().all())

    next_cursor = None
    if len(items) > limit:
        items = items[:limit]
        next_cursor = str(items[-1].id)

    return PaginatedResponse(items=items, next_cursor=next_cursor)


@app.get(
    "/accounts/{account_id}/entries",
    response_model=PaginatedResponse[LedgerEntryResponse],
)
def list_entries(
    account_id: UUID,
    cursor: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
    )

    if cursor is not None:
        cursor_entry = db.get(LedgerEntry, cursor)
        if cursor_entry is not None:
            stmt = stmt.where(LedgerEntry.id > cursor_entry.id)

    stmt = stmt.order_by(LedgerEntry.id).limit(limit + 1)
    items = list(db.execute(stmt).scalars().all())

    next_cursor = None
    if len(items) > limit:
        items = items[:limit]
        next_cursor = str(items[-1].id)

    return PaginatedResponse(items=items, next_cursor=next_cursor)


@app.get(
    "/accounts/{account_id}/statement",
    response_model=StatementResponse,
)
def get_statement(
    account_id: UUID,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    stmt = (
        select(LedgerEntry, Transaction.created_at, Transaction.type, Transaction.reference)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
        .where(LedgerEntry.account_id == account_id)
    )

    if from_date is not None:
        start_dt = datetime.combine(from_date, datetime.min.time())
        stmt = stmt.where(Transaction.created_at >= start_dt)
    if to_date is not None:
        end_dt = datetime.combine(to_date, datetime.max.time())
        stmt = stmt.where(Transaction.created_at < end_dt)

    stmt = stmt.order_by(Transaction.created_at.asc())
    rows = db.execute(stmt).all()

    running = Decimal("0")
    entries = []
    for entry, created_at, txn_type, reference in rows:
        running += entry.amount
        entries.append(StatementEntry(
            entry_id=entry.id,
            transaction_id=entry.transaction_id,
            type=txn_type,
            amount=entry.amount,
            running_balance=running,
            reference=reference,
            created_at=created_at,
        ))

    return StatementResponse(
        account_id=account_id,
        entries=entries,
        closing_balance=running,
    )


@app.get("/outbox/pending")
def outbox_pending(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    events = list(db.execute(stmt).scalars().all())
    return {
        "pending_count": len(events),
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "aggregate_id": str(e.aggregate_id),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@app.post("/outbox/publish", status_code=200)
def outbox_publish(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    events = list(db.execute(stmt).scalars().all())

    published = 0
    for event in events:
        event.published_at = datetime.now(tz=timezone.utc)
        published += 1

    db.commit()
    logger.info(f"Outbox relay: marked {published} events as published")
    return {"published": published}

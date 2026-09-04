from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, LedgerEntry, Transaction, TransactionType
from app.schemas import (
    AccountCreate,
    AccountResponse,
    BalanceResponse,
    LedgerEntryResponse,
    TransactionCreate,
    TransactionResponse,
)
from app.service import compute_balance, create_transaction

app = FastAPI(title="Ledger API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


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


@app.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    account_id: UUID | None = Query(None),
    type: TransactionType | None = Query(None),
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

    stmt = stmt.order_by(Transaction.created_at.desc())
    return list(db.execute(stmt).scalars().all())


@app.get(
    "/accounts/{account_id}/entries",
    response_model=list[LedgerEntryResponse],
)
def list_entries(account_id: UUID, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    entries = db.execute(
        select(LedgerEntry)
        .where(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.id)
    ).scalars().all()
    return list(entries)

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, LedgerEntry, Transaction, TransactionType
from app.schemas import TransactionCreate

EXTERNAL_CLEARING_NAME = "External Clearing"


def get_or_create_clearing_account(db: Session) -> Account:
    account = db.execute(
        select(Account).where(Account.name == EXTERNAL_CLEARING_NAME)
    ).scalar_one_or_none()
    if account is None:
        account = Account(name=EXTERNAL_CLEARING_NAME, is_system=True)
        db.add(account)
        db.flush()
    return account


def compute_balance(db: Session, account_id: UUID) -> Decimal:
    result = db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.account_id == account_id
        )
    ).scalar()
    return Decimal(str(result))


def _request_hash(data: TransactionCreate) -> str:
    canonical = json.dumps(
        {
            "type": data.type.value,
            "amount": str(data.amount),
            "account_id": str(data.account_id) if data.account_id else None,
            "from_account_id": str(data.from_account_id) if data.from_account_id else None,
            "to_account_id": str(data.to_account_id) if data.to_account_id else None,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _lock_accounts(db: Session, *account_ids: UUID) -> list[Account]:
    sorted_ids = sorted(account_ids)
    accounts = []
    for aid in sorted_ids:
        account = db.execute(
            select(Account).where(Account.id == aid).with_for_update()
        ).scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail=f"Account {aid} not found")
        accounts.append(account)
    return accounts


def create_transaction(db: Session, data: TransactionCreate) -> Transaction:
    req_hash = _request_hash(data)

    existing = db.execute(
        select(Transaction).where(
            Transaction.idempotency_key == data.idempotency_key
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.request_hash != req_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used with different parameters",
            )
        return existing

    if data.type == TransactionType.deposit:
        if data.account_id is None:
            raise HTTPException(status_code=422, detail="account_id required for deposit")
        clearing = get_or_create_clearing_account(db)
        _lock_accounts(db, data.account_id, clearing.id)

        txn = Transaction(
            idempotency_key=data.idempotency_key,
            type=data.type,
            amount=data.amount,
            request_hash=req_hash,
            reference=data.reference,
        )
        db.add(txn)
        db.flush()

        db.add(LedgerEntry(transaction_id=txn.id, account_id=clearing.id, amount=-data.amount))
        db.add(LedgerEntry(transaction_id=txn.id, account_id=data.account_id, amount=data.amount))

    elif data.type == TransactionType.withdrawal:
        if data.account_id is None:
            raise HTTPException(status_code=422, detail="account_id required for withdrawal")
        clearing = get_or_create_clearing_account(db)
        _lock_accounts(db, data.account_id, clearing.id)

        balance = compute_balance(db, data.account_id)
        if balance < data.amount:
            raise HTTPException(status_code=422, detail="Insufficient balance")

        txn = Transaction(
            idempotency_key=data.idempotency_key,
            type=data.type,
            amount=data.amount,
            request_hash=req_hash,
            reference=data.reference,
        )
        db.add(txn)
        db.flush()

        db.add(LedgerEntry(transaction_id=txn.id, account_id=data.account_id, amount=-data.amount))
        db.add(LedgerEntry(transaction_id=txn.id, account_id=clearing.id, amount=data.amount))

    elif data.type == TransactionType.transfer:
        if data.from_account_id is None or data.to_account_id is None:
            raise HTTPException(
                status_code=422,
                detail="from_account_id and to_account_id required for transfer",
            )
        if data.from_account_id == data.to_account_id:
            raise HTTPException(status_code=422, detail="Cannot transfer to the same account")

        _lock_accounts(db, data.from_account_id, data.to_account_id)

        balance = compute_balance(db, data.from_account_id)
        if balance < data.amount:
            raise HTTPException(status_code=422, detail="Insufficient balance")

        txn = Transaction(
            idempotency_key=data.idempotency_key,
            type=data.type,
            amount=data.amount,
            request_hash=req_hash,
            reference=data.reference,
        )
        db.add(txn)
        db.flush()

        db.add(LedgerEntry(
            transaction_id=txn.id, account_id=data.from_account_id, amount=-data.amount,
        ))
        db.add(LedgerEntry(
            transaction_id=txn.id, account_id=data.to_account_id, amount=data.amount,
        ))

    else:
        raise HTTPException(status_code=422, detail="Unknown transaction type")

    db.commit()
    db.refresh(txn)
    return txn

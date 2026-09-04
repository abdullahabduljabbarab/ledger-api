from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import TransactionType

T = TypeVar("T")


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class AccountResponse(BaseModel):
    id: UUID
    name: str
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BalanceResponse(BaseModel):
    account_id: UUID
    balance: Decimal


class TransactionCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    type: TransactionType
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    account_id: UUID | None = None
    from_account_id: UUID | None = None
    to_account_id: UUID | None = None
    reference: str | None = None


class TransactionResponse(BaseModel):
    id: UUID
    idempotency_key: str
    type: TransactionType
    amount: Decimal
    reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LedgerEntryResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    account_id: UUID
    amount: Decimal

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    detail: str


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class StatementEntry(BaseModel):
    entry_id: UUID
    transaction_id: UUID
    type: TransactionType
    amount: Decimal
    running_balance: Decimal
    reference: str | None
    created_at: datetime


class StatementResponse(BaseModel):
    account_id: UUID
    entries: list[StatementEntry]
    closing_balance: Decimal

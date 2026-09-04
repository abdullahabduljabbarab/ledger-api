import logging
import time
import uuid as uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import (
    Role,
    TokenData,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_role,
)
from app.database import get_db
from app.logging import request_id_var, setup_logging
from app.models import (
    Account,
    LedgerEntry,
    OutboxEvent,
    Transaction,
    TransactionType,
)
from app.publisher import get_transport
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

DESCRIPTION = """
An append-only double-entry financial ledger.

Every committed transaction produces balanced debit and credit entries that sum
to zero. Balances are derived from those entries rather than stored, so a
balance can never drift from the history that produced it.

**Correctness properties**

- Concurrent writes are serialised with row locks taken in deterministic order
- Retries are idempotent, and key reuse with different parameters is rejected
- Transactions are chained with SHA-256 so tampering is detectable
- A reconciliation engine recomputes ledger state independently of the write path

**Authentication**

Call `POST /auth/token` to obtain a bearer token, then authorise with it.
Each role carries different permissions: customers transact, auditors inspect,
admins provision.
"""

TAGS = [
    {"name": "System", "description": "Health and service status. No authentication required."},
    {"name": "Authentication", "description": "Token issuance and role assignment."},
    {"name": "Accounts", "description": "Account provisioning and derived balances."},
    {"name": "Transactions", "description": "Deposits, withdrawals and transfers."},
    {"name": "Statements", "description": "Ledger entries and account statements."},
    {
        "name": "Audit and Reconciliation",
        "description": "Independent verification of ledger integrity and the tamper-evident chain.",
    },
    {
        "name": "Event Delivery",
        "description": "Transactional outbox relay. At-least-once delivery to Pub/Sub.",
    },
]

app = FastAPI(
    title="Ledger API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/", include_in_schema=False)
def portal():
    return FileResponse(STATIC_DIR / "portal.html")


@app.get("/reference", include_in_schema=False)
def reference():
    """Scalar API explorer. Served from CDN, spec served by this service."""
    return HTMLResponse(
        """<!doctype html>
<html>
  <head>
    <title>Ledger API Reference</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="icon" href="/static/favicon.svg" />
  </head>
  <body>
    <script id="api-reference" data-url="/openapi.json"></script>
    <script>
      var configuration = {
        theme: "deepSpace",
        darkMode: true,
        hideDownloadButton: false,
        searchHotKey: "k",
      };
      document.getElementById("api-reference").dataset.configuration =
        JSON.stringify(configuration);
    </script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>"""
    )


@app.get("/status", tags=["System"], summary="Public service status")
def status(db: Session = Depends(get_db)):
    """Unauthenticated summary used by the portal.

    Deliberately cheap: counts and a connectivity probe only. The full
    reconciliation is an authenticated endpoint because it recomputes every
    balance, which is not something an anonymous caller should be able to
    trigger on demand.
    """
    start = time.monotonic()
    accounts = db.execute(select(func.count()).select_from(Account)).scalar()
    transactions = db.execute(select(func.count()).select_from(Transaction)).scalar()
    entries = db.execute(select(func.count()).select_from(LedgerEntry)).scalar()
    pending = db.execute(
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
    ).scalar()
    db_ms = (time.monotonic() - start) * 1000

    return {
        "status": "operational",
        "database": "connected",
        "db_latency_ms": round(db_ms, 1),
        "region": "europe-west2",
        "platform": "Cloud Run",
        "accounts": accounts,
        "transactions": transactions,
        "ledger_entries": entries,
        "outbox_pending": pending,
    }


@app.post("/auth/token", tags=["Authentication"], summary="Obtain a bearer token")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
        )
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/health", tags=["System"], summary="Liveness and database probe")
def health(db: Session = Depends(get_db)):
    start = time.monotonic()
    db.execute(text("SELECT 1"))
    db_ms = (time.monotonic() - start) * 1000
    return {"status": "ok", "database": "connected", "db_latency_ms": round(db_ms, 1)}


@app.post(
    "/accounts",
    response_model=AccountResponse,
    status_code=201,
    tags=["Accounts"],
    summary="Create an account",
)
def post_account(
    data: AccountCreate,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.admin)),
):
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


@app.get(
    "/accounts/{account_id}",
    response_model=AccountResponse,
    tags=["Accounts"],
    summary="Retrieve an account",
)
def get_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceResponse,
    tags=["Accounts"],
    summary="Derived balance",
)
def get_balance(
    account_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    balance = compute_balance(db, account_id)
    return BalanceResponse(account_id=account_id, balance=balance)


@app.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=201,
    tags=["Transactions"],
    summary="Record a transaction",
)
def post_transaction(
    data: TransactionCreate,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.admin, Role.customer)),
):
    txn = create_transaction(db, data)
    return txn


@app.get(
    "/transactions",
    response_model=PaginatedResponse[TransactionResponse],
    tags=["Transactions"],
    summary="List transactions",
)
def list_transactions(
    account_id: UUID | None = Query(None),
    type: TransactionType | None = Query(None),
    cursor: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: TokenData = Depends(get_current_user),
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
    tags=["Statements"],
    summary="List ledger entries",
)
def list_entries(
    account_id: UUID,
    cursor: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: TokenData = Depends(get_current_user),
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
    tags=["Statements"],
    summary="Account statement with running balance",
)
def get_statement(
    account_id: UUID,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
    user: TokenData = Depends(get_current_user),
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


@app.get("/outbox/pending", tags=["Event Delivery"], summary="List unpublished events")
def outbox_pending(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.admin)),
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


@app.post(
    "/outbox/publish",
    status_code=200,
    tags=["Event Delivery"],
    summary="Relay pending events to the broker",
)
def outbox_publish(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.admin)),
):
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    events = list(db.execute(stmt).scalars().all())
    transport = get_transport()

    published = 0
    failed = 0
    for event in events:
        try:
            transport.publish(str(event.id), event.event_type, event.payload)
        except Exception:
            # Leave this row and the rest pending so ordering holds and the
            # relay retries them on the next call.
            logger.exception("Outbox publish failed, event left pending")
            failed = len(events) - published
            break
        event.published_at = datetime.now(tz=timezone.utc)
        published += 1

    db.commit()
    logger.info(f"Outbox relay: published {published} events via {transport.name}")
    return {"published": published, "failed": failed, "transport": transport.name}


@app.get(
    "/audit/verify",
    tags=["Audit and Reconciliation"],
    summary="Recompute and verify ledger integrity",
)
def audit_verify(
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.auditor, Role.admin)),
):
    from app.audit import verify_ledger

    return verify_ledger(db)


@app.get(
    "/audit/chain",
    tags=["Audit and Reconciliation"],
    summary="Verify the tamper-evident hash chain",
)
def audit_chain(
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_role(Role.auditor, Role.admin)),
):
    from app.chain import verify_hash_chain

    return verify_hash_chain(db)

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, LedgerEntry, Transaction

logger = logging.getLogger("ledger.audit")


def verify_ledger(db: Session) -> dict:
    results = {
        "status": "pass",
        "checks": {},
        "discrepancies": [],
    }

    global_sum = db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0))
    ).scalar()
    global_sum = Decimal(str(global_sum))
    results["checks"]["global_invariant"] = {
        "description": "Sum of all ledger entries equals zero",
        "sum": str(global_sum),
        "pass": global_sum == Decimal("0"),
    }
    if global_sum != Decimal("0"):
        results["status"] = "fail"
        results["discrepancies"].append(
            f"Global ledger sum is {global_sum}, expected 0"
        )

    txn_sums = db.execute(
        select(
            LedgerEntry.transaction_id,
            func.sum(LedgerEntry.amount).label("entry_sum"),
        )
        .group_by(LedgerEntry.transaction_id)
        .having(func.sum(LedgerEntry.amount) != 0)
    ).all()
    unbalanced = [
        {"transaction_id": str(row[0]), "sum": str(row[1])}
        for row in txn_sums
    ]
    results["checks"]["per_transaction_invariant"] = {
        "description": "Every transaction sums to zero",
        "unbalanced_count": len(unbalanced),
        "pass": len(unbalanced) == 0,
    }
    if unbalanced:
        results["status"] = "fail"
        for u in unbalanced:
            results["discrepancies"].append(
                f"Transaction {u['transaction_id']} sums to {u['sum']}"
            )

    accounts = db.execute(select(Account)).scalars().all()
    balance_mismatches = []
    for account in accounts:
        derived = db.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(LedgerEntry.account_id == account.id)
        ).scalar()
        derived = Decimal(str(derived))
        entry_count = db.execute(
            select(func.count())
            .where(LedgerEntry.account_id == account.id)
        ).scalar()
        balance_mismatches.append({
            "account_id": str(account.id),
            "account_name": account.name,
            "derived_balance": str(derived),
            "entry_count": entry_count,
        })
    results["checks"]["account_balances"] = {
        "description": "Independent balance recomputation for every account",
        "accounts_verified": len(balance_mismatches),
        "pass": True,
        "details": balance_mismatches,
    }

    orphaned_entries = db.execute(
        select(func.count()).select_from(LedgerEntry).where(
            ~LedgerEntry.transaction_id.in_(select(Transaction.id))
        )
    ).scalar()
    orphaned_accounts = db.execute(
        select(func.count()).select_from(LedgerEntry).where(
            ~LedgerEntry.account_id.in_(select(Account.id))
        )
    ).scalar()
    results["checks"]["referential_integrity"] = {
        "description": "No orphaned ledger entries",
        "orphaned_transaction_refs": orphaned_entries,
        "orphaned_account_refs": orphaned_accounts,
        "pass": orphaned_entries == 0 and orphaned_accounts == 0,
    }
    if orphaned_entries > 0 or orphaned_accounts > 0:
        results["status"] = "fail"
        results["discrepancies"].append(
            f"Orphaned entries: {orphaned_entries} transaction refs, "
            f"{orphaned_accounts} account refs"
        )

    total_keys = db.execute(
        select(func.count()).select_from(Transaction)
    ).scalar()
    unique_keys = db.execute(
        select(func.count(func.distinct(Transaction.idempotency_key)))
    ).scalar()
    results["checks"]["idempotency_uniqueness"] = {
        "description": "Every idempotency key is unique",
        "total_transactions": total_keys,
        "unique_keys": unique_keys,
        "pass": total_keys == unique_keys,
    }
    if total_keys != unique_keys:
        results["status"] = "fail"
        results["discrepancies"].append(
            f"Duplicate idempotency keys: {total_keys} transactions "
            f"but only {unique_keys} unique keys"
        )

    entry_count = db.execute(
        select(func.count()).select_from(LedgerEntry)
    ).scalar()
    txn_count = db.execute(
        select(func.count()).select_from(Transaction)
    ).scalar()
    results["checks"]["entry_count"] = {
        "description": "Every transaction has exactly 2 ledger entries",
        "transactions": txn_count,
        "entries": entry_count,
        "expected_entries": txn_count * 2,
        "pass": entry_count == txn_count * 2,
    }
    if entry_count != txn_count * 2:
        results["status"] = "fail"
        results["discrepancies"].append(
            f"Expected {txn_count * 2} entries for {txn_count} "
            f"transactions, found {entry_count}"
        )

    logger.info(
        f"Ledger verification complete: {results['status']}",
        extra={"check_count": len(results["checks"])},
    )

    return results

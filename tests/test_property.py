import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def _fresh_account(client, name=None):
    name = name or f"prop-{uuid.uuid4().hex[:8]}"
    resp = client.post("/accounts", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def _deposit(client, account_id, amount, key=None):
    key = key or uuid.uuid4().hex
    return client.post("/transactions", json={
        "idempotency_key": key,
        "type": "deposit",
        "amount": str(amount),
        "account_id": account_id,
    })


def _withdraw(client, account_id, amount, key=None):
    key = key or uuid.uuid4().hex
    return client.post("/transactions", json={
        "idempotency_key": key,
        "type": "withdrawal",
        "amount": str(amount),
        "account_id": account_id,
    })


def _transfer(client, from_id, to_id, amount, key=None):
    key = key or uuid.uuid4().hex
    return client.post("/transactions", json={
        "idempotency_key": key,
        "type": "transfer",
        "amount": str(amount),
        "from_account_id": from_id,
        "to_account_id": to_id,
    })


def _balance(client, account_id):
    resp = client.get(f"/accounts/{account_id}/balance")
    return Decimal(resp.json()["balance"])


def _all_entries(client, account_id):
    resp = client.get(f"/accounts/{account_id}/entries?limit=100")
    return resp.json()["items"]


amount_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("9999.99"),
    places=2,
)

action_strategy = st.sampled_from(["deposit", "withdrawal", "transfer"])


@given(
    amounts=st.lists(amount_strategy, min_size=5, max_size=20),
    actions=st.lists(action_strategy, min_size=5, max_size=20),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_ledger_invariants_under_random_operations(client, amounts, actions):
    acc_a = _fresh_account(client)
    acc_b = _fresh_account(client)

    _deposit(client, acc_a, Decimal("50000.00"))
    _deposit(client, acc_b, Decimal("50000.00"))

    for i, (action, amount) in enumerate(zip(actions, amounts)):
        if action == "deposit":
            _deposit(client, acc_a, amount)
        elif action == "withdrawal":
            _withdraw(client, acc_a, amount)
        elif action == "transfer":
            _transfer(client, acc_a, acc_b, amount)

    txns_resp = client.get("/transactions?limit=100")
    txns = txns_resp.json()["items"]

    for txn in txns:
        entries_a = [
            e for e in _all_entries(client, acc_a)
            if e["transaction_id"] == txn["id"]
        ]
        entries_b = [
            e for e in _all_entries(client, acc_b)
            if e["transaction_id"] == txn["id"]
        ]
        all_entry_sum = sum(
            Decimal(e["amount"]) for e in entries_a + entries_b
        )
        if txn["type"] in ("deposit", "withdrawal"):
            pass
        elif txn["type"] == "transfer":
            assert all_entry_sum == Decimal("0"), (
                f"Transfer {txn['id']} entries do not sum to zero: {all_entry_sum}"
            )

    bal_a = _balance(client, acc_a)
    bal_b = _balance(client, acc_b)
    assert bal_a >= Decimal("0"), f"Account A has negative balance: {bal_a}"
    assert bal_b >= Decimal("0"), f"Account B has negative balance: {bal_b}"


@given(amounts=st.lists(amount_strategy, min_size=3, max_size=10))
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_balance_equals_sum_of_entries(client, amounts):
    acc = _fresh_account(client)

    expected = Decimal("0")
    for amount in amounts:
        _deposit(client, acc, amount)
        expected += amount

    actual = _balance(client, acc)
    assert actual == expected, f"Expected {expected}, got {actual}"

    entries = _all_entries(client, acc)
    entry_sum = sum(Decimal(e["amount"]) for e in entries)
    assert entry_sum == expected, f"Entry sum {entry_sum} != expected {expected}"


@given(amount=amount_strategy)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_idempotent_deposits_never_duplicate(client, amount):
    acc = _fresh_account(client)
    key = uuid.uuid4().hex

    r1 = _deposit(client, acc, amount, key=key)
    r2 = _deposit(client, acc, amount, key=key)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    bal = _balance(client, acc)
    assert bal == amount, f"Duplicate deposit created extra entry: balance {bal} != {amount}"


@given(
    amount=amount_strategy,
    alt_amount=amount_strategy,
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_idempotency_conflict_never_creates_transaction(client, amount, alt_amount):
    if amount == alt_amount:
        return

    acc = _fresh_account(client)
    key = uuid.uuid4().hex

    r1 = _deposit(client, acc, amount, key=key)
    assert r1.status_code == 201

    r2 = _deposit(client, acc, alt_amount, key=key)
    assert r2.status_code == 409

    bal = _balance(client, acc)
    assert bal == amount, f"409 conflict should not change balance: {bal} != {amount}"


@given(
    deposit=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100.00"), places=2),
    withdraw=st.decimals(min_value=Decimal("100.01"), max_value=Decimal("9999.99"), places=2),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_overdraw_never_permitted(client, deposit, withdraw):
    acc = _fresh_account(client)
    _deposit(client, acc, deposit)

    resp = _withdraw(client, acc, withdraw)
    assert resp.status_code == 422

    bal = _balance(client, acc)
    assert bal == deposit, f"Failed withdrawal changed balance: {bal} != {deposit}"

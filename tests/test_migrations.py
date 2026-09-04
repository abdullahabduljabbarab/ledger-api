import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://ledger:ledger@localhost:5432/ledger_test",
)


def _alembic_cfg():
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "..", "migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


def test_migrations_apply_incrementally():
    """Apply migrations one at a time and verify schema evolves correctly."""
    engine = create_engine(TEST_DATABASE_URL)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS outbox_events CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS ledger_entries CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS transactions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS accounts CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS transactiontype CASCADE"))

    cfg = _alembic_cfg()

    command.upgrade(cfg, "001")
    inspector = inspect(engine)
    tables_001 = inspector.get_table_names()
    assert "accounts" in tables_001
    assert "transactions" in tables_001
    assert "ledger_entries" in tables_001
    assert "outbox_events" not in tables_001

    cols_txn_001 = {c["name"] for c in inspector.get_columns("transactions")}
    assert "prev_hash" not in cols_txn_001
    assert "chain_hash" not in cols_txn_001

    command.upgrade(cfg, "002")
    inspector = inspect(engine)
    tables_002 = inspector.get_table_names()
    assert "outbox_events" in tables_002

    command.upgrade(cfg, "003")
    inspector = inspect(engine)
    cols_txn_003 = {c["name"] for c in inspector.get_columns("transactions")}
    assert "prev_hash" in cols_txn_003
    assert "chain_hash" in cols_txn_003
    assert "chain_seq" not in cols_txn_003

    command.upgrade(cfg, "004")
    inspector = inspect(engine)
    cols_txn_004 = {c["name"] for c in inspector.get_columns("transactions")}
    assert "chain_seq" in cols_txn_004

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO accounts (name, is_system) VALUES ('MigTest', false)"
        ))
        result = conn.execute(text("SELECT name FROM accounts WHERE name = 'MigTest'"))
        assert result.scalar() == "MigTest"

    command.downgrade(cfg, "001")
    inspector = inspect(engine)
    tables_down = inspector.get_table_names()
    assert "outbox_events" not in tables_down
    cols_down = {c["name"] for c in inspector.get_columns("transactions")}
    assert "prev_hash" not in cols_down

    with engine.begin() as conn:
        result = conn.execute(text("SELECT name FROM accounts WHERE name = 'MigTest'"))
        assert result.scalar() == "MigTest"

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS outbox_events CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS ledger_entries CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS transactions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS accounts CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS transactiontype CASCADE"))

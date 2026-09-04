import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine

from app.models import Base

load_dotenv()

config = context.config

target_metadata = Base.metadata

url = os.getenv(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url"),
)


def run_migrations_online():
    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()

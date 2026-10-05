import os
from uuid import uuid4

import pytest
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command


@pytest.fixture
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(".env").get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated database ending in _test")
    parsed = make_url(url)
    if (
        not parsed.database
        or not parsed.database.endswith("_test")
        or parsed.get_backend_name() != "postgresql"
    ):
        pytest.fail("Refusing integration tests outside a PostgreSQL *_test database")
    schema = "test_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-c timezone=UTC -c search_path={schema},public"},
    )
    try:
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        # Only the random schema created by this fixture is removed, never public/database.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def sessions(db_engine):
    return sessionmaker(db_engine, expire_on_commit=False)

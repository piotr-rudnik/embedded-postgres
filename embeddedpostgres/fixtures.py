"""pytest fixtures for embeddedpostgres.

Usage::

    # In your project's conftest.py
    pytest_plugins = ["embeddedpostgres.fixtures"]

Or install the fixtures automatically by adding ``embeddedpostgres`` to your
``pytest_plugins`` list.
"""

import pytest

from embeddedpostgres import EmbeddedPostgres


@pytest.fixture(scope="session")
def postgres_session():
    """Yields a session-scoped :class:`EmbeddedPostgres` instance.

    Use this when you want to reuse a single PostgreSQL server across all
    tests in a session for speed.
    """
    pg = EmbeddedPostgres()
    pg.start()
    yield pg
    pg.stop()


@pytest.fixture
def postgres(postgres_session):
    """Yields a fresh database inside the session-scoped server.

    This fixture creates a new database for each test and drops it
    afterwards, giving you test isolation without the cost of restarting
    the server.
    """
    import uuid

    import psycopg2

    db_name = f"test_db_{uuid.uuid4().hex}"
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=postgres_session._actual_port,
        user=postgres_session._username,
        dbname=postgres_session._username,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE {db_name}")
    cur.close()
    conn.close()

    yield postgres_session.url(database=db_name)

    # teardown
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=postgres_session._actual_port,
        user=postgres_session._username,
        dbname=postgres_session._username,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{db_name}'"
    )
    cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
    cur.close()
    conn.close()

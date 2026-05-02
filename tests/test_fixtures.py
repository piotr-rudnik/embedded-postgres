"""Tests for the built-in pytest fixtures."""

import psycopg2
import pytest

pytest_plugins = ["embeddedpostgres.fixtures"]


class TestPostgresSessionFixture:
    def test_server_is_running(self, postgres_session):
        assert postgres_session._running is True

    def test_can_connect(self, postgres_session):
        conn = psycopg2.connect(postgres_session.url())
        cur = conn.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
        cur.close()
        conn.close()


class TestPostgresDatabaseFixture:
    def test_fresh_database(self, postgres):
        conn = psycopg2.connect(postgres)
        cur = conn.cursor()
        cur.execute("CREATE TABLE t (id serial PRIMARY KEY)")
        cur.execute("INSERT INTO t DEFAULT VALUES")
        cur.execute("SELECT COUNT(*) FROM t")
        assert cur.fetchone()[0] == 1
        cur.close()
        conn.close()

    def test_isolated_database(self, postgres):
        # The database should be empty even though the previous test also
        # used the 'postgres' fixture.
        conn = psycopg2.connect(postgres)
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        assert cur.fetchone()[0] == 0
        cur.close()
        conn.close()

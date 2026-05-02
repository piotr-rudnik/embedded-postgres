"""Tests for embeddedpostgres.

These tests run the full stack including the automatic PostgreSQL binary
downloader if no local installation is found.
"""

import os

import pytest
import psycopg2

from embeddedpostgres import EmbeddedPostgres, PostgresBinaryManager


@pytest.fixture(scope="session", autouse=True)
def ensure_postgres_binary():
    """Pre-download the PostgreSQL binary so every test doesn't race.

    When the machine has no system PostgreSQL installed the
    PostgresBinaryManager will download and cache a prebuilt bundle
    from Maven Central.  Doing this once per test session keeps the
    individual tests fast and avoids concurrent extraction races.
    """
    manager = PostgresBinaryManager()
    manager.get_bin_dir()


class TestLifecycle:
    def test_start_stop(self):
        pg = EmbeddedPostgres()
        pg.start()
        assert pg._running is True
        pg.stop()
        assert pg._running is False

    def test_context_manager(self):
        with EmbeddedPostgres() as pg:
            assert pg._running is True
            url = pg.url()
            assert "postgresql://" in url
        assert pg._running is False


class TestConnections:
    def test_connect_with_url(self):
        with EmbeddedPostgres() as pg:
            conn = psycopg2.connect(pg.url())
            cur = conn.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
            cur.close()
            conn.close()

    def test_connect_with_dsn(self):
        with EmbeddedPostgres() as pg:
            conn = psycopg2.connect(**pg.dsn())
            cur = conn.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
            cur.close()
            conn.close()

    def test_create_table_and_insert(self):
        with EmbeddedPostgres() as pg:
            conn = psycopg2.connect(pg.url())
            cur = conn.cursor()
            cur.execute("CREATE TABLE test (id serial PRIMARY KEY, name text);")
            cur.execute("INSERT INTO test (name) VALUES ('hello');")
            cur.execute("SELECT name FROM test WHERE id = 1;")
            assert cur.fetchone()[0] == "hello"
            conn.commit()
            cur.close()
            conn.close()

    def test_multiple_databases(self):
        with EmbeddedPostgres() as pg:
            conn = psycopg2.connect(pg.url())
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("CREATE DATABASE otherdb;")
            cur.close()
            conn.close()

            conn2 = psycopg2.connect(pg.url(database="otherdb"))
            cur2 = conn2.cursor()
            cur2.execute("SELECT 1")
            assert cur2.fetchone()[0] == 1
            cur2.close()
            conn2.close()


class TestConfiguration:
    def test_custom_database_name(self):
        with EmbeddedPostgres(database="mydb") as pg:
            conn = psycopg2.connect(pg.url())
            cur = conn.cursor()
            cur.execute("SELECT current_database();")
            assert cur.fetchone()[0] == "mydb"
            cur.close()
            conn.close()

    def test_custom_port(self):
        with EmbeddedPostgres(port=25432) as pg:
            assert pg._actual_port == 25432
            conn = psycopg2.connect(pg.url())
            cur = conn.cursor()
            cur.execute("SHOW port;")
            assert int(cur.fetchone()[0]) == 25432
            cur.close()
            conn.close()

    def test_custom_data_dir(self, tmp_path):
        data_dir = str(tmp_path / "pg_data")
        pg = EmbeddedPostgres(data_dir=data_dir)
        with pg:
            assert os.path.exists(data_dir)
            conn = psycopg2.connect(pg.url())
            cur = conn.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
            cur.close()
            conn.close()

        # When using a custom data_dir we do not delete it automatically
        assert os.path.exists(data_dir)


class TestUrlAndDsn:
    def test_url_format(self):
        with EmbeddedPostgres(port=12345, database="testdb") as pg:
            url = pg.url()
            assert url == "postgresql://postgres:postgres@127.0.0.1:12345/testdb"

    def test_dsn_keys(self):
        with EmbeddedPostgres(port=12345) as pg:
            dsn = pg.dsn()
            assert dsn["host"] == "127.0.0.1"
            assert dsn["port"] == 12345
            assert dsn["user"] == "postgres"
            assert dsn["password"] == "postgres"
            assert dsn["dbname"] == "postgres"

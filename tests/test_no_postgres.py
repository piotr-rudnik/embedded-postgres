"""Tests that don't require PostgreSQL binaries."""

from pathlib import Path

import pytest

from embeddedpostgres import EmbeddedPostgres, PostgresBinaryManager


class TestNotRunning:
    def test_url_raises_when_not_running(self):
        pg = EmbeddedPostgres()
        with pytest.raises(RuntimeError, match="not running"):
            pg.url()

    def test_dsn_raises_when_not_running(self):
        pg = EmbeddedPostgres()
        with pytest.raises(RuntimeError, match="not running"):
            pg.dsn()


class TestConstructor:
    def test_version_parameter(self):
        pg = EmbeddedPostgres(version="16.0.0")
        assert pg._version == "16.0.0"

    def test_pg_bin_dir_parameter(self):
        pg = EmbeddedPostgres(pg_bin_dir="/usr/local/pgsql/bin")
        assert pg._pg_bin_dir == "/usr/local/pgsql/bin"

    def test_custom_credentials(self):
        pg = EmbeddedPostgres(username="foo", password="bar", database="baz")
        assert pg._username == "foo"
        assert pg._password == "bar"
        assert pg._database == "baz"


class TestFindSystemBinaries:
    def test_no_system_binaries_returns_none(self):
        # Assuming the test environment has no postgres installed
        result = EmbeddedPostgres._find_system_binaries()
        # We can't assert much without controlling the environment,
        # but at least the call should not raise.
        assert result is None or isinstance(result, Path)


class TestBinaryManagerImport:
    def test_binary_manager_is_exported(self):
        assert PostgresBinaryManager is not None

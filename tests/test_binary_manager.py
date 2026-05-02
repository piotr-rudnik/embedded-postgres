"""Unit tests for PostgresBinaryManager (no network required)."""

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from embeddedpostgres.binary_manager import PostgresBinaryManager


class TestPlatformDetection:
    def test_linux_amd64(self):
        with patch("platform.system", return_value="Linux"):
            with patch("platform.machine", return_value="x86_64"):
                mgr = PostgresBinaryManager()
                assert mgr._detect_platform() == ("linux", "amd64")

    def test_darwin_arm64(self):
        with patch("platform.system", return_value="Darwin"):
            with patch("platform.machine", return_value="arm64"):
                mgr = PostgresBinaryManager()
                assert mgr._detect_platform() == ("darwin", "arm64v8")

    def test_windows_amd64(self):
        with patch("platform.system", return_value="Windows"):
            with patch("platform.machine", return_value="AMD64"):
                mgr = PostgresBinaryManager()
                assert mgr._detect_platform() == ("windows", "amd64")

    def test_win32_normalized(self):
        with patch("platform.system", return_value="win32"):
            with patch("platform.machine", return_value="x86_64"):
                mgr = PostgresBinaryManager()
                assert mgr._detect_platform() == ("windows", "amd64")


class TestArtifactId:
    def test_known_combinations(self):
        mgr = PostgresBinaryManager()
        assert mgr._artifact_id("linux", "amd64") == "embedded-postgres-binaries-linux-amd64"
        assert mgr._artifact_id("darwin", "arm64v8") == "embedded-postgres-binaries-darwin-arm64v8"
        assert mgr._artifact_id("windows", "amd64") == "embedded-postgres-binaries-windows-amd64"

    def test_unsupported_raises(self):
        mgr = PostgresBinaryManager()
        with pytest.raises(RuntimeError, match="No prebuilt PostgreSQL binaries"):
            mgr._artifact_id("freebsd", "amd64")


class TestJarUrl:
    def test_url_construction(self):
        mgr = PostgresBinaryManager(version="16.0.0")
        url = mgr._jar_url("embedded-postgres-binaries-linux-amd64")
        assert (
            url == "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
            "embedded-postgres-binaries-linux-amd64/16.0.0/"
            "embedded-postgres-binaries-linux-amd64-16.0.0.jar"
        )


class TestCacheDir:
    def test_default_cache_dir(self):
        mgr = PostgresBinaryManager()
        assert mgr.cache_dir == Path.home() / ".cache" / "embeddedpostgres"

    def test_custom_cache_dir(self):
        mgr = PostgresBinaryManager(cache_dir="/tmp/my_cache")
        assert mgr.cache_dir == Path("/tmp/my_cache")

    def test_xdg_cache_home(self, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", "/xdg/cache")
        mgr = PostgresBinaryManager()
        assert mgr.cache_dir == Path("/xdg/cache/embeddedpostgres")

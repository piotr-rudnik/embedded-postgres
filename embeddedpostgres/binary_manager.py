"""Download and cache PostgreSQL binaries from Maven Central."""

import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional


class PostgresBinaryManager:
    """Manages downloading and caching of PostgreSQL binaries.

    Binaries are fetched from the `zonkyio/embedded-postgres-binaries` Maven
    repository and extracted to a local cache directory so that subsequent
    test runs are instant.
    """

    DEFAULT_VERSION = "16.0.0"
    MAVEN_BASE_URL = "https://repo1.maven.org/maven2/io/zonky/test/postgres"

    _PLATFORM_ARCH_MAP: dict[tuple[str, str], str] = {
        ("linux", "amd64"): "embedded-postgres-binaries-linux-amd64",
        ("linux", "arm64v8"): "embedded-postgres-binaries-linux-arm64v8",
        ("linux", "i386"): "embedded-postgres-binaries-linux-i386",
        ("darwin", "amd64"): "embedded-postgres-binaries-darwin-amd64",
        ("darwin", "arm64v8"): "embedded-postgres-binaries-darwin-arm64v8",
        ("windows", "amd64"): "embedded-postgres-binaries-windows-amd64",
        ("windows", "i386"): "embedded-postgres-binaries-windows-i386",
    }

    def __init__(
        self,
        version: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ):
        self.version = version or self.DEFAULT_VERSION
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir
            else self._default_cache_dir()
        )

    @staticmethod
    def _default_cache_dir() -> Path:
        """Return the default cache directory."""
        cache_base = os.environ.get("XDG_CACHE_HOME")
        if cache_base:
            return Path(cache_base) / "embeddedpostgres"
        return Path.home() / ".cache" / "embeddedpostgres"

    def _detect_platform(self) -> tuple[str, str]:
        """Return (system, arch) suitable for the Maven artifact mapping."""
        system = platform.system().lower()
        machine = platform.machine().lower()

        if machine in ("amd64", "x86_64", "x64"):
            arch = "amd64"
        elif machine in ("arm64", "aarch64"):
            arch = "arm64v8"
        elif machine in ("i386", "i686", "x86"):
            arch = "i386"
        else:
            arch = machine

        if system == "win32":
            system = "windows"

        return system, arch

    def _artifact_id(self, system: str, arch: str) -> str:
        """Return the Maven artifact ID for the given platform/arch."""
        key = (system, arch)
        artifact = self._PLATFORM_ARCH_MAP.get(key)
        if artifact is None:
            supported = ", ".join(
                f"{s}-{a}" for s, a in self._PLATFORM_ARCH_MAP
            )
            raise RuntimeError(
                f"No prebuilt PostgreSQL binaries for {system}-{arch}. "
                f"Supported combinations: {supported}"
            )
        return artifact

    def _jar_url(self, artifact_id: str) -> str:
        """Return the Maven Central download URL for the JAR artifact."""
        return (
            f"{self.MAVEN_BASE_URL}/{artifact_id}/{self.version}"
            f"/{artifact_id}-{self.version}.jar"
        )

    def _is_cached(self, artifact_id: str) -> bool:
        """Check whether the requested artifact is already present in cache."""
        bin_dir = self.cache_dir / self.version / artifact_id / "bin"
        return (
            (bin_dir / "initdb").exists()
            or (bin_dir / "initdb.exe").exists()
        )

    def _download(self, url: str, destination: str) -> None:
        """Download *url* to *destination* with a simple progress indicator."""
        print(f"[embeddedpostgres] Downloading PostgreSQL {self.version} ...")
        print(f"[embeddedpostgres] {url}")

        temp_path = destination + ".tmp"
        try:
            urllib.request.urlretrieve(url, temp_path)
            os.replace(temp_path, destination)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _extract_txz_from_jar(self, jar_path: str) -> str:
        """Extract the ``.txz`` archive contained inside the downloaded JAR."""
        with zipfile.ZipFile(jar_path, "r") as zf:
            txz_names = [n for n in zf.namelist() if n.endswith(".txz")]
            if not txz_names:
                raise RuntimeError(
                    f"No .txz archive found inside {jar_path}"
                )
            txz_name = txz_names[0]
            temp_dir = tempfile.mkdtemp(prefix="embedded_pg_jar_")
            zf.extract(txz_name, temp_dir)
            return os.path.join(temp_dir, txz_name)

    def _extract_txz(self, txz_path: str, target_dir: Path) -> None:
        """Extract a ``.txz`` tarball into *target_dir*."""
        with tarfile.open(txz_path, "r:xz") as tf:
            tf.extractall(str(target_dir))

    def _fix_permissions(self, artifact_id: str) -> None:
        """Ensure PostgreSQL binaries are executable on Unix-like systems."""
        if platform.system().lower() == "windows":
            return
        bin_dir = self.cache_dir / self.version / artifact_id / "bin"
        for binary in ("initdb", "pg_ctl", "postgres"):
            path = bin_dir / binary
            if path.exists():
                path.chmod(0o755)

    def _ensure_cached(self, artifact_id: str) -> Path:
        """Download and extract the artifact if it is not already cached."""
        if self._is_cached(artifact_id):
            return self.cache_dir / self.version / artifact_id / "bin"

        target_dir = self.cache_dir / self.version / artifact_id
        target_dir.mkdir(parents=True, exist_ok=True)

        url = self._jar_url(artifact_id)
        jar_fd, jar_path = tempfile.mkstemp(suffix=".jar")
        os.close(jar_fd)

        try:
            self._download(url, jar_path)
            txz_path = self._extract_txz_from_jar(jar_path)
            try:
                self._extract_txz(txz_path, target_dir)
            finally:
                shutil.rmtree(os.path.dirname(txz_path), ignore_errors=True)
        finally:
            if os.path.exists(jar_path):
                os.unlink(jar_path)

        self._fix_permissions(artifact_id)

        bin_dir = target_dir / "bin"
        if not (bin_dir / "initdb").exists() and not (
            bin_dir / "initdb.exe"
        ).exists():
            raise RuntimeError(
                f"PostgreSQL binaries not found after extraction in {bin_dir}"
            )

        return bin_dir

    def get_bin_dir(self) -> Path:
        """Return the absolute path to the PostgreSQL ``bin/`` directory.

        This will download and cache the binaries if they are not already
        present on the local machine.
        """
        system, arch = self._detect_platform()
        artifact_id = self._artifact_id(system, arch)
        return self._ensure_cached(artifact_id)

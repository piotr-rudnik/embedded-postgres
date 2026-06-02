"""Core implementation for EmbeddedPostgres."""

import atexit
import glob
import os
import signal
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from embeddedpostgres.binary_manager import PostgresBinaryManager


class EmbeddedPostgres:
    """Manages an ephemeral PostgreSQL instance for testing.

    Example::

        pg = EmbeddedPostgres()
        pg.start()
        url = pg.url()
        # ... run tests ...
        pg.stop()

    Or use as a context manager::

        with EmbeddedPostgres() as pg:
            url = pg.url()
            # ... run tests ...

    By default the class will look for PostgreSQL binaries on your
    ``$PATH`` or in common system locations.  If none are found you can
    ask it to download a specific version automatically::

        pg = EmbeddedPostgres(version="16.0.0")
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        port: Optional[int] = None,
        username: str = "postgres",
        password: str = "postgres",
        database: str = "postgres",
        version: Optional[str] = None,
        pg_bin_dir: Optional[str] = None,
    ):
        self._data_dir = data_dir
        self._port = port
        self._username = username
        self._password = password
        self._database = database
        self._version = version
        self._pg_bin_dir = pg_bin_dir

        self._process: Optional[subprocess.Popen] = None
        self._actual_data_dir: Optional[str] = None
        self._actual_port: Optional[int] = None
        self._bin_dir: Optional[Path] = None
        self._running = False
        self._postmaster_pid: Optional[int] = None
        self._atexit_registered = False

    @staticmethod
    def _find_system_binaries() -> Optional[Path]:
        """Check PATH and common installation directories for Postgres binaries."""
        for cmd in ("pg_ctl", "postgres", "initdb"):
            path = shutil.which(cmd)
            if path:
                return Path(path).parent

        common_paths = [
            "/usr/lib/postgresql",
            "/usr/local/lib/postgresql",
            "/opt/homebrew/opt/postgresql/libexec/bin",
            "/usr/local/opt/postgresql/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
        ]

        for base in common_paths:
            base_path = Path(base)
            if not base_path.exists():
                continue

            if base_path.name == "postgresql":
                for version_dir in sorted(base_path.iterdir(), reverse=True):
                    bin_dir = version_dir / "bin"
                    if (bin_dir / "initdb").exists() and (
                        bin_dir / "postgres"
                    ).exists():
                        return bin_dir

            bin_dir = base_path if "bin" in base_path.name else base_path / "bin"
            if (bin_dir / "initdb").exists() and (bin_dir / "postgres").exists():
                return bin_dir

        return None

    def _find_binaries(self) -> Path:
        """Locate PostgreSQL binaries – system first, then download if needed."""
        # 1. User-supplied directory
        if self._pg_bin_dir:
            bin_dir = Path(self._pg_bin_dir)
            if (bin_dir / "initdb").exists() or (bin_dir / "initdb.exe").exists():
                return bin_dir
            raise RuntimeError(
                f"Provided pg_bin_dir does not contain initdb: {bin_dir}"
            )

        # 2. System binaries
        system_bin_dir = self._find_system_binaries()
        if system_bin_dir is not None:
            return system_bin_dir

        # 3. Download and cache
        manager = PostgresBinaryManager(version=self._version)
        return manager.get_bin_dir()

    def _bin(self, name: str) -> str:
        """Return the full path to a PostgreSQL binary."""
        path = self._bin_dir / name
        if not path.exists() and os.name == "nt":
            path = self._bin_dir / f"{name}.exe"
        return str(path)

    @staticmethod
    def _find_free_port() -> int:
        """Find a free TCP port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _initdb(self) -> None:
        """Initialize the database cluster."""
        cmd = [
            self._bin("initdb"),
            "--username", self._username,
            "--encoding", "UTF8",
            "--locale", "C",
            "--no-locale",
            "--pgdata", self._actual_data_dir,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"initdb failed: {result.stderr}")

    def _start_postgres(self) -> None:
        """Start the PostgreSQL server process."""
        # Prefer pg_ctl if available for cleaner start/stop
        pg_ctl_available = os.path.exists(self._bin("pg_ctl"))

        if pg_ctl_available:
            cmd = [
                self._bin("pg_ctl"),
                "start",
                "--pgdata", self._actual_data_dir,
                "--log", os.path.join(self._actual_data_dir, "server.log"),
                "--wait",
            ]
            env = os.environ.copy()
            env["PGPORT"] = str(self._actual_port)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(f"pg_ctl start failed: {result.stderr}")
        else:
            env = os.environ.copy()
            env["PGDATA"] = self._actual_data_dir
            env["PGPORT"] = str(self._actual_port)

            cmd = [
                self._bin("postgres"),
                "-D", self._actual_data_dir,
                "-p", str(self._actual_port),
                "-h", "127.0.0.1",
                "-k", os.path.join(self._actual_data_dir, "socket"),
            ]
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

        # Wait for server to accept connections
        self._wait_for_server()

        # Track the actual postmaster PID for reliable force-kill
        pid_file = os.path.join(self._actual_data_dir, "postmaster.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    line = f.readline().strip()
                    if line.isdigit():
                        self._postmaster_pid = int(line)
            except (OSError, ValueError):
                pass

    def _ensure_database_exists(self) -> None:
        """Create the requested default database if it is not the superuser DB."""
        if self._database == self._username:
            return

        # Connect to the default postgres database and create the requested one.
        # We use psycopg2 directly because the embedded binaries bundle may not
        # include the `createdb` CLI tool.
        import psycopg2

        conn = psycopg2.connect(
            host="127.0.0.1",
            port=self._actual_port,
            user=self._username,
            dbname=self._username,
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (self._database,),
        )
        if cur.fetchone() is None:
            cur.execute(
                "CREATE DATABASE %s"
                % psycopg2.extensions.quote_ident(self._database, conn)
            )
        cur.close()
        conn.close()

    def _wait_for_server(self) -> None:
        """Poll until the server accepts connections."""
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", self._actual_port), timeout=1
                ):
                    return
            except (socket.timeout, ConnectionRefusedError, OSError):
                time.sleep(0.1)

        raise RuntimeError("PostgreSQL server did not start within 30 seconds")

    def start(self) -> "EmbeddedPostgres":
        """Start the ephemeral PostgreSQL instance.

        Returns *self* so calls can be chained.
        """
        if self._running:
            return self

        self._bin_dir = self._find_binaries()

        if self._data_dir is None:
            self._actual_data_dir = tempfile.mkdtemp(prefix="inmemory_pg_")
        else:
            self._actual_data_dir = os.path.abspath(self._data_dir)
            os.makedirs(self._actual_data_dir, exist_ok=True)

        if self._port is None:
            self._actual_port = self._find_free_port()
        else:
            self._actual_port = self._port

        try:
            self._initdb()
            self._start_postgres()
            self._ensure_database_exists()
            self._running = True
            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True
        except Exception:
            self._cleanup()
            raise

        return self

    def stop(self) -> None:
        """Stop the PostgreSQL server and clean up data files."""
        if not self._running:
            return

        # Unregister atexit handler to prevent double-stop
        if self._atexit_registered:
            try:
                atexit.unregister(self.stop)
            except Exception:
                pass
            self._atexit_registered = False

        stopped = False

        try:
            # Strategy 1: clean shutdown via pg_ctl or direct process
            try:
                if self._process is not None:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=5)
                        stopped = True
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait()
                        stopped = True
                    self._process = None
                elif self._bin_dir and os.path.exists(self._bin("pg_ctl")):
                    env = os.environ.copy()
                    env["PGPORT"] = str(self._actual_port)
                    result = subprocess.run(
                        [
                            self._bin("pg_ctl"),
                            "stop",
                            "--pgdata", self._actual_data_dir,
                            "--mode", "immediate",
                            "--wait",
                        ],
                        capture_output=True,
                        check=False,
                        env=env,
                    )
                    stopped = result.returncode == 0
            except Exception:
                pass

            # Strategy 2: force-kill by postmaster PID (handles orphaned processes)
            if not stopped and self._postmaster_pid is not None:
                try:
                    os.kill(self._postmaster_pid, signal.SIGKILL)
                    # Give it a moment to die
                    for _ in range(50):
                        try:
                            os.kill(self._postmaster_pid, 0)
                            time.sleep(0.1)
                        except OSError:
                            stopped = True
                            break
                except (OSError, PermissionError):
                    pass

            # Strategy 3: pg_ctl stop --mode immediate as last resort
            if not stopped and self._bin_dir and os.path.exists(self._bin("pg_ctl")):
                try:
                    subprocess.run(
                        [self._bin("pg_ctl"), "stop", "--pgdata", self._actual_data_dir,
                         "--mode", "immediate"],
                        capture_output=True, check=False, timeout=10,
                    )
                except Exception:
                    pass
        finally:
            self._cleanup()
            self._running = False
            self._postmaster_pid = None

    def _cleanup(self) -> None:
        """Remove the temporary data directory."""
        if self._actual_data_dir and (
            self._data_dir is None or not os.path.exists(self._data_dir)
        ):
            try:
                shutil.rmtree(self._actual_data_dir, ignore_errors=True)
            except Exception:
                pass
        self._actual_data_dir = None

    @staticmethod
    def cleanup_orphans() -> None:
        """Remove orphaned temp dirs from crashed or SIGKILL'd runs.

        Only removes directories whose postmaster process is confirmed
        dead.  If the postmaster is still alive the directory is assumed
        to be in use by another process (e.g. a parallel test worker)
        and is left untouched.
        """
        for data_dir in glob.glob(tempfile.gettempdir() + "/inmemory_pg_*"):
            pid_file = os.path.join(data_dir, "postmaster.pid")
            if not os.path.exists(pid_file):
                # No pid file — dir may be mid-initdb by another worker; skip
                continue

            orphaned = False
            try:
                with open(pid_file) as f:
                    line = f.readline().strip()
                    if line.isdigit():
                        pid = int(line)
                        try:
                            os.kill(pid, 0)
                            # Process is alive — leave it (in use by another worker)
                        except OSError:
                            # Process is dead — safe to clean
                            orphaned = True
                        except PermissionError:
                            # Can't check — leave it
                            pass
                    else:
                        # Invalid pid file — orphaned
                        orphaned = True
            except (OSError, ValueError):
                continue

            if orphaned:
                shutil.rmtree(data_dir, ignore_errors=True)

    def url(self, database: Optional[str] = None) -> str:
        """Return a psycopg2-compatible connection URL.

        Args:
            database: Override the default database name.
        """
        if not self._running:
            raise RuntimeError("Server is not running. Call start() first.")
        db = database or self._database
        return (
            f"postgresql://{self._username}:{self._password}"
            f"@127.0.0.1:{self._actual_port}/{db}"
        )

    def dsn(self, database: Optional[str] = None) -> dict:
        """Return connection parameters as a dict for psycopg2.

        Args:
            database: Override the default database name.
        """
        if not self._running:
            raise RuntimeError("Server is not running. Call start() first.")
        db = database or self._database
        return {
            "host": "127.0.0.1",
            "port": self._actual_port,
            "user": self._username,
            "password": self._password,
            "dbname": db,
        }

    def __enter__(self) -> "EmbeddedPostgres":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def __del__(self):
        # Guard against interpreter shutdown where globals may be None
        try:
            self.stop()
        except (TypeError, AttributeError, OSError):
            # During interpreter shutdown os.kill, subprocess etc. may be None
            pass

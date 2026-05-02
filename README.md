# embedded-postgres

Spin up ephemeral, isolated PostgreSQL instances for testing.

Zero configuration — works out of the box even if PostgreSQL is not installed on your machine.  The library automatically downloads and caches a lightweight prebuilt PostgreSQL bundle (~30 MB) on first use.

## Requirements

- Python 3.8+
- Internet access on first run (to download the prebuilt binary bundle)

## Installation

```bash
pip install embedded-postgres
```

Or add to your project's dependencies::

```toml
# pyproject.toml
[project]
dependencies = [
    "embedded-postgres",
]
```

## Quick start

### In Python code

```python
from embeddedpostgres import EmbeddedPostgres
import psycopg2

with EmbeddedPostgres() as pg:
    conn = psycopg2.connect(pg.url())
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print(cur.fetchone())  # (1,)
    cur.close()
    conn.close()
# Server is automatically stopped and data directory cleaned up.
```

### As a pytest fixture (recommended for test suites)

Add this to your ``conftest.py``::

```python
import pytest
from embeddedpostgres import EmbeddedPostgres


@pytest.fixture(scope="session")
def postgres():
    pg = EmbeddedPostgres()
    pg.start()
    yield pg
    pg.stop()
```

Then use it in tests::

```python
import psycopg2


def test_something(postgres):
    conn = psycopg2.connect(postgres.url())
    cur = conn.cursor()
    cur.execute("CREATE TABLE items (id serial PRIMARY KEY, name text)")
    cur.execute("INSERT INTO items (name) VALUES ('widget')")
    cur.execute("SELECT name FROM items")
    assert cur.fetchone()[0] == "widget"
    cur.close()
    conn.close()
```

### Using the built-in pytest plugin

``embeddedpostgres`` ships with ready-made fixtures.  Import them in your ``conftest.py``::

```python
pytest_plugins = ["embeddedpostgres.fixtures"]
```

Then use in tests::

```python
import psycopg2


def test_with_session_server(postgres_session):
    """Reuse a single server across the whole test session."""
    conn = psycopg2.connect(postgres_session.url())
    ...


def test_with_isolated_database(postgres):
    """Get a fresh database URL inside the shared server."""
    conn = psycopg2.connect(postgres)
    ...
```

- ``postgres_session`` — one server for the whole test session (fastest)
- ``postgres`` — a fresh database per test function inside the shared server
  (good balance of speed and isolation)

## How it works

1. **System lookup** — checks your ``$PATH`` and common install locations for a local PostgreSQL.
2. **Auto-download** — if nothing is found, downloads the correct prebuilt bundle from Maven Central (`zonkyio/embedded-postgres-binaries`).
3. **Cache** — extracts the bundle to ``~/.cache/embeddedpostgres/<version>/`` and reuses it forever.
4. **Boot** — ``initdb`` creates a temp data directory, ``postgres`` starts on a random free port.
5. **Cleanup** — on ``stop()`` or context-manager exit the server shuts down and temp data is removed.

First download takes ~10–30 s depending on your connection.  Every subsequent start is **~0.6 s**.

## Configuration options

| Parameter | Default | Description |
|-----------|---------|-------------|
| ``version`` | ``"16.0.0"`` | PostgreSQL version to download (e.g. ``"18.3.0"``) |
| ``port`` | random free port | TCP port to bind the server |
| ``database`` | ``"postgres"`` | Default database name |
| ``username`` | ``"postgres"`` | Superuser name |
| ``password`` | ``"postgres"`` | Superuser password |
| ``data_dir`` | temp directory | Where to store the data cluster |
| ``pg_bin_dir`` | ``None`` | Path to your own ``initdb``/``postgres`` binaries |

```python
# Use PostgreSQL 18.3.0
with EmbeddedPostgres(version="18.3.0") as pg:
    ...

# Use your own local binaries
pg = EmbeddedPostgres(pg_bin_dir="/opt/postgres/16/bin")
pg.start()
```

## Cache location

Downloaded binaries are cached in:

- ``~/.cache/embeddedpostgres/`` (Linux / macOS)
- ``%LOCALAPPDATA%\embeddedpostgres\`` (Windows, via ``platformdirs`` if added)

Set ``XDG_CACHE_HOME`` to override the cache directory.

## API reference

### ``EmbeddedPostgres``

```python
pg = EmbeddedPostgres(version="16.0.0", port=25432, database="myapp_test")
pg.start()

pg.url()          # -> "postgresql://postgres:postgres@127.0.0.1:25432/myapp_test"
pg.dsn()          # -> dict for psycopg2.connect(**pg.dsn())
pg.stop()
```

Context-manager support::

```python
with EmbeddedPostgres() as pg:
    url = pg.url()
    ...
```

### ``PostgresBinaryManager``

For advanced use you can manage the binary cache directly::

```python
from embeddedpostgres import PostgresBinaryManager

mgr = PostgresBinaryManager(version="16.0.0")
bin_dir = mgr.get_bin_dir()   # Path object to the bin/ directory
```

## Supported platforms

Prebuilt binaries are available for:

- **Linux** — amd64, arm64v8, i386
- **macOS** — amd64 (Intel), arm64v8 (Apple Silicon)
- **Windows** — amd64, i386

If your platform is unsupported the library raises ``RuntimeError`` with a clear message.

## For library authors

Add ``embedded-postgres`` to your ``pyproject.toml`` dependencies::

```toml
dependencies = [
    "embedded-postgres",
]
```

For development / test-only usage::

```toml
[project.optional-dependencies]
test = [
    "embedded-postgres",
    "pytest",
]
```

Users running your tests do **not** need PostgreSQL installed — the library handles everything automatically.

## License

MIT

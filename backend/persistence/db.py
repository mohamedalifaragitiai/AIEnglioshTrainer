"""SQLite access — WAL mode, single file, zero server.

A new connection is opened per operation (SQLite connections are cheap and this
keeps things thread-safe under FastAPI's sync threadpool). WAL, foreign keys, and a
busy timeout are set on every connect; WAL itself is a persistent property of the
database file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.core.logging import get_logger

log = get_logger("db")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Transactional connection: commits on success, rolls back on error."""
        con = self._connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def journal_mode(self) -> str:
        with self.connection() as con:
            return con.execute("PRAGMA journal_mode").fetchone()[0]

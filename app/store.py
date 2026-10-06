"""Small persistent JSON document store backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Transaction:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def get(self, collection: str, item_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT data FROM documents WHERE collection = ? AND id = ?",
            (collection, item_id),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, collection: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT data FROM documents WHERE collection = ? ORDER BY id",
            (collection,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, collection: str, item_id: str, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise TypeError("Stored documents must be JSON objects")
        if data.get("id") != item_id:
            raise ValueError("Document id must match its storage key")
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self._connection.execute(
            """INSERT INTO documents(collection, id, data) VALUES (?, ?, ?)
               ON CONFLICT(collection, id) DO UPDATE SET data = excluded.data""",
            (collection, item_id, encoded),
        )

    def delete(self, collection: str, item_id: str) -> None:
        self._connection.execute(
            "DELETE FROM documents WHERE collection = ? AND id = ?",
            (collection, item_id),
        )


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Store requires a file-backed SQLite database")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=45000")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS documents (
                       collection TEXT NOT NULL,
                       id TEXT NOT NULL,
                       data TEXT NOT NULL,
                       PRIMARY KEY(collection, id)
                   )"""
            )
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=45, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=45000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield Transaction(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[Transaction]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            yield Transaction(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

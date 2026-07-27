"""Kết nối SQLite, transaction và migration schema."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.constants import SQLITE_SCHEMA_VERSION


class DatabaseError(RuntimeError):
    """Lỗi tầng lưu trữ đã được chuẩn hóa."""


class Database:
    """Một kết nối SQLite tuần tự hóa bằng khóa re-entrant.

    ``check_same_thread=False`` cho phép watcher/service gọi repository từ thread
    nền; khóa bảo đảm không có hai transaction dùng chung connection đồng thời.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self.connect()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                connection = sqlite3.connect(
                    self.path,
                    timeout=30.0,
                    isolation_level=None,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 30000")
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA synchronous = FULL")
                except sqlite3.DatabaseError:
                    connection.close()
                    raise
                self._connection = connection
            return self._connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self.connect()

    def initialize(self) -> None:
        with self.transaction(immediate=True) as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > SQLITE_SCHEMA_VERSION:
                raise DatabaseError(
                    "Database được tạo bởi phiên bản ứng dụng mới hơn."
                )
            if current_version < 1:
                self._migration_1(connection)
                connection.execute("PRAGMA user_version = 1")
                current_version = 1
            if current_version != SQLITE_SCHEMA_VERSION:
                raise DatabaseError("Không thể nâng cấp database đến phiên bản hiện tại.")

    migrate = initialize

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        # Dùng từng statement để không kích hoạt implicit COMMIT của
        # sqlite3.Connection.executescript; migration vì thế nằm trọn trong
        # transaction do ``initialize`` quản lý.
        statements = (
            """
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_filename TEXT NOT NULL,
                source_inbox_path TEXT,
                original_archive_path TEXT NOT NULL,
                working_path TEXT NOT NULL,
                ready_path TEXT,
                sha256 TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (
                    status IN ('RECEIVED','REVIEWING','READY','INVALID','ARCHIVED')
                ),
                received_at TEXT NOT NULL,
                last_opened_at TEXT,
                last_saved_at TEXT,
                confirmed_at TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                valid_count INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                total_amount INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_batches_status_received
                ON batches(status, received_at DESC, id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_batches_confirmed
                ON batches(confirmed_at DESC, id DESC)
            """,
        )
        for statement in statements:
            connection.execute(statement)

    @contextmanager
    def transaction(
        self,
        *,
        immediate: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def query_one(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> sqlite3.Row | None:
        with self._lock:
            return self.connect().execute(sql, tuple(parameters)).fetchone()

    def query_all(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connect().execute(sql, tuple(parameters)).fetchall())

    def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> int:
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(sql, tuple(parameters))
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

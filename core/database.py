"""SQLite database access and archival support for DailyTodo."""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Sequence


class DatabaseError(RuntimeError):
    """Raised when a database operation fails."""


class Database:
    """Small SQLite wrapper used by the task manager and scheduler."""

    def __init__(self, db_path: Path | str = Path("data") / "todo.db") -> None:
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self.db_path = Path(db_path)
        self.data_dir = self.db_path.parent
        self.archive_dir = self.data_dir / "archive"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.connection = sqlite3.connect(
                self.db_path,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to connect to database: {self.db_path}") from exc

    def initialize(self) -> None:
        """Create required tables and archive stale rows."""

        try:
            with self.transaction():
                self.connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL CHECK(length(trim(content)) > 0),
                        target_date TEXT NOT NULL,
                        is_completed INTEGER NOT NULL DEFAULT 0 CHECK(is_completed IN (0, 1)),
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_target_date_sort
                    ON tasks(target_date, sort_order, id)
                    """
                )
                self.connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            self._archive_previous_month()
        except sqlite3.Error as exc:
            self.logger.exception("Database initialization failed")
            raise DatabaseError("Database initialization failed") from exc

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run statements atomically."""

        with self._lock:
            try:
                self.connection.execute("BEGIN")
                yield
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self.connection.execute(sql, parameters)
            except sqlite3.Error as exc:
                self.logger.exception("Database execute failed: %s", sql)
                raise DatabaseError("Database execute failed") from exc

    def executemany(self, sql: str, parameters: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self.connection.executemany(sql, parameters)
            except sqlite3.Error as exc:
                self.logger.exception("Database executemany failed: %s", sql)
                raise DatabaseError("Database executemany failed") from exc

    def fetch_all(self, sql: str, parameters: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.execute(sql, parameters).fetchall())

    def fetch_one(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.execute(sql, parameters).fetchone()

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        row = self.fetch_one("SELECT value FROM metadata WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def set_metadata(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO metadata(key, value, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            try:
                self.connection.close()
            except sqlite3.Error:
                self.logger.exception("Failed to close database connection")

    def _archive_previous_month(self) -> None:
        """Move rows older than the current month into per-month archive DBs."""

        first_day_this_month = date.today().replace(day=1).isoformat()
        rows = self.fetch_all(
            """
            SELECT id, content, target_date, is_completed, sort_order, created_at, updated_at
            FROM tasks
            WHERE target_date < ?
            ORDER BY target_date ASC, sort_order ASC, id ASC
            """,
            (first_day_this_month,),
        )
        if not rows:
            return

        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["target_date"])[:7], []).append(row)

        with self._lock:
            try:
                self.connection.execute("PRAGMA wal_checkpoint(FULL)")
                for month, month_rows in grouped.items():
                    archive_path = self.archive_dir / f"todo_{month}.db"
                    self._write_archive_month(archive_path, month, month_rows)

                with self.transaction():
                    self.execute("DELETE FROM tasks WHERE target_date < ?", (first_day_this_month,))
                    self.set_metadata("last_archive_month", date.today().strftime("%Y-%m"))
                self.connection.execute("VACUUM")
                self.logger.info("Archived %s task rows into %s monthly DB(s)", len(rows), len(grouped))
            except (OSError, sqlite3.Error, DatabaseError) as exc:
                self.logger.exception("Monthly archive failed")
                raise DatabaseError("Monthly archive failed") from exc

    def _write_archive_month(
        self,
        archive_path: Path,
        month: str,
        rows: Sequence[sqlite3.Row],
    ) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive = sqlite3.connect(archive_path)
        try:
            archive.execute("PRAGMA journal_mode = WAL")
            archive.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
                    target_date TEXT NOT NULL,
                    is_completed INTEGER NOT NULL DEFAULT 0 CHECK(is_completed IN (0, 1)),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            archive.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_target_date_sort
                ON tasks(target_date, sort_order, id)
                """
            )
            archive.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            archive.executemany(
                """
                INSERT OR REPLACE INTO tasks(
                    id, content, target_date, is_completed, sort_order, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(row["id"]),
                        str(row["content"]),
                        str(row["target_date"]),
                        int(row["is_completed"]),
                        int(row["sort_order"]),
                        str(row["created_at"]),
                        str(row["updated_at"]),
                    )
                    for row in rows
                ],
            )
            archive.execute(
                """
                INSERT INTO metadata(key, value, updated_at)
                VALUES('archive_month', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (month,),
            )
            archive.commit()
        except Exception:
            archive.rollback()
            raise
        finally:
            archive.close()

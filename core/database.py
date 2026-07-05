"""SQLite database access for DailyTodo."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
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
        """Create required tables and import legacy archive rows once."""

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
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        uid TEXT NOT NULL DEFAULT '',
                        base_version INTEGER NOT NULL DEFAULT 0,
                        deleted_at TEXT,
                        last_synced_at TEXT,
                        sync_dirty INTEGER NOT NULL DEFAULT 1 CHECK(sync_dirty IN (0, 1))
                    )
                    """
                )
                self._ensure_sync_columns()
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_target_date_sort
                    ON tasks(target_date, sort_order, id)
                    """
                )
                self.connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uid
                    ON tasks(uid)
                    """
                )
                self.connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_sync_dirty
                    ON tasks(sync_dirty, deleted_at)
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
                self._ensure_task_uids()
            self._merge_archived_tasks_once()
        except (sqlite3.Error, DatabaseError) as exc:
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

    def get_tasks_by_date(self, date_str: str) -> list[sqlite3.Row]:
        rows = self.fetch_all(
            """
            SELECT id, uid, content, target_date, is_completed, sort_order,
                   created_at, updated_at, base_version, deleted_at, last_synced_at, sync_dirty
            FROM tasks
            WHERE target_date = ? AND deleted_at IS NULL
            ORDER BY sort_order ASC, id ASC
            """,
            (date_str,),
        )
        return rows

    def get_task_dates(self, max_date: str) -> set[str]:
        rows = self.fetch_all(
            """
            SELECT DISTINCT target_date
            FROM tasks
            WHERE target_date <= ? AND deleted_at IS NULL
            """,
            (max_date,),
        )
        return {str(row["target_date"]) for row in rows}

    def count_tasks_by_date(self, date_str: str) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) AS count FROM tasks WHERE target_date = ? AND deleted_at IS NULL",
            (date_str,),
        )
        return int(row["count"]) if row else 0

    def insert_tasks(self, values: Sequence[tuple[str, str, int]]) -> None:
        with self.transaction():
            self.executemany(
                """
                INSERT INTO tasks(uid, content, target_date, sort_order, sync_dirty)
                VALUES(?, ?, ?, ?, ?)
                """,
                [(str(uuid.uuid4()), content, target_date, sort_order, 1) for content, target_date, sort_order in values],
            )

    def add_task(self, content: str, target_date: str, sort_order: int | None = None) -> int:
        if sort_order is None:
            row = self.fetch_one(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM tasks WHERE target_date = ?",
                (target_date,),
            )
            sort_order = int(row["next_order"]) if row else 0

        cursor = self.execute(
            """
            INSERT INTO tasks(uid, content, target_date, sort_order, sync_dirty)
            VALUES(?, ?, ?, ?, 1)
            """,
            (str(uuid.uuid4()), content, target_date, sort_order),
        )
        return int(cursor.lastrowid)

    def update_task(
        self,
        task_id: int,
        *,
        content: str | None = None,
        is_completed: bool | None = None,
        sort_order: int | None = None,
    ) -> bool:
        fields: list[str] = []
        values: list[Any] = []

        if content is not None:
            fields.append("content = ?")
            values.append(content)
        if is_completed is not None:
            fields.append("is_completed = ?")
            values.append(1 if is_completed else 0)
        if sort_order is not None:
            fields.append("sort_order = ?")
            values.append(sort_order)

        if not fields:
            return True

        fields.append("updated_at = CURRENT_TIMESTAMP")
        fields.append("sync_dirty = 1")
        values.append(task_id)
        cursor = self.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        return cursor.rowcount > 0

    def delete_task(self, task_id: int) -> bool:
        cursor = self.execute(
            """
            UPDATE tasks
            SET deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                sync_dirty = 1
            WHERE id = ? AND deleted_at IS NULL
            """,
            (task_id,),
        )
        return cursor.rowcount > 0

    def reorder_tasks(self, ordered_ids: Sequence[int]) -> None:
        with self.transaction():
            for sort_order, task_id in enumerate(ordered_ids):
                self.execute(
                    """
                    UPDATE tasks
                    SET sort_order = ?,
                        updated_at = CURRENT_TIMESTAMP,
                        sync_dirty = 1
                    WHERE id = ? AND deleted_at IS NULL
                    """,
                    (sort_order, task_id),
                )

    def get_dirty_tasks(self) -> list[sqlite3.Row]:
        return self.fetch_all(
            """
            SELECT id, uid, content, target_date, is_completed, sort_order,
                   created_at, updated_at, base_version, deleted_at, last_synced_at, sync_dirty
            FROM tasks
            WHERE sync_dirty = 1
            ORDER BY target_date ASC, sort_order ASC, id ASC
            """
        )

    def get_task_by_uid(self, uid: str) -> sqlite3.Row | None:
        return self.fetch_one(
            """
            SELECT id, uid, content, target_date, is_completed, sort_order,
                   created_at, updated_at, base_version, deleted_at, last_synced_at, sync_dirty
            FROM tasks
            WHERE uid = ?
            """,
            (uid,),
        )

    def mark_task_synced(self, uid: str, version: int) -> None:
        self.execute(
            """
            UPDATE tasks
            SET base_version = ?,
                sync_dirty = 0,
                last_synced_at = CURRENT_TIMESTAMP
            WHERE uid = ?
            """,
            (version, uid),
        )

    def upsert_remote_task(self, payload: dict[str, Any]) -> None:
        deleted_at = datetime.now().isoformat(timespec="seconds") if bool(payload.get("deleted", False)) else None
        existing = self.get_task_by_uid(str(payload["id"]))
        values = (
            str(payload["id"]),
            str(payload.get("content", "")),
            str(payload["target_date"]),
            1 if bool(payload.get("completed", False)) else 0,
            int(payload.get("sort_order", 0)),
            int(payload.get("version", 0)),
            deleted_at,
        )
        if existing is None:
            self.execute(
                """
                INSERT INTO tasks(
                    uid, content, target_date, is_completed, sort_order,
                    base_version, deleted_at, sync_dirty, last_synced_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                """,
                values,
            )
            return
        self.execute(
            """
            UPDATE tasks
            SET content = ?,
                target_date = ?,
                is_completed = ?,
                sort_order = ?,
                base_version = ?,
                deleted_at = ?,
                updated_at = CURRENT_TIMESTAMP,
                sync_dirty = 0,
                last_synced_at = CURRENT_TIMESTAMP
            WHERE uid = ?
            """,
            (values[1], values[2], values[3], values[4], values[5], values[6], values[0]),
        )

    def close(self) -> None:
        with self._lock:
            try:
                self.connection.close()
            except sqlite3.Error:
                self.logger.exception("Failed to close database connection")

    def backup_before_cloud_download(self) -> Path:
        backup_path = self.data_dir / f"todo.before-cloud-download.{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
        with self._lock:
            self.connection.execute("PRAGMA wal_checkpoint(FULL)")
            shutil.copy2(self.db_path, backup_path)
        return backup_path

    def prepare_for_cloud_download(self) -> None:
        """Hide local rows before applying a full cloud snapshot."""

        self.execute(
            """
            UPDATE tasks
            SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                sync_dirty = 0,
                last_synced_at = CURRENT_TIMESTAMP
            """
        )

    def _merge_archived_tasks_once(self) -> None:
        """Import rows from legacy monthly archive databases into the main database."""

        if self.get_metadata("archive_merge_completed_at") is not None:
            return

        imported = 0
        archive_paths = sorted(self.archive_dir.glob("todo_????-??.db")) if self.archive_dir.exists() else []
        with self.transaction():
            for archive_path in archive_paths:
                rows = self._fetch_archive_rows(
                    archive_path,
                    """
                    SELECT id, content, target_date, is_completed, sort_order, created_at, updated_at
                    FROM tasks
                    ORDER BY target_date ASC, sort_order ASC, id ASC
                    """,
                    (),
                )
                for row in rows:
                    cursor = self.execute(
                        """
                        INSERT OR IGNORE INTO tasks(
                            id, uid, content, target_date, is_completed, sort_order,
                            created_at, updated_at, sync_dirty
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            int(row["id"]),
                            str(uuid.uuid4()),
                            str(row["content"]),
                            str(row["target_date"]),
                            int(row["is_completed"]),
                            int(row["sort_order"]),
                            str(row["created_at"]),
                            str(row["updated_at"]),
                        ),
                    )
                    imported += cursor.rowcount
            self.execute(
                """
                INSERT INTO metadata(key, value, updated_at)
                VALUES('archive_merge_completed_at', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
        if archive_paths:
            self.logger.info("Imported %s legacy archive task row(s) into the main database", imported)

    def _fetch_archive_rows(
        self,
        archive_path: Path,
        sql: str,
        parameters: Sequence[Any],
    ) -> list[sqlite3.Row]:
        try:
            archive = sqlite3.connect(archive_path)
            archive.row_factory = sqlite3.Row
            try:
                return list(archive.execute(sql, parameters).fetchall())
            finally:
                archive.close()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to read archive database: %s", archive_path)
            raise DatabaseError("Failed to read archive database") from exc

    def _ensure_sync_columns(self) -> None:
        columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(tasks)").fetchall()}
        migrations = {
            "uid": "ALTER TABLE tasks ADD COLUMN uid TEXT NOT NULL DEFAULT ''",
            "base_version": "ALTER TABLE tasks ADD COLUMN base_version INTEGER NOT NULL DEFAULT 0",
            "deleted_at": "ALTER TABLE tasks ADD COLUMN deleted_at TEXT",
            "last_synced_at": "ALTER TABLE tasks ADD COLUMN last_synced_at TEXT",
            "sync_dirty": "ALTER TABLE tasks ADD COLUMN sync_dirty INTEGER NOT NULL DEFAULT 1",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.connection.execute(sql)

    def _ensure_task_uids(self) -> None:
        rows = self.connection.execute("SELECT id FROM tasks WHERE uid = '' OR uid IS NULL").fetchall()
        for row in rows:
            self.connection.execute("UPDATE tasks SET uid = ?, sync_dirty = 1 WHERE id = ?", (str(uuid.uuid4()), row["id"]))

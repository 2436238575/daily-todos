"""Task CRUD facade for DailyTodo."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from core.database import Database


@dataclass(frozen=True)
class Task:
    id: int
    content: str
    target_date: str
    is_completed: bool
    sort_order: int
    created_at: str
    updated_at: str


class TaskManager:
    """High-level task operations used by UI and scheduler."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.logger = logging.getLogger(__name__)

    def get_tasks_by_date(self, date_str: str) -> list[Task]:
        rows = self.database.fetch_all(
            """
            SELECT id, content, target_date, is_completed, sort_order, created_at, updated_at
            FROM tasks
            WHERE target_date = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (date_str,),
        )
        return [self._row_to_task(row) for row in rows]

    def count_tasks_by_date(self, date_str: str) -> int:
        row = self.database.fetch_one(
            "SELECT COUNT(*) AS count FROM tasks WHERE target_date = ?",
            (date_str,),
        )
        return int(row["count"]) if row else 0

    def insert_from_template(self, date_str: str, template_list: Iterable[dict[str, Any]]) -> int:
        values: list[tuple[str, str, int]] = []
        for index, item in enumerate(template_list):
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            sort_order = int(item.get("sort_order", index))
            values.append((content, date_str, sort_order))

        if not values:
            self.logger.info("Template is empty; no tasks inserted for %s", date_str)
            return 0

        with self.database.transaction():
            self.database.executemany(
                """
                INSERT INTO tasks(content, target_date, sort_order)
                VALUES(?, ?, ?)
                """,
                values,
            )
        self.logger.info("Inserted %s template tasks for %s", len(values), date_str)
        return len(values)

    def add_task(self, content: str, target_date: str, sort_order: int | None = None) -> int:
        content = content.strip()
        if not content:
            raise ValueError("Task content cannot be empty")

        if sort_order is None:
            row = self.database.fetch_one(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM tasks WHERE target_date = ?",
                (target_date,),
            )
            sort_order = int(row["next_order"]) if row else 0

        cursor = self.database.execute(
            """
            INSERT INTO tasks(content, target_date, sort_order)
            VALUES(?, ?, ?)
            """,
            (content, target_date, sort_order),
        )
        task_id = int(cursor.lastrowid)
        self.logger.info("Added task %s for %s", task_id, target_date)
        return task_id

    def update_task(
        self,
        task_id: int,
        *,
        content: str | None = None,
        is_completed: bool | None = None,
        sort_order: int | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []

        if content is not None:
            content = content.strip()
            if not content:
                raise ValueError("Task content cannot be empty")
            fields.append("content = ?")
            values.append(content)
        if is_completed is not None:
            fields.append("is_completed = ?")
            values.append(1 if is_completed else 0)
        if sort_order is not None:
            fields.append("sort_order = ?")
            values.append(sort_order)

        if not fields:
            return

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(task_id)
        cursor = self.database.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Task {task_id} does not exist")

    def delete_task(self, task_id: int) -> None:
        cursor = self.database.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise ValueError(f"Task {task_id} does not exist")
        self.logger.info("Deleted task %s", task_id)

    def reorder_tasks(self, ordered_ids: list[int]) -> None:
        with self.database.transaction():
            for sort_order, task_id in enumerate(ordered_ids):
                self.database.execute(
                    "UPDATE tasks SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (sort_order, task_id),
                )

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        return Task(
            id=int(row["id"]),
            content=str(row["content"]),
            target_date=str(row["target_date"]),
            is_completed=bool(row["is_completed"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


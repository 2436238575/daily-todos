"""Task CRUD facade for DailyTodo."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from core.database import Database


@dataclass(frozen=True)
class Task:
    id: int
    uid: str
    content: str
    target_date: str
    is_completed: bool
    sort_order: int
    created_at: str
    updated_at: str
    base_version: int
    deleted_at: str | None
    last_synced_at: str | None
    sync_dirty: bool


class TaskManager:
    """High-level task operations used by UI and scheduler."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.logger = logging.getLogger(__name__)

    def get_tasks_by_date(self, date_str: str) -> list[Task]:
        return [self._row_to_task(row) for row in self.database.get_tasks_by_date(date_str)]

    def get_available_dates(self) -> set[str]:
        today = date.today().isoformat()
        dates = self.database.get_task_dates(today)
        dates.add(today)
        return dates

    def count_tasks_by_date(self, date_str: str) -> int:
        return self.database.count_tasks_by_date(date_str)

    def insert_from_template(self, date_str: str, template_list: Iterable[dict[str, Any]]) -> int:
        values: list[tuple[str, str, int]] = []
        for index, item in enumerate(template_list):
            if bool(item.get("deleted", False)):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            sort_order = int(item.get("sort_order", index))
            values.append((content, date_str, sort_order))

        if not values:
            self.logger.info("Template is empty; no tasks inserted for %s", date_str)
            return 0

        self.database.insert_tasks(values)
        self.logger.info("Inserted %s template tasks for %s", len(values), date_str)
        return len(values)

    def add_task(self, content: str, target_date: str, sort_order: int | None = None) -> int:
        content = content.strip()
        if not content:
            raise ValueError("Task content cannot be empty")

        task_id = self.database.add_task(content, target_date, sort_order)
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
        if content is not None:
            content = content.strip()
            if not content:
                raise ValueError("Task content cannot be empty")
        updated = self.database.update_task(
            task_id,
            content=content,
            is_completed=is_completed,
            sort_order=sort_order,
        )
        if not updated:
            raise ValueError(f"Task {task_id} does not exist")
        fields = []
        if content is not None:
            fields.append(f"content_len={len(content)}")
        if is_completed is not None:
            fields.append(f"is_completed={is_completed}")
        if sort_order is not None:
            fields.append(f"sort_order={sort_order}")
        self.logger.info("Updated task %s: %s", task_id, ", ".join(fields) or "no fields")

    def delete_task(self, task_id: int) -> None:
        if not self.database.delete_task(task_id):
            raise ValueError(f"Task {task_id} does not exist")
        self.logger.info("Deleted task %s", task_id)

    def reorder_tasks(self, ordered_ids: list[int]) -> None:
        self.database.reorder_tasks(ordered_ids)
        self.logger.info("Reordered %s task(s)", len(ordered_ids))

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        return Task(
            id=int(row["id"]),
            uid=str(row["uid"]),
            content=str(row["content"]),
            target_date=str(row["target_date"]),
            is_completed=bool(row["is_completed"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            base_version=int(row["base_version"]),
            deleted_at=str(row["deleted_at"]) if row["deleted_at"] is not None else None,
            last_synced_at=str(row["last_synced_at"]) if row["last_synced_at"] is not None else None,
            sync_dirty=bool(row["sync_dirty"]),
        )

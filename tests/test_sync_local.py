from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.sync_utils import (
    dedupe_resolutions,
    merge_conflicts,
    sync_change_counts,
    sync_change_lines,
    sync_summary_message,
)


class LocalSyncDatabaseTest(unittest.TestCase):
    def test_task_sync_fields_and_soft_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "todo.db")
            database.initialize()
            task_id = database.add_task("sync me", "2026-07-05")

            rows = database.get_dirty_tasks()
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["uid"])
            self.assertEqual(rows[0]["base_version"], 0)

            self.assertTrue(database.delete_task(task_id))
            self.assertEqual(database.get_tasks_by_date("2026-07-05"), [])
            deleted = database.get_task_by_uid(rows[0]["uid"])
            self.assertIsNotNone(deleted)
            self.assertIsNotNone(deleted["deleted_at"])
            self.assertEqual(deleted["sync_dirty"], 1)
            database.close()

    def test_prepare_for_cloud_download_hides_local_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "todo.db")
            database.initialize()
            database.add_task("local only", "2026-07-05")

            database.prepare_for_cloud_download()

            self.assertEqual(database.get_tasks_by_date("2026-07-05"), [])
            rows = database.fetch_all("SELECT deleted_at, sync_dirty FROM tasks")
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0]["deleted_at"])
            self.assertEqual(rows[0]["sync_dirty"], 0)
            database.close()


class TemplateSyncSettingsTest(unittest.TestCase):
    def test_deleted_template_items_do_not_shift_visible_order(self) -> None:
        try:
            from lib.utils import _normalize_template
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6":
                self.skipTest("PySide6 is not installed in this environment")
            raise

        template = _normalize_template(
            [
                {"uid": "deleted", "content": "old", "sort_order": 0, "deleted": True, "sync_dirty": True},
                {"uid": "visible-a", "content": "a", "sort_order": 0, "deleted": False, "sync_dirty": False},
                {"uid": "visible-b", "content": "b", "sort_order": 1, "deleted": False, "sync_dirty": False},
            ]
        )

        visible = [item for item in template if not item["deleted"]]
        self.assertEqual([item["sort_order"] for item in visible], [0, 1])


class SyncConflictDedupeTest(unittest.TestCase):
    def test_merge_conflicts_keeps_unique_ids(self) -> None:
        push_conflict = {"id": "conflict-1", "entity_id": "task-1"}
        pull_conflict = {"id": "conflict-1", "entity_id": "task-1"}
        other_conflict = {"id": "conflict-2", "entity_id": "task-2"}

        merged = merge_conflicts([push_conflict], [pull_conflict, other_conflict])

        self.assertEqual([item["id"] for item in merged], ["conflict-1", "conflict-2"])
        self.assertIs(merged[0], push_conflict)

    def test_dedupe_resolutions_keeps_first_choice(self) -> None:
        resolutions = [
            {"conflict_id": "conflict-1", "choice": "local"},
            {"conflict_id": "conflict-1", "choice": "remote"},
            {"conflict_id": "conflict-2", "choice": "remote"},
        ]

        deduped = dedupe_resolutions(resolutions)

        self.assertEqual(
            deduped,
            [
                {"conflict_id": "conflict-1", "choice": "local"},
                {"conflict_id": "conflict-2", "choice": "remote"},
            ],
        )

    def test_sync_change_lines_mark_upload_download_and_delete(self) -> None:
        lines = sync_change_lines(
            accepted=[
                {"entity_type": "task", "entity_id": "local-task", "version": 2},
                {"entity_type": "template_item", "entity_id": "deleted-template", "version": 3},
            ],
            pushed={
                "tasks": [{"id": "local-task", "content": "local edit", "deleted": False}],
                "template_items": [{"id": "deleted-template", "content": "old template", "deleted": True}],
            },
            pulled={
                "tasks": [
                    {"id": "local-task", "content": "local edit", "deleted": False},
                    {"id": "remote-task", "content": "remote edit", "deleted": False},
                ],
                "template_items": [{"id": "remote-delete", "content": "remote old", "deleted": True}],
            },
            conflicts=[],
        )

        self.assertEqual(
            lines,
            [
                "+ 上传任务: local edit",
                "- 上传母本: old template",
                "+ 下载任务: remote edit",
                "- 下载母本: remote old",
            ],
        )
        self.assertEqual(sync_change_counts(lines), (2, 2))

    def test_sync_summary_message_shows_only_counts(self) -> None:
        message = sync_summary_message(["+ 上传任务: a", "+ 上传任务: b", "- 下载任务: c"])

        self.assertEqual(message, "同步完成\n+2 -1")


if __name__ == "__main__":
    unittest.main()

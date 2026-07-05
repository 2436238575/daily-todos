from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.database import Database

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


if __name__ == "__main__":
    unittest.main()

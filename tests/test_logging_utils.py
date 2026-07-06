from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

from lib.logging_utils import BuildInfo, MaaLogFormatter, load_build_info


class MaaLogFormatterTest(unittest.TestCase):
    def test_formats_maa_style_prefix(self) -> None:
        formatter = MaaLogFormatter()
        record = logging.LogRecord(
            name="Bootstrapper",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="DailyTodo GUI started",
            args=(),
            exc_info=None,
        )
        record.created = 1783260000.123
        record.msecs = 123
        record.threadName = "MainThread"

        formatted = formatter.format(record)

        self.assertRegex(formatted, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.123\]\[INF\]\[Bootstrapper\]")
        self.assertIn("<MainThread> DailyTodo GUI started", formatted)

    def test_formats_exception_traceback(self) -> None:
        formatter = MaaLogFormatter()
        try:
            raise ValueError("broken")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="core.database",
            level=logging.ERROR,
            pathname=__file__,
            lineno=30,
            msg="Database failed",
            args=(),
            exc_info=exc_info,
        )

        formatted = formatter.format(record)

        self.assertIn("[ERR][core.database]", formatted)
        self.assertIn("Traceback", formatted)
        self.assertIn("ValueError: broken", formatted)


class BuildInfoTest(unittest.TestCase):
    def test_load_build_info_defaults_without_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load_build_info(Path(temp_dir)), BuildInfo())

    def test_load_build_info_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build_info.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "1.2.3",
                        "env": "Production",
                        "built_at": "2026-07-05T12:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )

            info = load_build_info(Path(temp_dir))

            self.assertEqual(info.version, "1.2.3")
            self.assertEqual(info.env, "Production")
            self.assertEqual(info.built_at, "2026-07-05T12:00:00+08:00")

    def test_load_build_info_falls_back_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "build_info.json"
            path.write_text("{", encoding="utf-8")

            self.assertEqual(load_build_info(Path(temp_dir)), BuildInfo())


if __name__ == "__main__":
    unittest.main()

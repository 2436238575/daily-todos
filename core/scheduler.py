"""Background daily reset scheduler."""

from __future__ import annotations

import logging
from datetime import date, datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot

from core.task_manager import TaskManager
from lib.utils import load_settings


class DailyScheduler(QThread):
    """Polls the clock and fills today's tasks once the reset threshold is reached."""

    reset_finished = Signal(str, int)
    reset_failed = Signal(str)

    def __init__(self, task_manager: TaskManager, parent=None) -> None:
        super().__init__(parent)
        self.task_manager = task_manager
        self.logger = logging.getLogger(__name__)
        self._timer: QTimer | None = None
        self._last_reset_date: str | None = None

    def run(self) -> None:
        self.logger.info("Daily scheduler thread started")
        self._timer = QTimer()
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._on_timeout, Qt.ConnectionType.DirectConnection)
        self._timer.start()
        self._startup_check()
        self.exec()
        self._timer.stop()
        self._timer.deleteLater()
        self._timer = None
        self.logger.info("Daily scheduler thread exited")

    @Slot()
    def _startup_check(self) -> None:
        today = date.today().isoformat()
        self.logger.info("Scheduler startup check for %s", today)
        self._check_and_fill(today)
        self._last_reset_date = today

    @Slot()
    def _on_timeout(self) -> None:
        settings = load_settings()
        reset_time = str(settings.get("reset_time", "03:00"))
        now = datetime.now()
        today = now.date().isoformat()

        if now.strftime("%H:%M") >= reset_time and self._last_reset_date != today:
            self.logger.info("Daily reset threshold reached: date=%s, reset_time=%s", today, reset_time)
            self._check_and_fill(today)
            self._last_reset_date = today

    def _check_and_fill(self, date_str: str) -> None:
        try:
            count = self.task_manager.count_tasks_by_date(date_str)
            if count > 0:
                self.logger.info("Tasks already exist for %s; skip reset fill: count=%s", date_str, count)
                self.reset_finished.emit(date_str, 0)
                return

            settings = load_settings()
            inserted = self.task_manager.insert_from_template(
                date_str,
                settings.get("daily_template", []),
            )
            self.logger.info("Daily reset fill completed: date=%s, inserted=%s", date_str, inserted)
            self.reset_finished.emit(date_str, inserted)
        except Exception as exc:
            self.logger.exception("Daily reset failed")
            self.reset_failed.emit(str(exc))

    def stop(self) -> None:
        self.logger.info("Stopping daily scheduler")
        self.quit()
        self.wait(3000)

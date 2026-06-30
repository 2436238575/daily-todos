"""Main DailyTodo window."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QFile, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.scheduler import DailyScheduler
from core.task_manager import Task, TaskManager
from lib.utils import APP_NAME, apply_theme, setup_tray_icon
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.task_edit_dialog import TaskEditDialog


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self, task_manager: TaskManager, scheduler: DailyScheduler, parent=None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.task_manager = task_manager
        self.scheduler = scheduler
        self._allow_close = False
        self._refreshing = False
        self.refresh_action: QAction | None = None
        self.tray_icon = None

        self._ui = self._load_ui()
        self.date_label: QLabel = self._ui.findChild(QLabel, "dateLabel")
        self.task_list: QListWidget = self._ui.findChild(QListWidget, "taskListWidget")
        self.add_button: QPushButton = self._ui.findChild(QPushButton, "addTaskButton")
        self.delete_button: QPushButton = self._ui.findChild(QPushButton, "deleteTaskButton")
        self.settings_button: QPushButton = self._ui.findChild(QPushButton, "settingsButton")

        self._install_loaded_ui()
        self._configure_task_list()
        self._connect_signals()
        self._create_actions()
        self.retranslate_ui()

        self.tray_icon = setup_tray_icon(
            self,
            self.show_from_tray,
            self.request_quit,
            self.show_today_overview,
        )
        self.refresh_today_view()

    def refresh_today_view(self) -> None:
        today = date.today().isoformat()
        self.date_label.setText(self.tr("{date}").format(date=today))
        self._refreshing = True
        try:
            self.task_list.clear()
            for task in self.task_manager.get_tasks_by_date(today):
                self._add_task_item(task)
        except Exception as exc:
            self.logger.exception("Failed to refresh today's tasks")
            QMessageBox.critical(self, self.tr("刷新失败"), str(exc))
        finally:
            self._refreshing = False

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_quit(self) -> None:
        self._allow_close = True
        self.quit_requested.emit()
        QApplication.instance().quit()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.settings_button.setText(self.tr("设置"))
        self.add_button.setText(self.tr("添加任务"))
        self.delete_button.setText(self.tr("删除选中"))
        if self.refresh_action is not None:
            self.refresh_action.setText(self.tr("刷新"))
        if self.tray_icon is not None and self.tray_icon.contextMenu() is not None:
            actions = self.tray_icon.contextMenu().actions()
            if len(actions) >= 1:
                actions[0].setText(self.tr("显示主窗口"))
            if len(actions) >= 2:
                actions[1].setText(self.tr("今日任务概览"))
            if len(actions) >= 4:
                actions[3].setText(self.tr("退出"))
        self.refresh_today_view()

    def show_today_overview(self) -> None:
        tasks = self.task_manager.get_tasks_by_date(date.today().isoformat())
        completed = sum(1 for task in tasks if task.is_completed)
        QMessageBox.information(
            self,
            self.tr("今日任务概览"),
            self.tr("共 {total} 项，已完成 {completed} 项。").format(
                total=len(tasks),
                completed=completed,
            ),
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                "DailyTodo",
                self.tr("DailyTodo 已隐藏到系统托盘。"),
            )

    def _install_loaded_ui(self) -> None:
        self.setWindowTitle(self._ui.windowTitle())
        self.resize(self._ui.size())
        central = self._ui.findChild(QWidget, "centralWidget")
        central.setParent(None)
        self.setCentralWidget(central)

    def _configure_task_list(self) -> None:
        self.task_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.task_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.task_list.setAlternatingRowColors(True)

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self._add_task)
        self.delete_button.clicked.connect(self._delete_selected_task)
        self.settings_button.clicked.connect(self._open_settings)
        self.task_list.itemChanged.connect(self._task_item_changed)
        self.task_list.itemDoubleClicked.connect(self._edit_task)
        self.task_list.model().rowsMoved.connect(lambda *_: self._persist_task_order())
        self.scheduler.reset_finished.connect(self._on_scheduler_reset)
        self.scheduler.reset_failed.connect(self._on_scheduler_failed)

    def _create_actions(self) -> None:
        self.refresh_action = QAction(self.tr("刷新"), self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_today_view)
        self.addAction(self.refresh_action)

    def _add_task_item(self, task: Task) -> None:
        item = QListWidgetItem(task.content)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
        item.setCheckState(Qt.CheckState.Checked if task.is_completed else Qt.CheckState.Unchecked)
        item.setData(Qt.ItemDataRole.UserRole, task.id)
        self.task_list.addItem(item)

    def _add_task(self) -> None:
        dialog = TaskEditDialog(parent=self)
        if dialog.exec() != TaskEditDialog.DialogCode.Accepted:
            return
        try:
            self.task_manager.add_task(dialog.content, date.today().isoformat())
            self.refresh_today_view()
        except Exception as exc:
            self.logger.exception("Failed to add task")
            QMessageBox.critical(self, self.tr("添加失败"), str(exc))

    def _edit_task(self, item: QListWidgetItem) -> None:
        task_id = int(item.data(Qt.ItemDataRole.UserRole))
        dialog = TaskEditDialog(item.text(), self)
        if dialog.exec() != TaskEditDialog.DialogCode.Accepted:
            return
        try:
            self.task_manager.update_task(task_id, content=dialog.content)
            item.setText(dialog.content)
        except Exception as exc:
            self.logger.exception("Failed to edit task")
            QMessageBox.critical(self, self.tr("编辑失败"), str(exc))
            self.refresh_today_view()

    def _delete_selected_task(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            return
        if QMessageBox.question(
            self,
            self.tr("确认删除"),
            self.tr("确定删除选中的任务吗？"),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.task_manager.delete_task(int(item.data(Qt.ItemDataRole.UserRole)))
            self.refresh_today_view()
        except Exception as exc:
            self.logger.exception("Failed to delete task")
            QMessageBox.critical(self, self.tr("删除失败"), str(exc))

    def _task_item_changed(self, item: QListWidgetItem) -> None:
        if self._refreshing:
            return
        try:
            self.task_manager.update_task(
                int(item.data(Qt.ItemDataRole.UserRole)),
                content=item.text(),
                is_completed=item.checkState() == Qt.CheckState.Checked,
            )
        except Exception as exc:
            self.logger.exception("Failed to update task item")
            QMessageBox.critical(self, self.tr("更新失败"), str(exc))
            self.refresh_today_view()

    def _persist_task_order(self) -> None:
        if self._refreshing:
            return
        ids = [
            int(self.task_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.task_list.count())
        ]
        try:
            self.task_manager.reorder_tasks(ids)
        except Exception:
            self.logger.exception("Failed to persist task order")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            app = QApplication.instance()
            settings = dialog.saved_settings()
            apply_theme(app, settings.get("theme", "system"))
            app.update_theme_signal(settings.get("theme", "system"))
            if app.change_language(settings.get("language", "zh_CN")):
                self.retranslate_ui()

    def _on_scheduler_reset(self, date_str: str, inserted: int) -> None:
        if date_str == date.today().isoformat():
            self.refresh_today_view()
        if inserted > 0 and self.tray_icon is not None:
            self.tray_icon.showMessage(
                "DailyTodo",
                self.tr("已生成今日任务 {count} 项。").format(count=inserted),
            )

    def _on_scheduler_failed(self, message: str) -> None:
        self.logger.error("Scheduler reset failed: %s", message)

    @staticmethod
    def _load_ui():
        ui_path = Path(__file__).resolve().parent / "resources" / "main_window.ui"
        file = QFile(str(ui_path))
        if not file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")
        try:
            return QUiLoader().load(file)
        finally:
            file.close()

"""Main DailyTodo window."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QFile, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QFont, QPalette, QTextCharFormat
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.scheduler import DailyScheduler
from core.sync_manager import SyncManager, sync_error_message
from core.task_manager import Task, TaskManager
from lib.utils import APP_NAME, apply_theme, load_settings, setup_tray_icon
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.task_edit_dialog import TaskEditDialog


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(
        self,
        task_manager: TaskManager,
        scheduler: DailyScheduler,
        sync_manager: SyncManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.task_manager = task_manager
        self.scheduler = scheduler
        self.sync_manager = sync_manager
        self._allow_close = False
        self._refreshing = False
        self._right_button_drag_disabled = False
        self._selected_date = date.today().isoformat()
        self._available_dates: set[str] = set()
        self.refresh_action: QAction | None = None
        self.tray_icon = None

        self._ui = self._load_ui()
        self.date_label: QLabel = self._ui.findChild(QLabel, "dateLabel")
        self.task_list: QListWidget = self._ui.findChild(QListWidget, "taskListWidget")
        self.select_date_button: QPushButton = self._ui.findChild(QPushButton, "selectDateButton")
        self.today_button: QPushButton = self._ui.findChild(QPushButton, "todayButton")
        self.settings_button: QPushButton = self._ui.findChild(QPushButton, "settingsButton")

        self._install_loaded_ui()
        self._refresh_available_dates()
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
        QTimer.singleShot(1500, self._attempt_startup_sync)

    def refresh_today_view(self) -> None:
        self._select_date(date.today().isoformat())

    def refresh_current_view(self) -> None:
        self._refresh_available_dates()
        self._render_selected_date()

    def _select_date(self, date_str: str) -> None:
        self._refresh_available_dates()
        today = date.today().isoformat()
        if date_str > today or (date_str != today and date_str not in self._available_dates):
            return
        self._selected_date = date_str
        self._render_selected_date()

    def _render_selected_date(self) -> None:
        selected_date = self._selected_date
        is_history = selected_date != date.today().isoformat()
        self.date_label.setText(
            self.tr("历史记录：{date}").format(date=selected_date)
            if is_history
            else self.tr("今日：{date}").format(date=selected_date)
        )
        self.today_button.setVisible(is_history)
        self._sync_task_drag_mode()
        self._refreshing = True
        try:
            self.task_list.clear()
            tasks = sorted(
                self.task_manager.get_tasks_by_date(selected_date),
                key=lambda task: (task.is_completed, task.sort_order, task.id),
            )
            for task in tasks:
                self._add_task_item(task, read_only=is_history)
        except Exception as exc:
            self.logger.exception("Failed to refresh tasks for %s", selected_date)
            QMessageBox.critical(self, self.tr("刷新失败"), str(exc))
        finally:
            self._refreshing = False

    def show_from_tray(self) -> None:
        self.refresh_today_view()
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
        self.select_date_button.setText(self.tr("选择日期"))
        self.today_button.setText(self.tr("回到今日"))
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
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.viewport().installEventFilter(self)

    def _connect_signals(self) -> None:
        self.select_date_button.clicked.connect(self._open_date_picker)
        self.today_button.clicked.connect(self.refresh_today_view)
        self.settings_button.clicked.connect(self._open_settings)
        self.task_list.customContextMenuRequested.connect(self._open_task_context_menu)
        self.task_list.itemChanged.connect(self._task_item_changed)
        self.task_list.itemDoubleClicked.connect(self._edit_task)
        self.task_list.model().rowsMoved.connect(lambda *_: self._persist_task_order())
        self.scheduler.reset_finished.connect(self._on_scheduler_reset)
        self.scheduler.reset_failed.connect(self._on_scheduler_failed)

    def _create_actions(self) -> None:
        self.refresh_action = QAction(self.tr("刷新"), self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_view)
        self.addAction(self.refresh_action)

    def _open_task_context_menu(self, position: QPoint) -> None:
        item = self.task_list.itemAt(position)
        if item is not None:
            self.task_list.setCurrentItem(item)

        is_today = self._selected_date == date.today().isoformat()
        menu = QMenu(self.task_list)

        menu.addSeparator()
        refresh_action = menu.addAction(self.tr("刷新"))

        add_action = menu.addAction(self.tr("添加"))
        add_action.setEnabled(is_today)

        delete_action = menu.addAction(self.tr("删除"))
        delete_action.setEnabled(is_today and self.task_list.currentItem() is not None)

        selected_action = menu.exec(self.task_list.viewport().mapToGlobal(position))
        if selected_action == refresh_action:
            self.refresh_current_view()
        elif selected_action == add_action:
            self._add_task()
        elif selected_action == delete_action:
            self._delete_selected_task()

    def _add_task_item(self, task: Task, *, read_only: bool = False) -> None:
        item = QListWidgetItem(task.content)
        flags = item.flags()
        if read_only:
            flags &= ~Qt.ItemFlag.ItemIsEditable
            flags &= ~Qt.ItemFlag.ItemIsUserCheckable
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
            flags &= ~Qt.ItemFlag.ItemIsDropEnabled
        else:
            flags |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)
        item.setCheckState(Qt.CheckState.Checked if task.is_completed else Qt.CheckState.Unchecked)
        item.setData(Qt.ItemDataRole.UserRole, task.id)
        self._apply_task_item_style(item)
        self.task_list.addItem(item)

    def _add_task(self) -> None:
        if self._selected_date != date.today().isoformat():
            return
        dialog = TaskEditDialog(parent=self)
        if dialog.exec() != TaskEditDialog.DialogCode.Accepted:
            return
        try:
            self.task_manager.add_task(dialog.content, self._selected_date)
            self.refresh_today_view()
        except Exception as exc:
            self.logger.exception("Failed to add task")
            QMessageBox.critical(self, self.tr("添加失败"), str(exc))

    def _edit_task(self, item: QListWidgetItem) -> None:
        if self._selected_date != date.today().isoformat():
            return
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
        if self._selected_date != date.today().isoformat():
            return
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
        if self._refreshing or self._selected_date != date.today().isoformat():
            return
        task_id = int(item.data(Qt.ItemDataRole.UserRole))
        content = item.text()
        is_completed = item.checkState() == Qt.CheckState.Checked
        try:
            self.task_manager.update_task(
                task_id,
                content=content,
                is_completed=is_completed,
            )
            QTimer.singleShot(0, self._render_selected_date)
        except Exception as exc:
            self.logger.exception("Failed to update task item")
            QMessageBox.critical(self, self.tr("更新失败"), str(exc))
            self.refresh_today_view()

    def _persist_task_order(self) -> None:
        if self._refreshing or self._selected_date != date.today().isoformat():
            return
        ids = [
            int(self.task_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.task_list.count())
        ]
        try:
            self.task_manager.reorder_tasks(ids)
        except Exception:
            self.logger.exception("Failed to persist task order")

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if watched == self.task_list.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                self._right_button_drag_disabled = True
                self._sync_task_drag_mode()
            elif event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.RightButton:
                self._right_button_drag_disabled = True
                self._sync_task_drag_mode()
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
                self._right_button_drag_disabled = False
                self._sync_task_drag_mode()
        return super().eventFilter(watched, event)

    def _sync_task_drag_mode(self) -> None:
        can_drag = (
            self._selected_date == date.today().isoformat()
            and not self._right_button_drag_disabled
        )
        self.task_list.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
            if can_drag
            else QListWidget.DragDropMode.NoDragDrop
        )

    @staticmethod
    def _apply_task_item_style(item: QListWidgetItem) -> None:
        is_completed = item.checkState() == Qt.CheckState.Checked
        font = item.font()
        font.setStrikeOut(is_completed)
        item.setFont(font)
        item.setForeground(
            QBrush(QColor("#8a8a8a"))
            if is_completed
            else QApplication.palette().brush(QPalette.ColorRole.Text)
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self, sync_manager=self.sync_manager)
        dialog.settings_changed.connect(self._apply_settings)
        dialog.exec()
        self.refresh_current_view()

    def _apply_settings(self, settings) -> None:
        app = QApplication.instance()
        apply_theme(app, settings.get("theme", "system"))
        app.update_theme_signal(settings.get("theme", "system"))
        if app.change_language(settings.get("language", "zh_CN")):
            self.retranslate_ui()

    def _on_scheduler_reset(self, date_str: str, inserted: int) -> None:
        if date_str == date.today().isoformat():
            self._refresh_available_dates()
            self._select_date(date_str)
        if inserted > 0 and self.tray_icon is not None:
            self.tray_icon.showMessage(
                "DailyTodo",
                self.tr("已生成今日任务 {count} 项。").format(count=inserted),
            )

    def _on_scheduler_failed(self, message: str) -> None:
        self.logger.error("Scheduler reset failed: %s", message)

    def _attempt_startup_sync(self) -> None:
        if self.sync_manager is None:
            return
        sync = load_settings().get("sync", {})
        if not sync.get("refresh_token") or not sync.get("initialized"):
            return
        try:
            result = self.sync_manager.sync("normal")
            self.refresh_current_view()
            if result.conflicts and self.tray_icon is not None:
                self.tray_icon.showMessage(
                    "DailyTodo",
                    self.tr("同步完成，发现 {count} 个冲突。").format(count=len(result.conflicts)),
                )
        except Exception as exc:
            self.logger.info("Startup sync skipped or failed: %s", sync_error_message(exc))

    def _open_date_picker(self) -> None:
        self._refresh_available_dates()
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("选择日期"))
        layout = QVBoxLayout(dialog)

        calendar = QCalendarWidget(dialog)
        calendar.setGridVisible(True)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar.setMaximumDate(QDate.currentDate())
        calendar.setSelectedDate(QDate.fromString(self._selected_date, "yyyy-MM-dd"))
        self._mark_available_dates(calendar)
        layout.addWidget(calendar)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected = calendar.selectedDate().toString("yyyy-MM-dd")
        if selected == date.today().isoformat() or selected in self._available_dates:
            self._select_date(selected)

    def _refresh_available_dates(self) -> None:
        try:
            self._available_dates = self.task_manager.get_available_dates()
        except Exception:
            self.logger.exception("Failed to load available task dates")
            self._available_dates = {date.today().isoformat()}

    def _mark_available_dates(self, calendar: QCalendarWidget) -> None:
        marked_format = QTextCharFormat()
        marked_format.setFontWeight(QFont.Weight.Bold)
        for date_str in self._available_dates:
            qdate = QDate.fromString(date_str, "yyyy-MM-dd")
            if qdate.isValid():
                calendar.setDateTextFormat(qdate, marked_format)

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

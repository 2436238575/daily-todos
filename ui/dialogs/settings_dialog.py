"""Settings dialog including daily template editing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFile, QSignalBlocker, QTime, Signal
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
)

from core.database import test_postgresql_connection, validate_postgresql_url
from lib.utils import load_settings, save_settings, set_auto_start
from ui.dialogs.task_edit_dialog import TaskEditDialog


class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.settings = load_settings()
        self._loading = False
        self._ui = self._load_ui()

        self.theme_combo: QComboBox = self._ui.findChild(QComboBox, "themeComboBox")
        self.language_combo: QComboBox = self._ui.findChild(QComboBox, "languageComboBox")
        self.reset_time_edit: QTimeEdit = self._ui.findChild(QTimeEdit, "resetTimeEdit")
        self.auto_start_check: QCheckBox = self._ui.findChild(QCheckBox, "autoStartCheckBox")
        self.sqlite_sync_check: QCheckBox = self._ui.findChild(QCheckBox, "sqliteSyncCheckBox")
        self.postgresql_sync_url_edit: QLineEdit = self._ui.findChild(QLineEdit, "postgresqlSyncUrlLineEdit")
        self.test_sync_button: QPushButton = self._ui.findChild(QPushButton, "testPostgresqlSyncButton")
        self.template_list: QListWidget = self._ui.findChild(QListWidget, "templateListWidget")
        self.add_button: QPushButton = self._ui.findChild(QPushButton, "addTemplateButton")
        self.edit_button: QPushButton = self._ui.findChild(QPushButton, "editTemplateButton")
        self.remove_button: QPushButton = self._ui.findChild(QPushButton, "removeTemplateButton")
        self.apply_button: QPushButton = self._ui.findChild(QPushButton, "applyTemplateButton")
        self.button_box: QDialogButtonBox = self._ui.findChild(QDialogButtonBox, "buttonBox")

        self._configure_widgets()
        self._load_settings_into_ui()
        self._connect_signals()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._ui)
        self.setWindowTitle(self._ui.windowTitle())
        self.resize(self._ui.size())

    def _configure_widgets(self) -> None:
        self.theme_combo.addItem(self.tr("跟随系统"), "system")
        self.theme_combo.addItem(self.tr("浅色"), "light")
        self.theme_combo.addItem(self.tr("深色"), "dark")
        self.language_combo.addItem("简体中文", "zh_CN")
        self.language_combo.addItem("English", "en_US")
        self.template_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.apply_button.setEnabled(False)

    def _load_settings_into_ui(self) -> None:
        self._loading = True
        try:
            with (
                QSignalBlocker(self.theme_combo),
                QSignalBlocker(self.language_combo),
                QSignalBlocker(self.reset_time_edit),
                QSignalBlocker(self.auto_start_check),
                QSignalBlocker(self.sqlite_sync_check),
                QSignalBlocker(self.postgresql_sync_url_edit),
                QSignalBlocker(self.template_list),
            ):
                self.theme_combo.setCurrentIndex(
                    max(0, self.theme_combo.findData(self.settings.get("theme", "system")))
                )
                self.language_combo.setCurrentIndex(
                    max(0, self.language_combo.findData(self.settings.get("language", "zh_CN")))
                )
                time = QTime.fromString(str(self.settings.get("reset_time", "03:00")), "HH:mm")
                self.reset_time_edit.setTime(time if time.isValid() else QTime(3, 0))
                self.auto_start_check.setChecked(bool(self.settings.get("auto_start", False)))
                self.sqlite_sync_check.setChecked(bool(self.settings.get("sqlite_sync", False)))
                self.postgresql_sync_url_edit.setText(str(self.settings.get("postgresql_sync_url", "")))
                self._reload_template_list(self.settings.get("daily_template", []))
        finally:
            self._loading = False

    def _connect_signals(self) -> None:
        self.theme_combo.currentIndexChanged.connect(self._save_general_settings)
        self.language_combo.currentIndexChanged.connect(self._save_general_settings)
        self.reset_time_edit.timeChanged.connect(self._save_general_settings)
        self.auto_start_check.toggled.connect(self._save_general_settings)
        self.sqlite_sync_check.toggled.connect(self._sync_settings_changed)
        self.postgresql_sync_url_edit.textChanged.connect(self._sync_settings_changed)
        self.test_sync_button.clicked.connect(self._test_and_save_sync_settings)
        self.add_button.clicked.connect(self._add_template_item)
        self.edit_button.clicked.connect(self._edit_template_item)
        self.remove_button.clicked.connect(self._remove_template_item)
        self.apply_button.clicked.connect(self._apply_template)
        self.template_list.itemDoubleClicked.connect(lambda _: self._edit_template_item())
        self.template_list.model().rowsMoved.connect(lambda *_: self._set_template_dirty(True))
        self.button_box.rejected.connect(self.reject)

    def _reload_template_list(self, template: list[dict[str, Any]]) -> None:
        self.template_list.clear()
        for item in sorted(template, key=lambda value: int(value.get("sort_order", 0))):
            content = str(item.get("content", "")).strip()
            if content:
                self.template_list.addItem(content)

    def _add_template_item(self) -> None:
        dialog = TaskEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.template_list.addItem(dialog.content)
            self._set_template_dirty(True)

    def _edit_template_item(self) -> None:
        current = self.template_list.currentItem()
        if current is None:
            return
        dialog = TaskEditDialog(current.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            current.setText(dialog.content)
            self._set_template_dirty(True)

    def _remove_template_item(self) -> None:
        current_row = self.template_list.currentRow()
        if current_row >= 0:
            self.template_list.takeItem(current_row)
            self._set_template_dirty(True)

    def _collect_template(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index in range(self.template_list.count()):
            item: QListWidgetItem = self.template_list.item(index)
            content = item.text().strip()
            if content:
                result.append({"content": content, "sort_order": index})
        return result

    def _save_general_settings(self) -> None:
        if self._loading:
            return
        previous_auto_start = bool(self.settings.get("auto_start", False))
        self.settings.update(
            {
                "theme": self.theme_combo.currentData(),
                "language": self.language_combo.currentData(),
                "reset_time": self.reset_time_edit.time().toString("HH:mm"),
                "auto_start": self.auto_start_check.isChecked(),
            }
        )

        try:
            save_settings(self.settings)
            if previous_auto_start != self.settings["auto_start"]:
                set_auto_start(bool(self.settings["auto_start"]))
        except Exception as exc:
            self.logger.exception("Failed to save settings")
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self.settings_changed.emit(dict(self.settings))

    def _sync_settings_changed(self) -> None:
        if self._loading:
            return
        saved_enabled = bool(self.settings.get("sqlite_sync", False))
        saved_url = str(self.settings.get("postgresql_sync_url", ""))
        current_enabled = self.sqlite_sync_check.isChecked()
        current_url = self.postgresql_sync_url_edit.text().strip()
        if current_enabled == saved_enabled and current_url == saved_url:
            return
        self.test_sync_button.setEnabled(True)

    def _test_and_save_sync_settings(self) -> None:
        enabled = self.sqlite_sync_check.isChecked()
        url = self.postgresql_sync_url_edit.text().strip()

        if not enabled:
            self.settings.update({"sqlite_sync": False, "postgresql_sync_url": ""})
            try:
                save_settings(self.settings)
            except Exception as exc:
                self.logger.exception("Failed to save sync settings")
                QMessageBox.critical(self, self.tr("保存失败"), str(exc))
                return
            self.settings_changed.emit(dict(self.settings))
            QMessageBox.information(self, self.tr("提示"), self.tr("SQLite-Sync 已关闭。"))
            return

        validation = validate_postgresql_url(url)
        if not validation.ok:
            QMessageBox.warning(self, self.tr("测试失败"), validation.message)
            return

        self.test_sync_button.setEnabled(False)
        try:
            result = test_postgresql_connection(url)
        finally:
            self.test_sync_button.setEnabled(True)

        if not result.ok:
            QMessageBox.warning(self, self.tr("测试失败"), result.message)
            return

        self.settings.update({"sqlite_sync": True, "postgresql_sync_url": url})
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.logger.exception("Failed to save sync settings")
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self.settings_changed.emit(dict(self.settings))
        QMessageBox.information(self, self.tr("测试通过"), result.message)

    def _apply_template(self) -> None:
        self.settings["daily_template"] = self._collect_template()
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.logger.exception("Failed to save template")
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._set_template_dirty(False)
        self.settings_changed.emit(dict(self.settings))
        QMessageBox.information(self, self.tr("提示"), self.tr("母本修改将在下次重置时生效。"))

    def _set_template_dirty(self, dirty: bool) -> None:
        self.apply_button.setEnabled(dirty)

    @staticmethod
    def _load_ui():
        ui_path = Path(__file__).resolve().parents[1] / "resources" / "dialogs" / "settings_dialog.ui"
        file = QFile(str(ui_path))
        if not file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")
        try:
            return QUiLoader().load(file)
        finally:
            file.close()

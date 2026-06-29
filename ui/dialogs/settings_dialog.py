"""Settings dialog including daily template editing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFile, QTime
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
)

from lib.utils import load_settings, save_settings, set_auto_start
from ui.dialogs.task_edit_dialog import TaskEditDialog


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.settings = load_settings()
        self._ui = self._load_ui()

        self.theme_combo: QComboBox = self._ui.findChild(QComboBox, "themeComboBox")
        self.language_combo: QComboBox = self._ui.findChild(QComboBox, "languageComboBox")
        self.reset_time_edit: QTimeEdit = self._ui.findChild(QTimeEdit, "resetTimeEdit")
        self.auto_start_check: QCheckBox = self._ui.findChild(QCheckBox, "autoStartCheckBox")
        self.template_list: QListWidget = self._ui.findChild(QListWidget, "templateListWidget")
        self.add_button: QPushButton = self._ui.findChild(QPushButton, "addTemplateButton")
        self.edit_button: QPushButton = self._ui.findChild(QPushButton, "editTemplateButton")
        self.remove_button: QPushButton = self._ui.findChild(QPushButton, "removeTemplateButton")
        self.button_box: QDialogButtonBox = self._ui.findChild(QDialogButtonBox, "buttonBox")

        self._configure_widgets()
        self._load_settings_into_ui()
        self._connect_signals()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._ui)
        self.setWindowTitle(self._ui.windowTitle())
        self.resize(self._ui.size())

    def saved_settings(self) -> dict[str, Any]:
        return self.settings

    def _configure_widgets(self) -> None:
        self.theme_combo.addItem(self.tr("跟随系统"), "system")
        self.theme_combo.addItem(self.tr("浅色"), "light")
        self.theme_combo.addItem(self.tr("深色"), "dark")
        self.language_combo.addItem("简体中文", "zh_CN")
        self.language_combo.addItem("English", "en_US")
        self.template_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)

    def _load_settings_into_ui(self) -> None:
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.settings.get("theme", "system")))
        )
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(self.settings.get("language", "zh_CN")))
        )
        time = QTime.fromString(str(self.settings.get("reset_time", "03:00")), "HH:mm")
        self.reset_time_edit.setTime(time if time.isValid() else QTime(3, 0))
        self.auto_start_check.setChecked(bool(self.settings.get("auto_start", False)))
        self._reload_template_list(self.settings.get("daily_template", []))

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self._add_template_item)
        self.edit_button.clicked.connect(self._edit_template_item)
        self.remove_button.clicked.connect(self._remove_template_item)
        self.template_list.itemDoubleClicked.connect(lambda _: self._edit_template_item())
        self.button_box.accepted.connect(self._save_and_accept)
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

    def _edit_template_item(self) -> None:
        current = self.template_list.currentItem()
        if current is None:
            return
        dialog = TaskEditDialog(current.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            current.setText(dialog.content)

    def _remove_template_item(self) -> None:
        current_row = self.template_list.currentRow()
        if current_row >= 0:
            self.template_list.takeItem(current_row)

    def _collect_template(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index in range(self.template_list.count()):
            item: QListWidgetItem = self.template_list.item(index)
            content = item.text().strip()
            if content:
                result.append({"content": content, "sort_order": index})
        return result

    def _save_and_accept(self) -> None:
        previous_auto_start = bool(self.settings.get("auto_start", False))
        self.settings.update(
            {
                "theme": self.theme_combo.currentData(),
                "language": self.language_combo.currentData(),
                "reset_time": self.reset_time_edit.time().toString("HH:mm"),
                "auto_start": self.auto_start_check.isChecked(),
                "daily_template": self._collect_template(),
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

        QMessageBox.information(self, self.tr("提示"), self.tr("母本修改将在下次重置时生效。"))
        self.accept()

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


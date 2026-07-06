"""Settings dialog including daily template editing."""

from __future__ import annotations

import logging
import uuid
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFile, QSignalBlocker, Qt, QTime, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
)

from core.sync_manager import SyncManager, SyncResult, sync_error_message
from lib.utils import load_settings, save_settings, set_auto_start
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.conflict_dialog import ConflictDialog
from ui.dialogs.task_edit_dialog import TaskEditDialog


ADDITION_COLOR = "#22863a"
DELETION_COLOR = "#cb2431"


def _parse_diff_summary(summary: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for part in summary.split():
        if part.startswith("+"):
            additions = _parse_count(part[1:])
        elif part.startswith("-"):
            deletions = _parse_count(part[1:])
    return additions, deletions


def _parse_count(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, parent=None, sync_manager: SyncManager | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.sync_manager = sync_manager
        self.settings = load_settings()
        self._loading = False
        self._deleted_template_items: list[dict[str, Any]] = []
        self._ui = self._load_ui()

        self.theme_combo: QComboBox = self._ui.findChild(QComboBox, "themeComboBox")
        self.language_combo: QComboBox = self._ui.findChild(QComboBox, "languageComboBox")
        self.reset_time_edit: QTimeEdit = self._ui.findChild(QTimeEdit, "resetTimeEdit")
        self.auto_start_check: QCheckBox = self._ui.findChild(QCheckBox, "autoStartCheckBox")
        self.server_url_edit: QLineEdit = self._ui.findChild(QLineEdit, "syncServerUrlLineEdit")
        self.username_edit: QLineEdit = self._ui.findChild(QLineEdit, "syncUsernameLineEdit")
        self.password_edit: QLineEdit = self._ui.findChild(QLineEdit, "syncPasswordLineEdit")
        self.sync_status_label: QLabel = self._ui.findChild(QLabel, "syncStatusValueLabel")
        self.login_button: QPushButton = self._ui.findChild(QPushButton, "syncLoginButton")
        self.logout_button: QPushButton = self._ui.findChild(QPushButton, "syncLogoutButton")
        self.sync_now_button: QPushButton = self._ui.findChild(QPushButton, "syncNowButton")
        self.conflicts_button: QPushButton = self._ui.findChild(QPushButton, "syncConflictsButton")
        self.template_list: QListWidget = self._ui.findChild(QListWidget, "templateListWidget")
        self.add_button: QPushButton = self._ui.findChild(QPushButton, "addTemplateButton")
        self.edit_button: QPushButton = self._ui.findChild(QPushButton, "editTemplateButton")
        self.remove_button: QPushButton = self._ui.findChild(QPushButton, "removeTemplateButton")
        self.apply_button: QPushButton = self._ui.findChild(QPushButton, "applyTemplateButton")
        self.about_button: QPushButton = self._ui.findChild(QPushButton, "aboutButton")
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
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.apply_button.setEnabled(False)
        self._update_sync_controls()

    def _load_settings_into_ui(self) -> None:
        self._loading = True
        try:
            with (
                QSignalBlocker(self.theme_combo),
                QSignalBlocker(self.language_combo),
                QSignalBlocker(self.reset_time_edit),
                QSignalBlocker(self.auto_start_check),
                QSignalBlocker(self.server_url_edit),
                QSignalBlocker(self.username_edit),
                QSignalBlocker(self.password_edit),
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
                sync = self.settings.get("sync", {})
                self.server_url_edit.setText(str(sync.get("server_url", "")))
                self.username_edit.setText(str(sync.get("username", "")))
                self.password_edit.clear()
                self._reload_template_list(self.settings.get("daily_template", []))
                self._update_sync_status()
        finally:
            self._loading = False

    def _connect_signals(self) -> None:
        self.theme_combo.currentIndexChanged.connect(self._save_general_settings)
        self.language_combo.currentIndexChanged.connect(self._save_general_settings)
        self.reset_time_edit.timeChanged.connect(self._save_general_settings)
        self.auto_start_check.toggled.connect(self._save_general_settings)
        self.add_button.clicked.connect(self._add_template_item)
        self.edit_button.clicked.connect(self._edit_template_item)
        self.remove_button.clicked.connect(self._remove_template_item)
        self.apply_button.clicked.connect(self._apply_template)
        self.template_list.itemDoubleClicked.connect(lambda _: self._edit_template_item())
        self.template_list.model().rowsMoved.connect(lambda *_: self._set_template_dirty(True))
        self.login_button.clicked.connect(self._login_sync)
        self.logout_button.clicked.connect(self._logout_sync)
        self.sync_now_button.clicked.connect(self._run_manual_sync)
        self.conflicts_button.clicked.connect(self._open_conflicts)
        self.about_button.clicked.connect(self._open_about)
        self.button_box.rejected.connect(self.reject)

    def _reload_template_list(self, template: list[dict[str, Any]]) -> None:
        self.template_list.clear()
        self._deleted_template_items = [dict(item) for item in template if bool(item.get("deleted", False))]
        for item in sorted(template, key=lambda value: int(value.get("sort_order", 0))):
            content = str(item.get("content", "")).strip()
            if content and not bool(item.get("deleted", False)):
                list_item = QListWidgetItem(content)
                list_item.setData(Qt.ItemDataRole.UserRole, dict(item))
                self.template_list.addItem(list_item)

    def _add_template_item(self) -> None:
        dialog = TaskEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item = QListWidgetItem(dialog.content)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "uid": str(uuid.uuid4()),
                    "content": dialog.content,
                    "sort_order": self.template_list.count(),
                    "base_version": 0,
                    "deleted": False,
                    "sync_dirty": True,
                },
            )
            self.template_list.addItem(item)
            self._set_template_dirty(True)

    def _edit_template_item(self) -> None:
        current = self.template_list.currentItem()
        if current is None:
            return
        dialog = TaskEditDialog(current.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            meta = self._template_meta(current)
            if dialog.content != meta.get("content"):
                meta["sync_dirty"] = True
            meta["content"] = dialog.content
            current.setData(Qt.ItemDataRole.UserRole, meta)
            current.setText(dialog.content)
            self._set_template_dirty(True)

    def _remove_template_item(self) -> None:
        current_row = self.template_list.currentRow()
        if current_row >= 0:
            item = self.template_list.takeItem(current_row)
            if item is not None:
                meta = self._template_meta(item)
                if int(meta.get("base_version", 0)) > 0 or not bool(meta.get("sync_dirty", True)):
                    meta.update({"deleted": True, "sync_dirty": True})
                    self._deleted_template_items.append(meta)
            self._set_template_dirty(True)

    def _collect_template(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index in range(self.template_list.count()):
            item: QListWidgetItem = self.template_list.item(index)
            content = item.text().strip()
            if content:
                meta = self._template_meta(item)
                dirty = (
                    bool(meta.get("sync_dirty", True))
                    or content != str(meta.get("content", ""))
                    or index != int(meta.get("sort_order", index))
                )
                result.append(
                    {
                        "uid": str(meta.get("uid") or uuid.uuid4()),
                        "content": content,
                        "sort_order": index,
                        "base_version": int(meta.get("base_version", 0)),
                        "deleted": False,
                        "sync_dirty": dirty,
                    }
                )
        result.extend(dict(item) for item in self._deleted_template_items)
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

        self.logger.info(
            "General settings saved: theme=%s, language=%s, reset_time=%s, auto_start=%s",
            self.settings["theme"],
            self.settings["language"],
            self.settings["reset_time"],
            self.settings["auto_start"],
        )
        self.settings_changed.emit(dict(self.settings))

    def _apply_template(self) -> None:
        self.settings["daily_template"] = self._collect_template()
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.logger.exception("Failed to save template")
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self.settings = load_settings()
        self._reload_template_list(self.settings.get("daily_template", []))
        self._set_template_dirty(False)
        visible_count = len([item for item in self.settings.get("daily_template", []) if not bool(item.get("deleted", False))])
        deleted_count = len([item for item in self.settings.get("daily_template", []) if bool(item.get("deleted", False))])
        self.logger.info("Template saved: visible=%s, deleted=%s", visible_count, deleted_count)
        self.settings_changed.emit(dict(self.settings))
        QMessageBox.information(self, self.tr("提示"), self.tr("母本修改将在下次重置时生效。"))

    def _set_template_dirty(self, dirty: bool) -> None:
        self.apply_button.setEnabled(dirty)

    def _save_sync_inputs(self) -> None:
        self.settings["sync"]["server_url"] = self.server_url_edit.text().strip()
        self.settings["sync"]["username"] = self.username_edit.text().strip()
        save_settings(self.settings)
        self.settings = load_settings()
        self.logger.info(
            "Sync inputs saved: server_url_len=%s, username_len=%s",
            len(str(self.settings["sync"].get("server_url", ""))),
            len(str(self.settings["sync"].get("username", ""))),
        )

    def _login_sync(self) -> None:
        if self.sync_manager is None:
            return
        try:
            self.logger.info(
                "Sync login requested from settings: server_url_len=%s, username_len=%s",
                len(self.server_url_edit.text().strip()),
                len(self.username_edit.text().strip()),
            )
            result = self.sync_manager.login(
                self.server_url_edit.text(),
                self.username_edit.text(),
                self.password_edit.text(),
            )
            self.settings = load_settings()
            self.password_edit.clear()
            self._update_sync_status(result.message)
            self._update_sync_controls()
            self.settings_changed.emit(dict(self.settings))
            self.logger.info("Sync login succeeded from settings")
        except Exception as exc:
            self.logger.exception("Sync login failed")
            QMessageBox.critical(self, self.tr("登录失败"), sync_error_message(exc))

    def _logout_sync(self) -> None:
        if self.sync_manager is None:
            return
        try:
            self.logger.info("Sync logout requested from settings")
            result = self.sync_manager.logout()
            self.settings = load_settings()
            self._update_sync_status(result.message)
            self._update_sync_controls()
            self.settings_changed.emit(dict(self.settings))
            self.logger.info("Sync logout succeeded from settings")
        except Exception as exc:
            self.logger.exception("Sync logout failed")
            QMessageBox.critical(self, self.tr("退出失败"), sync_error_message(exc))

    def _run_manual_sync(self) -> None:
        if self.sync_manager is None:
            return
        try:
            self._save_sync_inputs()
            mode = "normal"
            if not bool(self.settings.get("sync", {}).get("initialized", False)):
                selected = self._choose_initial_sync_mode()
                if selected is None:
                    self.logger.info("Manual sync canceled before initial mode selection")
                    return
                mode = selected
            self.logger.info("Manual sync requested from settings: mode=%s", mode)
            result = self.sync_manager.sync(mode)
            self.settings = load_settings()
            self._update_sync_status(result.message.splitlines()[0])
            self._update_sync_controls()
            self.settings_changed.emit(dict(self.settings))
            self.logger.info("Manual sync succeeded from settings: conflicts=%s", len(result.conflicts))
            if result.conflicts:
                self._show_sync_result(self.tr("同步冲突"), result)
                self._open_conflicts()
            else:
                self._show_sync_result(self.tr("同步完成"), result)
        except Exception as exc:
            self.logger.exception("Manual sync failed")
            self._update_sync_status(self.tr("同步失败"))
            QMessageBox.critical(self, self.tr("同步失败"), sync_error_message(exc))

    def _show_sync_result(self, title: str, result: SyncResult) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        message = QLabel(dialog)
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setText(self._sync_result_html(result))
        layout.addWidget(message)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        diff_button = QPushButton(self.tr("Diff"), dialog)
        ok_button = QPushButton(self.tr("OK"), dialog)
        ok_button.setDefault(True)
        button_layout.addWidget(diff_button)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

        diff_button.clicked.connect(lambda: self._show_sync_diff(result.diff_lines))
        ok_button.clicked.connect(dialog.accept)
        dialog.exec()

    def _show_sync_diff(self, lines: list[str]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("同步 Diff"))
        layout = QVBoxLayout(dialog)

        diff_view = QTextEdit(dialog)
        diff_view.setReadOnly(True)
        diff_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        diff_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        diff_view.setHtml(self._sync_diff_html(lines))
        layout.addWidget(diff_view)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.resize(640, 360)
        dialog.exec()

    def _sync_result_html(self, result: SyncResult) -> str:
        lines = result.message.splitlines()
        header = escape(lines[0] if lines else self.tr("同步完成"))
        summary = lines[1] if len(lines) > 1 else "+0 -0"
        additions, deletions = _parse_diff_summary(summary)
        return (
            f"<p>{header}</p>"
            f"<p style='font-family: monospace; font-size: 18px;'>"
            f"<span style='color: {ADDITION_COLOR}; font-weight: 600;'>+{additions}</span>"
            f"&nbsp;&nbsp;"
            f"<span style='color: {DELETION_COLOR}; font-weight: 600;'>-{deletions}</span>"
            f"</p>"
        )

    def _sync_diff_html(self, lines: list[str]) -> str:
        if not lines:
            return f"<pre>{escape(self.tr('没有变更。'))}</pre>"
        html_lines = []
        for line in lines:
            color = ADDITION_COLOR if line.startswith("+") else DELETION_COLOR if line.startswith("-") else "inherit"
            html_lines.append(f"<span style='color: {color};'>{escape(line)}</span>")
        return (
            "<pre style='font-family: monospace; white-space: pre; margin: 0;'>"
            + "<br>".join(html_lines)
            + "</pre>"
        )

    def _open_conflicts(self) -> None:
        if self.sync_manager is None:
            return
        conflicts = list(self.sync_manager.last_conflicts)
        if not conflicts:
            QMessageBox.information(self, self.tr("同步冲突"), self.tr("当前没有待处理冲突。"))
            self._update_sync_controls()
            self.logger.info("Conflict dialog skipped: no conflicts")
            return
        dialog = ConflictDialog(conflicts, self)
        dialog.exec()
        if not dialog.resolutions:
            self.logger.info("Conflict dialog closed without resolutions: conflicts=%s", len(conflicts))
            return
        try:
            self.logger.info("Conflict resolution requested from settings: count=%s", len(dialog.resolutions))
            result = self.sync_manager.resolve_conflicts(dialog.resolutions)
            self.settings = load_settings()
            self._update_sync_status(result.message)
            self._update_sync_controls()
            self.settings_changed.emit(dict(self.settings))
            self.logger.info("Conflict resolution succeeded from settings: remaining=%s", len(result.conflicts))
            QMessageBox.information(self, self.tr("同步冲突"), result.message)
        except Exception as exc:
            self.logger.exception("Conflict resolution failed")
            QMessageBox.critical(self, self.tr("冲突处理失败"), sync_error_message(exc))

    def _choose_initial_sync_mode(self) -> str | None:
        message = QMessageBox(self)
        message.setWindowTitle(self.tr("首次同步"))
        message.setText(self.tr("请选择首次同步方式。"))
        upload_button = message.addButton(self.tr("上传本机"), QMessageBox.ButtonRole.AcceptRole)
        download_button = message.addButton(self.tr("下载云端"), QMessageBox.ButtonRole.DestructiveRole)
        merge_button = message.addButton(self.tr("合并两边"), QMessageBox.ButtonRole.AcceptRole)
        message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()
        clicked = message.clickedButton()
        if clicked == upload_button:
            return "upload"
        if clicked == download_button:
            return "download"
        if clicked == merge_button:
            return "merge"
        return None

    def _update_sync_controls(self) -> None:
        available = self.sync_manager is not None
        logged_in = bool(self.settings.get("sync", {}).get("refresh_token", ""))
        for widget in (
            self.server_url_edit,
            self.username_edit,
            self.password_edit,
            self.login_button,
            self.logout_button,
            self.sync_now_button,
            self.conflicts_button,
        ):
            widget.setEnabled(available)
        self.logout_button.setEnabled(available and logged_in)
        self.sync_now_button.setEnabled(available and logged_in)
        self.conflicts_button.setEnabled(available and bool(getattr(self.sync_manager, "last_conflicts", [])))

    def _update_sync_status(self, message: str | None = None) -> None:
        sync = self.settings.get("sync", {})
        if message:
            self.sync_status_label.setText(message)
            return
        if not sync.get("refresh_token"):
            self.sync_status_label.setText(self.tr("未登录"))
            return
        last_sync = str(sync.get("last_sync_at", ""))
        initialized = bool(sync.get("initialized", False))
        if last_sync:
            self.sync_status_label.setText(self.tr("已登录，上次同步：{time}").format(time=last_sync))
        elif initialized:
            self.sync_status_label.setText(self.tr("已登录"))
        else:
            self.sync_status_label.setText(self.tr("已登录，尚未首次同步"))

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    @staticmethod
    def _template_meta(item: QListWidgetItem) -> dict[str, Any]:
        data = item.data(Qt.ItemDataRole.UserRole)
        return dict(data) if isinstance(data, dict) else {}

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

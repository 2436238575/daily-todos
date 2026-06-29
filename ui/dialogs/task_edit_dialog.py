"""Dialog for creating or editing one task/template item."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QMessageBox, QVBoxLayout


class TaskEditDialog(QDialog):
    def __init__(self, content: str = "", parent=None) -> None:
        super().__init__(parent)
        self._ui = self._load_ui()
        self.content_line_edit: QLineEdit = self._ui.findChild(QLineEdit, "contentLineEdit")
        self.button_box: QDialogButtonBox = self._ui.findChild(QDialogButtonBox, "buttonBox")

        self.content_line_edit.setText(content)
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._ui)
        self.setWindowTitle(self._ui.windowTitle())
        self.resize(self._ui.size())

    @property
    def content(self) -> str:
        return self.content_line_edit.text().strip()

    def _validate_and_accept(self) -> None:
        if not self.content:
            QMessageBox.warning(self, self.tr("提示"), self.tr("任务内容不能为空。"))
            self.content_line_edit.setFocus()
            return
        self.accept()

    @staticmethod
    def _load_ui():
        ui_path = Path(__file__).resolve().parents[1] / "resources" / "dialogs" / "task_edit_dialog.ui"
        file = QFile(str(ui_path))
        if not file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")
        try:
            return QUiLoader().load(file)
        finally:
            file.close()


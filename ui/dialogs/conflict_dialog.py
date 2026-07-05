"""Conflict resolution dialog for sync conflicts."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)


class ConflictDialog(QDialog):
    def __init__(self, conflicts: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("同步冲突"))
        self.conflicts = conflicts
        self.resolutions: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget(self)
        for conflict in conflicts:
            self.list_widget.addItem(self._conflict_title(conflict))
        layout.addWidget(self.list_widget)

        details_layout = QHBoxLayout()
        self.local_text = QTextEdit(self)
        self.local_text.setReadOnly(True)
        self.remote_text = QTextEdit(self)
        self.remote_text.setReadOnly(True)
        details_layout.addWidget(self._labeled_text(self.tr("本地版本"), self.local_text))
        details_layout.addWidget(self._labeled_text(self.tr("服务端版本"), self.remote_text))
        layout.addLayout(details_layout)

        action_layout = QHBoxLayout()
        self.local_button = QPushButton(self.tr("使用本地版本"), self)
        self.remote_button = QPushButton(self.tr("使用服务端版本"), self)
        action_layout.addWidget(self.local_button)
        action_layout.addWidget(self.remote_button)
        layout.addLayout(action_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.list_widget.currentRowChanged.connect(self._show_conflict)
        self.local_button.clicked.connect(lambda: self._resolve_current("local"))
        self.remote_button.clicked.connect(lambda: self._resolve_current("remote"))
        if conflicts:
            self.list_widget.setCurrentRow(0)

    def _resolve_current(self, choice: str) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        conflict = self.conflicts.pop(row)
        self.resolutions.append({"conflict_id": conflict["id"], "choice": choice})
        self.list_widget.takeItem(row)
        if not self.conflicts:
            self.accept()
            return
        self.list_widget.setCurrentRow(min(row, len(self.conflicts) - 1))

    def _show_conflict(self, row: int) -> None:
        if row < 0 or row >= len(self.conflicts):
            self.local_text.clear()
            self.remote_text.clear()
            return
        conflict = self.conflicts[row]
        self.local_text.setPlainText(self._format_payload(conflict.get("client_payload", {})))
        self.remote_text.setPlainText(self._format_payload(conflict.get("server_payload", {})))

    @staticmethod
    def _labeled_text(label: str, widget: QTextEdit):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label, container))
        layout.addWidget(widget)
        return container

    @staticmethod
    def _format_payload(payload: dict[str, Any]) -> str:
        lines = []
        for key in ("content", "target_date", "completed", "sort_order", "deleted", "version"):
            if key in payload:
                lines.append(f"{key}: {payload[key]}")
        return "\n".join(lines) if lines else str(payload)

    @staticmethod
    def _conflict_title(conflict: dict[str, Any]) -> str:
        payload = conflict.get("client_payload", {})
        content = payload.get("content") or conflict.get("entity_id")
        return f"{conflict.get('entity_type', '')}: {content}"

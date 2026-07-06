"""About dialog for build and project metadata."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from lib.logging_utils import load_build_info
from lib.utils import APP_NAME, BASE_DIR


PROJECT_REPOSITORY = "https://github.com/2436238575/daily-todos"


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("关于"))

        build_info = load_build_info(BASE_DIR)
        build_type = "release" if build_info.env == "Production" else "dev"

        title_label = QLabel(APP_NAME, self)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setObjectName("aboutTitleLabel")

        form_layout = QFormLayout()
        form_layout.addRow(self.tr("构建类型"), self._value_label(build_type))
        form_layout.addRow(self.tr("版本号"), self._value_label(build_info.version))
        form_layout.addRow(self.tr("项目仓库"), self._value_label(PROJECT_REPOSITORY))

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title_label)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.resize(360, self.sizeHint().height())

    def _value_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        return label

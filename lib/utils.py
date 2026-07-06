"""Application utilities: settings, logging, styles, and OS integration."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from lib.logging_utils import configure_logging


APP_NAME = "DailyTodo"
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
STYLE_PATH = CONFIG_DIR / "style.qss"

DEFAULT_SETTINGS: dict[str, Any] = {
    "reset_time": "03:00",
    "auto_start": False,
    "theme": "system",
    "language": "zh_CN",
    "sync": {
        "server_url": "",
        "username": "",
        "refresh_token": "",
        "last_server_version": 0,
        "initialized": False,
        "last_sync_at": "",
    },
    "daily_template": [
        {"content": "晨会复盘", "sort_order": 0},
        {"content": "核心功能开发", "sort_order": 1},
        {"content": "代码审查", "sort_order": 2},
    ],
}
DEPRECATED_SETTINGS_KEYS = {"sqlite_sync", "postgresql_sync_url"}

DEFAULT_QSS = """
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: palette(window);
}
QPushButton {
    min-height: 28px;
    padding: 4px 10px;
}
QListWidget {
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 4px;
}
QListWidget::item {
    min-height: 32px;
    padding: 4px;
}
QLineEdit, QComboBox, QTimeEdit {
    min-height: 28px;
    padding: 2px 6px;
}
"""


def ensure_runtime_dirs() -> None:
    for path in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not STYLE_PATH.exists():
        STYLE_PATH.write_text(DEFAULT_QSS.strip() + "\n", encoding="utf-8")


def setup_logging() -> None:
    ensure_runtime_dirs()
    configure_logging(LOG_DIR / "gui.log")


def load_settings() -> dict[str, Any]:
    ensure_runtime_dirs()
    if not SETTINGS_PATH.exists():
        settings = deepcopy(DEFAULT_SETTINGS)
        save_settings(settings)
        return settings

    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("settings root must be an object")
    except (OSError, json.JSONDecodeError, ValueError):
        logging.getLogger(__name__).exception("Settings are invalid; falling back to defaults")
        backup_path = SETTINGS_PATH.with_suffix(".invalid.json")
        try:
            SETTINGS_PATH.replace(backup_path)
        except OSError:
            logging.getLogger(__name__).exception("Failed to back up invalid settings")
        settings = deepcopy(DEFAULT_SETTINGS)
        save_settings(settings)
        return settings

    settings = deepcopy(DEFAULT_SETTINGS)
    settings.update(loaded)
    for key in DEPRECATED_SETTINGS_KEYS:
        settings.pop(key, None)
    settings["sync"] = _normalize_sync_settings(settings.get("sync", {}))
    settings["daily_template"] = _normalize_template(settings.get("daily_template", []))
    save_settings(settings)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update(settings)
    for key in DEPRECATED_SETTINGS_KEYS:
        merged.pop(key, None)
    merged["sync"] = _normalize_sync_settings(merged.get("sync", {}))
    merged["daily_template"] = _normalize_template(merged.get("daily_template", []))
    SETTINGS_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def apply_theme(app: QGuiApplication, theme: str) -> None:
    """Apply a palette and the shared QSS file."""

    effective = theme
    if theme == "system":
        scheme = app.styleHints().colorScheme()
        effective = "dark" if scheme == Qt.ColorScheme.Dark else "light"

    app.setPalette(_dark_palette() if effective == "dark" else QPalette())
    try:
        app.setStyleSheet(STYLE_PATH.read_text(encoding="utf-8"))
    except OSError:
        logging.getLogger(__name__).exception("Failed to load style sheet")


def create_app_icon() -> QIcon:
    """Create a non-empty application icon for windows and system tray use."""

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = max(2, size // 10)
        radius = max(3, size // 7)
        rect = pixmap.rect().adjusted(margin, margin, -margin, -margin)

        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(QPen(QColor("#ffffff"), max(2, size // 12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x1 = int(size * 0.30)
        y1 = int(size * 0.52)
        x2 = int(size * 0.44)
        y2 = int(size * 0.66)
        x3 = int(size * 0.72)
        y3 = int(size * 0.36)
        painter.drawLine(x1, y1, x2, y2)
        painter.drawLine(x2, y2, x3, y3)
        painter.end()

        icon.addPixmap(pixmap)
    return icon


def setup_tray_icon(
    parent,
    show_callback,
    quit_callback,
    overview_callback=None,
) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logging.getLogger(__name__).warning("System tray is not available")
        return None

    tray = QSystemTrayIcon(parent)
    icon = QIcon.fromTheme("view-calendar-tasks")
    if icon.isNull():
        icon = parent.windowIcon()
    if icon.isNull():
        icon = create_app_icon()
    if parent.windowIcon().isNull():
        parent.setWindowIcon(icon)
    tray.setIcon(icon)
    tray.setToolTip(APP_NAME)

    menu = QMenu(parent)
    show_action = menu.addAction(parent.tr("显示主窗口"))
    show_action.triggered.connect(show_callback)
    if overview_callback is not None:
        overview_action = menu.addAction(parent.tr("今日任务概览"))
        overview_action.triggered.connect(overview_callback)
    menu.addSeparator()
    quit_action = menu.addAction(parent.tr("退出"))
    quit_action.triggered.connect(quit_callback)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: show_callback()
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick)
        else None
    )
    tray.setVisible(True)
    return tray


def set_auto_start(enabled: bool) -> None:
    logger = logging.getLogger(__name__)
    executable = Path(sys.executable).resolve()
    script = BASE_DIR / "main.py"

    if sys.platform.startswith("win"):
        import winreg

        command = f'"{executable}" "{script}"'
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        logger.info("Windows autostart set to %s", enabled)
        return

    if sys.platform.startswith("linux"):
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / f"{APP_NAME}.desktop"
        if enabled:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        f"Name={APP_NAME}",
                        f"Exec={executable} {script}",
                        "X-GNOME-Autostart-enabled=true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            desktop_file.unlink(missing_ok=True)
        logger.info("Linux autostart set to %s", enabled)
        return

    logger.warning("Autostart is not implemented on this platform: %s", sys.platform)


def _normalize_template(template: Any) -> list[dict[str, Any]]:
    if not isinstance(template, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(template):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        normalized.append(
            {
                "uid": str(item.get("uid") or uuid.uuid4()),
                "content": content,
                "sort_order": int(item.get("sort_order", index)),
                "base_version": int(item.get("base_version", 0)),
                "deleted": bool(item.get("deleted", False)),
                "sync_dirty": bool(item.get("sync_dirty", True)),
            }
        )
    normalized.sort(key=lambda item: int(item["sort_order"]))
    visible_index = 0
    for item in normalized:
        if bool(item.get("deleted", False)):
            continue
        item["sort_order"] = visible_index
        visible_index += 1
    return normalized


def _normalize_sync_settings(sync: Any) -> dict[str, Any]:
    defaults = deepcopy(DEFAULT_SETTINGS["sync"])
    if isinstance(sync, dict):
        defaults.update(sync)
    defaults["server_url"] = str(defaults.get("server_url", "")).strip()
    defaults["username"] = str(defaults.get("username", "")).strip()
    defaults["refresh_token"] = str(defaults.get("refresh_token", ""))
    defaults["last_server_version"] = int(defaults.get("last_server_version", 0) or 0)
    defaults["initialized"] = bool(defaults.get("initialized", False))
    defaults["last_sync_at"] = str(defaults.get("last_sync_at", ""))
    return defaults


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.AlternateBase, Qt.GlobalColor.darkGray)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, Qt.GlobalColor.darkGray)
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.darkCyan)
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    return palette


def translate(context: str, text: str) -> str:
    return QCoreApplication.translate(context, text)

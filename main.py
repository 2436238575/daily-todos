"""DailyTodo application entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTranslator
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from core.database import Database
from core.scheduler import DailyScheduler
from core.sync_manager import SyncManager, sync_error_message
from core.task_manager import TaskManager
from lib.logging_utils import load_build_info, log_startup_banner
from lib.utils import APP_NAME, BASE_DIR, CONFIG_DIR, DATA_DIR, LOG_DIR, apply_theme, create_app_icon, load_settings, setup_logging
from ui.main_window import MainWindow


INSTANCE_KEY = "com.dailytodo.desktop.single-instance"


class SingleInstance:
    """QLocalServer based single-instance guard."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.server: QLocalServer | None = None
        self.window: MainWindow | None = None
        self.logger = logging.getLogger(__name__)

    def already_running(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if socket.waitForConnected(300):
            self.logger.info("Existing DailyTodo instance detected; requesting foreground window")
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return True
        return False

    def listen(self) -> None:
        QLocalServer.removeServer(self.key)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._handle_connection)
        if not self.server.listen(self.key):
            raise RuntimeError(f"Cannot create local server: {self.server.errorString()}")

    def _handle_connection(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(socket.deleteLater)
            if self.window is not None:
                self.window.show_from_tray()


def install_exception_hook() -> None:
    logger = logging.getLogger(__name__)

    def excepthook(exc_type, exc_value, exc_traceback) -> None:
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(None, APP_NAME, f"Unhandled exception:\n{exc_value}")

    sys.excepthook = excepthook


class DailyTodoApplication(QApplication):
    """QApplication with runtime theme and language helpers."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._translator: QTranslator | None = None
        self._theme_signal_connected = False

    def change_language(self, language: str) -> bool:
        if self._translator is not None:
            self.removeTranslator(self._translator)
            self._translator = None

        translator = QTranslator(self)
        qm_path = BASE_DIR / "translations" / f"{language}.qm"
        if qm_path.exists() and translator.load(str(qm_path)):
            self.installTranslator(translator)
            self._translator = translator
            return True

        logging.getLogger(__name__).info("Translation file not loaded: %s", qm_path)
        return False

    def update_theme_signal(self, theme: str) -> None:
        hints = self.styleHints()
        if theme == "system" and not self._theme_signal_connected:
            hints.colorSchemeChanged.connect(self._apply_system_theme)
            self._theme_signal_connected = True
        elif theme != "system" and self._theme_signal_connected:
            try:
                hints.colorSchemeChanged.disconnect(self._apply_system_theme)
            except RuntimeError:
                pass
            self._theme_signal_connected = False

    def _apply_system_theme(self, _scheme) -> None:
        apply_theme(self, "system")


def main() -> int:
    setup_logging()
    install_exception_hook()
    logger = logging.getLogger(__name__)
    bootstrapper = logging.getLogger("Bootstrapper")
    log_startup_banner(
        bootstrapper,
        app_name=APP_NAME,
        build_info=load_build_info(BASE_DIR),
        base_dir=BASE_DIR,
        config_dir=CONFIG_DIR,
        data_dir=DATA_DIR,
        log_dir=LOG_DIR,
        argv=sys.argv,
    )

    logger.info("Creating QApplication")
    app = DailyTodoApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(create_app_icon())
    app.setQuitOnLastWindowClosed(False)

    single_instance = SingleInstance(INSTANCE_KEY)
    if single_instance.already_running():
        return 0
    single_instance.listen()
    logger.info("Single-instance server listening: %s", INSTANCE_KEY)

    settings = load_settings()
    app.change_language(str(settings.get("language", "zh_CN")))
    apply_theme(app, str(settings.get("theme", "system")))
    app.update_theme_signal(str(settings.get("theme", "system")))
    logger.info(
        "Runtime settings applied: language=%s, theme=%s",
        settings.get("language", "zh_CN"),
        settings.get("theme", "system"),
    )

    database = Database(Path("data") / "todo.db")
    logger.info("Initializing database: %s", database.db_path)
    database.initialize()
    logger.info("Database initialized")
    task_manager = TaskManager(database)
    scheduler = DailyScheduler(task_manager)
    sync_manager = SyncManager(database)
    scheduler.start()
    logger.info("Daily scheduler started")

    window = MainWindow(task_manager, scheduler, sync_manager)
    single_instance.window = window
    window.show()
    logger.info("Main window shown")

    def shutdown() -> None:
        logger.info("Shutting down DailyTodo")
        sync = load_settings().get("sync", {})
        if sync.get("refresh_token") and sync.get("initialized"):
            try:
                result = sync_manager.sync("normal")
                logger.info(
                    "Exit sync completed: message=%s, conflicts=%s",
                    result.message,
                    len(result.conflicts),
                )
            except Exception as exc:
                logger.info("Exit sync skipped or failed: %s", sync_error_message(exc))
        scheduler.stop()
        logger.info("Daily scheduler stopped")
        database.close()
        logger.info("Database closed")

    app.aboutToQuit.connect(shutdown)
    exit_code = app.exec()
    logger.info("DailyTodo GUI exited: code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

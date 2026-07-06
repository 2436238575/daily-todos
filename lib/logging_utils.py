"""Logging and build metadata helpers for DailyTodo."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


DEFAULT_VERSION = "0.0.0-dev"
DEFAULT_BUILD_ENV = "Development"
DEFAULT_BUILT_AT = "source"
LEVEL_NAMES = {
    logging.DEBUG: "DBG",
    logging.INFO: "INF",
    logging.WARNING: "WRN",
    logging.ERROR: "ERR",
    logging.CRITICAL: "CRT",
}


@dataclass(frozen=True)
class BuildInfo:
    version: str = DEFAULT_VERSION
    env: str = DEFAULT_BUILD_ENV
    built_at: str = DEFAULT_BUILT_AT


class MaaLogFormatter(logging.Formatter):
    """MAA-inspired fixed-prefix formatter."""

    def __init__(self, *, name_width: int = 26) -> None:
        super().__init__()
        self.name_width = name_width

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        timestamp = f"{timestamp}.{int(record.msecs):03d}"
        level = LEVEL_NAMES.get(record.levelno, record.levelname[:3].upper())
        name = f"[{record.name}]".ljust(self.name_width)
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        return f"[{timestamp}][{level}]{name}<{record.threadName}> {message}"


def configure_logging(log_file: Path, *, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return

    formatter = MaaLogFormatter()
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def load_build_info(base_dir: Path, build_info_path: Path | None = None) -> BuildInfo:
    candidates = [build_info_path] if build_info_path is not None else [
        base_dir / "build_info.json",
        base_dir / "build" / "build_info.json",
    ]
    for path in candidates:
        if path is None or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return BuildInfo()
        if not isinstance(payload, dict):
            return BuildInfo()
        version = str(payload.get("version") or DEFAULT_VERSION).strip()
        env = str(payload.get("env") or DEFAULT_BUILD_ENV).strip()
        built_at = str(payload.get("built_at") or DEFAULT_BUILT_AT).strip()
        return BuildInfo(version=version, env=env, built_at=built_at)
    return BuildInfo()


def write_build_info(path: Path, *, version: str, build_type: str) -> BuildInfo:
    env = "Production" if build_type == "release" else "Development"
    info = BuildInfo(
        version=version,
        env=env,
        built_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": info.version, "env": info.env, "built_at": info.built_at},
            ensure_ascii=False,
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )
    return info


def log_startup_banner(
    logger: logging.Logger,
    *,
    app_name: str,
    build_info: BuildInfo,
    base_dir: Path,
    config_dir: Path,
    data_dir: Path,
    log_dir: Path,
    argv: list[str] | None = None,
) -> None:
    command_line = " ".join(argv if argv is not None else sys.argv)
    logger.info("===================================")
    logger.info("%s GUI started", app_name)
    logger.info("Version v%s", build_info.version)
    logger.info("Built at %s", build_info.built_at)
    logger.info("%s ENV: %s", app_name, build_info.env)
    logger.info("Command Line: %s", command_line)
    logger.info("User Dir %s", base_dir)
    logger.info("Config Dir %s", config_dir)
    logger.info("Data Dir %s", data_dir)
    logger.info("Log Dir %s", log_dir)
    logger.info("===================================")

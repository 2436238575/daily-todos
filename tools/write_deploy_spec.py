"""Write a platform-local pyside6-deploy spec for DailyTodo."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "pysidedeploy.spec"
DEFAULT_VERSION = "0.0.0"
BUILD_TYPES = {"dev", "release"}
VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){0,3})$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write the pyside6-deploy spec for DailyTodo."
    )
    parser.add_argument(
        "--version",
        default=DEFAULT_VERSION,
        help=f"Build version, up to four numeric parts. Default: {DEFAULT_VERSION}",
    )
    parser.add_argument(
        "--build-type",
        choices=sorted(BUILD_TYPES),
        default="dev",
        help="Build type. Release builds hide the Windows console.",
    )
    return parser.parse_args()


def _normalize_version(version: str) -> str:
    match = VERSION_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(
            "Version must be numeric with up to four dot-separated parts, "
            "for example 1.2.3 or v1.2.3.4."
        )
    return match.group(1)


def main() -> int:
    args = _parse_args()
    try:
        version = _normalize_version(args.version)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    python_path = Path(sys.executable).resolve()
    icon_path = (
        python_path.parent.parent
        / "Lib"
        / "site-packages"
        / "PySide6"
        / "scripts"
        / "deploy_lib"
        / "pyside_icon.ico"
    )
    icon_value = str(icon_path) if icon_path.exists() else ""
    extra_args = " ".join(
        [
            "--quiet",
            "--noinclude-qt-translations",
            "--product-name=DailyTodo",
            "--file-description=DailyTodo",
            f"--file-version={version}",
            f"--product-version={version}",
            "--include-data-dir=ui/resources=ui/resources",
            "--include-data-dir=translations=translations",
            "--include-data-file=config/style.qss=config/style.qss",
            *(
                ["--windows-console-mode=disable"]
                if args.build_type == "release" and sys.platform == "win32"
                else []
            ),
        ]
    )

    SPEC_PATH.write_text(
        f"""[app]
title = DailyTodo
project_dir = .
input_file = main.py
exec_directory = .
project_file =
icon = {icon_value}

[python]
python_path = {python_path}
packages = Nuitka==4.0
android_packages = buildozer==1.5.0,cython==0.29.33

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Network,UiTools,Widgets
plugins =

[android]
wheel_pyside =
wheel_shiboken =
plugins =

[nuitka]
macos.permissions =
mode = standalone
extra_args = {extra_args}

[buildozer]
mode = debug
recipe_dir =
jars_dir =
ndk_path =
sdk_path =
local_libs =
arch =
""",
        encoding="utf-8",
    )
    print(f"Wrote {SPEC_PATH} ({args.build_type}, version {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

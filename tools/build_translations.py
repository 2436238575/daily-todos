"""Compile Qt translation sources into .qm files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "translations" / "source"
OUTPUT_DIR = ROOT / "translations"


def main() -> int:
    sources = sorted(SOURCE_DIR.glob("*.ts"))
    if not sources:
        print("No translation sources found.", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lrelease = _find_lrelease()
    for source in sources:
        target = OUTPUT_DIR / f"{source.stem}.qm"
        subprocess.run(
            [str(lrelease), str(source), "-qm", str(target)],
            check=True,
        )
        print(f"built {target}")
    return 0


def _find_lrelease() -> Path | str:
    executable_dir = Path(sys.executable).resolve().parent
    candidates = [
        executable_dir / "pyside6-lrelease.exe",
        executable_dir / "pyside6-lrelease",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return "pyside6-lrelease"


if __name__ == "__main__":
    raise SystemExit(main())

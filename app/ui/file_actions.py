from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_file_in_default_app(path: Path) -> None:
    resolved_path = path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(str(resolved_path))

    system_name = platform.system().lower()
    if system_name == "windows":
        os.startfile(str(resolved_path))  # type: ignore[attr-defined]
        return
    if system_name == "darwin":
        subprocess.Popen(["open", str(resolved_path)])
        return
    subprocess.Popen(["xdg-open", str(resolved_path)])

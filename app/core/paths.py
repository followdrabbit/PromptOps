from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


def resolve_path(path: str | Path) -> Path:
    return (ROOT_DIR / path).resolve() if not isinstance(path, Path) else path.resolve()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

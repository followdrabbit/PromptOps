from __future__ import annotations

from pathlib import Path
import os
from cryptography.fernet import Fernet, InvalidToken

from app.core.paths import ROOT_DIR, ensure_dir


MASTER_KEY_ENV = "PROMPTOPS_MASTER_KEY"
KEYFILE_ENV = "PROMPTOPS_ALLOW_KEYFILE"
DEFAULT_KEYFILE = ROOT_DIR / "data" / ".master_key"


class EncryptionService:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            plaintext = self._fernet.decrypt(token.encode("utf-8"))
            return plaintext.decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid encryption token or master key") from exc


def load_master_key() -> bytes:
    env_key = os.getenv(MASTER_KEY_ENV)
    if env_key:
        return env_key.encode("utf-8")

    if DEFAULT_KEYFILE.exists():
        return DEFAULT_KEYFILE.read_text(encoding="utf-8").strip().encode("utf-8")

    if os.getenv(KEYFILE_ENV, "").lower() in {"1", "true", "yes"}:
        ensure_dir(DEFAULT_KEYFILE.parent)
        key = Fernet.generate_key()
        DEFAULT_KEYFILE.write_bytes(key)
        return key

    raise RuntimeError(
        "Master key not configured. Set PROMPTOPS_MASTER_KEY or enable "
        "PROMPTOPS_ALLOW_KEYFILE=1 to auto-generate a local key file."
    )


def build_encryption_service() -> EncryptionService:
    key = load_master_key()
    return EncryptionService(key)


def is_safe_path(candidate: Path, base_dir: Path) -> bool:
    try:
        return base_dir.resolve() in candidate.resolve().parents or candidate.resolve() == base_dir.resolve()
    except FileNotFoundError:
        return base_dir.resolve() in candidate.resolve().parents

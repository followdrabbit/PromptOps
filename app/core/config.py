from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from app.core.paths import ROOT_DIR, ensure_dir


@dataclass(frozen=True)
class AppConfig:
    name: str = "PromptOps"
    language: str = "en"
    log_level: str = "INFO"
    default_timeout: int = 30
    output_dir: str = "data/exports"
    import_dir: str = "data/imports"
    db_path: str = "data/promptops.db"
    app_log_path: str = "data/logs/app.log"
    audit_log_path: str = "data/audit/audit.log"
    log_retention_days: int = 30
    audit_verbosity: str = "standard"
    tools_enabled: bool = True
    secure_storage: str = "fernet"

    @property
    def output_path(self) -> Path:
        return (ROOT_DIR / self.output_dir).resolve()

    @property
    def import_path(self) -> Path:
        return (ROOT_DIR / self.import_dir).resolve()

    @property
    def db_file(self) -> Path:
        return (ROOT_DIR / self.db_path).resolve()

    @property
    def app_log_file(self) -> Path:
        return (ROOT_DIR / self.app_log_path).resolve()

    @property
    def audit_log_file(self) -> Path:
        return (ROOT_DIR / self.audit_log_path).resolve()


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or (ROOT_DIR / "config.toml")
    if not config_path.exists():
        return AppConfig()

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    app = raw.get("app", {})
    return AppConfig(
        name=app.get("name", "PromptOps"),
        language=app.get("language", "en"),
        log_level=app.get("log_level", "INFO"),
        default_timeout=int(app.get("default_timeout", 30)),
        output_dir=app.get("output_dir", "data/exports"),
        import_dir=app.get("import_dir", "data/imports"),
        db_path=app.get("db_path", "data/promptops.db"),
        app_log_path=app.get("app_log_path", "data/logs/app.log"),
        audit_log_path=app.get("audit_log_path", "data/audit/audit.log"),
        log_retention_days=int(app.get("log_retention_days", 30)),
        audit_verbosity=app.get("audit_verbosity", "standard"),
        tools_enabled=bool(app.get("tools_enabled", True)),
        secure_storage=app.get("secure_storage", "fernet"),
    )


def ensure_directories(config: AppConfig) -> None:
    ensure_dir(config.output_path)
    ensure_dir(config.import_path)
    ensure_dir(config.app_log_file.parent)
    ensure_dir(config.audit_log_file.parent)
    ensure_dir(config.db_file.parent)


def get_actor() -> str:
    return os.getenv("PROMPTOPS_ACTOR", "local_user")

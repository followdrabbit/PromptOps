from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.redaction import redact_text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            record.args = tuple(redact_text(str(arg)) for arg in record.args)
        return True


def setup_logging(app_log_path: Path, audit_log_path: Path, level: str = "INFO") -> None:
    app_log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_handler = RotatingFileHandler(app_log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    app_handler.setFormatter(formatter)
    app_handler.addFilter(RedactingFilter())

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactingFilter())

    existing_app = any(getattr(h, "baseFilename", None) == str(app_log_path) for h in root_logger.handlers)
    if not existing_app:
        root_logger.addHandler(app_handler)
        root_logger.addHandler(stream_handler)

    audit_logger = logging.getLogger("promptops.audit")
    existing_audit = any(getattr(h, "baseFilename", None) == str(audit_log_path) for h in audit_logger.handlers)
    if not existing_audit:
        audit_handler = RotatingFileHandler(audit_log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        audit_handler.setFormatter(formatter)
        audit_handler.addFilter(RedactingFilter())
        audit_logger.addHandler(audit_handler)
    audit_logger.setLevel("INFO")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

from app.core.redaction import redact_text


APP_FILE_HANDLER_NAME = "promptops_app_file"
APP_STREAM_HANDLER_NAME = "promptops_app_stream"
AUDIT_FILE_HANDLER_NAME = "promptops_audit_file"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            record.args = tuple(redact_text(str(arg)) for arg in record.args)
        return True


def _get_level_number(level: str) -> int:
    return getattr(logging, level, logging.INFO)


def _ensure_redacting_filter(handler: logging.Handler) -> None:
    if not any(isinstance(filter_obj, RedactingFilter) for filter_obj in handler.filters):
        handler.addFilter(RedactingFilter())


def _find_named_handler(handlers: Iterable[logging.Handler], name: str) -> logging.Handler | None:
    for handler in handlers:
        if handler.get_name() == name:
            return handler
    return None


def normalize_log_level(level: str | None) -> str:
    candidate = (level or "INFO").upper().strip()
    aliases = {"WARN": "WARNING", "FATAL": "CRITICAL"}
    candidate = aliases.get(candidate, candidate)
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    return candidate if candidate in allowed else "INFO"


def set_log_level(level: str | None) -> str:
    normalized = normalize_log_level(level)
    level_no = _get_level_number(normalized)
    root_logger = logging.getLogger()
    root_logger.setLevel(level_no)
    for handler in root_logger.handlers:
        handler.setLevel(level_no)

    audit_logger = logging.getLogger("promptops.audit")
    # Keep audit predictable and focused on actionable events.
    audit_logger.setLevel(logging.INFO)
    return normalized


def setup_logging(app_log_path: Path, audit_log_path: Path, level: str = "INFO") -> None:
    app_log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_level = normalize_log_level(level)
    level_no = _get_level_number(normalized_level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level_no)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Remove legacy handlers created before named-handler support to prevent duplicates.
    for handler in list(root_logger.handlers):
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(app_log_path):
            if handler.get_name() != APP_FILE_HANDLER_NAME:
                root_logger.removeHandler(handler)
                handler.close()
                continue
        is_stream = isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
        if is_stream and handler.get_name() != APP_STREAM_HANDLER_NAME:
            if any(isinstance(filter_obj, RedactingFilter) for filter_obj in handler.filters):
                root_logger.removeHandler(handler)
                handler.close()

    app_handler = _find_named_handler(root_logger.handlers, APP_FILE_HANDLER_NAME)
    if app_handler is None:
        app_handler = RotatingFileHandler(app_log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        app_handler.set_name(APP_FILE_HANDLER_NAME)
        root_logger.addHandler(app_handler)
    app_handler.setLevel(level_no)
    app_handler.setFormatter(formatter)
    _ensure_redacting_filter(app_handler)

    stream_handler = _find_named_handler(root_logger.handlers, APP_STREAM_HANDLER_NAME)
    if stream_handler is None:
        stream_handler = logging.StreamHandler()
        stream_handler.set_name(APP_STREAM_HANDLER_NAME)
        root_logger.addHandler(stream_handler)
    stream_handler.setLevel(level_no)
    stream_handler.setFormatter(formatter)
    _ensure_redacting_filter(stream_handler)

    audit_logger = logging.getLogger("promptops.audit")
    audit_logger.propagate = False
    for handler in list(audit_logger.handlers):
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(audit_log_path):
            if handler.get_name() != AUDIT_FILE_HANDLER_NAME:
                audit_logger.removeHandler(handler)
                handler.close()
    audit_handler = _find_named_handler(audit_logger.handlers, AUDIT_FILE_HANDLER_NAME)
    if audit_handler is None:
        audit_handler = RotatingFileHandler(audit_log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        audit_handler.set_name(AUDIT_FILE_HANDLER_NAME)
        audit_logger.addHandler(audit_handler)
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(formatter)
    _ensure_redacting_filter(audit_handler)
    audit_logger.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

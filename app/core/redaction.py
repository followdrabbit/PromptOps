from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "x_api_key",
    "apikey",
    "api-key",
    "token",
    "access_token",
    "secret",
    "password",
    "bearer",
    "cookie",
    "set_cookie",
    "set-cookie",
}


def mask_secret(value: str, show_last: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= show_last:
        return "*" * len(value)
    return "*" * (len(value) - show_last) + value[-show_last:]


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized in SENSITIVE_KEYS:
        return True
    suffixes = ("_token", "_secret", "_password", "_api_key")
    return normalized.endswith(suffixes)


def redact_text(text: str) -> str:
    redacted = text
    for key in sorted(SENSITIVE_KEYS):
        escaped = re.escape(key)
        pattern = re.compile(
            rf"([\"']?{escaped}[\"']?\s*[:=]\s*)([\"']?)([^\"'\n\r,;}}]+)([\"']?)",
            re.IGNORECASE,
        )
        redacted = pattern.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{mask_secret(m.group(3))}{m.group(4)}",
            redacted,
        )
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: mask_secret(str(item))
            if is_sensitive_key(str(key))
            else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    result = redact_value(data)
    return result if isinstance(result, dict) else {}

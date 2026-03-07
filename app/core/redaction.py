from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "secret",
    "password",
    "bearer",
}


def mask_secret(value: str, show_last: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= show_last:
        return "*" * len(value)
    return "*" * (len(value) - show_last) + value[-show_last:]


def redact_text(text: str) -> str:
    redacted = text
    for key in SENSITIVE_KEYS:
        pattern = re.compile(rf"({key}\s*[:=]\s*)([^\s,;]+)", re.IGNORECASE)
        redacted = pattern.sub(lambda m: f"{m.group(1)}{mask_secret(m.group(2))}", redacted)
    return redacted


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = mask_secret(str(value))
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        else:
            redacted[key] = value
    return redacted

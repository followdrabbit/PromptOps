from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ProviderResponse:
    content: str
    raw: dict[str, Any] | None
    latency_ms: int | None = None


class BaseProvider(Protocol):
    def send_prompt(self, messages: list[dict[str, Any]], params: dict[str, Any]) -> ProviderResponse:
        ...

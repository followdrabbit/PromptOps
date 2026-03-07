from __future__ import annotations

import json
import time
from typing import Any
import requests

from app.adapters.base import ProviderResponse
from app.core.logging import get_logger
from app.core.redaction import redact_dict
from app.domain.models import Endpoint


class OpenAICompatibleProvider:
    def __init__(self, endpoint: Endpoint, secret: str | None) -> None:
        self.endpoint = endpoint
        self.secret = secret
        self.logger = get_logger("promptops.provider")

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.endpoint.custom_headers:
            headers.update({str(k): str(v) for k, v in self.endpoint.custom_headers.items()})

        if self.endpoint.auth_type.lower() in {"bearer", "api_key", "header"} and self.secret:
            header_name = self.endpoint.auth_header or "Authorization"
            prefix = self.endpoint.auth_prefix or ("Bearer " if self.endpoint.auth_type.lower() == "bearer" else "")
            headers[header_name] = f"{prefix}{self.secret}"

        return headers

    def _replace_placeholders(self, payload: Any, prompt_text: str) -> Any:
        if isinstance(payload, str):
            return payload.replace("MODEL_NAME", self.endpoint.model_name).replace("<PROMPT>", prompt_text)
        if isinstance(payload, list):
            return [self._replace_placeholders(item, prompt_text) for item in payload]
        if isinstance(payload, dict):
            return {key: self._replace_placeholders(value, prompt_text) for key, value in payload.items()}
        return payload

    def _extract_by_path(self, data: Any, path: str) -> Any | None:
        if not path:
            return None
        current = data
        cleaned = path.strip()
        if cleaned.startswith("$"):
            cleaned = cleaned[1:]
        if cleaned.startswith("."):
            cleaned = cleaned[1:]
        if not cleaned:
            return None
        parts = cleaned.split(".")
        for part in parts:
            if current is None:
                return None
            if part == "":
                continue
            token = part
            while token:
                if "[" in token:
                    name, rest = token.split("[", 1)
                    if name:
                        if isinstance(current, dict):
                            current = current.get(name)
                        else:
                            return None
                    if "]" not in rest:
                        return None
                    idx_raw, remainder = rest.split("]", 1)
                    try:
                        idx = int(idx_raw)
                    except ValueError:
                        return None
                    if isinstance(current, list) and 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                    token = remainder
                else:
                    if isinstance(current, dict):
                        current = current.get(token)
                    else:
                        return None
                    token = ""
        return current

    def send_prompt(self, messages: list[dict[str, Any]], params: dict[str, Any]) -> ProviderResponse:
        payload: dict[str, Any] = {"model": self.endpoint.model_name, "messages": messages}
        payload.update(params or {})

        prompt_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                prompt_text = str(msg.get("content", ""))
                break
        if not prompt_text and messages:
            prompt_text = str(messages[-1].get("content", ""))
        payload = self._replace_placeholders(payload, prompt_text)

        base_url = self.endpoint.base_url.rstrip("/")
        endpoint_path = (self.endpoint.endpoint_path or "").lstrip("/")
        url = f"{base_url}/{endpoint_path}" if endpoint_path else base_url
        timeout = self.endpoint.timeout or params.get("timeout")
        retries = self.endpoint.retry_count or 0

        headers = self._build_headers()
        safe_headers = redact_dict(headers)
        self.logger.info("Sending request to provider %s with headers %s", url, safe_headers)

        start = time.time()
        response = None
        for attempt in range(retries + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout or 30)
                response.raise_for_status()
                break
            except Exception:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise

        latency_ms = int((time.time() - start) * 1000)
        content = ""
        if self.endpoint.response_type == "text":
            content = response.text if response is not None else ""
            raw = content
            return ProviderResponse(content=content, raw=raw, latency_ms=latency_ms)

        data: Any = {}
        if response is not None:
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text}

        if self.endpoint.response_paths:
            paths = [p.strip() for p in self.endpoint.response_paths.replace(",", "\n").splitlines() if p.strip()]
            for candidate in paths:
                extracted = self._extract_by_path(data, candidate)
                if extracted is not None:
                    if isinstance(extracted, (dict, list)):
                        content = json.dumps(extracted)
                    else:
                        content = str(extracted)
                    return ProviderResponse(content=content, raw=data, latency_ms=latency_ms)

        if isinstance(data, dict):
            choices = data.get("choices")
            if choices:
                message = choices[0].get("message") if isinstance(choices, list) else None
                if message:
                    content = message.get("content", "")
        return ProviderResponse(content=content, raw=data, latency_ms=latency_ms)

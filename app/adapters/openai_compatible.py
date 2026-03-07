from __future__ import annotations

import json
import re
import time
from uuid import uuid4
from typing import Any
import requests

from app.adapters.base import ProviderResponse
from app.core.logging import get_logger
from app.core.redaction import redact_dict, redact_text, redact_value
from app.domain.models import Endpoint


class OpenAICompatibleProvider:
    REQUEST_PREVIEW_LIMIT = 6_000
    RESPONSE_PREVIEW_LIMIT = 8_000

    def __init__(
        self,
        endpoint: Endpoint,
        variables: dict[str, str] | None = None,
        *,
        verify_ssl: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.variables = variables or {}
        self.verify_ssl = verify_ssl
        self.logger = get_logger("promptops.provider")

    @staticmethod
    def _truncate_preview(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated {len(text) - limit} chars]"

    def _to_preview(self, payload: Any, limit: int) -> str:
        safe_payload = redact_value(payload)
        try:
            serialized = json.dumps(safe_payload, ensure_ascii=False)
        except TypeError:
            serialized = str(safe_payload)
        return self._truncate_preview(serialized, limit)

    def _replace_string(self, value: str, runtime_vars: dict[str, str]) -> str:
        replaced = value
        # 1) Replace template placeholders ({{VAR}}, ${VAR}, and legacy <VAR>).
        def replace_token(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(runtime_vars.get(key, match.group(0)))

        for pattern in (
            r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}",
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
            r"<([A-Za-z_][A-Za-z0-9_]*)>",
        ):
            replaced = re.sub(pattern, replace_token, replaced)
        # 2) Replace reserved/bare variable tokens like MODEL_NAME and PROMPT.
        for key, var_value in runtime_vars.items():
            replaced = re.sub(rf"\b{re.escape(key)}\b", lambda _m: str(var_value), replaced)
        return replaced

    def _replace_placeholders(self, payload: Any, runtime_vars: dict[str, str]) -> Any:
        if isinstance(payload, str):
            return self._replace_string(payload, runtime_vars)
        if isinstance(payload, list):
            return [self._replace_placeholders(item, runtime_vars) for item in payload]
        if isinstance(payload, dict):
            return {key: self._replace_placeholders(value, runtime_vars) for key, value in payload.items()}
        return payload

    def _build_headers(self, runtime_vars: dict[str, str]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.endpoint.custom_headers:
            rendered_headers = self._replace_placeholders(self.endpoint.custom_headers, runtime_vars)
            if isinstance(rendered_headers, dict):
                headers.update({str(k): str(v) for k, v in rendered_headers.items()})

        api_token = runtime_vars.get("API_TOKEN")
        if self.endpoint.auth_type.lower() in {"bearer", "api_key", "header"} and api_token:
            header_name = self.endpoint.auth_header or "Authorization"
            prefix = self.endpoint.auth_prefix or ("Bearer " if self.endpoint.auth_type.lower() == "bearer" else "")
            headers[header_name] = f"{prefix}{api_token}"

        return headers

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

    def _collect_text_values(self, payload: Any) -> list[str]:
        texts: list[str] = []
        if isinstance(payload, str):
            normalized = payload.strip()
            if normalized:
                texts.append(normalized)
            return texts
        if isinstance(payload, list):
            for item in payload:
                texts.extend(self._collect_text_values(item))
            return texts
        if isinstance(payload, dict):
            text_value = payload.get("text")
            if isinstance(text_value, str) and text_value.strip():
                texts.append(text_value.strip())
            content_value = payload.get("content")
            if content_value is not None:
                texts.extend(self._collect_text_values(content_value))
            output_text_value = payload.get("output_text")
            if output_text_value is not None:
                texts.extend(self._collect_text_values(output_text_value))
            return texts
        return texts

    def _extract_content_fallback(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        output_text = data.get("output_text")
        if output_text is not None:
            found = self._collect_text_values(output_text)
            if found:
                return "\n".join(found)

        output = data.get("output")
        if isinstance(output, list):
            extracted: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "message" or "content" in item:
                    extracted.extend(self._collect_text_values(item.get("content")))
            if extracted:
                return "\n".join(extracted)

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    extracted = self._collect_text_values(message.get("content"))
                    if extracted:
                        return "\n".join(extracted)
        return ""

    @staticmethod
    def _extract_incomplete_reason(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        if data.get("status") != "incomplete":
            return None
        details = data.get("incomplete_details")
        if isinstance(details, dict):
            reason = details.get("reason")
            if reason:
                return str(reason)
        return "unknown"

    def send_prompt(self, messages: list[dict[str, Any]], params: dict[str, Any]) -> ProviderResponse:
        prompt_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                prompt_text = str(msg.get("content", ""))
                break
        if not prompt_text and messages:
            prompt_text = str(messages[-1].get("content", ""))
        runtime_vars = dict(self.variables)
        runtime_vars["MODEL_NAME"] = self.endpoint.model_name
        runtime_vars["PROMPT"] = prompt_text

        payload_template = self.endpoint.default_params
        if not isinstance(payload_template, dict):
            raise ValueError(
                "Endpoint body is required and must be a JSON object with placeholders like "
                "{{MODEL_NAME}} and {{PROMPT}}."
            )
        payload = self._replace_placeholders(payload_template, runtime_vars)
        if not isinstance(payload, dict):
            raise ValueError("Body must be a JSON object.")
        for key, value in (params or {}).items():
            # Keep payload vendor-agnostic: only override keys already present in template body.
            if key in payload:
                payload[key] = value
        payload = self._replace_placeholders(payload, runtime_vars)

        base_url = self.endpoint.base_url.rstrip("/")
        endpoint_path = (self.endpoint.endpoint_path or "").lstrip("/")
        url = f"{base_url}/{endpoint_path}" if endpoint_path else base_url
        timeout = params.get("timeout") or self.endpoint.timeout
        retries = self.endpoint.retry_count or 0

        headers = self._build_headers(runtime_vars)
        safe_headers = redact_dict(headers)
        request_id = f"req-{uuid4().hex[:8]}"
        self.logger.info("Sending request request_id=%s to provider %s", request_id, url)
        self.logger.debug(
            "Provider request details request_id=%s endpoint=%s provider=%s method=POST url=%s prompt_chars=%s timeout=%s retries=%s ssl_verify=%s headers=%s payload=%s",
            request_id,
            self.endpoint.name,
            self.endpoint.provider,
            url,
            len(prompt_text),
            timeout or 30,
            retries,
            self.verify_ssl,
            self._to_preview(safe_headers, 2_000),
            self._to_preview(payload, self.REQUEST_PREVIEW_LIMIT),
        )
        if not self.verify_ssl:
            self.logger.warning("SSL verification disabled for request_id=%s url=%s", request_id, url)

        start = time.time()
        response = None
        for attempt in range(retries + 1):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout or 30,
                    verify=self.verify_ssl,
                )
                response.raise_for_status()
                break
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if exc.response is not None:
                    self.logger.debug(
                        "Provider HTTP error request_id=%s status=%s headers=%s body_preview=%s",
                        request_id,
                        status_code,
                        self._to_preview(redact_dict(dict(exc.response.headers)), 2_000),
                        self._truncate_preview(redact_text(exc.response.text), self.RESPONSE_PREVIEW_LIMIT),
                    )
                if status_code == 401:
                    header_names = ", ".join(headers.keys())
                    raise requests.HTTPError(
                        "401 Unauthorized. Check token and auth headers. "
                        "For OpenAI Responses, use Authorization: Bearer {{API_TOKEN}}. "
                        f"Headers sent: {header_names}",
                        response=exc.response,
                    ) from exc
                if attempt < retries:
                    self.logger.warning(
                        "Provider request retrying request_id=%s url=%s next_attempt=%s/%s",
                        request_id,
                        url,
                        attempt + 2,
                        retries + 1,
                    )
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise
            except Exception as exc:
                if attempt < retries:
                    self.logger.warning(
                        "Provider request failed request_id=%s url=%s error=%s next_attempt=%s/%s",
                        request_id,
                        url,
                        exc,
                        attempt + 2,
                        retries + 1,
                    )
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise

        latency_ms = int((time.time() - start) * 1000)
        content = ""
        if self.endpoint.response_type == "text":
            content = response.text if response is not None else ""
            raw = {"raw_text": content}
            self.logger.debug(
                "Provider response details request_id=%s status=%s latency_ms=%s response_type=text headers=%s body_preview=%s",
                request_id,
                response.status_code if response is not None else None,
                latency_ms,
                self._to_preview(redact_dict(dict(response.headers)) if response is not None else {}, 2_000),
                self._truncate_preview(redact_text(content), self.RESPONSE_PREVIEW_LIMIT),
            )
            return ProviderResponse(content=content, raw=raw, latency_ms=latency_ms)

        data: Any = {}
        if response is not None:
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text}
            self.logger.debug(
                "Provider response details request_id=%s status=%s latency_ms=%s headers=%s body_preview=%s",
                request_id,
                response.status_code,
                latency_ms,
                self._to_preview(redact_dict(dict(response.headers)), 2_000),
                self._to_preview(data, self.RESPONSE_PREVIEW_LIMIT),
            )
        incomplete_reason = self._extract_incomplete_reason(data)
        if incomplete_reason:
            self.logger.warning(
                "Provider response incomplete request_id=%s endpoint=%s reason=%s",
                request_id,
                self.endpoint.name,
                incomplete_reason,
            )

        if self.endpoint.response_paths:
            paths = [p.strip() for p in self.endpoint.response_paths.replace(",", "\n").splitlines() if p.strip()]
            for candidate in paths:
                extracted = self._extract_by_path(data, candidate)
                if extracted is not None:
                    self.logger.debug(
                        "Provider response path matched request_id=%s path=%s extracted_preview=%s",
                        request_id,
                        candidate,
                        self._to_preview(extracted, 2_000),
                    )
                    if isinstance(extracted, (dict, list)):
                        content = json.dumps(extracted)
                    else:
                        content = str(extracted)
                    return ProviderResponse(content=content, raw=data, latency_ms=latency_ms)
            self.logger.debug(
                "Provider response path no match request_id=%s configured_paths=%s",
                request_id,
                paths,
            )

        content = self._extract_content_fallback(data)
        if content:
            self.logger.debug(
                "Provider fallback extraction used request_id=%s extracted_preview=%s",
                request_id,
                self._to_preview(content, 2_000),
            )
        self.logger.debug(
            "Provider response parsed request_id=%s endpoint=%s status=%s latency_ms=%s content_chars=%s",
            request_id,
            self.endpoint.name,
            response.status_code if response is not None else None,
            latency_ms,
            len(content) if content else 0,
        )
        return ProviderResponse(content=content, raw=data, latency_ms=latency_ms)

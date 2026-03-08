from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.secrets import SecretManager
from app.domain import models
from app.services.audit_service import record_event

RESERVED_TEMPLATE_VARS = {"API_TOKEN", "MODEL_NAME", "PROMPT"}
TEMPLATE_VAR_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
TEMPLATE_VAR_PATTERNS = (
    re.compile(r"\{\{\s*(" + TEMPLATE_VAR_NAME + r")\s*\}\}"),
    re.compile(r"\$\{(" + TEMPLATE_VAR_NAME + r")\}"),
    re.compile(r"<(" + TEMPLATE_VAR_NAME + r")>"),
)
BARE_RESERVED_PATTERN = re.compile(r"\b(API_TOKEN|MODEL_NAME|PROMPT)\b")


def _split_endpoint_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return base_url, path
    raise ValueError(f"invalid endpoint_url '{url}'")


def _compose_endpoint_url(base_url: str, endpoint_path: str | None) -> str:
    base = (base_url or "").rstrip("/")
    path = (endpoint_path or "").strip()
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def _extract_template_variables(*texts: str) -> list[str]:
    variables: set[str] = set()
    for text in texts:
        if not text:
            continue
        for pattern in TEMPLATE_VAR_PATTERNS:
            variables.update(pattern.findall(text))
        variables.update(BARE_RESERVED_PATTERN.findall(text))
    return sorted(variables)


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and value != value)


def _read_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and not _is_missing(row.get(key)):
            return row.get(key)
    return None


def _parse_json_object(value: Any, *, field_name: str, row_index: int) -> dict[str, Any]:
    if _is_missing(value):
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"row {row_index}: '{field_name}' must be a JSON object")
        return parsed
    raise ValueError(f"row {row_index}: '{field_name}' must be a JSON object")


def list_endpoints(session: Session) -> list[models.Endpoint]:
    return session.query(models.Endpoint).order_by(models.Endpoint.name.asc()).all()


def get_endpoint(session: Session, endpoint_id: int) -> models.Endpoint | None:
    return session.query(models.Endpoint).filter(models.Endpoint.id == endpoint_id).one_or_none()


def create_endpoint(
    session: Session,
    data: dict,
    secret_value: str | None = None,
    secret_type: str = "api_key",
    variable_values: dict[str, str] | None = None,
) -> models.Endpoint:
    endpoint = models.Endpoint(**data)
    session.add(endpoint)
    session.flush()

    if variable_values is not None or secret_value:
        stored_variables = dict(variable_values or {})
        if secret_value:
            stored_variables["API_TOKEN"] = secret_value
        if stored_variables:
            SecretManager().store_variables(session, endpoint.id, stored_variables, secret_type="template_vars")

    record_event(session, "create", "endpoint", endpoint.id, after_value=data)
    return endpoint


def update_endpoint(
    session: Session,
    endpoint: models.Endpoint,
    data: dict,
    secret_value: str | None = None,
    secret_type: str = "api_key",
    variable_values: dict[str, str] | None = None,
) -> models.Endpoint:
    before = {
        "name": endpoint.name,
        "provider": endpoint.provider,
        "base_url": endpoint.base_url,
        "endpoint_path": endpoint.endpoint_path,
        "model_name": endpoint.model_name,
        "auth_type": endpoint.auth_type,
        "response_paths": endpoint.response_paths,
        "response_type": endpoint.response_type,
    }
    for key, value in data.items():
        setattr(endpoint, key, value)

    if variable_values is not None or secret_value:
        stored_variables = dict(variable_values or {})
        if secret_value:
            stored_variables["API_TOKEN"] = secret_value
        if stored_variables:
            SecretManager().store_variables(session, endpoint.id, stored_variables, secret_type="template_vars")
        record_event(session, "rotate", "endpoint_secret", endpoint.id)

    record_event(session, "update", "endpoint", endpoint.id, before_value=before, after_value=data)
    session.add(endpoint)
    return endpoint


def delete_endpoint(session: Session, endpoint: models.Endpoint) -> None:
    record_event(session, "delete", "endpoint", endpoint.id, before_value={"name": endpoint.name})
    session.delete(endpoint)


def endpoints_to_records(session: Session, endpoints: list[models.Endpoint]) -> list[dict[str, Any]]:
    secret_manager = SecretManager()
    records: list[dict[str, Any]] = []
    for endpoint in endpoints:
        endpoint_variables = secret_manager.get_variables(session, endpoint.id)
        custom_variables = {
            key: value
            for key, value in endpoint_variables.items()
            if key not in RESERVED_TEMPLATE_VARS
        }
        records.append(
            {
                "name": endpoint.name,
                "provider": endpoint.provider,
                "endpoint_url": _compose_endpoint_url(endpoint.base_url, endpoint.endpoint_path),
                "model_name": endpoint.model_name,
                "headers": endpoint.custom_headers or {},
                "body": endpoint.default_params or {},
                "response_paths": endpoint.response_paths or "",
                "response_type": endpoint.response_type or "json",
                "additional_variables": custom_variables,
                # Always blank in exports for security.
                "api_token": "",
            }
        )
    return records


def validate_endpoint_records(
    records: list[dict[str, Any]],
    *,
    default_timeout: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    ignored_api_token_rows = 0

    for row_index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {row_index}: invalid row format (expected object)")
            continue

        name_raw = _read_value(row, ["name", "endpoint_name"])
        provider_raw = _read_value(row, ["provider"])
        endpoint_url_raw = _read_value(row, ["endpoint_url", "url"])
        model_name_raw = _read_value(row, ["model_name", "model"])
        headers_raw = _read_value(row, ["headers", "custom_headers"])
        body_raw = _read_value(row, ["body", "default_params"])
        response_paths_raw = _read_value(row, ["response_paths", "response_json_paths"])
        response_type_raw = _read_value(row, ["response_type"])
        additional_vars_raw = _read_value(row, ["additional_variables", "variables", "extra_variables"])
        api_token_raw = _read_value(row, ["api_token", "API_TOKEN", "key"])

        name = "" if _is_missing(name_raw) else str(name_raw).strip()
        provider = "" if _is_missing(provider_raw) else str(provider_raw).strip()
        endpoint_url = "" if _is_missing(endpoint_url_raw) else str(endpoint_url_raw).strip()
        model_name = "" if _is_missing(model_name_raw) else str(model_name_raw).strip()
        response_paths = "" if _is_missing(response_paths_raw) else str(response_paths_raw).strip()
        response_type = "json" if _is_missing(response_type_raw) else str(response_type_raw).strip().lower()

        if not name and not provider and not endpoint_url and not model_name:
            continue

        missing_fields: list[str] = []
        if not name:
            missing_fields.append("name")
        if not provider:
            missing_fields.append("provider")
        if not endpoint_url:
            missing_fields.append("endpoint_url")
        if not model_name:
            missing_fields.append("model_name")
        if missing_fields:
            errors.append(f"row {row_index}: missing required field(s): {', '.join(missing_fields)}")
            continue

        if len(name) > 120:
            errors.append(f"row {row_index}: 'name' exceeds 120 characters")
            continue
        name_key = name.lower()
        if name_key in seen_names:
            errors.append(f"row {row_index}: duplicate endpoint name '{name}' in file")
            continue
        seen_names.add(name_key)

        if response_type not in {"json", "text"}:
            errors.append(f"row {row_index}: 'response_type' must be 'json' or 'text'")
            continue

        try:
            base_url, endpoint_path = _split_endpoint_url(endpoint_url)
        except ValueError:
            errors.append(f"row {row_index}: invalid endpoint_url '{endpoint_url}'")
            continue

        try:
            headers = _parse_json_object(headers_raw, field_name="headers", row_index=row_index)
            body = _parse_json_object(body_raw, field_name="body", row_index=row_index)
            additional_variables = _parse_json_object(
                additional_vars_raw,
                field_name="additional_variables",
                row_index=row_index,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue

        normalized_variables = {
            str(key).strip(): "" if value is None else str(value)
            for key, value in additional_variables.items()
            if str(key).strip()
        }

        detected_vars = _extract_template_variables(
            json.dumps(headers, ensure_ascii=False),
            json.dumps(body, ensure_ascii=False),
        )
        missing_vars = [
            variable
            for variable in detected_vars
            if variable not in RESERVED_TEMPLATE_VARS and variable not in normalized_variables
        ]
        if missing_vars:
            errors.append(
                f"row {row_index}: missing value for custom variable(s): {', '.join(sorted(set(missing_vars)))}"
            )
            continue

        if not _is_missing(api_token_raw):
            ignored_api_token_rows += 1

        variable_values = {"MODEL_NAME": model_name, **normalized_variables}

        normalized.append(
            {
                "name": name,
                "provider": provider,
                "base_url": base_url,
                "endpoint_path": endpoint_path,
                "model_name": model_name,
                "custom_headers": headers,
                "default_params": body,
                "response_paths": response_paths or None,
                "response_type": response_type,
                "timeout": int(default_timeout),
                "retry_count": 0,
                "variable_values": variable_values,
            }
        )

    if not normalized and not errors:
        errors.append("no valid endpoint records found")

    return normalized, errors, ignored_api_token_rows


def import_endpoint_records(session: Session, records: list[dict[str, Any]]) -> dict[str, Any]:
    existing_names = {endpoint.name.strip().lower() for endpoint in list_endpoints(session)}
    created = 0
    skipped_existing = 0
    skipped_existing_names: list[str] = []

    for record in records:
        name = str(record["name"]).strip()
        if name.lower() in existing_names:
            skipped_existing += 1
            skipped_existing_names.append(name)
            continue

        data = {
            "name": name,
            "provider": record["provider"],
            "base_url": record["base_url"],
            "endpoint_path": record["endpoint_path"],
            "model_name": record["model_name"],
            "auth_type": "none",
            "auth_header": None,
            "auth_prefix": None,
            "custom_headers": record["custom_headers"],
            "default_params": record["default_params"],
            "timeout": int(record.get("timeout", 30)),
            "retry_count": int(record.get("retry_count", 0)),
            "response_paths": record.get("response_paths"),
            "response_type": record.get("response_type", "json"),
        }
        create_endpoint(
            session,
            data,
            None,
            secret_type="none",
            variable_values=record.get("variable_values"),
        )
        existing_names.add(name.lower())
        created += 1

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_existing_names": skipped_existing_names,
    }

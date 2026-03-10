from __future__ import annotations

import json
from typing import Any, Mapping

import streamlit as st


RESERVED_TEMPLATE_VARS = {"API_TOKEN", "MODEL_NAME", "PROMPT"}
SUPPORTED_VARIABLE_TYPES = {"string", "number", "boolean", "json"}


def _normalize_variable_type(value: Any) -> str:
    normalized = str(value or "string").strip().lower()
    return normalized if normalized in SUPPORTED_VARIABLE_TYPES else "string"


def _infer_variable_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


def _parse_number(value: Any) -> tuple[float, bool]:
    if isinstance(value, bool):
        return 0.0, False
    if isinstance(value, int):
        return float(value), True
    if isinstance(value, float):
        return value, False
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0, False
        try:
            if "." in raw:
                return float(raw), False
            return float(int(raw)), True
        except ValueError:
            return 0.0, False
    return 0.0, False


def _parse_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in {"true", "1", "yes", "on"}
    return bool(value)


def _parse_json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return value
    return value


def get_custom_endpoint_variables(variables: Mapping[str, Any] | None) -> dict[str, Any]:
    if not variables:
        return {}
    return {
        str(key): value
        for key, value in variables.items()
        if str(key) not in RESERVED_TEMPLATE_VARS
    }


def get_custom_endpoint_variable_types(
    variables: Mapping[str, Any] | None,
    variable_types: Mapping[str, str] | None,
) -> dict[str, str]:
    custom_variables = get_custom_endpoint_variables(variables)
    return {
        key: _normalize_variable_type(variable_types.get(key) if variable_types else _infer_variable_type(value))
        for key, value in custom_variables.items()
    }


def render_runtime_variable_editor(
    tr,
    *,
    endpoint_name: str,
    endpoint_id: int,
    variables: Mapping[str, Any] | None,
    variable_types: Mapping[str, str] | None,
    key_prefix: str,
) -> dict[str, Any]:
    custom_variables = get_custom_endpoint_variables(variables)
    custom_types = get_custom_endpoint_variable_types(custom_variables, variable_types)
    st.markdown(f"**{tr('label_runtime_variables_for_endpoint', endpoint=endpoint_name)}**")
    st.caption(tr("help_runtime_additional_variables"))
    if not custom_variables:
        st.info(tr("info_no_additional_variables_for_endpoint", endpoint=endpoint_name))
        return {}

    overrides: dict[str, Any] = {}
    for variable_name in sorted(custom_variables):
        variable_type = custom_types.get(variable_name, "string")
        widget_key = f"{key_prefix}_{endpoint_id}_{variable_name}_{variable_type}"
        label = f"{variable_name} ({variable_type})"

        if variable_type == "boolean":
            if widget_key not in st.session_state:
                st.session_state[widget_key] = _parse_boolean(custom_variables[variable_name])
            overrides[variable_name] = st.toggle(
                label,
                key=widget_key,
                help=tr("help_runtime_variable_input", variable=variable_name),
            )
            continue

        if variable_type == "number":
            parsed_number, is_integer = _parse_number(custom_variables[variable_name])
            if widget_key not in st.session_state:
                st.session_state[widget_key] = int(parsed_number) if is_integer else float(parsed_number)
            value = st.number_input(
                label,
                key=widget_key,
                step=1 if is_integer else 0.1,
                format="%d" if is_integer else "%.6f",
                help=tr("help_runtime_variable_input", variable=variable_name),
            )
            overrides[variable_name] = int(value) if is_integer else float(value)
            continue

        if variable_type == "json":
            default_json = _parse_json_value(custom_variables[variable_name])
            if widget_key not in st.session_state:
                st.session_state[widget_key] = (
                    json.dumps(default_json, indent=2, ensure_ascii=False)
                    if not isinstance(default_json, str)
                    else default_json
                )
            raw_text = st.text_area(
                label,
                key=widget_key,
                height=120,
                help=tr("help_runtime_variable_input", variable=variable_name),
            )
            try:
                overrides[variable_name] = json.loads(raw_text) if raw_text.strip() else {}
            except json.JSONDecodeError:
                st.warning(tr("warning_runtime_variable_json_invalid", variable=variable_name))
                overrides[variable_name] = default_json
            continue

        if widget_key not in st.session_state:
            st.session_state[widget_key] = "" if custom_variables[variable_name] is None else str(custom_variables[variable_name])
        overrides[variable_name] = st.text_input(
            label,
            key=widget_key,
            help=tr("help_runtime_variable_input", variable=variable_name),
        )
    return overrides

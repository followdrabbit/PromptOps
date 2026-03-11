from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from app.adapters.registry import get_provider_class
from app.core.config import AppConfig
from app.core.logging import set_log_level
from app.core.redaction import mask_secret
from app.core.secrets import SecretManager
from app.core.security import is_safe_path
from app.core.paths import ROOT_DIR
from app.domain import models
from app.infra.db import get_session
from app.services.audit_service import record_event
from app.services.endpoint_service import (
    clone_endpoint,
    create_endpoint,
    delete_endpoint,
    endpoints_to_records,
    get_endpoint,
    import_endpoint_records,
    list_endpoints,
    normalize_request_mode,
    update_endpoint,
    validate_endpoint_records,
)
from app.services.settings_service import set_setting
from app.services.test_service import (
    create_suite_prompt,
    create_suite,
    delete_suite_prompt,
    delete_suite,
    import_suite_records,
    import_tests_from_dataframe,
    list_suite_test_cases,
    load_suite_records_from_file,
    suites_to_records,
    update_suite_prompt,
    update_suite,
    validate_suite_import_records,
)
from app.services.provider_service import (
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    providers_to_records,
    update_provider,
    upsert_provider_records,
    validate_provider_records,
)
from app.ui import red_team_config
from app.ui.utils import get_runtime_settings, parse_json_field
from app.ui.i18n import get_translator


TEST_PROMPT_COLUMN = "prompt"
TEST_NOTES_COLUMN = "notes"
TEST_IMPORT_COLUMNS = [TEST_PROMPT_COLUMN, TEST_NOTES_COLUMN]
TEST_TEMPLATE_XLSX_DOWNLOAD_NAME = "cyberprompt_ai_test_suites_template.xlsx"
TEST_TEMPLATE_JSON_DOWNLOAD_NAME = "cyberprompt_ai_test_suites_template.json"
PROVIDER_TEMPLATE_XLSX_DOWNLOAD_NAME = "cyberprompt_ai_provider_template.xlsx"
PROVIDER_TEMPLATE_JSON_DOWNLOAD_NAME = "cyberprompt_ai_provider_template.json"
ENDPOINT_TEMPLATE_XLSX_DOWNLOAD_NAME = "cyberprompt_ai_endpoint_template.xlsx"
ENDPOINT_TEMPLATE_JSON_DOWNLOAD_NAME = "cyberprompt_ai_endpoint_template.json"
TEST_TEMPLATE_XLSX_PATHS = [
    "examples/default_imports/cyberprompt_ai_default_test_suites.xlsx",
]
TEST_TEMPLATE_JSON_PATHS = [
    "examples/default_imports/cyberprompt_ai_default_test_suites.json",
]
DEFAULT_IMPORT_FILES_DIR = (ROOT_DIR / "examples" / "default_imports").resolve()

RESERVED_TEMPLATE_VARS = {"API_TOKEN", "MODEL_NAME", "PROMPT"}
SUPPORTED_VARIABLE_TYPES = {"string", "number", "boolean", "json"}
TEMPLATE_VAR_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
TEMPLATE_VAR_PATTERNS = (
    re.compile(r"\{\{\s*(" + TEMPLATE_VAR_NAME + r")\s*\}\}"),
    re.compile(r"\$\{(" + TEMPLATE_VAR_NAME + r")\}"),
    re.compile(r"<(" + TEMPLATE_VAR_NAME + r")>"),
)
BARE_RESERVED_PATTERN = re.compile(r"\b(API_TOKEN|MODEL_NAME|PROMPT)\b")
ADDITIONAL_VARIABLES_EXAMPLE_DATA = {
    "REASONING": {
        "value": {"effort": "medium"},
        "type": "json",
    },
    "TEMPERATURE": {
        "value": 0.7,
        "type": "number",
    },
}
ADDITIONAL_VARIABLES_EXAMPLE_JSON = json.dumps(
    ADDITIONAL_VARIABLES_EXAMPLE_DATA,
    indent=2,
    ensure_ascii=False,
)


def _safe_resolve(path_input: str, base: Path) -> Path:
    candidate = (base / path_input).resolve() if not Path(path_input).is_absolute() else Path(path_input).resolve()
    return candidate


def _sanitize_filename(name: str, fallback: str = "import.xlsx") -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip()
    return cleaned or fallback


def _split_endpoint_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return base_url, path
    return url, "/"


def _extract_template_variables(*texts: str) -> list[str]:
    variables: set[str] = set()
    for text in texts:
        if not text:
            continue
        for pattern in TEMPLATE_VAR_PATTERNS:
            variables.update(pattern.findall(text))
        variables.update(BARE_RESERVED_PATTERN.findall(text))
    return sorted(variables)


def _normalize_variable_type(value: str | None) -> str:
    normalized = str(value or "string").strip().lower()
    if normalized not in SUPPORTED_VARIABLE_TYPES:
        raise ValueError("variables_type_invalid")
    return normalized


def _infer_variable_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


def _coerce_number(value: object) -> int | float:
    if isinstance(value, bool):
        raise ValueError("variables_number_invalid")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("variables_number_invalid")
        if "." in raw:
            return float(raw)
        return int(raw)
    raise ValueError("variables_number_invalid")


def _coerce_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError("variables_boolean_invalid")


def _coerce_json(value: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        return json.loads(raw)
    return value


def _coerce_variable_value(value: object, variable_type: str) -> object:
    if variable_type == "string":
        return "" if value is None else str(value)
    if variable_type == "number":
        return _coerce_number(value)
    if variable_type == "boolean":
        return _coerce_boolean(value)
    if variable_type == "json":
        return _coerce_json(value)
    raise ValueError("variables_type_invalid")


def _parse_variable_values(raw: str) -> tuple[dict[str, object], dict[str, str]]:
    if not raw.strip():
        return {}, {}
    parsed = parse_json_field(raw)
    if parsed is None:
        return {}, {}
    if not isinstance(parsed, dict):
        raise ValueError("variables_json_type")
    values: dict[str, object] = {}
    variable_types: dict[str, str] = {}
    for key, entry in parsed.items():
        variable_name = str(key).strip()
        if not variable_name:
            continue
        if isinstance(entry, dict) and ("value" in entry or "type" in entry):
            variable_type = _normalize_variable_type(str(entry.get("type", "string")))
            variable_value = _coerce_variable_value(entry.get("value"), variable_type)
        else:
            variable_type = _infer_variable_type(entry)
            variable_value = _coerce_variable_value(entry, variable_type)
        values[variable_name] = variable_value
        variable_types[variable_name] = variable_type
    return values, variable_types


def _serialize_variable_definitions(
    values: dict[str, object],
    variable_types: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        key: {
            "value": values.get(key),
            "type": variable_types.get(key, _infer_variable_type(values.get(key))),
        }
        for key in sorted(values.keys())
    }


def _truncate_text(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"


def _test_endpoint_connection(
    *,
    provider: str,
    endpoint_url: str,
    model_name: str,
    request_mode: str,
    custom_headers_raw: str,
    default_params_raw: str,
    response_paths: str,
    response_type: str,
    extra_variables_raw: str,
    api_token: str,
    stored_api_token: str | None = None,
    test_prompt: str,
    default_timeout: int,
    verify_ssl: bool,
    tr,
) -> tuple[str, int | None]:
    provider_name = (provider or "").strip()
    endpoint_url_value = (endpoint_url or "").strip()
    model_name_value = (model_name or "").strip()
    request_mode_value = (request_mode or "").strip()
    response_type_value = (response_type or "").strip() or "json"
    prompt_value = (test_prompt or "").strip()

    missing_fields: list[str] = []
    if not provider_name:
        missing_fields.append(tr("label_provider"))
    if not endpoint_url_value:
        missing_fields.append(tr("label_endpoint_url"))
    if not model_name_value:
        missing_fields.append(tr("label_model_name"))
    if not request_mode_value:
        missing_fields.append(tr("label_request_mode"))
    if not prompt_value:
        missing_fields.append(tr("label_test_prompt"))
    if missing_fields:
        raise ValueError(tr("error_required_fields", fields=", ".join(missing_fields)))

    custom_headers = parse_json_field(custom_headers_raw) or {}
    default_params = parse_json_field(default_params_raw) or {}
    custom_variables, _custom_variable_types = _parse_variable_values(extra_variables_raw)
    if not isinstance(custom_headers, dict) or not isinstance(default_params, dict):
        raise ValueError(tr("error_invalid_json"))

    detected_variables = _extract_template_variables(custom_headers_raw, default_params_raw)
    missing_variables = [
        variable
        for variable in detected_variables
        if variable not in RESERVED_TEMPLATE_VARS and variable not in custom_variables
    ]
    if missing_variables:
        raise ValueError(tr("error_missing_template_variables", variables=", ".join(missing_variables)))

    resolved_api_token = (api_token or "").strip() or (stored_api_token or "").strip()
    if "API_TOKEN" in detected_variables and not resolved_api_token:
        raise ValueError(tr("error_api_token_required"))

    base_url, endpoint_path = _split_endpoint_url(endpoint_url_value)
    endpoint_config = SimpleNamespace(
        name="connection-test",
        provider=provider_name,
        base_url=base_url,
        endpoint_path=endpoint_path,
        model_name=model_name_value,
        request_mode=normalize_request_mode(request_mode_value),
        auth_type="none",
        auth_header=None,
        auth_prefix=None,
        custom_headers=custom_headers,
        default_params=default_params,
        timeout=int(default_timeout),
        retry_count=0,
        response_paths=response_paths or None,
        response_type=response_type_value,
    )

    runtime_variables = dict(custom_variables)
    runtime_variables["MODEL_NAME"] = model_name_value
    if resolved_api_token:
        runtime_variables["API_TOKEN"] = resolved_api_token

    provider_adapter = get_provider_class(provider_name)(
        endpoint_config,
        runtime_variables,
        verify_ssl=verify_ssl,
    )
    response = provider_adapter.send_prompt(
        [{"role": "user", "content": prompt_value}],
        {"timeout": int(default_timeout)},
    )
    return response.content or "", response.latency_ms


def _load_provider_records(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        dataframe = pd.read_excel(path)
        return dataframe.to_dict(orient="records")

    if suffix == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            if isinstance(content.get("providers"), list):
                content = content["providers"]
            else:
                content = [content]
        if not isinstance(content, list):
            raise ValueError("invalid_json_root")
        if not all(isinstance(item, dict) for item in content):
            raise ValueError("invalid_json_records")
        return [dict(item) for item in content]

    raise ValueError("unsupported_file_type")


def _load_endpoint_records(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        dataframe = pd.read_excel(path)
        return dataframe.to_dict(orient="records")

    if suffix == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            if isinstance(content.get("endpoints"), list):
                content = content["endpoints"]
            else:
                content = [content]
        if not isinstance(content, list):
            raise ValueError("invalid_json_root")
        if not all(isinstance(item, dict) for item in content):
            raise ValueError("invalid_json_records")
        return [dict(item) for item in content]

    raise ValueError("unsupported_file_type")


def _load_template_bytes(relative_path: str) -> bytes | None:
    template_path = (ROOT_DIR / relative_path).resolve()
    if not is_safe_path(template_path, ROOT_DIR) or not template_path.exists() or not template_path.is_file():
        return None
    try:
        return template_path.read_bytes()
    except OSError:
        return None


def _normalize_test_prompt_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    lowered_columns = {str(column).strip().lower(): column for column in df.columns}
    prompt_column = lowered_columns.get(TEST_PROMPT_COLUMN)
    notes_column = lowered_columns.get(TEST_NOTES_COLUMN)
    if prompt_column is None:
        raise ValueError("missing_prompt_column")

    normalized = pd.DataFrame(
        {
            TEST_PROMPT_COLUMN: df[prompt_column],
            TEST_NOTES_COLUMN: df[notes_column] if notes_column is not None else None,
        }
    )
    return normalized


def _load_test_prompt_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _normalize_test_prompt_dataframe(pd.read_excel(path))

    if suffix == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            if isinstance(content.get("tests"), list):
                content = content["tests"]
            elif isinstance(content.get("prompts"), list):
                content = content["prompts"]
            else:
                content = [content]
        if not isinstance(content, list):
            raise ValueError("invalid_json_root")
        if not all(isinstance(item, dict) for item in content):
            raise ValueError("invalid_json_records")
        return _normalize_test_prompt_dataframe(pd.DataFrame(content))

    raise ValueError("unsupported_file_type")


def _scan_test_prompt_files(directory: Path, import_base: Path) -> list[Path]:
    if not is_safe_path(directory, import_base):
        raise ValueError("directory_outside_import_base")
    if not directory.exists():
        raise ValueError("directory_missing")
    files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".xlsx", ".json"}]
    return sorted(files)


def _build_prompt_import_mapping(df: pd.DataFrame) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {field: None for field in TEST_IMPORT_COLUMNS}
    for field in TEST_IMPORT_COLUMNS:
        if field in df.columns:
            mapping[field] = field
    return mapping


def _render_test_template_downloads(tr, key_prefix: str) -> None:
    st.markdown(f"**{tr('section_templates')}**")
    test_template_xlsx = None
    for candidate in TEST_TEMPLATE_XLSX_PATHS:
        test_template_xlsx = _load_template_bytes(candidate)
        if test_template_xlsx is not None:
            break

    test_template_json = None
    for candidate in TEST_TEMPLATE_JSON_PATHS:
        test_template_json = _load_template_bytes(candidate)
        if test_template_json is not None:
            break
    template_cols = st.columns(2, gap="small")
    template_cols[0].download_button(
        tr("button_download_test_template_xlsx"),
        data=test_template_xlsx or b"",
        file_name=TEST_TEMPLATE_XLSX_DOWNLOAD_NAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_download_test_template_xlsx",
        disabled=test_template_xlsx is None,
        width="stretch",
    )
    template_cols[1].download_button(
        tr("button_download_test_template_json"),
        data=test_template_json or b"",
        file_name=TEST_TEMPLATE_JSON_DOWNLOAD_NAME,
        mime="application/json",
        key=f"{key_prefix}_download_test_template_json",
        disabled=test_template_json is None,
        width="stretch",
    )
    if test_template_xlsx is None or test_template_json is None:
        st.warning(tr("warning_template_files_missing"))


def _render_default_import_files_hint(tr) -> None:
    if DEFAULT_IMPORT_FILES_DIR.exists() and DEFAULT_IMPORT_FILES_DIR.is_dir():
        st.caption(tr("label_default_import_files_dir", path=DEFAULT_IMPORT_FILES_DIR))


def render(context: dict) -> None:
    config: AppConfig = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
    tr = get_translator(lang)

    config_sections = {
        "general": tr("tab_general_settings"),
        "providers": tr("tab_provider_settings"),
        "endpoints": tr("tab_endpoint_settings"),
        "tests": tr("tab_test_settings"),
        "red_teaming": tr("tab_red_team_settings"),
    }
    config_section_key = "config_section_nav"
    if st.session_state.get(config_section_key) not in config_sections:
        st.session_state[config_section_key] = "general"
    st.sidebar.markdown("---")
    st.sidebar.subheader(tr("nav_configuration"))
    st.sidebar.radio(
        tr("label_configuration_page"),
        options=list(config_sections.keys()),
        format_func=lambda key: config_sections[key],
        key=config_section_key,
    )
    config_page = st.session_state[config_section_key]
    config_intro = {
        "general": (
            tr("config_general_badge"),
            tr("config_general_title"),
            tr("config_general_subtitle"),
        ),
        "providers": (
            tr("config_providers_badge"),
            tr("config_providers_title"),
            tr("config_providers_subtitle"),
        ),
        "endpoints": (
            tr("config_endpoints_badge"),
            tr("config_endpoints_title"),
            tr("config_endpoints_subtitle"),
        ),
        "tests": (
            tr("config_tests_badge"),
            tr("config_tests_title"),
            tr("config_tests_subtitle"),
        ),
        "red_teaming": (
            tr("config_red_team_badge"),
            tr("config_red_team_title"),
            tr("config_red_team_subtitle"),
        ),
    }
    badge, title, subtitle = config_intro.get(config_page, config_intro["general"])
    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{badge}</span>
            <div class="intro-title">{title}</div>
            <p class="intro-subtitle">
                {subtitle}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if config_page == "general":
        with get_session(session_factory) as session:
            settings = get_runtime_settings(session, config)

            language_options = ["en", "pt-BR"]
            language_labels = {"en": tr("language_en"), "pt-BR": tr("language_ptbr")}
            if (
                "app_language" not in st.session_state
                or st.session_state["app_language"] not in language_options
                or st.session_state["app_language"] != settings["language"]
            ):
                st.session_state["app_language"] = settings["language"]

            def _apply_language() -> None:
                with get_session(session_factory) as lang_session:
                    set_setting(lang_session, "language", st.session_state["app_language"])

            st.selectbox(
                tr("label_application_language"),
                language_options,
                format_func=lambda val: language_labels.get(val, val),
                key="app_language",
                on_change=_apply_language,
            )

            with st.form("general_settings"):
                log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                log_level = st.selectbox(
                    tr("label_log_level"),
                    log_levels,
                    index=log_levels.index(settings["log_level"]) if settings["log_level"] in log_levels else 1,
                )
                default_timeout = st.number_input(
                    tr("label_default_timeout"),
                    min_value=5,
                    max_value=300,
                    value=int(settings["default_timeout"]),
                )
                output_dir = st.text_input(tr("label_output_dir"), value=settings["output_dir"])
                import_dir = st.text_input(tr("label_import_dir"), value=settings["import_dir"])
                ssl_verify = st.checkbox(
                    tr("label_verify_ssl"),
                    value=settings.get("ssl_verify", True),
                    help=tr("help_verify_ssl"),
                )
                log_retention_days = st.number_input(
                    tr("label_log_retention"),
                    min_value=1,
                    max_value=365,
                    value=int(settings["log_retention_days"]),
                )
                secure_storage = st.selectbox(tr("label_secure_storage"), ["fernet"], index=0)
                audit_verbosity = st.selectbox(
                    tr("label_audit_verbosity"),
                    ["standard", "verbose"],
                    format_func=lambda val: tr("audit_standard") if val == "standard" else tr("audit_verbose"),
                    index=0 if settings["audit_verbosity"] == "standard" else 1,
                )

                save = st.form_submit_button(tr("button_save_settings"))
                if save:
                    output_path = _safe_resolve(output_dir, ROOT_DIR)
                    import_path = _safe_resolve(import_dir, ROOT_DIR)
                    if not is_safe_path(output_path, ROOT_DIR) or not is_safe_path(import_path, ROOT_DIR):
                        st.error(tr("error_dirs_within_project"))
                    else:
                        set_setting(session, "log_level", log_level)
                        set_setting(session, "default_timeout", str(default_timeout))
                        set_setting(session, "output_dir", str(output_dir))
                        set_setting(session, "import_dir", str(import_dir))
                        set_setting(session, "ssl_verify", str(ssl_verify))
                        set_setting(session, "log_retention_days", str(log_retention_days))
                        set_setting(session, "secure_storage", secure_storage)
                        set_setting(session, "audit_verbosity", audit_verbosity)
                        set_log_level(log_level)
                        record_event(session, "update", "settings", "general")
                        session.commit()
                        st.success(tr("msg_settings_saved"))
                        st.rerun()

    if config_page == "providers":
        with get_session(session_factory) as session:
            provider_import_flash_key = "provider_import_flash_messages"
            flash_messages = st.session_state.pop(provider_import_flash_key, [])
            for level, message in flash_messages:
                if level == "warning":
                    st.warning(message)
                elif level == "error":
                    st.error(message)
                else:
                    st.success(message)

            st.subheader(tr("section_registered_providers"))
            providers = list_providers(session)
            if providers:
                st.dataframe(
                    [
                        {
                            tr("table_id"): provider.id,
                            tr("table_name"): provider.name,
                            tr("label_provider_notes"): provider.notes,
                        }
                        for provider in providers
                    ],
                    width="stretch",
                )
            else:
                st.info(tr("no_providers"))

            provider_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete"), tr("tab_import_export")])

            with provider_tabs[0]:
                st.subheader(tr("section_create_provider"))
                st.info(tr("provider_tips"))
                with st.form("create_provider"):
                    name = st.text_input(tr("label_provider_name"), help=tr("help_provider_name"))
                    notes = st.text_area(tr("label_provider_notes"), help=tr("help_provider_notes"))
                    submit = st.form_submit_button(tr("button_create_provider"))

                    if submit:
                        try:
                            data = {
                                "name": name,
                                "notes": notes or None,
                            }
                            create_provider(session, data)
                            session.commit()
                            st.success(tr("msg_provider_created"))
                            st.rerun()
                        except Exception as exc:
                            st.error(tr("error_failed_create_provider", error=exc))

            with provider_tabs[1]:
                st.subheader(tr("section_edit_provider"))
                if not providers:
                    st.info(tr("no_providers"))
                else:
                    selected_id = st.selectbox(
                        tr("label_select_provider"),
                        options=[None] + [provider.id for provider in providers],
                        format_func=lambda provider_id: next(
                            provider.name for provider in providers if provider.id == provider_id
                        )
                        if provider_id is not None
                        else tr("option_select"),
                        key="edit_provider_select",
                    )
                    if selected_id is None:
                        st.info(tr("info_select_item_to_edit"))
                    else:
                        provider = get_provider(session, selected_id)

                        with st.form("edit_provider"):
                            name = st.text_input(
                                tr("label_provider_name"),
                                value=provider.name if provider else "",
                                help=tr("help_provider_name"),
                            )
                            notes = st.text_area(
                                tr("label_provider_notes"),
                                value=provider.notes or "",
                                help=tr("help_provider_notes"),
                            )
                            update = st.form_submit_button(tr("button_update_provider"))

                            if update:
                                try:
                                    data = {
                                        "name": name,
                                        "notes": notes or None,
                                    }
                                    update_provider(session, provider, data)
                                    session.commit()
                                    st.success(tr("msg_provider_updated"))
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_failed_update_provider", error=exc))

            with provider_tabs[2]:
                st.subheader(tr("section_delete_provider"))
                if not providers:
                    st.info(tr("no_providers"))
                else:
                    provider_delete_id = st.selectbox(
                        tr("label_select_provider_to_delete"),
                        options=[provider.id for provider in providers],
                        format_func=lambda provider_id: next(
                            provider.name for provider in providers if provider.id == provider_id
                        ),
                        key="delete_provider_select",
                    )
                    provider_to_delete = get_provider(session, provider_delete_id)
                    pending_delete_provider_key = "pending_delete_provider_id"
                    confirm_provider_delete_key = f"confirm_delete_provider_{provider_to_delete.id}"
                    confirm_provider_delete = st.checkbox(
                        tr("label_confirm_delete_provider"),
                        key=confirm_provider_delete_key,
                    )
                    if st.button(tr("button_delete_provider"), key=f"delete_provider_{provider_to_delete.id}"):
                        if not confirm_provider_delete:
                            st.warning(tr("warning_confirm_delete_provider"))
                        else:
                            st.session_state[pending_delete_provider_key] = provider_to_delete.id
                            st.rerun()

                    if st.session_state.get(pending_delete_provider_key) == provider_to_delete.id:
                        st.warning(tr("confirm_delete_provider", name=provider_to_delete.name))
                        confirm_cols = st.columns(2, gap="small")
                        if confirm_cols[0].button(
                            tr("button_confirm_delete_provider"),
                            key=f"confirm_delete_provider_final_{provider_to_delete.id}",
                            width="stretch",
                        ):
                            try:
                                delete_provider(session, provider_to_delete)
                                session.commit()
                                st.session_state.pop(pending_delete_provider_key, None)
                                st.success(tr("msg_provider_deleted"))
                                st.rerun()
                            except Exception as exc:
                                st.error(tr("error_failed_delete_provider", error=exc))
                        if confirm_cols[1].button(
                            tr("button_cancel_delete_provider"),
                            key=f"cancel_delete_provider_{provider_to_delete.id}",
                            width="stretch",
                        ):
                            st.session_state.pop(pending_delete_provider_key, None)
                            st.rerun()

            with provider_tabs[3]:
                st.subheader(tr("section_provider_import_export"))
                st.info(tr("provider_import_export_tips"))

                settings = get_runtime_settings(session, config)
                import_base = _safe_resolve(settings["import_dir"], ROOT_DIR)
                output_base = _safe_resolve(settings["output_dir"], ROOT_DIR)
                if not is_safe_path(import_base, ROOT_DIR) or not is_safe_path(output_base, ROOT_DIR):
                    st.error(tr("error_provider_dirs_within_project"))
                else:
                    st.caption(tr("label_approved_import_dir", path=import_base))
                    st.caption(tr("label_approved_output_dir", path=output_base))
                    _render_default_import_files_hint(tr)
                    st.markdown(f"**{tr('section_templates')}**")
                    provider_template_xlsx = _load_template_bytes("examples/sample_providers.xlsx")
                    provider_template_json = _load_template_bytes("examples/sample_providers.json")
                    template_cols = st.columns(2, gap="small")
                    template_cols[0].download_button(
                        tr("button_download_provider_template_xlsx"),
                        data=provider_template_xlsx or b"",
                        file_name=PROVIDER_TEMPLATE_XLSX_DOWNLOAD_NAME,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_provider_template_xlsx",
                        disabled=provider_template_xlsx is None,
                        width="stretch",
                    )
                    template_cols[1].download_button(
                        tr("button_download_provider_template_json"),
                        data=provider_template_json or b"",
                        file_name=PROVIDER_TEMPLATE_JSON_DOWNLOAD_NAME,
                        mime="application/json",
                        key="download_provider_template_json",
                        disabled=provider_template_json is None,
                        width="stretch",
                    )
                    if provider_template_xlsx is None or provider_template_json is None:
                        st.warning(tr("warning_template_files_missing"))

                    st.markdown(f"**{tr('section_import_providers')}**")
                    st.caption(tr("label_provider_supported_formats"))

                    import_source: Path | None = None
                    uploaded = st.file_uploader(
                        tr("label_upload_provider_file"),
                        type=["xlsx", "json"],
                        key="provider_import_upload",
                    )
                    if uploaded:
                        safe_name = _sanitize_filename(uploaded.name, fallback="providers_import.xlsx")
                        destination = (import_base / safe_name).resolve()
                        if not is_safe_path(destination, import_base):
                            st.error(tr("error_provider_import_path"))
                        elif destination.suffix.lower() not in {".xlsx", ".json"}:
                            st.error(tr("error_provider_import_file_type"))
                        else:
                            import_base.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(uploaded.getbuffer())
                            import_source = destination

                    if import_source:
                        try:
                            raw_records = _load_provider_records(import_source)
                            normalized_records, validation_errors = validate_provider_records(raw_records)
                        except (json.JSONDecodeError, ValueError) as exc:
                            st.error(tr("error_provider_import_parse", error=exc))
                            raw_records = []
                            normalized_records = []
                            validation_errors = []
                        except Exception as exc:
                            st.error(tr("error_provider_import_parse", error=exc))
                            raw_records = []
                            normalized_records = []
                            validation_errors = []
                        else:
                            st.caption(
                                tr(
                                    "label_provider_import_loaded",
                                    source=import_source.name,
                                    count=len(raw_records),
                                )
                            )

                        if validation_errors:
                            st.error(tr("error_provider_import_validation"))
                            for issue in validation_errors:
                                st.write(f"- {issue}")

                        if normalized_records and not validation_errors:
                            st.dataframe(normalized_records, width="stretch")
                            if st.button(tr("button_import_providers"), key="button_import_providers"):
                                try:
                                    stats = upsert_provider_records(session, normalized_records)
                                    record_event(
                                        session,
                                        "import",
                                        "provider",
                                        after_value={
                                            "source": import_source.name,
                                            "format": import_source.suffix.lower().lstrip("."),
                                            "rows": len(normalized_records),
                                            "created": stats["created"],
                                            "skipped_existing": stats["skipped_existing"],
                                        },
                                    )
                                    session.commit()
                                    messages: list[tuple[str, str]] = []
                                    if stats["skipped_existing_names"]:
                                        messages.append(
                                            (
                                                "warning",
                                                tr(
                                                    "warning_provider_existing_skipped",
                                                    names=", ".join(stats["skipped_existing_names"]),
                                                ),
                                            )
                                        )
                                    messages.append(
                                        (
                                            "success",
                                            tr(
                                                "msg_providers_imported",
                                                created=stats["created"],
                                                skipped_existing=stats["skipped_existing"],
                                            ),
                                        )
                                    )
                                    st.session_state[provider_import_flash_key] = messages
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_provider_import_failed", error=exc))

                    st.markdown(f"**{tr('section_export_providers')}**")
                    if not providers:
                        st.info(tr("no_providers"))
                    else:
                        export_format = st.selectbox(
                            tr("label_provider_export_format"),
                            ["xlsx", "json"],
                            format_func=lambda value: value.upper(),
                            key="provider_export_format",
                        )
                        default_export_name = (
                            f"providers_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
                        )
                        export_filename = st.text_input(
                            tr("label_provider_export_filename"),
                            value=default_export_name,
                            key="provider_export_filename",
                        )
                        allow_overwrite = st.checkbox(
                            tr("label_provider_export_overwrite"),
                            value=False,
                            key="provider_export_allow_overwrite",
                        )
                        if st.button(tr("button_export_providers"), key="button_export_providers"):
                            safe_filename = _sanitize_filename(
                                export_filename,
                                fallback=f"providers_backup.{export_format}",
                            )
                            safe_path_name = Path(safe_filename)
                            if safe_path_name.suffix.lower() != f".{export_format}":
                                safe_filename = f"{safe_path_name.stem}.{export_format}"
                            target_path = _safe_resolve(safe_filename, output_base)
                            if not is_safe_path(target_path, output_base):
                                st.error(tr("error_provider_export_path"))
                            elif target_path.exists() and not allow_overwrite:
                                st.error(tr("error_provider_export_exists"))
                            else:
                                try:
                                    output_base.mkdir(parents=True, exist_ok=True)
                                    records = providers_to_records(providers)
                                    if export_format == "xlsx":
                                        pd.DataFrame(records).to_excel(target_path, index=False)
                                    else:
                                        target_path.write_text(
                                            json.dumps(records, indent=2, ensure_ascii=False),
                                            encoding="utf-8",
                                        )
                                    record_event(
                                        session,
                                        "export",
                                        "provider",
                                        after_value={
                                            "path": str(target_path),
                                            "format": export_format,
                                            "count": len(records),
                                        },
                                    )
                                    session.commit()
                                    st.success(tr("msg_providers_exported", path=target_path))
                                except Exception as exc:
                                    st.error(tr("error_provider_export_failed", error=exc))

    if config_page == "endpoints":
        with get_session(session_factory) as session:
            endpoint_import_flash_key = "endpoint_import_flash_messages"
            endpoint_clone_flash_key = "endpoint_clone_flash_message"
            flash_messages = st.session_state.pop(endpoint_import_flash_key, [])
            for level, message in flash_messages:
                if level == "warning":
                    st.warning(message)
                elif level == "error":
                    st.error(message)
                else:
                    st.success(message)
            clone_flash_message = st.session_state.pop(endpoint_clone_flash_key, None)
            if clone_flash_message:
                st.success(clone_flash_message)

            st.subheader(tr("section_registered_endpoints"))
            settings = get_runtime_settings(session, config)
            endpoints = list_endpoints(session)
            providers = list_providers(session)
            provider_names = [provider.name for provider in providers]
            provider_display = {provider.name: provider.display_name or provider.name for provider in providers}
            if endpoints:
                st.dataframe(
                    [
                        {
                            tr("table_id"): ep.id,
                            tr("table_name"): ep.name,
                            tr("table_provider"): ep.provider,
                            tr("table_model"): ep.model_name,
                            tr("table_request_mode"): (
                                tr("option_request_mode_responses")
                                if normalize_request_mode(getattr(ep, "request_mode", "responses")) == "responses"
                                else tr("option_request_mode_completions")
                            ),
                        }
                        for ep in endpoints
                    ],
                    width="stretch",
                )
            else:
                st.info(tr("no_endpoints"))

            endpoint_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete"), tr("tab_import_export")])

            with endpoint_tabs[0]:
                st.subheader(tr("section_create_endpoint"))
                if not provider_names:
                    st.info(tr("no_providers"))
                st.info(tr("endpoint_tips"))
                st.markdown(f"**{tr('label_additional_variables_example')}**")
                st.code(ADDITIONAL_VARIABLES_EXAMPLE_JSON, language="json")
                create_defaults = {
                    "create_ep_name": "",
                    "create_ep_provider_select": "",
                    "create_ep_provider_text": "",
                    "create_ep_url": "",
                    "create_ep_model_name": "",
                    "create_ep_request_mode": "",
                    "create_ep_api_token": "",
                    "create_ep_headers": "",
                    "create_ep_body": "",
                    "create_ep_response_paths": "",
                    "create_ep_response_type": "",
                    "create_ep_extra_vars": "",
                    "create_ep_test_prompt": tr("default_test_prompt"),
                }
                for state_key, state_value in create_defaults.items():
                    if state_key not in st.session_state:
                        st.session_state[state_key] = state_value

                if st.button(tr("button_fill_endpoint_example"), key="button_fill_endpoint_example"):
                    st.session_state["create_ep_name"] = "Example Endpoint"
                    if provider_names:
                        if "OpenAI" in provider_names:
                            st.session_state["create_ep_provider_select"] = "OpenAI"
                        else:
                            st.session_state["create_ep_provider_select"] = provider_names[0]
                    else:
                        st.session_state["create_ep_provider_text"] = "OpenAI"
                    st.session_state["create_ep_url"] = "https://api.openai.com/v1/responses"
                    st.session_state["create_ep_model_name"] = "gpt-4.1-mini"
                    st.session_state["create_ep_request_mode"] = "responses"
                    st.session_state["create_ep_headers"] = (
                        '{\n'
                        '  "Content-Type": "application/json",\n'
                        '  "Authorization": "Bearer {{API_TOKEN}}"\n'
                        '}'
                    )
                    st.session_state["create_ep_body"] = (
                        '{\n'
                        '  "model": "{{MODEL_NAME}}",\n'
                        '  "input": "{{PROMPT}}",\n'
                        '  "max_output_tokens": 1000,\n'
                        '  "temperature": "{{TEMPERATURE}}",\n'
                        '  "reasoning": "{{REASONING}}"\n'
                        '}'
                    )
                    st.session_state["create_ep_response_paths"] = "$output[1].content[0].text\n$output[0].content[0].text"
                    st.session_state["create_ep_response_type"] = "json"
                    st.session_state["create_ep_extra_vars"] = ADDITIONAL_VARIABLES_EXAMPLE_JSON

                if st.button(
                    tr("button_use_additional_variables_example"),
                    key="button_use_additional_variables_example_create",
                ):
                    st.session_state["create_ep_extra_vars"] = ADDITIONAL_VARIABLES_EXAMPLE_JSON

                with st.form("create_endpoint"):
                    name = st.text_input(
                        tr("label_friendly_name"),
                        help=tr("help_friendly_name"),
                        key="create_ep_name",
                    )
                    if provider_names:
                        provider = st.selectbox(
                            tr("label_provider"),
                            [""] + provider_names,
                            format_func=lambda name: tr("option_select_provider")
                            if not name
                            else provider_display.get(name, name),
                            help=tr("help_endpoint_provider"),
                            key="create_ep_provider_select",
                        )
                    else:
                        provider = st.text_input(
                            tr("label_provider"),
                            help=tr("help_endpoint_provider"),
                            key="create_ep_provider_text",
                        )
                    endpoint_url = st.text_input(
                        tr("label_endpoint_url"),
                        help=tr("help_endpoint_url"),
                        key="create_ep_url",
                    )
                    model_name = st.text_input(
                        tr("label_model_name"),
                        help=tr("help_model_name"),
                        key="create_ep_model_name",
                    )
                    request_mode = st.selectbox(
                        tr("label_request_mode"),
                        ["", "responses", "completions"],
                        format_func=lambda val: tr("option_select")
                        if not val
                        else (
                            tr("option_request_mode_responses")
                            if val == "responses"
                            else tr("option_request_mode_completions")
                        ),
                        help=tr("help_request_mode"),
                        key="create_ep_request_mode",
                    )
                    api_token = st.text_input(
                        tr("label_api_token"),
                        type="password",
                        help=tr("help_api_token"),
                        key="create_ep_api_token",
                    )
                    custom_headers_raw = st.text_area(
                        tr("label_headers"),
                        help=tr("help_headers"),
                        key="create_ep_headers",
                    )
                    default_params_raw = st.text_area(
                        tr("label_body"),
                        help=tr("help_body"),
                        key="create_ep_body",
                    )
                    response_paths = st.text_area(
                        tr("label_response_paths"),
                        help=tr("help_response_paths"),
                        key="create_ep_response_paths",
                    )
                    response_type = st.selectbox(
                        tr("label_response_type"),
                        ["", "json", "text"],
                        format_func=lambda val: tr("option_select")
                        if not val
                        else (tr("option_json") if val == "json" else tr("option_text")),
                        help=tr("help_response_type"),
                        key="create_ep_response_type",
                    )
                    extra_variables_raw = st.text_area(
                        tr("label_additional_variables"),
                        help=tr("help_additional_variables"),
                        key="create_ep_extra_vars",
                    )
                    test_prompt = st.text_input(
                        tr("label_test_prompt"),
                        help=tr("help_test_prompt"),
                        key="create_ep_test_prompt",
                    )
                    detected_variables = _extract_template_variables(custom_headers_raw, default_params_raw)
                    st.caption(
                        tr(
                            "label_detected_variables",
                            values=", ".join(detected_variables) if detected_variables else tr("option_none"),
                        )
                    )
                    test_connection = st.form_submit_button(
                        tr("button_test_endpoint_connection"),
                        type="secondary",
                    )
                    submit = st.form_submit_button(tr("button_create_endpoint"))

                    if test_connection:
                        try:
                            with st.spinner(tr("msg_testing_endpoint_connection")):
                                response_content, latency_ms = _test_endpoint_connection(
                                    provider=provider,
                                    endpoint_url=endpoint_url,
                                    model_name=model_name,
                                    request_mode=request_mode,
                                    custom_headers_raw=custom_headers_raw,
                                    default_params_raw=default_params_raw,
                                    response_paths=response_paths,
                                    response_type=response_type,
                                    extra_variables_raw=extra_variables_raw,
                                    api_token=api_token,
                                    test_prompt=test_prompt,
                                    default_timeout=int(settings["default_timeout"]),
                                    verify_ssl=settings.get("ssl_verify", True),
                                    tr=tr,
                                )
                            st.success(tr("msg_test_endpoint_connection_success", latency=latency_ms or 0))
                            if response_content:
                                st.caption(tr("label_test_connection_response_preview"))
                                st.code(_truncate_text(response_content), language="text")
                        except (json.JSONDecodeError, ValueError) as exc:
                            st.error(str(exc))
                        except Exception as exc:
                            st.error(tr("error_test_endpoint_connection_failed", error=exc))
                    elif submit:
                        try:
                            required_fields: list[str] = []
                            if not name.strip():
                                required_fields.append(tr("label_friendly_name"))
                            if not provider.strip():
                                required_fields.append(tr("label_provider"))
                            if not endpoint_url.strip():
                                required_fields.append(tr("label_endpoint_url"))
                            if not model_name.strip():
                                required_fields.append(tr("label_model_name"))
                            if not request_mode.strip():
                                required_fields.append(tr("label_request_mode"))
                            if not response_type.strip():
                                required_fields.append(tr("label_response_type"))
                            if required_fields:
                                st.error(tr("error_required_fields", fields=", ".join(required_fields)))
                            else:
                                custom_headers = parse_json_field(custom_headers_raw) or {}
                                default_params = parse_json_field(default_params_raw) or {}
                                custom_variables, custom_variable_types = _parse_variable_values(extra_variables_raw)
                                if not isinstance(custom_headers, dict) or not isinstance(default_params, dict):
                                    raise ValueError("json_type")
                                missing_variables = [
                                    variable
                                    for variable in detected_variables
                                    if variable not in RESERVED_TEMPLATE_VARS and variable not in custom_variables
                                ]
                                if missing_variables:
                                    st.error(tr("error_missing_template_variables", variables=", ".join(missing_variables)))
                                elif "API_TOKEN" in detected_variables and not api_token.strip():
                                    st.error(tr("error_api_token_required"))
                                else:
                                    base_url, endpoint_path = _split_endpoint_url(endpoint_url)
                                    variable_values = dict(custom_variables)
                                    if api_token.strip():
                                        variable_values["API_TOKEN"] = api_token.strip()
                                    variable_values["MODEL_NAME"] = model_name
                                    data = {
                                        "name": name,
                                        "provider": provider,
                                        "base_url": base_url,
                                        "endpoint_path": endpoint_path,
                                        "model_name": model_name,
                                        "request_mode": normalize_request_mode(request_mode),
                                        "auth_type": "none",
                                        "auth_header": None,
                                        "auth_prefix": None,
                                        "custom_headers": custom_headers,
                                        "default_params": default_params,
                                        "timeout": int(settings["default_timeout"]),
                                        "retry_count": 0,
                                        "response_paths": response_paths or None,
                                        "response_type": response_type,
                                    }
                                    create_endpoint(
                                        session,
                                        data,
                                        None,
                                        secret_type="none",
                                        variable_values=variable_values,
                                        variable_types=custom_variable_types,
                                    )
                                    session.commit()
                                    st.success(tr("msg_endpoint_created"))
                                    st.rerun()
                        except (json.JSONDecodeError, ValueError):
                            st.error(tr("error_invalid_json"))
                        except Exception as exc:
                            st.error(tr("error_failed_create_endpoint", error=exc))

            with endpoint_tabs[1]:
                st.subheader(tr("section_edit_endpoint"))
                if not endpoints:
                    st.info(tr("no_endpoints"))
                else:
                    pending_edit_endpoint_select_key = "pending_edit_endpoint_select"
                    valid_endpoint_ids = {ep.id for ep in endpoints}
                    if pending_edit_endpoint_select_key in st.session_state:
                        pending_selected_id = st.session_state.pop(pending_edit_endpoint_select_key)
                        if pending_selected_id in valid_endpoint_ids or pending_selected_id is None:
                            st.session_state["edit_endpoint_select"] = pending_selected_id
                    selected_id = st.selectbox(
                        tr("label_select_endpoint"),
                        options=[None] + [ep.id for ep in endpoints],
                        format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id)
                        if ep_id is not None
                        else tr("option_select"),
                        key="edit_endpoint_select",
                    )
                    if selected_id is None:
                        st.info(tr("info_select_item_to_edit"))
                    else:
                        endpoint = get_endpoint(session, selected_id)
                        secret_manager = SecretManager()
                        endpoint_variables = secret_manager.get_variables(session, endpoint.id) if endpoint else {}
                        endpoint_variable_types = (
                            secret_manager.get_variable_types(session, endpoint.id) if endpoint else {}
                        )
                        st.markdown(f"**{tr('section_clone_endpoint')}**")
                        clone_name_key = f"clone_endpoint_name_{endpoint.id}"
                        if clone_name_key not in st.session_state:
                            st.session_state[clone_name_key] = f"{endpoint.name} (Copy)"
                        with st.form(f"clone_endpoint_form_{endpoint.id}"):
                            clone_name = st.text_input(
                                tr("label_clone_endpoint_name"),
                                key=clone_name_key,
                                help=tr("help_clone_endpoint_name"),
                            )
                            clone_submit = st.form_submit_button(tr("button_clone_endpoint"))
                            if clone_submit:
                                try:
                                    cloned_endpoint = clone_endpoint(session, endpoint, clone_name)
                                    session.commit()
                                    st.session_state[pending_edit_endpoint_select_key] = cloned_endpoint.id
                                    st.session_state[endpoint_clone_flash_key] = tr(
                                        "msg_endpoint_cloned",
                                        source=endpoint.name,
                                        clone=cloned_endpoint.name,
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_failed_clone_endpoint", error=exc))

                        stored_api_token = str(endpoint_variables.get("API_TOKEN", "") or "")
                        masked_token = mask_secret(stored_api_token, show_last=4) if stored_api_token else tr("secret_not_set")
                        stored_custom_variables = {
                            key: value
                            for key, value in endpoint_variables.items()
                            if key not in RESERVED_TEMPLATE_VARS
                        }
                        stored_custom_variable_types = {
                            key: endpoint_variable_types.get(key, _infer_variable_type(value))
                            for key, value in stored_custom_variables.items()
                        }
                        stored_custom_variable_definitions = _serialize_variable_definitions(
                            stored_custom_variables,
                            stored_custom_variable_types,
                        )
                        edit_extra_vars_key = f"edit_ep_extra_vars_{endpoint.id}"
                        if edit_extra_vars_key not in st.session_state:
                            st.session_state[edit_extra_vars_key] = (
                                json.dumps(stored_custom_variable_definitions, indent=2, ensure_ascii=False)
                                if stored_custom_variable_definitions
                                else "{}"
                            )
                        st.markdown(f"**{tr('label_additional_variables_example')}**")
                        st.code(ADDITIONAL_VARIABLES_EXAMPLE_JSON, language="json")
                        if st.button(
                            tr("button_use_additional_variables_example"),
                            key=f"button_use_additional_variables_example_edit_{endpoint.id}",
                        ):
                            st.session_state[edit_extra_vars_key] = ADDITIONAL_VARIABLES_EXAMPLE_JSON
                        edit_test_prompt_key = f"edit_ep_test_prompt_{endpoint.id}"
                        if edit_test_prompt_key not in st.session_state:
                            st.session_state[edit_test_prompt_key] = tr("default_test_prompt")

                        with st.form("edit_endpoint"):
                            name = st.text_input(
                                tr("label_friendly_name"),
                                value=endpoint.name if endpoint else "",
                                help=tr("help_friendly_name"),
                            )
                            provider_options = provider_names[:]
                            if endpoint and endpoint.provider not in provider_options:
                                provider_options.append(endpoint.provider)
                            if provider_options:
                                provider = st.selectbox(
                                    tr("label_provider"),
                                    provider_options,
                                    index=provider_options.index(endpoint.provider) if endpoint else 0,
                                    format_func=lambda name: provider_display.get(name, name),
                                    help=tr("help_endpoint_provider"),
                                )
                            else:
                                provider = st.text_input(
                                    tr("label_provider"),
                                    value=endpoint.provider if endpoint else "",
                                    help=tr("help_endpoint_provider"),
                                )
                            endpoint_url_value = ""
                            if endpoint:
                                endpoint_url_value = endpoint.base_url.rstrip("/")
                                if endpoint.endpoint_path:
                                    endpoint_url_value = (
                                        f"{endpoint_url_value}/{endpoint.endpoint_path.lstrip('/')}"
                                    )
                            endpoint_url = st.text_input(
                                tr("label_endpoint_url"),
                                value=endpoint_url_value,
                                help=tr("help_endpoint_url"),
                            )
                            model_name = st.text_input(
                                tr("label_model_name"),
                                value=endpoint.model_name if endpoint else "",
                                help=tr("help_model_name"),
                            )
                            try:
                                endpoint_request_mode = normalize_request_mode(
                                    getattr(endpoint, "request_mode", "responses"),
                                    default="responses",
                                )
                            except ValueError:
                                endpoint_request_mode = "responses"
                            request_mode_options = ["responses", "completions"]
                            request_mode = st.selectbox(
                                tr("label_request_mode"),
                                request_mode_options,
                                index=request_mode_options.index(endpoint_request_mode),
                                format_func=lambda val: (
                                    tr("option_request_mode_responses")
                                    if val == "responses"
                                    else tr("option_request_mode_completions")
                                ),
                                help=tr("help_request_mode"),
                            )
                            st.caption(tr("label_stored_secret", value=masked_token))
                            api_token = st.text_input(
                                tr("label_rotate_api_token"),
                                value="",
                                type="password",
                                help=tr("help_rotate_api_token"),
                            )
                            custom_headers_raw = st.text_area(
                                tr("label_headers"),
                                value=json.dumps(endpoint.custom_headers or {}, indent=2),
                                help=tr("help_headers"),
                            )
                            default_params_raw = st.text_area(
                                tr("label_body"),
                                value=json.dumps(endpoint.default_params or {}, indent=2),
                                help=tr("help_body"),
                            )
                            response_paths = st.text_area(
                                tr("label_response_paths"),
                                value=endpoint.response_paths or "",
                                help=tr("help_response_paths"),
                            )
                            response_type = st.selectbox(
                                tr("label_response_type"),
                                ["json", "text"],
                                index=0 if (endpoint.response_type or "json") == "json" else 1,
                                format_func=lambda val: tr("option_json") if val == "json" else tr("option_text"),
                                help=tr("help_response_type"),
                            )
                            extra_variables_raw = st.text_area(
                                tr("label_additional_variables"),
                                key=edit_extra_vars_key,
                                help=tr("help_additional_variables"),
                            )
                            test_prompt = st.text_input(
                                tr("label_test_prompt"),
                                key=edit_test_prompt_key,
                                help=tr("help_test_prompt"),
                            )
                            detected_variables = _extract_template_variables(custom_headers_raw, default_params_raw)
                            st.caption(
                                tr(
                                    "label_detected_variables",
                                    values=", ".join(detected_variables) if detected_variables else tr("option_none"),
                                )
                            )
                            test_connection = st.form_submit_button(
                                tr("button_test_endpoint_connection"),
                                type="secondary",
                            )
                            update = st.form_submit_button(tr("button_update_endpoint"))

                            if test_connection:
                                try:
                                    with st.spinner(tr("msg_testing_endpoint_connection")):
                                        response_content, latency_ms = _test_endpoint_connection(
                                            provider=provider,
                                            endpoint_url=endpoint_url,
                                            model_name=model_name,
                                            request_mode=request_mode,
                                            custom_headers_raw=custom_headers_raw,
                                            default_params_raw=default_params_raw,
                                            response_paths=response_paths,
                                            response_type=response_type,
                                            extra_variables_raw=extra_variables_raw,
                                            api_token=api_token,
                                            stored_api_token=stored_api_token,
                                            test_prompt=test_prompt,
                                            default_timeout=int(settings["default_timeout"]),
                                            verify_ssl=settings.get("ssl_verify", True),
                                            tr=tr,
                                        )
                                    st.success(tr("msg_test_endpoint_connection_success", latency=latency_ms or 0))
                                    if response_content:
                                        st.caption(tr("label_test_connection_response_preview"))
                                        st.code(_truncate_text(response_content), language="text")
                                except (json.JSONDecodeError, ValueError) as exc:
                                    st.error(str(exc))
                                except Exception as exc:
                                    st.error(tr("error_test_endpoint_connection_failed", error=exc))
                            elif update:
                                try:
                                    custom_headers = parse_json_field(custom_headers_raw) or {}
                                    default_params = parse_json_field(default_params_raw) or {}
                                    custom_variables, custom_variable_types = _parse_variable_values(extra_variables_raw)
                                    if not isinstance(custom_headers, dict) or not isinstance(default_params, dict):
                                        raise ValueError("json_type")
                                    missing_variables = [
                                        variable
                                        for variable in detected_variables
                                        if variable not in RESERVED_TEMPLATE_VARS and variable not in custom_variables
                                    ]
                                    resolved_api_token = api_token.strip() or stored_api_token
                                    if missing_variables:
                                        st.error(tr("error_missing_template_variables", variables=", ".join(missing_variables)))
                                    elif "API_TOKEN" in detected_variables and not resolved_api_token:
                                        st.error(tr("error_api_token_required"))
                                    else:
                                        base_url, endpoint_path = _split_endpoint_url(endpoint_url)
                                        variable_values = dict(custom_variables)
                                        if resolved_api_token:
                                            variable_values["API_TOKEN"] = resolved_api_token
                                        variable_values["MODEL_NAME"] = model_name
                                        data = {
                                            "name": name,
                                            "provider": provider,
                                            "base_url": base_url,
                                            "endpoint_path": endpoint_path,
                                            "model_name": model_name,
                                            "request_mode": normalize_request_mode(request_mode),
                                            "auth_type": "none",
                                            "auth_header": None,
                                            "auth_prefix": None,
                                            "custom_headers": custom_headers,
                                            "default_params": default_params,
                                            "timeout": int(settings["default_timeout"]),
                                            "retry_count": 0,
                                            "response_paths": response_paths or None,
                                            "response_type": response_type,
                                        }
                                        update_endpoint(
                                            session,
                                            endpoint,
                                            data,
                                            None,
                                            secret_type="none",
                                            variable_values=variable_values,
                                            variable_types=custom_variable_types,
                                        )
                                        session.commit()
                                        st.success(tr("msg_endpoint_updated"))
                                        st.rerun()
                                except (json.JSONDecodeError, ValueError):
                                    st.error(tr("error_invalid_json"))
                                except Exception as exc:
                                    st.error(tr("error_failed_update_endpoint", error=exc))

            with endpoint_tabs[2]:
                st.subheader(tr("section_delete_endpoint"))
                if not endpoints:
                    st.info(tr("no_endpoints"))
                else:
                    endpoint_delete_id = st.selectbox(
                        tr("label_select_endpoint_to_delete"),
                        options=[ep.id for ep in endpoints],
                        format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id),
                        key="delete_endpoint_select",
                    )
                    endpoint = get_endpoint(session, endpoint_delete_id)
                    confirm_delete_endpoint_key = f"confirm_delete_endpoint_{endpoint.id}"
                    confirm_delete_endpoint = st.checkbox(
                        tr("label_confirm_delete_endpoint"),
                        key=confirm_delete_endpoint_key,
                    )
                    pending_delete_endpoint_key = "pending_delete_endpoint_id"
                    if st.button(tr("button_delete_endpoint"), key=f"delete_endpoint_{endpoint.id}"):
                        if not confirm_delete_endpoint:
                            st.warning(tr("warning_confirm_delete_endpoint"))
                        else:
                            st.session_state[pending_delete_endpoint_key] = endpoint.id
                            st.rerun()

                    if st.session_state.get(pending_delete_endpoint_key) == endpoint.id:
                        st.warning(tr("confirm_delete_endpoint", name=endpoint.name))
                        confirm_cols = st.columns(2, gap="small")
                        if confirm_cols[0].button(
                            tr("button_confirm_delete_endpoint"),
                            key=f"confirm_delete_endpoint_final_{endpoint.id}",
                            width="stretch",
                        ):
                            try:
                                delete_endpoint(session, endpoint)
                                session.commit()
                                st.session_state.pop(pending_delete_endpoint_key, None)
                                st.success(tr("msg_endpoint_deleted"))
                                st.rerun()
                            except Exception as exc:
                                st.error(tr("error_failed_delete_endpoint", error=exc))
                        if confirm_cols[1].button(
                            tr("button_cancel_delete_endpoint"),
                            key=f"cancel_delete_endpoint_{endpoint.id}",
                            width="stretch",
                        ):
                            st.session_state.pop(pending_delete_endpoint_key, None)
                            st.rerun()

            with endpoint_tabs[3]:
                st.subheader(tr("section_endpoint_import_export"))
                st.info(tr("endpoint_import_export_tips"))

                import_base = _safe_resolve(settings["import_dir"], ROOT_DIR)
                output_base = _safe_resolve(settings["output_dir"], ROOT_DIR)
                if not is_safe_path(import_base, ROOT_DIR) or not is_safe_path(output_base, ROOT_DIR):
                    st.error(tr("error_endpoint_dirs_within_project"))
                else:
                    st.caption(tr("label_approved_import_dir", path=import_base))
                    st.caption(tr("label_approved_output_dir", path=output_base))
                    _render_default_import_files_hint(tr)
                    st.markdown(f"**{tr('section_templates')}**")
                    endpoint_template_xlsx = _load_template_bytes("examples/sample_endpoints.xlsx")
                    endpoint_template_json = _load_template_bytes("examples/sample_endpoints.json")
                    template_cols = st.columns(2, gap="small")
                    template_cols[0].download_button(
                        tr("button_download_endpoint_template_xlsx"),
                        data=endpoint_template_xlsx or b"",
                        file_name=ENDPOINT_TEMPLATE_XLSX_DOWNLOAD_NAME,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_endpoint_template_xlsx",
                        disabled=endpoint_template_xlsx is None,
                        width="stretch",
                    )
                    template_cols[1].download_button(
                        tr("button_download_endpoint_template_json"),
                        data=endpoint_template_json or b"",
                        file_name=ENDPOINT_TEMPLATE_JSON_DOWNLOAD_NAME,
                        mime="application/json",
                        key="download_endpoint_template_json",
                        disabled=endpoint_template_json is None,
                        width="stretch",
                    )
                    if endpoint_template_xlsx is None or endpoint_template_json is None:
                        st.warning(tr("warning_template_files_missing"))

                    st.markdown(f"**{tr('section_import_endpoints')}**")
                    st.caption(tr("label_endpoint_supported_formats"))

                    import_source: Path | None = None
                    uploaded = st.file_uploader(
                        tr("label_upload_endpoint_file"),
                        type=["xlsx", "json"],
                        key="endpoint_import_upload",
                    )
                    if uploaded:
                        safe_name = _sanitize_filename(uploaded.name, fallback="endpoints_import.xlsx")
                        destination = (import_base / safe_name).resolve()
                        if not is_safe_path(destination, import_base):
                            st.error(tr("error_endpoint_import_path"))
                        elif destination.suffix.lower() not in {".xlsx", ".json"}:
                            st.error(tr("error_endpoint_import_file_type"))
                        else:
                            import_base.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(uploaded.getbuffer())
                            import_source = destination

                    if import_source:
                        try:
                            raw_records = _load_endpoint_records(import_source)
                            normalized_records, validation_errors, ignored_key_rows = validate_endpoint_records(
                                raw_records,
                                default_timeout=int(settings["default_timeout"]),
                            )
                        except (json.JSONDecodeError, ValueError) as exc:
                            st.error(tr("error_endpoint_import_parse", error=exc))
                            raw_records = []
                            normalized_records = []
                            validation_errors = []
                            ignored_key_rows = 0
                        except Exception as exc:
                            st.error(tr("error_endpoint_import_parse", error=exc))
                            raw_records = []
                            normalized_records = []
                            validation_errors = []
                            ignored_key_rows = 0
                        else:
                            st.caption(
                                tr(
                                    "label_endpoint_import_loaded",
                                    source=import_source.name,
                                    count=len(raw_records),
                                )
                            )

                        if validation_errors:
                            st.error(tr("error_endpoint_import_validation"))
                            for issue in validation_errors:
                                st.write(f"- {issue}")

                        if normalized_records and not validation_errors:
                            preview_rows = [
                                {
                                    tr("table_name"): endpoint_row["name"],
                                    tr("table_provider"): endpoint_row["provider"],
                                    tr("label_endpoint_url"): (
                                        f"{endpoint_row['base_url'].rstrip('/')}/"
                                        f"{str(endpoint_row['endpoint_path'] or '').lstrip('/')}"
                                    ).rstrip("/"),
                                    tr("label_model_name"): endpoint_row["model_name"],
                                    tr("label_api_token"): "",
                                }
                                for endpoint_row in normalized_records
                            ]
                            st.dataframe(preview_rows, width="stretch")
                            if st.button(tr("button_import_endpoints"), key="button_import_endpoints"):
                                try:
                                    stats = import_endpoint_records(session, normalized_records)
                                    record_event(
                                        session,
                                        "import",
                                        "endpoint",
                                        after_value={
                                            "source": import_source.name,
                                            "format": import_source.suffix.lower().lstrip("."),
                                            "rows": len(normalized_records),
                                            "created": stats["created"],
                                            "skipped_existing": stats["skipped_existing"],
                                            "ignored_api_token_rows": ignored_key_rows,
                                        },
                                    )
                                    session.commit()
                                    messages: list[tuple[str, str]] = []
                                    if stats["skipped_existing_names"]:
                                        messages.append(
                                            (
                                                "warning",
                                                tr(
                                                    "warning_endpoint_existing_skipped",
                                                    names=", ".join(stats["skipped_existing_names"]),
                                                ),
                                            )
                                        )
                                    if ignored_key_rows > 0:
                                        messages.append(
                                            (
                                                "warning",
                                                tr("warning_endpoint_key_ignored", count=ignored_key_rows),
                                            )
                                        )
                                    messages.append(
                                        (
                                            "success",
                                            tr(
                                                "msg_endpoints_imported",
                                                created=stats["created"],
                                                skipped_existing=stats["skipped_existing"],
                                            ),
                                        )
                                    )
                                    st.session_state[endpoint_import_flash_key] = messages
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_endpoint_import_failed", error=exc))

                    st.markdown(f"**{tr('section_export_endpoints')}**")
                    if not endpoints:
                        st.info(tr("no_endpoints"))
                    else:
                        export_format = st.selectbox(
                            tr("label_endpoint_export_format"),
                            ["xlsx", "json"],
                            format_func=lambda value: value.upper(),
                            key="endpoint_export_format",
                        )
                        default_export_name = (
                            f"endpoints_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
                        )
                        export_filename = st.text_input(
                            tr("label_endpoint_export_filename"),
                            value=default_export_name,
                            key="endpoint_export_filename",
                        )
                        allow_overwrite = st.checkbox(
                            tr("label_endpoint_export_overwrite"),
                            value=False,
                            key="endpoint_export_allow_overwrite",
                        )
                        if st.button(tr("button_export_endpoints"), key="button_export_endpoints"):
                            safe_filename = _sanitize_filename(
                                export_filename,
                                fallback=f"endpoints_backup.{export_format}",
                            )
                            safe_path_name = Path(safe_filename)
                            if safe_path_name.suffix.lower() != f".{export_format}":
                                safe_filename = f"{safe_path_name.stem}.{export_format}"
                            target_path = _safe_resolve(safe_filename, output_base)
                            if not is_safe_path(target_path, output_base):
                                st.error(tr("error_endpoint_export_path"))
                            elif target_path.exists() and not allow_overwrite:
                                st.error(tr("error_endpoint_export_exists"))
                            else:
                                try:
                                    output_base.mkdir(parents=True, exist_ok=True)
                                    records = endpoints_to_records(session, endpoints)
                                    if export_format == "xlsx":
                                        xlsx_records = []
                                        for record in records:
                                            xlsx_record = dict(record)
                                            xlsx_record["headers"] = json.dumps(
                                                xlsx_record.get("headers") or {},
                                                ensure_ascii=False,
                                            )
                                            xlsx_record["body"] = json.dumps(
                                                xlsx_record.get("body") or {},
                                                ensure_ascii=False,
                                            )
                                            xlsx_record["additional_variables"] = json.dumps(
                                                xlsx_record.get("additional_variables") or {},
                                                ensure_ascii=False,
                                            )
                                            # Always blank in exports; users can rotate token later in Edit.
                                            xlsx_record["api_token"] = ""
                                            xlsx_records.append(xlsx_record)
                                        pd.DataFrame(xlsx_records).to_excel(target_path, index=False)
                                    else:
                                        target_path.write_text(
                                            json.dumps(records, indent=2, ensure_ascii=False),
                                            encoding="utf-8",
                                        )
                                    record_event(
                                        session,
                                        "export",
                                        "endpoint",
                                        after_value={
                                            "path": str(target_path),
                                            "format": export_format,
                                            "count": len(records),
                                        },
                                    )
                                    session.commit()
                                    st.success(tr("msg_endpoints_exported", path=target_path))
                                except Exception as exc:
                                    st.error(tr("error_endpoint_export_failed", error=exc))

    if config_page == "tests":
        with get_session(session_factory) as session:
            suites = session.query(models.TestSuite).order_by(models.TestSuite.created_at.desc()).all()
            settings = get_runtime_settings(session, config)

            st.subheader(tr("section_test_module_settings"))
            current_tests_threads = max(1, int(settings.get("tests_max_threads", 1)))
            current_tests_timeout = max(5, int(settings.get("tests_request_timeout", settings["default_timeout"])))
            current_tests_retries = max(0, int(settings.get("tests_retries", 0)))
            with st.form("test_module_settings"):
                tests_max_threads = st.number_input(
                    tr("label_tests_max_threads"),
                    min_value=1,
                    max_value=32,
                    value=current_tests_threads,
                    step=1,
                    help=tr("help_tests_max_threads"),
                )
                tests_request_timeout = st.number_input(
                    tr("label_tests_request_timeout"),
                    min_value=5,
                    max_value=600,
                    value=current_tests_timeout,
                    step=1,
                    help=tr("help_tests_request_timeout"),
                )
                tests_retries = st.number_input(
                    tr("label_tests_retries"),
                    min_value=0,
                    max_value=10,
                    value=current_tests_retries,
                    step=1,
                    help=tr("help_tests_retries"),
                )
                tests_result_format = st.selectbox(
                    tr("label_tests_result_format"),
                    options=["xlsx", "json"],
                    index=0 if settings.get("tests_result_format", "xlsx") == "xlsx" else 1,
                    format_func=lambda value: value.upper(),
                    help=tr("help_tests_result_format"),
                )
                save_test_module_settings = st.form_submit_button(tr("button_save_test_module_settings"))
                if save_test_module_settings:
                    set_setting(session, "tests_max_threads", str(int(tests_max_threads)))
                    set_setting(session, "tests_request_timeout", str(int(tests_request_timeout)))
                    set_setting(session, "tests_retries", str(int(tests_retries)))
                    set_setting(session, "tests_result_format", tests_result_format)
                    record_event(
                        session,
                        "update",
                        "settings",
                        "tests_module",
                        after_value={
                            "tests_max_threads": int(tests_max_threads),
                            "tests_request_timeout": int(tests_request_timeout),
                            "tests_retries": int(tests_retries),
                            "tests_result_format": tests_result_format,
                        },
                    )
                    session.commit()
                    st.success(tr("msg_test_module_settings_saved"))
                    st.rerun()

            st.subheader(tr("section_test_suites"))
            if suites:
                st.caption(tr("label_registered_suites_count", count=len(suites)))
                for row_start in range(0, len(suites), 3):
                    row_cols = st.columns(3, gap="small")
                    for col_index in range(3):
                        suite_index = row_start + col_index
                        if suite_index >= len(suites):
                            continue
                        with row_cols[col_index]:
                            suite_name = suites[suite_index].name or "-"
                            escaped_name = html_escape(suite_name)
                            st.markdown(
                                f'<div class="suite-chip" title="{escaped_name}">{escaped_name}</div>',
                                unsafe_allow_html=True,
                            )
            else:
                st.info(tr("no_test_suites"))

            suite_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete"), tr("tab_import_export")])

            with suite_tabs[0]:
                st.subheader(tr("section_create_suite"))
                st.info(tr("suite_create_upload_tips"))
                _render_test_template_downloads(tr, "suite_create")
                with st.form("create_suite"):
                    suite_name = st.text_input(tr("label_suite_name"))
                    suite_description = st.text_area(tr("label_description"))
                    uploaded_suite_files = st.file_uploader(
                        tr("label_suite_source_files"),
                        type=["xlsx", "json"],
                        accept_multiple_files=True,
                        key="create_suite_source_files",
                    )
                    create = st.form_submit_button(tr("button_create_suite"))
                    if create:
                        try:
                            required_fields: list[str] = []
                            if not suite_name.strip():
                                required_fields.append(tr("label_suite_name"))
                            if required_fields:
                                st.error(tr("error_required_fields", fields=", ".join(required_fields)))
                            elif not uploaded_suite_files:
                                st.error(tr("error_suite_files_required"))
                            else:
                                import_base = _safe_resolve(settings["import_dir"], ROOT_DIR)
                                if not is_safe_path(import_base, ROOT_DIR):
                                    st.error(tr("error_test_dirs_within_project"))
                                    return

                                import_base.mkdir(parents=True, exist_ok=True)
                                valid_dataframes: list[tuple[str, pd.DataFrame]] = []
                                skipped_reasons: list[str] = []
                                stored_file_names: list[str] = []

                                for file_index, uploaded_file in enumerate(uploaded_suite_files, start=1):
                                    suffix = Path(uploaded_file.name).suffix.lower()
                                    fallback_suffix = ".json" if suffix == ".json" else ".xlsx"
                                    if suffix not in {".xlsx", ".json"}:
                                        skipped_reasons.append(
                                            tr("error_suite_file_type", file=uploaded_file.name)
                                        )
                                        continue
                                    safe_name = _sanitize_filename(
                                        uploaded_file.name,
                                        fallback=f"suite_file_{file_index}{fallback_suffix}",
                                    )
                                    destination = (import_base / safe_name).resolve()
                                    if not is_safe_path(destination, import_base):
                                        skipped_reasons.append(
                                            tr("error_suite_file_path", file=uploaded_file.name)
                                        )
                                        continue
                                    try:
                                        destination.write_bytes(uploaded_file.getbuffer())
                                        df = _load_test_prompt_dataframe(destination)
                                    except ValueError as exc:
                                        reason = str(exc)
                                        if reason == "missing_prompt_column":
                                            skipped_reasons.append(
                                                tr("error_suite_file_missing_columns", file=uploaded_file.name)
                                            )
                                        else:
                                            skipped_reasons.append(
                                                tr("error_suite_file_read", file=uploaded_file.name, error=exc)
                                            )
                                    except Exception as exc:
                                        skipped_reasons.append(
                                            tr("error_suite_file_read", file=uploaded_file.name, error=exc)
                                        )
                                        continue
                                    else:
                                        valid_dataframes.append((uploaded_file.name, df))
                                        stored_file_names.append(safe_name)

                                if not valid_dataframes:
                                    st.error(tr("error_suite_no_valid_files"))
                                    for reason in skipped_reasons:
                                        st.write(f"- {reason}")
                                    return

                                suite = create_suite(
                                    session,
                                    suite_name,
                                    suite_description,
                                    "file",
                                    ", ".join(stored_file_names)[:255] if stored_file_names else None,
                                    None,
                                )
                                imported_total = 0
                                for _, dataframe in valid_dataframes:
                                    mapping = _build_prompt_import_mapping(dataframe)
                                    imported_total += import_tests_from_dataframe(session, suite, dataframe, mapping)

                                if imported_total == 0:
                                    session.rollback()
                                    st.error(tr("error_suite_no_valid_tests"))
                                    for reason in skipped_reasons:
                                        st.write(f"- {reason}")
                                    return

                                session.commit()
                                st.success(
                                    tr(
                                        "msg_suite_created_with_import",
                                        name=suite.name,
                                        files=len(valid_dataframes),
                                        count=imported_total,
                                    )
                                )
                                if skipped_reasons:
                                    st.warning(tr("warning_suite_files_skipped"))
                                    for reason in skipped_reasons:
                                        st.write(f"- {reason}")
                                st.rerun()
                        except ValueError as exc:
                            reason = str(exc)
                            if reason == "suite_name_required":
                                st.error(tr("error_suite_name_required"))
                            else:
                                st.error(tr("error_failed_create_suite", error=exc))
                        except Exception as exc:
                            st.error(tr("error_failed_create_suite", error=exc))

            with suite_tabs[1]:
                st.subheader(tr("section_edit_suite"))
                if not suites:
                    st.info(tr("no_test_suites"))
                else:
                    edit_suite_id = st.selectbox(
                        tr("label_select_suite_to_edit"),
                        options=[None] + [suite.id for suite in suites],
                        format_func=lambda suite_id: next(suite.name for suite in suites if suite.id == suite_id)
                        if suite_id is not None
                        else tr("option_select"),
                        key="edit_suite_select",
                    )
                    if edit_suite_id is None:
                        st.info(tr("info_select_item_to_edit"))
                    else:
                        edit_suite = next((suite for suite in suites if suite.id == edit_suite_id), None)

                        if edit_suite:
                            with st.form("edit_suite"):
                                edit_name = st.text_input(tr("label_suite_name"), value=edit_suite.name)
                                edit_description = st.text_area(
                                    tr("label_description"),
                                    value=edit_suite.description or "",
                                )
                                edit_is_active = st.checkbox(
                                    tr("label_active"),
                                    value=bool(edit_suite.is_active),
                                )
                                update_suite_submit = st.form_submit_button(tr("button_update_suite"))

                                if update_suite_submit:
                                    try:
                                        update_suite(
                                            session,
                                            edit_suite,
                                            edit_name,
                                            edit_description,
                                            edit_suite.source_type or "file",
                                            edit_suite.source_path,
                                            edit_suite.default_endpoint_id,
                                            is_active=edit_is_active,
                                        )
                                        session.commit()
                                        st.success(tr("msg_suite_updated"))
                                        st.rerun()
                                    except ValueError as exc:
                                        reason = str(exc)
                                        if reason == "suite_name_required":
                                            st.error(tr("error_suite_name_required"))
                                        elif reason == "source_type_required":
                                            st.error(tr("error_source_type_required"))
                                        elif reason == "source_path_required":
                                            st.error(tr("error_suite_source_path_required"))
                                        else:
                                            st.error(tr("error_failed_update_suite", error=exc))
                                    except Exception as exc:
                                        st.error(tr("error_failed_update_suite", error=exc))

                            st.markdown(f"**{tr('section_suite_prompts')}**")
                            prompt_cases = list_suite_test_cases(session, edit_suite)
                            if prompt_cases:
                                st.dataframe(
                                    [
                                        {
                                            tr("table_id"): test_case.id,
                                            tr("label_prompt_text"): test_case.prompt,
                                            tr("label_prompt_notes"): test_case.notes or "",
                                        }
                                        for test_case in prompt_cases
                                    ],
                                    width="stretch",
                                )
                            else:
                                st.info(tr("no_suite_prompts"))

                            prompt_tabs = st.tabs(
                                [tr("tab_add_prompt"), tr("tab_edit_prompt"), tr("tab_delete_prompt")]
                            )

                            with prompt_tabs[0]:
                                with st.form(f"add_suite_prompt_form_{edit_suite.id}"):
                                    new_prompt = st.text_area(tr("label_prompt_text"), value="")
                                    new_notes = st.text_area(tr("label_prompt_notes"), value="")
                                    add_prompt_submit = st.form_submit_button(tr("button_add_prompt"))
                                    if add_prompt_submit:
                                        try:
                                            create_suite_prompt(session, edit_suite, new_prompt, new_notes)
                                            session.commit()
                                            st.success(tr("msg_prompt_added"))
                                            st.rerun()
                                        except ValueError as exc:
                                            if str(exc) == "prompt_required":
                                                st.error(tr("error_prompt_required"))
                                            else:
                                                st.error(tr("error_prompt_save_failed", error=exc))
                                        except Exception as exc:
                                            st.error(tr("error_prompt_save_failed", error=exc))

                            with prompt_tabs[1]:
                                if not prompt_cases:
                                    st.info(tr("no_suite_prompts"))
                                else:
                                    edit_prompt_id = st.selectbox(
                                        tr("label_select_prompt_to_edit"),
                                        options=[None] + [test_case.id for test_case in prompt_cases],
                                        format_func=lambda prompt_id: tr("option_select")
                                        if prompt_id is None
                                        else (
                                            f"#{prompt_id} - "
                                            + next(
                                                tc.prompt.replace("\n", " ")[:80]
                                                + ("..." if len(tc.prompt or "") > 80 else "")
                                                for tc in prompt_cases
                                                if tc.id == prompt_id
                                            )
                                        ),
                                        key=f"edit_suite_prompt_select_{edit_suite.id}",
                                    )
                                    if edit_prompt_id is None:
                                        st.info(tr("info_select_item_to_edit"))
                                    else:
                                        edit_prompt_case = next(
                                            (tc for tc in prompt_cases if tc.id == edit_prompt_id),
                                            None,
                                        )
                                        if edit_prompt_case:
                                            with st.form(
                                                f"edit_suite_prompt_form_{edit_suite.id}_{edit_prompt_case.id}"
                                            ):
                                                updated_prompt = st.text_area(
                                                    tr("label_prompt_text"),
                                                    value=edit_prompt_case.prompt or "",
                                                )
                                                updated_notes = st.text_area(
                                                    tr("label_prompt_notes"),
                                                    value=edit_prompt_case.notes or "",
                                                )
                                                update_prompt_submit = st.form_submit_button(
                                                    tr("button_update_prompt")
                                                )
                                                if update_prompt_submit:
                                                    try:
                                                        update_suite_prompt(
                                                            session,
                                                            edit_prompt_case,
                                                            updated_prompt,
                                                            updated_notes,
                                                        )
                                                        session.commit()
                                                        st.success(tr("msg_prompt_updated"))
                                                        st.rerun()
                                                    except ValueError as exc:
                                                        if str(exc) == "prompt_required":
                                                            st.error(tr("error_prompt_required"))
                                                        else:
                                                            st.error(tr("error_prompt_save_failed", error=exc))
                                                    except Exception as exc:
                                                        st.error(tr("error_prompt_save_failed", error=exc))

                            with prompt_tabs[2]:
                                if not prompt_cases:
                                    st.info(tr("no_suite_prompts"))
                                else:
                                    delete_prompt_id = st.selectbox(
                                        tr("label_select_prompt_to_delete"),
                                        options=[test_case.id for test_case in prompt_cases],
                                        format_func=lambda prompt_id: (
                                            f"#{prompt_id} - "
                                            + next(
                                                tc.prompt.replace("\n", " ")[:80]
                                                + ("..." if len(tc.prompt or "") > 80 else "")
                                                for tc in prompt_cases
                                                if tc.id == prompt_id
                                            )
                                        ),
                                        key=f"delete_suite_prompt_select_{edit_suite.id}",
                                    )
                                    prompt_to_delete = next(
                                        (tc for tc in prompt_cases if tc.id == delete_prompt_id),
                                        None,
                                    )
                                    if prompt_to_delete:
                                        confirm_delete_prompt = st.checkbox(
                                            tr("label_confirm_delete_prompt"),
                                            key=f"confirm_delete_prompt_{edit_suite.id}_{prompt_to_delete.id}",
                                        )
                                        if st.button(
                                            tr("button_delete_prompt"),
                                            key=f"delete_prompt_button_{edit_suite.id}_{prompt_to_delete.id}",
                                        ):
                                            if not confirm_delete_prompt:
                                                st.warning(tr("warning_confirm_delete_prompt"))
                                            else:
                                                try:
                                                    delete_suite_prompt(session, prompt_to_delete)
                                                    session.commit()
                                                    st.success(tr("msg_prompt_deleted"))
                                                    st.rerun()
                                                except Exception as exc:
                                                    st.error(tr("error_prompt_delete_failed", error=exc))

            with suite_tabs[2]:
                st.subheader(tr("section_delete_suite"))
                if not suites:
                    st.info(tr("no_test_suites"))
                else:
                    delete_suite_id = st.selectbox(
                        tr("label_select_suite_to_delete"),
                        options=[suite.id for suite in suites],
                        format_func=lambda suite_id: next(suite.name for suite in suites if suite.id == suite_id),
                        key="delete_suite_select",
                    )
                    suite_to_delete = next((suite for suite in suites if suite.id == delete_suite_id), None)

                    if suite_to_delete:
                        confirm_delete_key = f"confirm_delete_suite_{suite_to_delete.id}"
                        confirm_delete = st.checkbox(tr("label_confirm_delete_suite"), key=confirm_delete_key)
                        pending_delete_suite_key = "pending_delete_suite_id"
                        if st.button(tr("button_delete_suite"), key=f"delete_suite_{suite_to_delete.id}"):
                            if not confirm_delete:
                                st.warning(tr("warning_confirm_delete_suite"))
                            else:
                                st.session_state[pending_delete_suite_key] = suite_to_delete.id
                                st.rerun()

                        if st.session_state.get(pending_delete_suite_key) == suite_to_delete.id:
                            st.warning(tr("confirm_delete_suite", name=suite_to_delete.name))
                            confirm_cols = st.columns(2, gap="small")
                            if confirm_cols[0].button(
                                tr("button_confirm_delete_suite"),
                                key=f"confirm_delete_suite_final_{suite_to_delete.id}",
                                width="stretch",
                            ):
                                try:
                                    delete_suite(session, suite_to_delete)
                                    session.commit()
                                    st.session_state.pop(pending_delete_suite_key, None)
                                    st.success(tr("msg_suite_deleted"))
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_failed_delete_suite", error=exc))
                            if confirm_cols[1].button(
                                tr("button_cancel_delete_suite"),
                                key=f"cancel_delete_suite_{suite_to_delete.id}",
                                width="stretch",
                            ):
                                st.session_state.pop(pending_delete_suite_key, None)
                                st.rerun()

            with suite_tabs[3]:
                st.subheader(tr("section_test_import_export"))
                st.info(tr("suite_import_export_tips"))

                settings = get_runtime_settings(session, config)
                import_base = _safe_resolve(settings["import_dir"], ROOT_DIR)
                output_base = _safe_resolve(settings["output_dir"], ROOT_DIR)
                if not is_safe_path(import_base, ROOT_DIR) or not is_safe_path(output_base, ROOT_DIR):
                    st.error(tr("error_test_dirs_within_project"))
                else:
                    st.caption(tr("label_approved_import_dir", path=import_base))
                    st.caption(tr("label_approved_output_dir", path=output_base))
                    _render_default_import_files_hint(tr)
                    _render_test_template_downloads(tr, "test_import_export")

                    st.markdown(f"**{tr('section_import_suites')}**")
                    import_mode = st.radio(
                        tr("label_import_mode"),
                        ["upload", "directory"],
                        format_func=lambda val: tr("option_upload_file")
                        if val == "upload"
                        else tr("option_use_directory"),
                        key="suite_import_mode",
                    )
                    source_path: Path | None = None
                    raw_suite_records: list[dict] | None = None

                    if import_mode == "upload":
                        uploaded = st.file_uploader(
                            tr("label_upload_test_file"),
                            type=["xlsx", "json"],
                            key="suite_import_upload_file",
                        )
                        if uploaded:
                            suffix = Path(uploaded.name).suffix.lower()
                            fallback_suffix = ".json" if suffix == ".json" else ".xlsx"
                            if suffix not in {".xlsx", ".json"}:
                                st.error(tr("error_test_import_file_type"))
                            else:
                                safe_name = _sanitize_filename(
                                    uploaded.name,
                                    fallback=f"suites_import{fallback_suffix}",
                                )
                                destination = (import_base / safe_name).resolve()
                                if not is_safe_path(destination, import_base):
                                    st.error(tr("error_test_import_path"))
                                else:
                                    import_base.mkdir(parents=True, exist_ok=True)
                                    destination.write_bytes(uploaded.getbuffer())
                                    source_path = destination
                                    try:
                                        raw_suite_records = load_suite_records_from_file(destination)
                                    except Exception as exc:
                                        st.error(tr("error_test_import_parse", error=exc))
                    else:
                        directory_input = st.text_input(
                            tr("label_directory_relative"),
                            value="",
                            key="suite_import_directory_relative",
                        )
                        if directory_input:
                            directory = _safe_resolve(directory_input, import_base)
                            try:
                                files = _scan_test_prompt_files(directory, import_base)
                                if not files:
                                    st.warning(tr("warning_no_test_files"))
                                else:
                                    file_choice = st.selectbox(
                                        tr("label_select_file"),
                                        options=files,
                                        key="suite_import_select_file",
                                    )
                                    source_path = file_choice
                                    try:
                                        raw_suite_records = load_suite_records_from_file(file_choice)
                                    except Exception as exc:
                                        st.error(tr("error_test_import_parse", error=exc))
                            except ValueError as exc:
                                reason = str(exc)
                                if reason == "directory_outside_import_base":
                                    st.error(tr("error_test_import_directory_path"))
                                elif reason == "directory_missing":
                                    st.error(tr("error_test_import_directory_missing"))
                                else:
                                    st.error(tr("error_failed_scan_directory", error=exc))
                            except Exception as exc:
                                st.error(tr("error_failed_scan_directory", error=exc))

                    if raw_suite_records is not None:
                        source_label = source_path.name if source_path else tr("source_upload")
                        normalized_suite_records, validation_errors = validate_suite_import_records(raw_suite_records)
                        if validation_errors:
                            st.warning(tr("warning_suite_import_validation_issues"))
                            for issue in validation_errors:
                                st.write(f"- {issue}")

                        if normalized_suite_records:
                            preview_df = pd.DataFrame(normalized_suite_records)
                            st.success(tr("msg_loaded_rows", count=len(normalized_suite_records), source=source_label))
                            st.dataframe(preview_df.fillna(""), width="stretch")
                            if st.button(tr("button_import_suites"), key="button_import_suites"):
                                try:
                                    import_summary = import_suite_records(session, normalized_suite_records)
                                    session.commit()
                                    st.success(
                                        tr(
                                            "msg_suites_imported",
                                            created=import_summary["created_suites"],
                                            tests=import_summary["imported_tests"],
                                            skipped_existing=import_summary["skipped_existing"],
                                        )
                                    )
                                    skipped_names = import_summary.get("skipped_existing_names") or []
                                    if skipped_names:
                                        st.warning(
                                            tr(
                                                "warning_suite_existing_skipped",
                                                names=", ".join(skipped_names),
                                            )
                                        )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(tr("error_import_failed", error=exc))
                        else:
                            st.error(tr("error_suite_no_valid_files"))

                    st.markdown(f"**{tr('section_export_suites')}**")
                    if not suites:
                        st.info(tr("info_create_suite_first"))
                    else:
                        export_scope = st.selectbox(
                            tr("label_suite_export_scope"),
                            options=["all"] + [suite.id for suite in suites],
                            format_func=lambda value: tr("option_all_suites")
                            if value == "all"
                            else next(suite.name for suite in suites if suite.id == value),
                            key="suite_export_scope",
                        )
                        suites_for_export = (
                            suites
                            if export_scope == "all"
                            else [next(suite for suite in suites if suite.id == export_scope)]
                        )
                        suite_records = suites_to_records(session, suites_for_export)
                        st.caption(
                            tr(
                                "label_suites_for_export_count",
                                suites=len(suites_for_export),
                                tests=len(suite_records),
                            )
                        )

                        export_format = st.selectbox(
                            tr("label_test_export_format"),
                            ["xlsx", "json"],
                            format_func=lambda value: value.upper(),
                            key="suite_export_format",
                        )
                        scope_name = "all_suites" if export_scope == "all" else f"suite_{export_scope}"
                        default_export_name = (
                            f"{scope_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
                        )
                        export_filename = st.text_input(
                            tr("label_test_export_filename"),
                            value=default_export_name,
                            key="suite_export_filename",
                        )
                        allow_overwrite = st.checkbox(
                            tr("label_test_export_overwrite"),
                            value=False,
                            key="suite_export_allow_overwrite",
                        )

                        if st.button(tr("button_export_suites"), key="button_export_suites"):
                            if not suite_records:
                                st.warning(tr("warning_no_suite_records_to_export"))
                            else:
                                safe_filename = _sanitize_filename(
                                    export_filename,
                                    fallback=f"{scope_name}.{export_format}",
                                )
                                safe_path_name = Path(safe_filename)
                                if safe_path_name.suffix.lower() != f".{export_format}":
                                    safe_filename = f"{safe_path_name.stem}.{export_format}"
                                target_path = _safe_resolve(safe_filename, output_base)
                                if not is_safe_path(target_path, output_base):
                                    st.error(tr("error_test_export_path"))
                                elif target_path.exists() and not allow_overwrite:
                                    st.error(tr("error_test_export_exists"))
                                else:
                                    try:
                                        output_base.mkdir(parents=True, exist_ok=True)
                                        if export_format == "xlsx":
                                            pd.DataFrame(suite_records).to_excel(target_path, index=False)
                                        else:
                                            target_path.write_text(
                                                json.dumps(suite_records, indent=2, ensure_ascii=False),
                                                encoding="utf-8",
                                            )
                                        record_event(
                                            session,
                                            "export",
                                            "test_suites",
                                            str(export_scope),
                                            after_value={
                                                "path": str(target_path),
                                                "format": export_format,
                                                "suites": len(suites_for_export),
                                                "tests": len(suite_records),
                                            },
                                        )
                                        session.commit()
                                        st.success(tr("msg_suites_exported", path=target_path))
                                    except Exception as exc:
                                        st.error(tr("error_test_export_failed", error=exc))

    if config_page == "red_teaming":
        red_team_config.render(context, tr)

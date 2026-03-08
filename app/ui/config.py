from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from app.core.config import AppConfig
from app.core.logging import set_log_level
from app.core.redaction import mask_secret
from app.core.secrets import SecretManager
from app.core.security import is_safe_path
from app.core.paths import ROOT_DIR
from app.domain import models
from app.infra.db import get_session
from app.services.audit_service import record_event
from app.services.endpoint_service import create_endpoint, delete_endpoint, get_endpoint, list_endpoints, update_endpoint
from app.services.settings_service import set_setting
from app.services.test_service import (
    create_suite,
    delete_suite,
    import_tests_from_dataframe,
    scan_directory,
    update_suite,
    validate_columns,
)
from app.services.provider_service import (
    list_providers,
    create_provider,
    get_provider,
    update_provider,
    delete_provider,
)
from app.ui.utils import get_runtime_settings, parse_json_field
from app.ui.i18n import get_translator


TEST_FIELDS = [
    "order",
    "enabled",
    "test_name",
    "prompt",
    "expected_result",
    "validation_type",
    "tags",
    "temperature",
    "max_tokens",
    "notes",
]

RESERVED_TEMPLATE_VARS = {"API_TOKEN", "MODEL_NAME", "PROMPT"}
TEMPLATE_VAR_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
TEMPLATE_VAR_PATTERNS = (
    re.compile(r"\{\{\s*(" + TEMPLATE_VAR_NAME + r")\s*\}\}"),
    re.compile(r"\$\{(" + TEMPLATE_VAR_NAME + r")\}"),
    re.compile(r"<(" + TEMPLATE_VAR_NAME + r")>"),
)
BARE_RESERVED_PATTERN = re.compile(r"\b(API_TOKEN|MODEL_NAME|PROMPT)\b")


def _safe_resolve(path_input: str, base: Path) -> Path:
    candidate = (base / path_input).resolve() if not Path(path_input).is_absolute() else Path(path_input).resolve()
    return candidate


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip()
    return cleaned or "import.xlsx"


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


def _parse_variable_values(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    parsed = parse_json_field(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError("variables_json_type")
    return {
        str(key).strip(): "" if value is None else str(value)
        for key, value in parsed.items()
        if str(key).strip()
    }


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

            provider_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete")])

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
                                "is_active": True,
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

    if config_page == "endpoints":
        with get_session(session_factory) as session:
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
                            tr("table_active"): ep.is_active,
                        }
                        for ep in endpoints
                    ],
                    width="stretch",
                )
            else:
                st.info(tr("no_endpoints"))

            endpoint_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete")])

            with endpoint_tabs[0]:
                st.subheader(tr("section_create_endpoint"))
                if not provider_names:
                    st.info(tr("no_providers"))
                st.info(tr("endpoint_tips"))
                create_defaults = {
                    "create_ep_name": "",
                    "create_ep_provider_select": "",
                    "create_ep_provider_text": "",
                    "create_ep_url": "",
                    "create_ep_model_name": "",
                    "create_ep_api_token": "",
                    "create_ep_headers": "",
                    "create_ep_body": "",
                    "create_ep_response_paths": "",
                    "create_ep_response_type": "",
                    "create_ep_extra_vars": "",
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
                        '  "temperature": 0.7\n'
                        '}'
                    )
                    st.session_state["create_ep_response_paths"] = "$output[1].content[0].text\n$output[0].content[0].text"
                    st.session_state["create_ep_response_type"] = "json"
                    st.session_state["create_ep_extra_vars"] = "{}"

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
                    detected_variables = _extract_template_variables(custom_headers_raw, default_params_raw)
                    st.caption(
                        tr(
                            "label_detected_variables",
                            values=", ".join(detected_variables) if detected_variables else tr("option_none"),
                        )
                    )
                    submit = st.form_submit_button(tr("button_create_endpoint"))

                    if submit:
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
                            if not response_type.strip():
                                required_fields.append(tr("label_response_type"))
                            if required_fields:
                                st.error(tr("error_required_fields", fields=", ".join(required_fields)))
                            else:
                                custom_headers = parse_json_field(custom_headers_raw) or {}
                                default_params = parse_json_field(default_params_raw) or {}
                                custom_variables = _parse_variable_values(extra_variables_raw)
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
                                        "auth_type": "none",
                                        "auth_header": None,
                                        "auth_prefix": None,
                                        "custom_headers": custom_headers,
                                        "default_params": default_params,
                                        "timeout": int(settings["default_timeout"]),
                                        "retry_count": 0,
                                        "response_paths": response_paths or None,
                                        "response_type": response_type,
                                        "is_active": True,
                                    }
                                    create_endpoint(
                                        session,
                                        data,
                                        None,
                                        secret_type="none",
                                        variable_values=variable_values,
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
                        stored_api_token = endpoint_variables.get("API_TOKEN", "")
                        masked_token = mask_secret(stored_api_token, show_last=4) if stored_api_token else tr("secret_not_set")
                        stored_custom_variables = {
                            key: value
                            for key, value in endpoint_variables.items()
                            if key not in RESERVED_TEMPLATE_VARS
                        }

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
                                value=json.dumps(stored_custom_variables, indent=2) if stored_custom_variables else "{}",
                                help=tr("help_additional_variables"),
                            )
                            detected_variables = _extract_template_variables(custom_headers_raw, default_params_raw)
                            st.caption(
                                tr(
                                    "label_detected_variables",
                                    values=", ".join(detected_variables) if detected_variables else tr("option_none"),
                                )
                            )
                            update = st.form_submit_button(tr("button_update_endpoint"))

                            if update:
                                try:
                                    custom_headers = parse_json_field(custom_headers_raw) or {}
                                    default_params = parse_json_field(default_params_raw) or {}
                                    custom_variables = _parse_variable_values(extra_variables_raw)
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
                                            "auth_type": "none",
                                            "auth_header": None,
                                            "auth_prefix": None,
                                            "custom_headers": custom_headers,
                                            "default_params": default_params,
                                            "timeout": int(settings["default_timeout"]),
                                            "retry_count": 0,
                                            "response_paths": response_paths or None,
                                            "response_type": response_type,
                                            "is_active": True,
                                        }
                                        update_endpoint(
                                            session,
                                            endpoint,
                                            data,
                                            None,
                                            secret_type="none",
                                            variable_values=variable_values,
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

    if config_page == "tests":
        with get_session(session_factory) as session:
            st.subheader(tr("section_test_suites"))
            suites = session.query(models.TestSuite).order_by(models.TestSuite.created_at.desc()).all()
            endpoints = list_endpoints(session)
            if suites:
                st.dataframe(
                    [
                        {
                            tr("table_id"): suite.id,
                            tr("table_name"): suite.name,
                            tr("table_source"): suite.source_type,
                            tr("table_active"): suite.is_active,
                        }
                        for suite in suites
                    ],
                    width="stretch",
                )
            else:
                st.info(tr("no_test_suites"))

            suite_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete")])

            with suite_tabs[0]:
                st.subheader(tr("section_create_suite"))
                with st.form("create_suite"):
                    suite_name = st.text_input(tr("label_suite_name"))
                    suite_description = st.text_area(tr("label_description"))
                    source_type = st.selectbox(
                        tr("label_source_type"),
                        ["", "file", "directory"],
                        format_func=lambda val: tr("option_select")
                        if not val
                        else (tr("source_file") if val == "file" else tr("source_directory")),
                    )
                    source_path = st.text_input(tr("label_source_path"), value="")
                    default_endpoint_options = [None] + [ep.id for ep in endpoints]
                    default_endpoint = st.selectbox(
                        tr("label_default_endpoint"),
                        options=default_endpoint_options,
                        format_func=lambda ep_id: tr("option_none")
                        if ep_id is None
                        else next((ep.name for ep in endpoints if ep.id == ep_id), tr("label_unknown")),
                    )
                    create = st.form_submit_button(tr("button_create_suite"))
                    if create:
                        try:
                            required_fields: list[str] = []
                            if not suite_name.strip():
                                required_fields.append(tr("label_suite_name"))
                            if not source_type:
                                required_fields.append(tr("label_source_type"))
                            if required_fields:
                                st.error(tr("error_required_fields", fields=", ".join(required_fields)))
                            else:
                                suite = create_suite(
                                    session,
                                    suite_name,
                                    suite_description,
                                    source_type,
                                    source_path or None,
                                    default_endpoint,
                                )
                                session.commit()
                                st.success(tr("msg_suite_created", name=suite.name))
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
                            default_endpoint_options = [None] + [ep.id for ep in endpoints]
                            current_default_endpoint = (
                                edit_suite.default_endpoint_id
                                if edit_suite.default_endpoint_id in default_endpoint_options
                                else None
                            )
                            with st.form("edit_suite"):
                                edit_name = st.text_input(tr("label_suite_name"), value=edit_suite.name)
                                edit_description = st.text_area(
                                    tr("label_description"),
                                    value=edit_suite.description or "",
                                )
                                edit_source_type = st.selectbox(
                                    tr("label_source_type"),
                                    ["file", "directory"],
                                    index=0 if edit_suite.source_type == "file" else 1,
                                    format_func=lambda val: tr("source_file") if val == "file" else tr("source_directory"),
                                )
                                edit_source_path = st.text_input(
                                    tr("label_source_path"),
                                    value=edit_suite.source_path or "",
                                )
                                edit_default_endpoint = st.selectbox(
                                    tr("label_default_endpoint"),
                                    options=default_endpoint_options,
                                    index=default_endpoint_options.index(current_default_endpoint),
                                    format_func=lambda ep_id: tr("option_none")
                                    if ep_id is None
                                    else next((ep.name for ep in endpoints if ep.id == ep_id), tr("label_unknown")),
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
                                            edit_source_type,
                                            edit_source_path or None,
                                            edit_default_endpoint,
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

            st.subheader(tr("section_import_tests"))
            if not suites:
                st.info(tr("info_create_suite_first"))
                return

            selected_suite_id = st.selectbox(
                tr("label_select_suite"),
                options=[suite.id for suite in suites],
                format_func=lambda s_id: next(suite.name for suite in suites if suite.id == s_id),
            )
            selected_suite = next(suite for suite in suites if suite.id == selected_suite_id)

            settings = get_runtime_settings(session, config)
            import_base = (ROOT_DIR / settings["import_dir"]).resolve()
            st.caption(tr("label_approved_import_dir", path=import_base))

            import_mode = st.radio(
                tr("label_import_mode"),
                ["upload", "directory"],
                format_func=lambda val: tr("option_upload_file") if val == "upload" else tr("option_use_directory"),
            )
            df = None
            source_path = None

            if import_mode == "upload":
                uploaded = st.file_uploader(tr("label_upload_xlsx"), type=["xlsx"])
                if uploaded:
                    import_base.mkdir(parents=True, exist_ok=True)
                    destination = import_base / _sanitize_filename(uploaded.name)
                    destination.write_bytes(uploaded.getbuffer())
                    source_path = destination
                    df = pd.read_excel(destination)
            else:
                directory_input = st.text_input(tr("label_directory_relative"), value="")
                if directory_input:
                    directory = _safe_resolve(directory_input, import_base)
                    try:
                        files = scan_directory(directory, import_base)
                        if not files:
                            st.warning(tr("warning_no_xlsx_files"))
                        else:
                            file_choice = st.selectbox(tr("label_select_file"), options=files)
                            source_path = file_choice
                            df = pd.read_excel(file_choice)
                    except Exception as exc:
                        st.error(tr("error_failed_scan_directory", error=exc))

            if df is not None:
                source_label = source_path.name if source_path else tr("source_upload")
                st.success(tr("msg_loaded_rows", count=len(df), source=source_label))
                missing = validate_columns(df, required=["test_name", "prompt"])
                if missing:
                    st.warning(tr("warning_missing_columns", columns=", ".join(missing)))

                with st.form("column_mapping"):
                    mapping = {}
                    for field in TEST_FIELDS:
                        options = ["(skip)"] + list(df.columns)
                        default = df.columns.get_loc(field) + 1 if field in df.columns else 0
                        selection = st.selectbox(tr("label_map_column", field=field), options, index=default)
                        mapping[field] = None if selection == "(skip)" else selection
                    import_now = st.form_submit_button(tr("button_import_tests"))
                    if import_now:
                        try:
                            imported = import_tests_from_dataframe(session, selected_suite, df, mapping)
                            st.success(tr("msg_imported_tests", count=imported))
                        except Exception as exc:
                            st.error(tr("error_import_failed", error=exc))

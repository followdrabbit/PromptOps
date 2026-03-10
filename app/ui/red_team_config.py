from __future__ import annotations

import json
from datetime import datetime
from html import escape as html_escape
from pathlib import Path

import pandas as pd
import streamlit as st

from app.core.config import AppConfig
from app.core.paths import ROOT_DIR
from app.core.red_team_prompts import DEFAULT_EVALUATOR_PROMPT_TEMPLATE
from app.core.security import is_safe_path
from app.domain import models
from app.infra.db import get_session
from app.services.audit_service import record_event
from app.services.endpoint_service import list_endpoints
from app.services.red_team_service import (
    create_red_team_case,
    create_red_team_suite,
    delete_red_team_case,
    delete_red_team_suite,
    get_red_team_suite,
    import_red_team_records,
    list_red_team_cases,
    list_red_team_suites,
    load_red_team_records_from_file,
    red_team_suites_to_records,
    update_red_team_case,
    update_red_team_suite,
    validate_red_team_import_records,
)
from app.services.settings_service import set_setting
from app.ui.utils import get_runtime_settings


RED_TEAM_TEMPLATE_XLSX_DOWNLOAD_NAME = "cyberprompt_ai_red_team_suites_template.xlsx"
RED_TEAM_TEMPLATE_JSON_DOWNLOAD_NAME = "cyberprompt_ai_red_team_suites_template.json"
RED_TEAM_TEMPLATE_XLSX_PATHS = [
    "examples/default_imports/cyberprompt_ai_default_red_team_suites.xlsx",
]
RED_TEAM_TEMPLATE_JSON_PATHS = [
    "examples/default_imports/cyberprompt_ai_default_red_team_suites.json",
]


def _to_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _safe_resolve(path_input: str, base: Path) -> Path:
    candidate = (base / path_input).resolve() if not Path(path_input).is_absolute() else Path(path_input).resolve()
    return candidate


def _sanitize_filename(name: str, fallback: str = "import.xlsx") -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip()
    return cleaned or fallback


def _scan_red_team_files(directory: Path, import_base: Path) -> list[Path]:
    if not is_safe_path(directory, import_base):
        raise ValueError("directory_outside_import_base")
    if not directory.exists():
        raise ValueError("directory_missing")
    files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".xlsx", ".json"}]
    return sorted(files)


def _load_template_bytes(relative_path: str) -> bytes | None:
    template_path = (ROOT_DIR / relative_path).resolve()
    if not is_safe_path(template_path, ROOT_DIR) or not template_path.exists() or not template_path.is_file():
        return None
    try:
        return template_path.read_bytes()
    except OSError:
        return None


def _render_red_team_template_downloads(tr, key_prefix: str) -> None:
    st.markdown(f"**{tr('section_templates')}**")
    template_xlsx_bytes = None
    for candidate in RED_TEAM_TEMPLATE_XLSX_PATHS:
        template_xlsx_bytes = _load_template_bytes(candidate)
        if template_xlsx_bytes is not None:
            break

    template_json_bytes = None
    for candidate in RED_TEAM_TEMPLATE_JSON_PATHS:
        template_json_bytes = _load_template_bytes(candidate)
        if template_json_bytes is not None:
            break

    template_cols = st.columns(2, gap="small")
    template_cols[0].download_button(
        tr("button_download_red_team_template_xlsx"),
        data=template_xlsx_bytes or b"",
        file_name=RED_TEAM_TEMPLATE_XLSX_DOWNLOAD_NAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_download_red_team_template_xlsx",
        disabled=template_xlsx_bytes is None,
        width="stretch",
    )
    template_cols[1].download_button(
        tr("button_download_red_team_template_json"),
        data=template_json_bytes or b"",
        file_name=RED_TEAM_TEMPLATE_JSON_DOWNLOAD_NAME,
        mime="application/json",
        key=f"{key_prefix}_download_red_team_template_json",
        disabled=template_json_bytes is None,
        width="stretch",
    )
    if template_xlsx_bytes is None or template_json_bytes is None:
        st.warning(tr("warning_template_files_missing"))


def _render_suite_name_grid(suites: list[models.RedTeamSuite], tr) -> None:
    st.caption(tr("label_registered_red_team_suites_count", count=len(suites)))
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


def render(context: dict, tr) -> None:
    config: AppConfig = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        settings = get_runtime_settings(session, config)
        endpoints = list_endpoints(session)
        suites = list_red_team_suites(session)

        st.subheader(tr("section_red_team_module_settings"))
        current_threads = max(1, int(settings.get("redteam_max_threads", 1)))
        current_timeout = max(5, int(settings.get("redteam_request_timeout", settings.get("default_timeout", 30))))
        current_retries = max(0, int(settings.get("redteam_retries", 0)))
        current_format = str(settings.get("redteam_result_format", "xlsx")).lower()
        if current_format not in {"xlsx", "json"}:
            current_format = "xlsx"
        current_evaluator_id = _to_optional_int(settings.get("redteam_evaluator_endpoint_id"))
        current_evaluator_prompt_template = str(settings.get("redteam_evaluator_prompt_template", "") or "")
        effective_evaluator_prompt_template = (
            current_evaluator_prompt_template.strip() or DEFAULT_EVALUATOR_PROMPT_TEMPLATE
        )
        endpoint_ids = [endpoint.id for endpoint in endpoints]
        if current_evaluator_id not in endpoint_ids:
            current_evaluator_id = None

        evaluator_options = [None] + endpoint_ids
        with st.form("red_team_module_settings"):
            redteam_max_threads = st.number_input(
                tr("label_red_team_max_threads"),
                min_value=1,
                max_value=32,
                value=current_threads,
                step=1,
                help=tr("help_red_team_max_threads"),
            )
            redteam_request_timeout = st.number_input(
                tr("label_red_team_request_timeout"),
                min_value=5,
                max_value=600,
                value=current_timeout,
                step=1,
                help=tr("help_red_team_request_timeout"),
            )
            redteam_retries = st.number_input(
                tr("label_red_team_retries"),
                min_value=0,
                max_value=10,
                value=current_retries,
                step=1,
                help=tr("help_red_team_retries"),
            )
            redteam_result_format = st.selectbox(
                tr("label_red_team_result_format"),
                options=["xlsx", "json"],
                index=0 if current_format == "xlsx" else 1,
                format_func=lambda value: value.upper(),
                help=tr("help_red_team_result_format"),
            )
            redteam_evaluator_endpoint_id = st.selectbox(
                tr("label_red_team_evaluator_endpoint"),
                options=evaluator_options,
                index=evaluator_options.index(current_evaluator_id) if current_evaluator_id in evaluator_options else 0,
                format_func=lambda endpoint_id: tr("option_select")
                if endpoint_id is None
                else next((endpoint.name for endpoint in endpoints if endpoint.id == endpoint_id), tr("label_unknown")),
                help=tr("help_red_team_evaluator_endpoint"),
            )
            redteam_evaluator_prompt_template = st.text_area(
                tr("label_red_team_evaluator_prompt_template"),
                value=current_evaluator_prompt_template,
                height=260,
                help=tr("help_red_team_evaluator_prompt_template"),
                placeholder=tr("placeholder_red_team_evaluator_prompt_template"),
            )
            st.caption(tr("help_red_team_evaluator_prompt_template_variables"))
            save_module = st.form_submit_button(tr("button_save_red_team_module_settings"))
            if save_module:
                normalized_prompt_template = redteam_evaluator_prompt_template.strip()
                set_setting(session, "redteam_max_threads", str(int(redteam_max_threads)))
                set_setting(session, "redteam_request_timeout", str(int(redteam_request_timeout)))
                set_setting(session, "redteam_retries", str(int(redteam_retries)))
                set_setting(session, "redteam_result_format", redteam_result_format)
                set_setting(
                    session,
                    "redteam_evaluator_endpoint_id",
                    "" if redteam_evaluator_endpoint_id is None else str(redteam_evaluator_endpoint_id),
                )
                set_setting(
                    session,
                    "redteam_evaluator_prompt_template",
                    normalized_prompt_template,
                )
                record_event(
                    session,
                    "update",
                    "settings",
                    "red_team_module",
                    after_value={
                        "redteam_max_threads": int(redteam_max_threads),
                        "redteam_request_timeout": int(redteam_request_timeout),
                        "redteam_retries": int(redteam_retries),
                        "redteam_result_format": redteam_result_format,
                        "redteam_evaluator_endpoint_id": redteam_evaluator_endpoint_id,
                        "redteam_evaluator_prompt_template_custom": bool(normalized_prompt_template),
                        "redteam_evaluator_prompt_template_chars": len(normalized_prompt_template),
                    },
                )
                session.commit()
                st.success(tr("msg_red_team_module_settings_saved"))
                st.rerun()

        st.caption(
            tr("label_red_team_evaluator_prompt_source_custom")
            if current_evaluator_prompt_template.strip()
            else tr("label_red_team_evaluator_prompt_source_default")
        )
        st.text_area(
            tr("label_red_team_current_evaluator_prompt"),
            value=effective_evaluator_prompt_template,
            height=260,
            disabled=True,
            key="red_team_current_evaluator_prompt_display",
        )
        if st.button(
            tr("button_reset_red_team_evaluator_prompt_template"),
            key="button_reset_red_team_evaluator_prompt_template",
        ):
            set_setting(session, "redteam_evaluator_prompt_template", "")
            record_event(
                session,
                "update",
                "settings",
                "red_team_module",
                after_value={
                    "redteam_evaluator_prompt_template_custom": False,
                    "redteam_evaluator_prompt_template_chars": 0,
                },
            )
            session.commit()
            st.success(tr("msg_red_team_evaluator_prompt_template_reset"))
            st.rerun()

        st.subheader(tr("section_red_team_suites"))
        if suites:
            _render_suite_name_grid(suites, tr)
        else:
            st.info(tr("no_red_team_suites"))

        suite_tabs = st.tabs([tr("tab_create"), tr("tab_edit"), tr("tab_delete"), tr("tab_import_export")])

        with suite_tabs[0]:
            st.subheader(tr("section_create_red_team_suite"))
            _render_red_team_template_downloads(tr, "red_team_suite_create")
            with st.form("create_red_team_suite"):
                suite_name = st.text_input(tr("label_red_team_suite_name"))
                suite_description = st.text_area(tr("label_red_team_suite_description"))
                create = st.form_submit_button(tr("button_create_red_team_suite"))
                if create:
                    try:
                        create_red_team_suite(session, suite_name, suite_description)
                        session.commit()
                        st.success(tr("msg_red_team_suite_created"))
                        st.rerun()
                    except ValueError as exc:
                        reason = str(exc)
                        if reason == "suite_name_required":
                            st.error(tr("error_suite_name_required"))
                        elif reason == "suite_name_too_long":
                            st.error(tr("error_suite_name_too_long"))
                        else:
                            st.error(tr("error_failed_create_red_team_suite", error=exc))
                    except Exception as exc:
                        st.error(tr("error_failed_create_red_team_suite", error=exc))

        with suite_tabs[1]:
            st.subheader(tr("section_edit_red_team_suite"))
            if not suites:
                st.info(tr("no_red_team_suites"))
            else:
                selected_suite_id = st.selectbox(
                    tr("label_select_red_team_suite_to_edit"),
                    options=[None] + [suite.id for suite in suites],
                    format_func=lambda suite_id: tr("option_select")
                    if suite_id is None
                    else next((suite.name for suite in suites if suite.id == suite_id), tr("label_unknown")),
                    key="edit_red_team_suite_select",
                )
                if selected_suite_id is None:
                    st.info(tr("info_select_item_to_edit"))
                else:
                    suite = get_red_team_suite(session, selected_suite_id)
                    if suite is None:
                        st.error(tr("error_red_team_suite_not_found"))
                    else:
                        with st.form(f"edit_red_team_suite_form_{suite.id}"):
                            updated_name = st.text_input(tr("label_red_team_suite_name"), value=suite.name)
                            updated_description = st.text_area(
                                tr("label_red_team_suite_description"),
                                value=suite.description or "",
                            )
                            update = st.form_submit_button(tr("button_update_red_team_suite"))
                            if update:
                                try:
                                    update_red_team_suite(session, suite, updated_name, updated_description)
                                    session.commit()
                                    st.success(tr("msg_red_team_suite_updated"))
                                    st.rerun()
                                except ValueError as exc:
                                    reason = str(exc)
                                    if reason == "suite_name_required":
                                        st.error(tr("error_suite_name_required"))
                                    elif reason == "suite_name_too_long":
                                        st.error(tr("error_suite_name_too_long"))
                                    else:
                                        st.error(tr("error_failed_update_red_team_suite", error=exc))
                                except Exception as exc:
                                    st.error(tr("error_failed_update_red_team_suite", error=exc))

                        st.markdown(f"**{tr('section_red_team_cases')}**")
                        cases = list_red_team_cases(session, suite)
                        if cases:
                            st.caption(tr("label_red_team_case_count", count=len(cases)))
                        else:
                            st.info(tr("no_red_team_cases"))

                        case_tabs = st.tabs([tr("tab_add_case"), tr("tab_edit_case"), tr("tab_delete_case")])
                        with case_tabs[0]:
                            with st.form(f"add_red_team_case_{suite.id}"):
                                prompt = st.text_area(tr("label_red_team_prompt"))
                                purpose = st.text_area(tr("label_red_team_purpose"))
                                expected_result = st.text_area(tr("label_red_team_expected_result"))
                                relevance = st.slider(tr("label_red_team_relevance"), min_value=0, max_value=10, value=5)
                                notes = st.text_area(tr("label_red_team_notes"))
                                add = st.form_submit_button(tr("button_add_red_team_case"))
                                if add:
                                    try:
                                        create_red_team_case(
                                            session=session,
                                            suite=suite,
                                            prompt=prompt,
                                            purpose=purpose,
                                            expected_result=expected_result,
                                            relevance=relevance,
                                            notes=notes,
                                        )
                                        session.commit()
                                        st.success(tr("msg_red_team_case_added"))
                                        st.rerun()
                                    except ValueError as exc:
                                        reason = str(exc)
                                        if reason == "prompt_required":
                                            st.error(tr("error_prompt_required"))
                                        elif reason == "relevance_out_of_range":
                                            st.error(tr("error_red_team_relevance_range"))
                                        else:
                                            st.error(tr("error_failed_create_red_team_case", error=exc))
                                    except Exception as exc:
                                        st.error(tr("error_failed_create_red_team_case", error=exc))

                        with case_tabs[1]:
                            if not cases:
                                st.info(tr("no_red_team_cases"))
                            else:
                                case_id = st.selectbox(
                                    tr("label_select_red_team_case_to_edit"),
                                    options=[None] + [case.id for case in cases],
                                    format_func=lambda selected_case_id: tr("option_select")
                                    if selected_case_id is None
                                    else next(
                                        (
                                            f"#{case.id} - {case.prompt[:80]}"
                                            for case in cases
                                            if case.id == selected_case_id
                                        ),
                                        tr("label_unknown"),
                                    ),
                                    key=f"select_red_team_case_to_edit_{suite.id}",
                                )
                                if case_id is None:
                                    st.info(tr("info_select_item_to_edit"))
                                else:
                                    case = next((item for item in cases if item.id == case_id), None)
                                    if case is not None:
                                        with st.form(f"edit_red_team_case_{case.id}"):
                                            prompt = st.text_area(tr("label_red_team_prompt"), value=case.prompt)
                                            purpose = st.text_area(
                                                tr("label_red_team_purpose"),
                                                value=case.purpose or "",
                                            )
                                            expected_result = st.text_area(
                                                tr("label_red_team_expected_result"),
                                                value=case.expected_result or "",
                                            )
                                            relevance = st.slider(
                                                tr("label_red_team_relevance"),
                                                min_value=0,
                                                max_value=10,
                                                value=case.relevance if case.relevance is not None else 5,
                                            )
                                            notes = st.text_area(tr("label_red_team_notes"), value=case.notes or "")
                                            update = st.form_submit_button(tr("button_update_red_team_case"))
                                            if update:
                                                try:
                                                    update_red_team_case(
                                                        session=session,
                                                        case=case,
                                                        prompt=prompt,
                                                        purpose=purpose,
                                                        expected_result=expected_result,
                                                        relevance=relevance,
                                                        notes=notes,
                                                    )
                                                    session.commit()
                                                    st.success(tr("msg_red_team_case_updated"))
                                                    st.rerun()
                                                except ValueError as exc:
                                                    reason = str(exc)
                                                    if reason == "prompt_required":
                                                        st.error(tr("error_prompt_required"))
                                                    elif reason == "relevance_out_of_range":
                                                        st.error(tr("error_red_team_relevance_range"))
                                                    else:
                                                        st.error(tr("error_failed_update_red_team_case", error=exc))
                                                except Exception as exc:
                                                    st.error(tr("error_failed_update_red_team_case", error=exc))

                        with case_tabs[2]:
                            if not cases:
                                st.info(tr("no_red_team_cases"))
                            else:
                                case_id = st.selectbox(
                                    tr("label_select_red_team_case_to_delete"),
                                    options=[case.id for case in cases],
                                    format_func=lambda selected_case_id: next(
                                        (
                                            f"#{case.id} - {case.prompt[:80]}"
                                            for case in cases
                                            if case.id == selected_case_id
                                        ),
                                        tr("label_unknown"),
                                    ),
                                    key=f"select_red_team_case_to_delete_{suite.id}",
                                )
                                case_to_delete = next((item for item in cases if item.id == case_id), None)
                                if case_to_delete is not None:
                                    confirm_case_delete = st.checkbox(
                                        tr("label_confirm_delete_red_team_case"),
                                        key=f"confirm_delete_red_team_case_{case_to_delete.id}",
                                    )
                                    if st.button(
                                        tr("button_delete_red_team_case"),
                                        key=f"delete_red_team_case_btn_{case_to_delete.id}",
                                    ):
                                        if not confirm_case_delete:
                                            st.warning(tr("warning_confirm_delete_red_team_case"))
                                        else:
                                            try:
                                                delete_red_team_case(session, case_to_delete)
                                                session.commit()
                                                st.success(tr("msg_red_team_case_deleted"))
                                                st.rerun()
                                            except Exception as exc:
                                                st.error(tr("error_failed_delete_red_team_case", error=exc))

        with suite_tabs[2]:
            st.subheader(tr("section_delete_red_team_suite"))
            if not suites:
                st.info(tr("no_red_team_suites"))
            else:
                selected_suite_id = st.selectbox(
                    tr("label_select_red_team_suite_to_delete"),
                    options=[suite.id for suite in suites],
                    format_func=lambda suite_id: next((suite.name for suite in suites if suite.id == suite_id), ""),
                    key="delete_red_team_suite_select",
                )
                suite = get_red_team_suite(session, selected_suite_id)
                if suite is not None:
                    confirm_delete = st.checkbox(
                        tr("label_confirm_delete_red_team_suite"),
                        key=f"confirm_delete_red_team_suite_{suite.id}",
                    )
                    if st.button(tr("button_delete_red_team_suite"), key=f"delete_red_team_suite_{suite.id}"):
                        if not confirm_delete:
                            st.warning(tr("warning_confirm_delete_red_team_suite"))
                        else:
                            pending_key = "pending_delete_red_team_suite_id"
                            st.session_state[pending_key] = suite.id
                            st.rerun()

                    pending_key = "pending_delete_red_team_suite_id"
                    if st.session_state.get(pending_key) == suite.id:
                        st.warning(tr("confirm_delete_red_team_suite", name=suite.name))
                        confirm_cols = st.columns(2, gap="small")
                        if confirm_cols[0].button(
                            tr("button_confirm_delete_red_team_suite"),
                            key=f"confirm_delete_red_team_suite_final_{suite.id}",
                            width="stretch",
                        ):
                            try:
                                delete_red_team_suite(session, suite)
                                session.commit()
                                st.session_state.pop(pending_key, None)
                                st.success(tr("msg_red_team_suite_deleted"))
                                st.rerun()
                            except Exception as exc:
                                st.error(tr("error_failed_delete_red_team_suite", error=exc))
                        if confirm_cols[1].button(
                            tr("button_cancel_delete_red_team_suite"),
                            key=f"cancel_delete_red_team_suite_{suite.id}",
                            width="stretch",
                        ):
                            st.session_state.pop(pending_key, None)
                            st.rerun()

        with suite_tabs[3]:
            st.subheader(tr("section_red_team_import_export"))
            st.info(tr("red_team_import_export_tips"))

            settings = get_runtime_settings(session, config)
            import_base = _safe_resolve(settings["import_dir"], ROOT_DIR)
            output_base = _safe_resolve(settings["output_dir"], ROOT_DIR)
            if not is_safe_path(import_base, ROOT_DIR) or not is_safe_path(output_base, ROOT_DIR):
                st.error(tr("error_red_team_dirs_within_project"))
            else:
                st.caption(tr("label_approved_import_dir", path=import_base))
                st.caption(tr("label_approved_output_dir", path=output_base))
                _render_red_team_template_downloads(tr, "red_team_import_export")

                st.markdown(f"**{tr('section_import_red_team_suites')}**")
                import_mode = st.radio(
                    tr("label_import_mode"),
                    ["upload", "directory"],
                    format_func=lambda val: tr("option_upload_file")
                    if val == "upload"
                    else tr("option_use_directory"),
                    key="red_team_import_mode",
                )
                source_path: Path | None = None
                raw_records: list[dict] | None = None

                if import_mode == "upload":
                    uploaded = st.file_uploader(
                        tr("label_upload_red_team_file"),
                        type=["xlsx", "json"],
                        key="red_team_import_upload_file",
                    )
                    if uploaded:
                        suffix = Path(uploaded.name).suffix.lower()
                        fallback_suffix = ".json" if suffix == ".json" else ".xlsx"
                        if suffix not in {".xlsx", ".json"}:
                            st.error(tr("error_red_team_import_file_type"))
                        else:
                            safe_name = _sanitize_filename(
                                uploaded.name,
                                fallback=f"red_team_import{fallback_suffix}",
                            )
                            destination = (import_base / safe_name).resolve()
                            if not is_safe_path(destination, import_base):
                                st.error(tr("error_red_team_import_path"))
                            else:
                                import_base.mkdir(parents=True, exist_ok=True)
                                destination.write_bytes(uploaded.getbuffer())
                                source_path = destination
                                try:
                                    raw_records = load_red_team_records_from_file(destination)
                                except Exception as exc:
                                    st.error(tr("error_red_team_import_parse", error=exc))
                else:
                    directory_input = st.text_input(
                        tr("label_directory_relative"),
                        value="",
                        key="red_team_import_directory_relative",
                    )
                    if directory_input:
                        directory = _safe_resolve(directory_input, import_base)
                        try:
                            files = _scan_red_team_files(directory, import_base)
                            if not files:
                                st.warning(tr("warning_no_red_team_files"))
                            else:
                                file_choice = st.selectbox(
                                    tr("label_select_file"),
                                    options=files,
                                    key="red_team_import_select_file",
                                )
                                source_path = file_choice
                                try:
                                    raw_records = load_red_team_records_from_file(file_choice)
                                except Exception as exc:
                                    st.error(tr("error_red_team_import_parse", error=exc))
                        except ValueError as exc:
                            reason = str(exc)
                            if reason == "directory_outside_import_base":
                                st.error(tr("error_red_team_import_directory_path"))
                            elif reason == "directory_missing":
                                st.error(tr("error_red_team_import_directory_missing"))
                            else:
                                st.error(tr("error_failed_scan_directory", error=exc))
                        except Exception as exc:
                            st.error(tr("error_failed_scan_directory", error=exc))

                if raw_records is not None:
                    source_label = source_path.name if source_path else tr("source_upload")
                    normalized_records, validation_errors = validate_red_team_import_records(raw_records)
                    if validation_errors:
                        st.warning(tr("warning_red_team_import_validation_issues"))
                        for issue in validation_errors:
                            st.write(f"- {issue}")

                    if normalized_records:
                        preview_df = pd.DataFrame(normalized_records)
                        st.success(tr("msg_loaded_rows", count=len(normalized_records), source=source_label))
                        st.dataframe(preview_df.fillna(""), width="stretch")
                        if st.button(tr("button_import_red_team_suites"), key="button_import_red_team_suites"):
                            try:
                                summary = import_red_team_records(session, normalized_records)
                                session.commit()
                                st.success(
                                    tr(
                                        "msg_red_team_suites_imported",
                                        created=summary["created_suites"],
                                        cases=summary["imported_cases"],
                                        skipped_existing=summary["skipped_existing"],
                                    )
                                )
                                skipped_names = summary.get("skipped_existing_names") or []
                                if skipped_names:
                                    st.warning(
                                        tr(
                                            "warning_red_team_suite_existing_skipped",
                                            names=", ".join(skipped_names),
                                        )
                                    )
                                st.rerun()
                            except Exception as exc:
                                st.error(tr("error_import_failed", error=exc))
                    else:
                        st.error(tr("error_red_team_no_valid_records"))

                st.markdown(f"**{tr('section_export_red_team_suites')}**")
                if not suites:
                    st.info(tr("no_red_team_suites"))
                else:
                    export_scope = st.selectbox(
                        tr("label_red_team_export_scope"),
                        options=["all"] + [suite.id for suite in suites],
                        format_func=lambda value: tr("option_all_red_team_suites")
                        if value == "all"
                        else next(suite.name for suite in suites if suite.id == value),
                        key="red_team_export_scope",
                    )
                    suites_for_export = (
                        suites
                        if export_scope == "all"
                        else [next(suite for suite in suites if suite.id == export_scope)]
                    )
                    red_team_records = red_team_suites_to_records(session, suites_for_export)
                    st.caption(
                        tr(
                            "label_red_team_suites_for_export_count",
                            suites=len(suites_for_export),
                            cases=len(red_team_records),
                        )
                    )

                    export_format = st.selectbox(
                        tr("label_red_team_export_format"),
                        ["xlsx", "json"],
                        format_func=lambda value: value.upper(),
                        key="red_team_export_format",
                    )
                    scope_name = "all_red_team_suites" if export_scope == "all" else f"red_team_suite_{export_scope}"
                    default_export_name = f"{scope_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
                    export_filename = st.text_input(
                        tr("label_red_team_export_filename"),
                        value=default_export_name,
                        key="red_team_export_filename",
                    )
                    allow_overwrite = st.checkbox(
                        tr("label_red_team_export_overwrite"),
                        value=False,
                        key="red_team_export_allow_overwrite",
                    )
                    if st.button(tr("button_export_red_team_suites"), key="button_export_red_team_suites"):
                        if not red_team_records:
                            st.warning(tr("warning_no_red_team_records_to_export"))
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
                                st.error(tr("error_red_team_export_path"))
                            elif target_path.exists() and not allow_overwrite:
                                st.error(tr("error_red_team_export_exists"))
                            else:
                                try:
                                    output_base.mkdir(parents=True, exist_ok=True)
                                    if export_format == "xlsx":
                                        pd.DataFrame(red_team_records).to_excel(target_path, index=False)
                                    else:
                                        target_path.write_text(
                                            json.dumps(red_team_records, indent=2, ensure_ascii=False),
                                            encoding="utf-8",
                                        )
                                    record_event(
                                        session,
                                        "export",
                                        "red_team_suites",
                                        str(export_scope),
                                        after_value={
                                            "path": str(target_path),
                                            "format": export_format,
                                            "suites": len(suites_for_export),
                                            "cases": len(red_team_records),
                                        },
                                    )
                                    session.commit()
                                    st.success(tr("msg_red_team_suites_exported", path=target_path))
                                except Exception as exc:
                                    st.error(tr("error_red_team_export_failed", error=exc))

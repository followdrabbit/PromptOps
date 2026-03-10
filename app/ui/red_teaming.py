from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from app.core.paths import ROOT_DIR
from app.core.secrets import SecretManager
from app.core.security import is_safe_path
from app.domain import models
from app.infra.db import get_session
from app.jobs.red_team_runner import run_red_team_suite
from app.services.audit_service import record_event
from app.services.endpoint_service import list_endpoints
from app.services.red_team_service import (
    export_red_team_run_results,
    list_red_team_cases,
    list_red_team_suites,
)
from app.ui.endpoint_variables import render_runtime_variable_editor
from app.ui.file_actions import open_file_in_default_app
from app.ui.i18n import get_translator
from app.ui.utils import get_runtime_settings


SUITE_TOGGLE_KEY_PREFIX = "red_team_suite_toggle_"
SUITE_TOGGLE_ALL_KEY = "red_team_suite_toggle_all"
GENERATED_RESULTS_KEY = "red_team_generated_result_files"


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


def _sanitize_filename_segment(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in (value or "").strip())
    normalized = "_".join(part for part in cleaned.split("_") if part)
    return normalized or fallback


def _build_result_filename(endpoint_name: str, suite_name: str, extension: str) -> str:
    endpoint_part = _sanitize_filename_segment(endpoint_name, "endpoint")
    suite_part = _sanitize_filename_segment(suite_name, "redteam_suite")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"red_teaming_{endpoint_part}_{suite_part}_{timestamp}.{extension}"


def _suite_toggle_key(suite_id: int) -> str:
    return f"{SUITE_TOGGLE_KEY_PREFIX}{suite_id}"


def _on_toggle_all_suites_change(suite_ids: list[int]) -> None:
    enabled = bool(st.session_state.get(SUITE_TOGGLE_ALL_KEY, False))
    for suite_id in suite_ids:
        st.session_state[_suite_toggle_key(suite_id)] = enabled


def _on_suite_toggle_change(suite_ids: list[int]) -> None:
    if not suite_ids:
        st.session_state[SUITE_TOGGLE_ALL_KEY] = False
        return
    st.session_state[SUITE_TOGGLE_ALL_KEY] = all(
        bool(st.session_state.get(_suite_toggle_key(suite_id), False))
        for suite_id in suite_ids
    )


def _render_suite_toggle_grid(suites: list[models.RedTeamSuite], tr) -> list[models.RedTeamSuite]:
    st.markdown(f"**{tr('label_red_team_suites')}**")
    suite_ids = [suite.id for suite in suites]
    for suite_id in suite_ids:
        toggle_key = _suite_toggle_key(suite_id)
        if toggle_key not in st.session_state:
            st.session_state[toggle_key] = False

    all_enabled = bool(suite_ids) and all(
        bool(st.session_state.get(_suite_toggle_key(suite_id), False))
        for suite_id in suite_ids
    )
    st.session_state[SUITE_TOGGLE_ALL_KEY] = all_enabled

    with st.container(border=True):
        all_cols = st.columns([0.8, 0.2], gap="small")
        all_cols[0].markdown(f"**{tr('label_all_red_team_suites')}**")
        all_cols[1].toggle(
            tr("label_enable_all_red_team_suites"),
            key=SUITE_TOGGLE_ALL_KEY,
            help=tr("help_enable_all_red_team_suites"),
            label_visibility="collapsed",
            on_change=_on_toggle_all_suites_change,
            args=(suite_ids,),
        )

    for row_start in range(0, len(suites), 3):
        row_cols = st.columns(3, gap="small")
        for col_index in range(3):
            suite_index = row_start + col_index
            if suite_index >= len(suites):
                continue
            suite = suites[suite_index]
            with row_cols[col_index]:
                with st.container(border=True):
                    suite_cols = st.columns([0.8, 0.2], gap="small")
                    suite_cols[0].markdown(f"**{suite.name}**")
                    suite_cols[1].toggle(
                        tr("label_enable_red_team_suite"),
                        key=_suite_toggle_key(suite.id),
                        help=tr("help_enable_red_team_suite", name=suite.name),
                        label_visibility="collapsed",
                        on_change=_on_suite_toggle_change,
                        args=(suite_ids,),
                    )

    selected_suites = [suite for suite in suites if st.session_state.get(_suite_toggle_key(suite.id), False)]
    st.caption(tr("label_selected_red_team_suites_count", count=len(selected_suites)))
    return selected_suites


def _normalize_result_format(value: str | None) -> str:
    normalized = (value or "xlsx").strip().lower()
    return normalized if normalized in {"xlsx", "json"} else "xlsx"


def render(context: dict) -> None:
    config = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
    tr = get_translator(lang)

    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{tr("red_team_badge")}</span>
            <div class="intro-title">{tr("red_team_title")}</div>
            <p class="intro-subtitle">
                {tr("red_team_subtitle")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with get_session(session_factory) as session:
        if GENERATED_RESULTS_KEY not in st.session_state:
            st.session_state[GENERATED_RESULTS_KEY] = []
        runtime_settings = get_runtime_settings(session, config)
        max_threads = max(1, int(runtime_settings.get("redteam_max_threads", 1)))
        request_timeout = max(5, int(runtime_settings.get("redteam_request_timeout", runtime_settings.get("default_timeout", 30))))
        retries = max(0, int(runtime_settings.get("redteam_retries", 0)))
        result_format = _normalize_result_format(runtime_settings.get("redteam_result_format", "xlsx"))
        default_evaluator_id = _to_optional_int(runtime_settings.get("redteam_evaluator_endpoint_id"))
        evaluator_prompt_template = str(runtime_settings.get("redteam_evaluator_prompt_template", "") or "")

        suites = list_red_team_suites(session)
        endpoints = list_endpoints(session)
        if not suites:
            st.info(tr("info_create_red_team_suite_in_config"))
            return
        if not endpoints:
            st.info(tr("info_create_endpoint_in_config"))
            return

        selected_suites = _render_suite_toggle_grid(suites, tr)

        endpoint_ids = [endpoint.id for endpoint in endpoints]
        if default_evaluator_id not in endpoint_ids:
            default_evaluator_id = endpoint_ids[0]

        target_endpoint_id = st.selectbox(
            tr("label_red_team_target_endpoint"),
            options=endpoint_ids,
            format_func=lambda endpoint_id: next(
                (endpoint.name for endpoint in endpoints if endpoint.id == endpoint_id),
                tr("label_unknown"),
            ),
        )
        evaluator_endpoint_id = st.selectbox(
            tr("label_red_team_evaluator_endpoint"),
            options=endpoint_ids,
            index=endpoint_ids.index(default_evaluator_id) if default_evaluator_id in endpoint_ids else 0,
            format_func=lambda endpoint_id: next(
                (endpoint.name for endpoint in endpoints if endpoint.id == endpoint_id),
                tr("label_unknown"),
            ),
        )
        target_endpoint = next(endpoint for endpoint in endpoints if endpoint.id == target_endpoint_id)
        evaluator_endpoint = next(endpoint for endpoint in endpoints if endpoint.id == evaluator_endpoint_id)
        secret_manager = SecretManager()
        target_variables = secret_manager.get_variables(session, target_endpoint.id)
        evaluator_variables = secret_manager.get_variables(session, evaluator_endpoint.id)
        target_variable_types = secret_manager.get_variable_types(session, target_endpoint.id)
        evaluator_variable_types = secret_manager.get_variable_types(session, evaluator_endpoint.id)

        runtime_cols = st.columns(2, gap="large")
        with runtime_cols[0]:
            with st.expander(tr("section_runtime_additional_variables_target"), expanded=False):
                target_runtime_overrides = render_runtime_variable_editor(
                    tr,
                    endpoint_name=target_endpoint.name,
                    endpoint_id=target_endpoint.id,
                    variables=target_variables,
                    variable_types=target_variable_types,
                    key_prefix="redteam_target_runtime_var",
                )
        with runtime_cols[1]:
            with st.expander(tr("section_runtime_additional_variables_evaluator"), expanded=False):
                evaluator_runtime_overrides = render_runtime_variable_editor(
                    tr,
                    endpoint_name=evaluator_endpoint.name,
                    endpoint_id=evaluator_endpoint.id,
                    variables=evaluator_variables,
                    variable_types=evaluator_variable_types,
                    key_prefix="redteam_evaluator_runtime_var",
                )

        cases_by_suite: dict[int, list[models.RedTeamCase]] = {}
        total_cases = 0
        for suite in selected_suites:
            suite_cases = list_red_team_cases(session, suite)
            cases_by_suite[suite.id] = suite_cases
            total_cases += len(suite_cases)

        st.caption(tr("label_red_team_cases_to_validate", count=total_cases))
        st.caption(
            tr(
                "label_red_team_execution_profile",
                threads=max_threads,
                timeout=request_timeout,
                retries=retries,
                format=result_format.upper(),
            )
        )

        if st.button(tr("button_run_red_team_tests")):
            if not selected_suites:
                st.warning(tr("warning_select_red_team_suite_for_run"))
                return
            if total_cases == 0:
                st.warning(tr("warning_no_red_team_cases_in_selected_suites"))
                return

            progress = st.progress(0)
            status = st.empty()

            completed_global = 0
            completed_runs = 0
            run_errors: list[str] = []
            total_cases_safe = max(total_cases, 1)

            export_dir = (ROOT_DIR / runtime_settings["output_dir"]).resolve()
            export_allowed = is_safe_path(export_dir, ROOT_DIR)
            if export_allowed:
                export_dir.mkdir(parents=True, exist_ok=True)
            else:
                st.error(tr("error_export_dir"))

            for suite in selected_suites:
                cases = cases_by_suite.get(suite.id, [])
                if not cases:
                    continue

                def update_progress(completed: int, total: int, base: int = completed_global) -> None:
                    overall_completed = base + completed
                    pct = int((overall_completed / total_cases_safe) * 100)
                    progress.progress(pct)
                    status.info(tr("status_completed", completed=overall_completed, total=total_cases_safe))

                try:
                    run = run_red_team_suite(
                        session=session,
                        suite=suite,
                        target_endpoint=target_endpoint,
                        evaluator_endpoint=evaluator_endpoint,
                        cases=cases,
                        default_timeout=request_timeout,
                        max_threads=max_threads,
                        max_retries=retries,
                        target_variable_overrides=target_runtime_overrides,
                        evaluator_variable_overrides=evaluator_runtime_overrides,
                        evaluator_prompt_template=evaluator_prompt_template,
                        verify_ssl=runtime_settings.get("ssl_verify", True),
                        progress_callback=update_progress,
                    )
                    completed_global += len(cases)
                    completed_runs += 1
                    status.info(tr("status_completed", completed=completed_global, total=total_cases_safe))
                    st.success(tr("msg_red_team_run_completed_for_suite", run_id=run.id, suite=suite.name))

                    if export_allowed:
                        auto_filename = _build_result_filename(target_endpoint.name, suite.name, result_format)
                        auto_path = export_dir / auto_filename
                        export_red_team_run_results(session, run.id, auto_path, export_format=result_format)
                        record_event(
                            session,
                            "export",
                            "red_team_run_results",
                            str(run.id),
                            after_value={
                                "path": str(auto_path),
                                "format": result_format,
                                "source": "auto_after_run",
                            },
                        )
                        recent_paths = [str(auto_path)] + [
                            path
                            for path in st.session_state.get(GENERATED_RESULTS_KEY, [])
                            if str(path) != str(auto_path)
                        ]
                        st.session_state[GENERATED_RESULTS_KEY] = recent_paths[:20]
                        st.success(tr("msg_red_team_results_auto_exported", path=auto_path))
                except Exception as exc:
                    run_errors.append(f"{suite.name}: {exc}")
                    st.error(tr("error_red_team_run_failed_for_suite", suite=suite.name, error=exc))

            final_pct = int((completed_global / total_cases_safe) * 100)
            progress.progress(final_pct)
            if completed_runs:
                st.success(tr("msg_red_team_runs_completed_total", count=completed_runs))
            if run_errors:
                st.warning(tr("warning_red_team_suites_failed_count", count=len(run_errors)))

        generated_files = st.session_state.get(GENERATED_RESULTS_KEY, [])
        if generated_files:
            st.markdown(f"**{tr('section_generated_result_files')}**")
            for index, path_text in enumerate(generated_files):
                file_path = Path(path_text)
                row_cols = st.columns([0.78, 0.22], gap="small")
                row_cols[0].caption(str(file_path))
                if row_cols[1].button(
                    tr("button_open_generated_file"),
                    key=f"open_generated_red_team_file_{index}_{file_path.name}",
                    width="stretch",
                ):
                    try:
                        open_file_in_default_app(file_path)
                        st.success(tr("msg_open_generated_file", path=file_path))
                    except FileNotFoundError:
                        st.error(tr("error_generated_file_not_found", path=file_path))
                    except Exception as exc:
                        st.error(tr("error_open_generated_file", path=file_path, error=exc))

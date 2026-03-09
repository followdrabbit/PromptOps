from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.core.paths import ROOT_DIR
from app.core.security import is_safe_path
from app.domain import models
from app.infra.db import get_session
from app.jobs.test_runner import run_test_suite
from app.services.endpoint_service import list_endpoints
from app.services.test_service import export_run_results
from app.services.audit_service import record_event
from app.ui.utils import get_runtime_settings
from app.ui.i18n import get_translator


SUITE_TOGGLE_KEY_PREFIX = "automated_tests_suite_toggle_"


def _normalize_result_format(value: str | None) -> str:
    if not value:
        return "xlsx"
    normalized = value.strip().lower()
    return normalized if normalized in {"xlsx", "json"} else "xlsx"


def _sanitize_filename_segment(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in (value or "").strip())
    normalized = "_".join(part for part in cleaned.split("_") if part)
    return normalized or fallback


def _build_result_filename(endpoint_name: str, suite_name: str, extension: str) -> str:
    endpoint_part = _sanitize_filename_segment(endpoint_name, "endpoint")
    suite_part = _sanitize_filename_segment(suite_name, "suite")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"{endpoint_part}_{suite_part}_{timestamp}.{extension}"


def _render_suite_toggle_grid(suites: list[models.TestSuite], tr) -> list[models.TestSuite]:
    st.markdown(f"**{tr('label_test_suites')}**")
    for suite in suites:
        toggle_key = f"{SUITE_TOGGLE_KEY_PREFIX}{suite.id}"
        if toggle_key not in st.session_state:
            st.session_state[toggle_key] = False

    for row_start in range(0, len(suites), 3):
        row_cols = st.columns(3, gap="small")
        for col_index in range(3):
            suite_index = row_start + col_index
            if suite_index >= len(suites):
                continue
            suite = suites[suite_index]
            toggle_key = f"{SUITE_TOGGLE_KEY_PREFIX}{suite.id}"
            with row_cols[col_index]:
                with st.container(border=True):
                    suite_cols = st.columns([0.8, 0.2], gap="small")
                    suite_cols[0].markdown(f"**{suite.name}**")
                    suite_cols[1].toggle(
                        tr("label_enable_suite"),
                        key=toggle_key,
                        help=tr("help_enable_suite", name=suite.name),
                        label_visibility="collapsed",
                    )

    selected_suites = [
        suite
        for suite in suites
        if st.session_state.get(f"{SUITE_TOGGLE_KEY_PREFIX}{suite.id}", False)
    ]
    st.caption(tr("label_selected_suites_count", count=len(selected_suites)))
    return selected_suites


def _is_test_enabled(test_case: models.TestCase) -> bool:
    return bool(getattr(test_case, "enabled", True))


def render(context: dict) -> None:
    config = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
    tr = get_translator(lang)

    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{tr("tests_badge")}</span>
            <div class="intro-title">{tr("tests_title")}</div>
            <p class="intro-subtitle">
                {tr("tests_subtitle")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with get_session(session_factory) as session:
        runtime_settings = get_runtime_settings(session, config)
        tests_timeout = max(5, int(runtime_settings.get("tests_request_timeout", runtime_settings.get("default_timeout", 30))))
        tests_max_threads = max(1, int(runtime_settings.get("tests_max_threads", 1)))
        default_result_format = _normalize_result_format(runtime_settings.get("tests_result_format", "xlsx"))
        suites = session.query(models.TestSuite).order_by(models.TestSuite.created_at.desc()).all()
        endpoints = list_endpoints(session)
        if not suites:
            st.info(tr("info_create_suite_in_config"))
            return
        if not endpoints:
            st.info(tr("info_create_endpoint_in_config"))
            return

        selected_suites = _render_suite_toggle_grid(suites, tr)

        endpoint_id = st.selectbox(
            tr("label_endpoint"),
            options=[ep.id for ep in endpoints],
            format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id),
        )
        endpoint = next(ep for ep in endpoints if ep.id == endpoint_id)

        tests_by_suite: dict[int, list[models.TestCase]] = {}
        prompts_to_validate = 0
        for suite in selected_suites:
            suite_tests = (
                session.query(models.TestCase)
                .filter(models.TestCase.suite_id == suite.id)
                .order_by(models.TestCase.order.asc().nullslast(), models.TestCase.id.asc())
                .all()
            )
            tests_by_suite[suite.id] = suite_tests
            prompts_to_validate += len([test for test in suite_tests if _is_test_enabled(test)])

        st.caption(tr("label_prompts_to_validate", count=prompts_to_validate))
        st.caption(
            tr(
                "label_test_execution_profile",
                threads=tests_max_threads,
                timeout=tests_timeout,
                format=default_result_format.upper(),
            )
        )

        if st.button(tr("button_run_tests")):
            if not selected_suites:
                st.warning(tr("warning_select_suite_for_run"))
                return
            if prompts_to_validate == 0:
                st.warning(tr("warning_no_enabled_prompts_in_selected_suites"))
                return

            progress = st.progress(0)
            status = st.empty()
            total_prompts = max(prompts_to_validate, 1)
            completed_global = 0
            completed_runs = 0
            suite_errors: list[str] = []

            export_dir = (ROOT_DIR / runtime_settings["output_dir"]).resolve()
            export_allowed = is_safe_path(export_dir, ROOT_DIR)
            if export_allowed:
                export_dir.mkdir(parents=True, exist_ok=True)
            else:
                st.error(tr("error_export_dir"))

            for suite in selected_suites:
                tests = tests_by_suite.get(suite.id, [])
                enabled_count = len([test for test in tests if _is_test_enabled(test)])
                if enabled_count == 0:
                    continue

                def update_progress(completed: int, total: int, base: int = completed_global) -> None:
                    overall_completed = base + completed
                    pct = int((overall_completed / total_prompts) * 100)
                    progress.progress(pct)
                    status.info(tr("status_completed", completed=overall_completed, total=total_prompts))

                try:
                    run = run_test_suite(
                        session,
                        suite,
                        endpoint,
                        tests,
                        default_timeout=tests_timeout,
                        max_threads=tests_max_threads,
                        verify_ssl=runtime_settings.get("ssl_verify", True),
                        progress_callback=update_progress,
                    )
                    completed_global += enabled_count
                    completed_runs += 1
                    status.info(tr("status_completed", completed=completed_global, total=total_prompts))
                    st.success(tr("msg_test_run_completed_for_suite", run_id=run.id, suite=suite.name))

                    if export_allowed:
                        auto_filename = _build_result_filename(endpoint.name, suite.name, default_result_format)
                        auto_path = export_dir / auto_filename
                        export_run_results(session, run.id, auto_path, export_format=default_result_format)
                        record_event(
                            session,
                            "export",
                            "test_run_results",
                            str(run.id),
                            after_value={
                                "path": str(auto_path),
                                "format": default_result_format,
                                "source": "auto_after_run",
                            },
                        )
                        st.success(tr("msg_test_results_auto_exported", path=auto_path))
                except Exception as exc:
                    suite_errors.append(f"{suite.name}: {exc}")
                    st.error(tr("error_test_run_failed_for_suite", suite=suite.name, error=exc))

            final_pct = int((completed_global / total_prompts) * 100)
            progress.progress(final_pct)
            if completed_runs:
                st.success(tr("msg_test_runs_completed_total", count=completed_runs))
            if suite_errors:
                st.warning(tr("warning_suites_failed_count", count=len(suite_errors)))

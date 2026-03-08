from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_"}).strip()
    return cleaned or "test_run"


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
        suites = session.query(models.TestSuite).order_by(models.TestSuite.created_at.desc()).all()
        endpoints = list_endpoints(session)
        if not suites:
            st.info(tr("info_create_suite_in_config"))
            return
        if not endpoints:
            st.info(tr("info_create_endpoint_in_config"))
            return

        suite_id = st.selectbox(
            tr("label_test_suite"),
            options=[suite.id for suite in suites],
            format_func=lambda s_id: next(suite.name for suite in suites if suite.id == s_id),
        )
        suite = next(suite for suite in suites if suite.id == suite_id)

        endpoint_id = st.selectbox(
            tr("label_endpoint"),
            options=[ep.id for ep in endpoints],
            format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id),
        )
        endpoint = next(ep for ep in endpoints if ep.id == endpoint_id)

        tests = (
            session.query(models.TestCase)
            .filter(models.TestCase.suite_id == suite.id)
            .order_by(models.TestCase.order.asc().nullslast(), models.TestCase.id.asc())
            .all()
        )

        st.caption(tr("label_tests_in_suite", count=len(tests)))
        if tests:
            st.dataframe(
                [
                    {
                        tr("table_id"): test.id,
                        tr("table_order"): test.order,
                        tr("table_enabled"): test.enabled,
                        tr("table_name"): test.test_name,
                    }
                    for test in tests
                ],
                width="stretch",
            )

        if st.button(tr("button_run_tests")):
            progress = st.progress(0)
            status = st.empty()

            def update_progress(completed: int, total: int) -> None:
                pct = int((completed / max(total, 1)) * 100)
                progress.progress(pct)
                status.info(tr("status_completed", completed=completed, total=total))

            try:
                run = run_test_suite(
                    session,
                    suite,
                    endpoint,
                    tests,
                    default_timeout=int(runtime_settings.get("default_timeout", 30)),
                    verify_ssl=runtime_settings.get("ssl_verify", True),
                    progress_callback=update_progress,
                )
                st.success(tr("msg_test_run_completed", run_id=run.id))
            except Exception as exc:
                st.error(tr("error_test_run_failed", error=exc))

        st.subheader(tr("section_export_results"))
        run_id = st.number_input(tr("label_run_id"), min_value=1, step=1)
        export_name = st.text_input(tr("label_export_filename"), value=f"run_{run_id}_{datetime.utcnow().date()}")
        if st.button(tr("button_export_xlsx")):
            export_dir = (ROOT_DIR / runtime_settings["output_dir"]).resolve()
            if not is_safe_path(export_dir, ROOT_DIR):
                st.error(tr("error_export_dir"))
                return
            export_dir.mkdir(parents=True, exist_ok=True)
            filename = _sanitize_filename(export_name) + ".xlsx"
            output_path = export_dir / filename
            export_run_results(session, int(run_id), output_path)
            record_event(session, "export", "test_run_results", str(run_id), after_value={"path": str(output_path)})
            st.success(tr("msg_exported_to", path=output_path))

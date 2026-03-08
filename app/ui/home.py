from __future__ import annotations

import streamlit as st

from app.domain import models
from app.infra.db import get_session
from app.ui.utils import get_runtime_settings
from app.ui.i18n import get_translator


def render(context: dict) -> None:
    config = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
        tr = get_translator(lang)

        st.markdown(
            f"""
            <div class="page-intro">
                <span class="intro-badge">PromptOps</span>
                <div class="intro-title">{tr("home_title")}</div>
                <p class="intro-subtitle">
                    {tr("home_subtitle")}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        endpoint_count = session.query(models.Endpoint).count()
        chat_count = session.query(models.ChatSession).count()
        suite_count = session.query(models.TestSuite).count()
        run_count = session.query(models.TestRun).count()

        stats_html = f"""
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-label">{tr("stats_endpoints")}</div>
                <div class="stat-value">{endpoint_count}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">{tr("stats_chat_sessions")}</div>
                <div class="stat-value">{chat_count}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">{tr("stats_test_suites")}</div>
                <div class="stat-value">{suite_count}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">{tr("stats_test_runs")}</div>
                <div class="stat-value">{run_count}</div>
            </div>
        </div>
        """
        st.markdown(stats_html, unsafe_allow_html=True)

        st.markdown(f'<div class="section-title">{tr("quick_nav_title")}</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="card-grid">
                <a class="card" href="?nav=Configuration" target="_self">
                    <span class="card-badge">{tr("card_badge_settings")}</span>
                    <div class="card-title">{tr("card_title_configuration")}</div>
                    <p class="card-body">{tr("card_body_configuration")}</p>
                    <div class="card-action">{tr("card_action_open")}</div>
                </a>
                <a class="card" href="?nav=Chat" target="_self">
                    <span class="card-badge">{tr("card_badge_sessions")}</span>
                    <div class="card-title">{tr("card_title_chat")}</div>
                    <p class="card-body">{tr("card_body_chat")}</p>
                    <div class="card-action">{tr("card_action_open")}</div>
                </a>
                <a class="card" href="?nav=Compare" target="_self">
                    <span class="card-badge">{tr("card_badge_compare")}</span>
                    <div class="card-title">{tr("card_title_compare")}</div>
                    <p class="card-body">{tr("card_body_compare")}</p>
                    <div class="card-action">{tr("card_action_open")}</div>
                </a>
                <a class="card" href="?nav=Automated%20Tests" target="_self">
                    <span class="card-badge">{tr("card_badge_execution")}</span>
                    <div class="card-title">{tr("card_title_tests")}</div>
                    <p class="card-body">{tr("card_body_tests")}</p>
                    <div class="card-action">{tr("card_action_open")}</div>
                </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(f'<div class="section-title">{tr("recent_executions_title")}</div>', unsafe_allow_html=True)
        recent_runs = (
            session.query(models.TestRun)
            .order_by(models.TestRun.started_at.desc())
            .limit(5)
            .all()
        )
        if recent_runs:
            st.dataframe(
                [
                    {
                        tr("table_run_id"): run.id,
                        tr("table_suite_id"): run.suite_id,
                        tr("table_endpoint_id"): run.endpoint_id,
                        tr("table_status"): run.status,
                        tr("table_started"): run.started_at,
                        tr("table_finished"): run.finished_at,
                    }
                    for run in recent_runs
                ],
                width="stretch",
            )
        else:
            st.info(tr("no_test_executions"))

        st.markdown(f'<div class="section-title">{tr("recent_endpoints_title")}</div>', unsafe_allow_html=True)
        recent_endpoints = (
            session.query(models.Endpoint)
            .order_by(models.Endpoint.created_at.desc())
            .limit(5)
            .all()
        )
        if recent_endpoints:
            st.dataframe(
                [
                    {
                        tr("table_name"): endpoint.name,
                        tr("table_provider"): endpoint.provider,
                        tr("table_model"): endpoint.model_name,
                    }
                    for endpoint in recent_endpoints
                ],
                width="stretch",
            )
        else:
            st.info(tr("no_endpoints"))

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.core.paths import ROOT_DIR
from app.core.security import is_safe_path
from app.infra.db import get_session
from app.ui.i18n import get_translator
from app.ui.utils import get_runtime_settings


DOC_TABS: list[tuple[str, str]] = [
    ("docs_tab_overview", "docs/OVERVIEW.md"),
    ("docs_tab_getting_started", "docs/GETTING_STARTED.md"),
    ("docs_tab_modules", "docs/MODULES.md"),
    ("docs_tab_configuration", "docs/CONFIGURATION.md"),
    ("docs_tab_operations", "docs/OPERATIONS.md"),
    ("docs_tab_architecture", "docs/ARCHITECTURE.md"),
    ("docs_tab_security", "docs/SECURITY.md"),
    ("docs_tab_faq", "docs/FAQ.md"),
]


def _load_doc(relative_path: str) -> tuple[str | None, Path]:
    doc_path = (ROOT_DIR / relative_path).resolve()
    if not is_safe_path(doc_path, ROOT_DIR) or not doc_path.exists() or not doc_path.is_file():
        return None, doc_path
    try:
        return doc_path.read_text(encoding="utf-8"), doc_path
    except OSError:
        return None, doc_path


def render(context: dict) -> None:
    config = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
    tr = get_translator(lang)

    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{tr("docs_badge")}</span>
            <div class="intro-title">{tr("docs_title")}</div>
            <p class="intro-subtitle">
                {tr("docs_subtitle")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs([tr(label_key) for label_key, _ in DOC_TABS])
    for tab, (label_key, path) in zip(tabs, DOC_TABS):
        with tab:
            content, resolved_path = _load_doc(path)
            if content is None:
                st.warning(tr("docs_file_missing", path=path))
                continue
            st.caption(f"`{path}`")
            st.markdown(content)
            st.download_button(
                label=tr("docs_download_file"),
                data=content.encode("utf-8"),
                file_name=resolved_path.name,
                mime="text/markdown",
                key=f"docs_download_{label_key}",
                width="content",
            )

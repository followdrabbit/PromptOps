from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.core.config import ensure_directories, load_config
from app.core.logging import set_log_level, setup_logging
from app.infra.db import build_engine, build_session_factory, get_session, init_db
from app.ui import chat, config as config_ui, home, tests
from app.ui.utils import apply_global_styles, get_runtime_settings
from app.ui.i18n import get_translator


def bootstrap():
    config = load_config()
    ensure_directories(config)
    setup_logging(config.app_log_file, config.audit_log_file, config.log_level)
    engine = build_engine(config)
    init_db(engine)
    session_factory = build_session_factory(engine)
    return config, session_factory


def main() -> None:
    st.set_page_config(page_title="PromptOps", layout="wide")
    config, session_factory = bootstrap()
    context = {"config": config, "session_factory": session_factory}

    apply_global_styles()

    with get_session(session_factory) as session:
        runtime_settings = get_runtime_settings(session, config)
    set_log_level(runtime_settings.get("log_level", "INFO"))
    lang = runtime_settings.get("language", "en")
    tr = get_translator(lang)

    topbar = st.container()
    with topbar:
        st.markdown(
            f"""
            <div class="topbar-title">PromptOps</div>
            <div class="topbar-subtitle">{tr("topbar_subtitle")}</div>
            """,
            unsafe_allow_html=True,
        )

    st.sidebar.title("PromptOps")
    nav_options = ["Home", "Configuration", "Chat", "Automated Tests"]
    nav_labels = {
        "Home": tr("nav_home"),
        "Configuration": tr("nav_configuration"),
        "Chat": tr("nav_chat"),
        "Automated Tests": tr("nav_tests"),
    }
    if "nav" not in st.session_state:
        st.session_state["nav"] = "Home"
    try:
        query_params = st.query_params
        nav_param = query_params.get("nav")
    except Exception:
        nav_param = st.experimental_get_query_params().get("nav")
    if isinstance(nav_param, list):
        nav_param = nav_param[0] if nav_param else None
    if isinstance(nav_param, str) and nav_param in nav_options:
        st.session_state["nav"] = nav_param
    selection = st.sidebar.radio(
        tr("nav_label"),
        nav_options,
        format_func=lambda value: nav_labels.get(value, value),
        key="nav",
    )

    if selection == "Home":
        home.render(context)
    elif selection == "Configuration":
        config_ui.render(context)
    elif selection == "Chat":
        chat.render(context)
    elif selection == "Automated Tests":
        tests.render(context)


if __name__ == "__main__":
    main()

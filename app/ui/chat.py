from __future__ import annotations

import streamlit as st

from app.adapters.registry import get_provider_class
from app.core.secrets import SecretManager
from app.domain import models
from app.infra.db import get_session
from app.services.chat_service import add_message, create_session, list_sessions
from app.services.endpoint_service import list_endpoints
from app.ui.utils import get_runtime_settings
from app.ui.i18n import get_translator


def render(context: dict) -> None:
    session_factory = context["session_factory"]

    config = context["config"]
    with get_session(session_factory) as session:
        lang = get_runtime_settings(session, config).get("language", "en")
    tr = get_translator(lang)

    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{tr("chat_badge")}</span>
            <div class="intro-title">{tr("chat_title")}</div>
            <p class="intro-subtitle">
                {tr("chat_subtitle")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with get_session(session_factory) as session:
        endpoints = [ep for ep in list_endpoints(session) if ep.is_active]
        if not endpoints:
            st.info(tr("info_create_endpoint_before_chat"))
            return

        endpoint_id = st.selectbox(
            tr("label_endpoint"),
            options=[ep.id for ep in endpoints],
            format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id),
        )
        endpoint = next(ep for ep in endpoints if ep.id == endpoint_id)

        sessions = list_sessions(session, endpoint.id)
        session_options = ["__new__"] + [s.id for s in sessions]
        selected = st.selectbox(
            tr("label_chat_session"),
            options=session_options,
            format_func=lambda val: tr("option_new_session")
            if val == "__new__"
            else next((s.title for s in sessions if s.id == val), tr("label_unknown")),
        )

        if selected == "__new__":
            new_title = st.text_input(tr("label_session_title"), value=tr("chat_with_endpoint", name=endpoint.name))
            if st.button(tr("button_create_session")):
                chat_session = create_session(session, new_title, endpoint.id)
                st.success(tr("msg_session_created"))
                return
        else:
            chat_session = next((s for s in sessions if s.id == selected), None)

        if not chat_session:
            st.info(tr("info_select_or_create_session"))
            return

        st.subheader(chat_session.title)
        history = (
            session.query(models.ChatMessage)
            .filter(models.ChatMessage.session_id == chat_session.id)
            .order_by(models.ChatMessage.created_at.asc())
            .all()
        )

        for message in history:
            role = "assistant" if message.role == "assistant" else "user"
            with st.chat_message(role):
                st.markdown(message.content)

        prompt = st.text_area(tr("label_your_message"))
        with st.expander(tr("expander_chat_parameters")):
            temperature = st.slider(tr("label_temperature"), min_value=0.0, max_value=2.0, value=0.7, step=0.1)
            max_tokens = st.number_input(tr("label_max_tokens"), min_value=16, max_value=4096, value=512)

        if st.button(tr("button_send")):
            if not prompt.strip():
                st.warning(tr("warning_enter_prompt"))
                return
            add_message(session, chat_session.id, "user", prompt)
            messages = [{"role": msg.role, "content": msg.content} for msg in history] + [
                {"role": "user", "content": prompt}
            ]
            try:
                secret_value = None
                if endpoint.auth_type != "none":
                    secret_value = SecretManager().get_secret(session, endpoint.id)
                provider = get_provider_class(endpoint.provider)(endpoint, secret_value)
                params = dict(endpoint.default_params or {})
                params.update({"temperature": temperature, "max_tokens": int(max_tokens)})
                response = provider.send_prompt(messages, params)
                add_message(
                    session,
                    chat_session.id,
                    "assistant",
                    response.content,
                    metadata={"latency_ms": response.latency_ms},
                )
                st.success(tr("msg_response_stored"))
            except Exception as exc:
                add_message(session, chat_session.id, "assistant", f"Error: {exc}")
                st.error(tr("error_chat_failed", error=exc))

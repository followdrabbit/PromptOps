from __future__ import annotations

import streamlit as st

from app.adapters.registry import get_provider_class
from app.core.logging import get_logger
from app.core.secrets import SecretManager
from app.domain import models
from app.infra.db import get_session
from app.services.chat_service import add_message, create_session, delete_session, list_sessions, rename_session
from app.services.endpoint_service import list_endpoints
from app.ui.utils import get_runtime_settings
from app.ui.i18n import get_translator

logger = get_logger("promptops.chat")


def _build_auto_title(prompt: str, fallback: str) -> str:
    normalized = " ".join(prompt.split())
    if not normalized:
        return fallback
    words = normalized.split(" ")
    title = " ".join(words[:8])
    if len(words) > 8:
        title += "..."
    if len(title) > 70:
        title = f"{title[:67].rstrip()}..."
    return title


def render(context: dict) -> None:
    session_factory = context["session_factory"]

    config = context["config"]
    with get_session(session_factory) as session:
        runtime_settings = get_runtime_settings(session, config)
        lang = runtime_settings.get("language", "en")
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
        runtime_settings = get_runtime_settings(session, config)
        endpoints = [ep for ep in list_endpoints(session) if ep.is_active]
        if not endpoints:
            st.info(tr("info_create_endpoint_before_chat"))
            return

        st.sidebar.markdown("---")
        st.sidebar.subheader(tr("sidebar_chat_section"))

        endpoint_select_key = "chat_endpoint_sidebar"
        endpoint_ids = [ep.id for ep in endpoints]
        if st.session_state.get(endpoint_select_key) not in endpoint_ids:
            st.session_state[endpoint_select_key] = endpoint_ids[0]
        endpoint_id = st.sidebar.selectbox(
            tr("label_endpoint"),
            options=endpoint_ids,
            format_func=lambda ep_id: next(ep.name for ep in endpoints if ep.id == ep_id),
            key=endpoint_select_key,
        )
        endpoint = next(ep for ep in endpoints if ep.id == endpoint_id)

        default_title = tr("chat_default_title")
        if st.sidebar.button(tr("button_new_chat"), key=f"chat_new_btn_{endpoint.id}"):
            created = create_session(session, default_title, endpoint.id)
            session.flush()
            st.session_state[f"chat_session_sidebar_{endpoint.id}"] = created.id

        sessions = list_sessions(session, endpoint.id)
        if not sessions:
            st.sidebar.info(tr("info_no_chat_sessions"))
            st.info(tr("info_select_or_create_session"))
            return

        session_ids = [s.id for s in sessions]
        session_select_key = f"chat_session_sidebar_{endpoint.id}"
        if st.session_state.get(session_select_key) not in session_ids:
            st.session_state[session_select_key] = session_ids[0]
        selected_session_id = st.session_state[session_select_key]
        pending_delete_key = f"chat_delete_pending_{endpoint.id}"

        st.sidebar.caption(tr("label_sidebar_sessions"))
        for session_item in sessions:
            row = st.sidebar.columns([0.82, 0.18], gap="small")
            button_label = session_item.title
            if session_item.id == selected_session_id:
                button_label = f"> {button_label}"
            if row[0].button(
                button_label,
                key=f"chat_pick_{endpoint.id}_{session_item.id}",
                width="stretch",
            ):
                st.session_state[session_select_key] = session_item.id
                st.rerun()
            if row[1].button(
                " ",
                icon=":material/delete:",
                key=f"chat_trash_{endpoint.id}_{session_item.id}",
                width="stretch",
            ):
                st.session_state[pending_delete_key] = session_item.id
                st.rerun()

        pending_delete_id = st.session_state.get(pending_delete_key)
        if pending_delete_id is not None:
            pending_delete_session = next((s for s in sessions if s.id == pending_delete_id), None)
            if pending_delete_session is None:
                st.session_state.pop(pending_delete_key, None)
            else:
                st.sidebar.warning(
                    tr("confirm_delete_chat", title=pending_delete_session.title),
                    icon=":material/warning:",
                )
                confirm_cols = st.sidebar.columns(2, gap="small")
                if confirm_cols[0].button(
                    tr("button_confirm_delete_chat"),
                    key=f"chat_confirm_delete_{endpoint.id}_{pending_delete_session.id}",
                    width="stretch",
                ):
                    delete_session(session, pending_delete_session)
                    session.commit()
                    st.session_state.pop(pending_delete_key, None)
                    st.session_state.pop(f"chat_rename_title_{pending_delete_session.id}", None)
                    st.session_state.pop(f"chat_rename_title_{pending_delete_session.id}_pending", None)
                    st.session_state.pop(f"chat_rename_title_{pending_delete_session.id}_request", None)
                    remaining_session_ids = [s.id for s in sessions if s.id != pending_delete_session.id]
                    st.session_state[session_select_key] = remaining_session_ids[0] if remaining_session_ids else None
                    st.rerun()
                if confirm_cols[1].button(
                    tr("button_cancel_delete_chat"),
                    key=f"chat_cancel_delete_{endpoint.id}_{pending_delete_session.id}",
                    width="stretch",
                ):
                    st.session_state.pop(pending_delete_key, None)
                    st.rerun()

        chat_session = next((s for s in sessions if s.id == selected_session_id), None)

        if not chat_session:
            st.info(tr("info_select_or_create_session"))
            return

        rename_key = f"chat_rename_title_{chat_session.id}"
        pending_rename_key = f"{rename_key}_pending"
        rename_request_key = f"{rename_key}_request"
        if pending_rename_key in st.session_state:
            st.session_state[rename_key] = st.session_state.pop(pending_rename_key)
        if rename_key not in st.session_state:
            st.session_state[rename_key] = chat_session.title

        def _queue_rename(request_key: str) -> None:
            st.session_state[request_key] = True

        st.sidebar.text_input(
            tr("label_rename_chat"),
            key=rename_key,
            on_change=_queue_rename,
            args=(rename_request_key,),
        )
        if st.session_state.pop(rename_request_key, False):
            renamed = rename_session(session, chat_session, st.session_state[rename_key])
            st.session_state[pending_rename_key] = renamed.title
            session.commit()
            st.rerun()

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

        with st.form(f"chat_prompt_form_{chat_session.id}", clear_on_submit=True):
            prompt = st.text_area(
                tr("label_your_message"),
                placeholder=tr("placeholder_chat_message"),
                label_visibility="collapsed",
            )
            send = st.form_submit_button(tr("button_send"))

        if send:
            if not prompt.strip():
                st.warning(tr("warning_enter_prompt"))
                return
            logger.debug(
                "Chat send requested session_id=%s endpoint_id=%s endpoint_name=%s prompt_chars=%s history_messages=%s",
                chat_session.id,
                endpoint.id,
                endpoint.name,
                len(prompt),
                len(history),
            )
            default_title_candidates = {default_title, "New chat", "Novo chat"}
            if not any(msg.role == "user" for msg in history) and chat_session.title in default_title_candidates:
                auto_title = _build_auto_title(prompt, default_title)
                renamed = rename_session(session, chat_session, auto_title)
                st.session_state[pending_rename_key] = renamed.title
            add_message(session, chat_session.id, "user", prompt)
            with st.chat_message("user"):
                st.markdown(prompt)
            messages = [{"role": msg.role, "content": msg.content} for msg in history] + [
                {"role": "user", "content": prompt}
            ]
            try:
                variables = SecretManager().get_variables(session, endpoint.id)
                provider = get_provider_class(endpoint.provider)(
                    endpoint,
                    variables,
                    verify_ssl=runtime_settings.get("ssl_verify", True),
                )
                with st.chat_message("assistant"):
                    with st.spinner(tr("msg_waiting_response")):
                        response = provider.send_prompt(
                            messages,
                            {"timeout": int(runtime_settings.get("default_timeout", 30))},
                        )
                    st.markdown(response.content)
                add_message(
                    session,
                    chat_session.id,
                    "assistant",
                    response.content,
                    metadata={"latency_ms": response.latency_ms},
                )
                logger.debug(
                    "Chat response received session_id=%s endpoint_id=%s latency_ms=%s response_chars=%s",
                    chat_session.id,
                    endpoint.id,
                    response.latency_ms,
                    len(response.content or ""),
                )
                session.commit()
                st.rerun()
            except Exception as exc:
                logger.exception(
                    "Chat request failed session_id=%s endpoint_id=%s endpoint_name=%s",
                    chat_session.id,
                    endpoint.id,
                    endpoint.name,
                )
                with st.chat_message("assistant"):
                    st.error(tr("error_chat_failed", error=exc))
                add_message(session, chat_session.id, "assistant", f"Error: {exc}")
                session.commit()
                st.rerun()

from __future__ import annotations

import html

import streamlit as st

from app.adapters.registry import get_provider_class
from app.core.logging import get_logger
from app.core.secrets import SecretManager
from app.infra.db import get_session
from app.services.endpoint_service import list_endpoints
from app.ui.i18n import get_translator
from app.ui.utils import get_runtime_settings


logger = get_logger("promptops.compare")
MAX_COMPARE_ENDPOINTS = 10
SELECTED_ENDPOINTS_KEY = "compare_selected_endpoints"
COMPARE_TURNS_KEY = "compare_turns"
COMPARE_HISTORY_KEY = "compare_endpoint_histories"


def _sanitize_selected(selected_ids: list[int], valid_ids: set[int], fallback_ids: list[int]) -> list[int]:
    sanitized: list[int] = []
    for endpoint_id in selected_ids:
        if endpoint_id in valid_ids and endpoint_id not in sanitized:
            sanitized.append(endpoint_id)
    if sanitized:
        return sanitized
    return fallback_ids


def _render_response_cards(responses: list[dict], tr) -> None:
    cards_html: list[str] = []
    for item in responses:
        endpoint_name = html.escape(str(item.get("endpoint_name") or tr("label_unknown")))
        if item.get("error"):
            body_html = f'<div class="compare-card-error">{html.escape(str(item["error"]))}</div>'
        else:
            response_text = str(item.get("content") or tr("compare_empty_response"))
            body_html = f'<div class="compare-card-content">{html.escape(response_text)}</div>'
        latency_html = ""
        if item.get("latency_ms") is not None:
            latency_html = (
                f'<div class="compare-card-meta">'
                f'{html.escape(tr("compare_latency", latency=item["latency_ms"]))}'
                f"</div>"
            )
        incomplete_html = ""
        if item.get("incomplete_reason"):
            incomplete_html = (
                f'<div class="compare-card-warning">'
                f'{html.escape(tr("compare_incomplete_reason", reason=item["incomplete_reason"]))}'
                f"</div>"
            )
        cards_html.append(
            f'<div class="compare-card">'
            f'<div class="compare-card-title">{endpoint_name}</div>'
            f"{body_html}"
            f"{latency_html}"
            f"{incomplete_html}"
            f"</div>"
        )
    track_html = "".join(cards_html)
    st.markdown(
        f'<div class="compare-scroll"><div class="compare-track">{track_html}</div></div>',
        unsafe_allow_html=True,
    )


def render(context: dict) -> None:
    config = context["config"]
    session_factory = context["session_factory"]

    with get_session(session_factory) as session:
        runtime_settings = get_runtime_settings(session, config)
        lang = runtime_settings.get("language", "en")
    tr = get_translator(lang)

    st.markdown(
        f"""
        <div class="page-intro">
            <span class="intro-badge">{tr("compare_badge")}</span>
            <div class="intro-title">{tr("compare_title")}</div>
            <p class="intro-subtitle">
                {tr("compare_subtitle")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .compare-scroll {
            overflow-x: auto;
            overflow-y: hidden;
            padding-bottom: 0.35rem;
            margin: 0.45rem 0 1rem 0;
        }

        .compare-track {
            display: flex;
            align-items: stretch;
            gap: 0.8rem;
            min-width: max-content;
        }

        .compare-card {
            width: 360px;
            min-width: 360px;
            background: var(--secondary-background-color);
            border: 1px solid rgba(127, 127, 127, 0.28);
            border-radius: 14px;
            padding: 0.85rem 0.9rem;
            box-sizing: border-box;
        }

        .compare-card-title {
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: var(--text-color);
            word-break: break-word;
        }

        .compare-card-content {
            color: var(--text-color);
            white-space: pre-wrap;
            line-height: 1.45;
            word-break: break-word;
        }

        .compare-card-error {
            color: #b42318;
            background: rgba(180, 35, 24, 0.08);
            border: 1px solid rgba(180, 35, 24, 0.2);
            border-radius: 10px;
            padding: 0.55rem 0.65rem;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .compare-card-meta {
            margin-top: 0.55rem;
            color: var(--text-color);
            opacity: 0.75;
            font-size: 0.85rem;
        }

        .compare-card-warning {
            margin-top: 0.55rem;
            color: #9a3412;
            background: rgba(245, 158, 11, 0.16);
            border: 1px solid rgba(245, 158, 11, 0.35);
            border-radius: 10px;
            padding: 0.45rem 0.6rem;
            font-size: 0.82rem;
            line-height: 1.35;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with get_session(session_factory) as session:
        runtime_settings = get_runtime_settings(session, config)
        endpoints = [endpoint for endpoint in list_endpoints(session) if endpoint.is_active]
        if not endpoints:
            st.info(tr("info_create_endpoint_before_chat"))
            return

        endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
        endpoint_ids = list(endpoint_by_id.keys())
        fallback_selection = endpoint_ids[: min(2, len(endpoint_ids))]
        if SELECTED_ENDPOINTS_KEY not in st.session_state:
            st.session_state[SELECTED_ENDPOINTS_KEY] = fallback_selection

        selected_ids = _sanitize_selected(
            st.session_state.get(SELECTED_ENDPOINTS_KEY, []),
            set(endpoint_ids),
            fallback_selection,
        )
        st.session_state[SELECTED_ENDPOINTS_KEY] = selected_ids

        st.sidebar.markdown("---")
        st.sidebar.subheader(tr("compare_badge"))
        st.sidebar.multiselect(
            tr("label_compare_endpoints"),
            options=endpoint_ids,
            format_func=lambda endpoint_id: endpoint_by_id[endpoint_id].name,
            key=SELECTED_ENDPOINTS_KEY,
        )
        selected_ids = _sanitize_selected(
            st.session_state.get(SELECTED_ENDPOINTS_KEY, []),
            set(endpoint_ids),
            fallback_selection,
        )
        if len(selected_ids) > MAX_COMPARE_ENDPOINTS:
            st.sidebar.error(tr("warning_compare_max_endpoints", max_count=MAX_COMPARE_ENDPOINTS))
            selected_ids = selected_ids[:MAX_COMPARE_ENDPOINTS]

        st.sidebar.caption(
            tr(
                "label_compare_selected_count",
                count=len(selected_ids),
                max_count=MAX_COMPARE_ENDPOINTS,
            )
        )

        if st.sidebar.button(tr("button_new_compare_session"), key="compare_new_session"):
            st.session_state[COMPARE_TURNS_KEY] = []
            st.session_state[COMPARE_HISTORY_KEY] = {}
            st.rerun()

        compare_turns = st.session_state.setdefault(COMPARE_TURNS_KEY, [])
        endpoint_histories = st.session_state.setdefault(COMPARE_HISTORY_KEY, {})
        active_endpoint_id_strings = {str(endpoint_id) for endpoint_id in endpoint_ids}
        stale_keys = [key for key in endpoint_histories.keys() if key not in active_endpoint_id_strings]
        for stale_key in stale_keys:
            endpoint_histories.pop(stale_key, None)
        st.session_state[COMPARE_HISTORY_KEY] = endpoint_histories

        if compare_turns:
            for turn in compare_turns:
                with st.chat_message("user"):
                    st.markdown(turn.get("prompt", ""))
                responses = turn.get("responses", [])
                if not responses:
                    continue
                st.markdown(f"**{tr('compare_results_title')}**")
                _render_response_cards(responses, tr)
        else:
            st.info(tr("info_compare_empty"))

        with st.form("compare_prompt_form", clear_on_submit=True):
            prompt = st.text_area(
                tr("label_your_message"),
                placeholder=tr("placeholder_chat_message"),
                label_visibility="collapsed",
            )
            send = st.form_submit_button(tr("button_send"))

        if send:
            user_prompt = prompt.strip()
            if not user_prompt:
                st.warning(tr("warning_enter_prompt"))
                return
            if not selected_ids:
                st.warning(tr("warning_compare_select_endpoint"))
                return

            compare_results: list[dict] = []
            progress = st.progress(0)
            total = len(selected_ids)
            for index, endpoint_id in enumerate(selected_ids, start=1):
                endpoint = endpoint_by_id[endpoint_id]
                history = endpoint_histories.get(str(endpoint_id), [])
                messages = history + [{"role": "user", "content": user_prompt}]
                try:
                    variables = SecretManager().get_variables(session, endpoint.id)
                    provider = get_provider_class(endpoint.provider)(
                        endpoint,
                        variables,
                        verify_ssl=runtime_settings.get("ssl_verify", True),
                    )
                    response = provider.send_prompt(
                        messages,
                        {"timeout": int(runtime_settings.get("default_timeout", 30))},
                    )
                    endpoint_histories[str(endpoint_id)] = messages + [
                        {"role": "assistant", "content": response.content}
                    ]
                    compare_results.append(
                        {
                            "endpoint_id": endpoint.id,
                            "endpoint_name": endpoint.name,
                            "content": response.content,
                            "latency_ms": response.latency_ms,
                            "incomplete_reason": (
                                (
                                    response.raw.get("incomplete_details") or {}
                                ).get("reason")
                                if isinstance(response.raw, dict)
                                else None
                            ),
                            "error": None,
                        }
                    )
                    logger.debug(
                        "Compare response received endpoint_id=%s endpoint_name=%s latency_ms=%s response_chars=%s",
                        endpoint.id,
                        endpoint.name,
                        response.latency_ms,
                        len(response.content or ""),
                    )
                except Exception as exc:
                    logger.exception(
                        "Compare request failed endpoint_id=%s endpoint_name=%s",
                        endpoint.id,
                        endpoint.name,
                    )
                    endpoint_histories[str(endpoint_id)] = messages
                    compare_results.append(
                        {
                            "endpoint_id": endpoint.id,
                            "endpoint_name": endpoint.name,
                            "content": "",
                            "latency_ms": None,
                            "incomplete_reason": None,
                            "error": str(exc),
                        }
                    )
                progress.progress(int((index / total) * 100))

            progress.empty()
            compare_turns.append({"prompt": user_prompt, "responses": compare_results})
            st.session_state[COMPARE_TURNS_KEY] = compare_turns
            st.session_state[COMPARE_HISTORY_KEY] = endpoint_histories
            st.rerun()

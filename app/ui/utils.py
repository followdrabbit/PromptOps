from __future__ import annotations

import json
from typing import Any

import streamlit as st

from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.services.settings_service import get_setting


SETTINGS_KEYS = {
    "language": "language",
    "log_level": "log_level",
    "default_timeout": "default_timeout",
    "output_dir": "output_dir",
    "import_dir": "import_dir",
    "tools_enabled": "tools_enabled",
    "log_retention_days": "log_retention_days",
    "secure_storage": "secure_storage",
    "audit_verbosity": "audit_verbosity",
    "ssl_verify": "ssl_verify",
    "tests_max_threads": "tests_max_threads",
    "tests_request_timeout": "tests_request_timeout",
    "tests_result_format": "tests_result_format",
}


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def get_runtime_settings(session: Session, config: AppConfig) -> dict[str, Any]:
    tests_result_format = (
        get_setting(session, "tests_result_format", config.tests_result_format).strip().lower()
    )
    if tests_result_format not in {"xlsx", "json"}:
        tests_result_format = "xlsx"
    return {
        "language": get_setting(session, "language", config.language),
        "log_level": get_setting(session, "log_level", config.log_level),
        "default_timeout": _to_int(
            get_setting(session, "default_timeout", str(config.default_timeout)),
            config.default_timeout,
        ),
        "output_dir": get_setting(session, "output_dir", config.output_dir),
        "import_dir": get_setting(session, "import_dir", config.import_dir),
        "tools_enabled": get_setting(session, "tools_enabled", str(config.tools_enabled)).lower() == "true",
        "log_retention_days": _to_int(
            get_setting(session, "log_retention_days", str(config.log_retention_days)),
            config.log_retention_days,
        ),
        "secure_storage": get_setting(session, "secure_storage", config.secure_storage),
        "audit_verbosity": get_setting(session, "audit_verbosity", config.audit_verbosity),
        "ssl_verify": get_setting(session, "ssl_verify", str(config.ssl_verify)).lower() == "true",
        "tests_max_threads": _to_int(
            get_setting(session, "tests_max_threads", str(config.tests_max_threads)),
            config.tests_max_threads,
        ),
        "tests_request_timeout": _to_int(
            get_setting(session, "tests_request_timeout", str(config.tests_request_timeout)),
            config.tests_request_timeout,
        ),
        "tests_result_format": tests_result_format,
    }


def parse_json_field(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)


def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 3.4rem;
            padding-bottom: 2.5rem;
            max-width: 1200px;
        }

        [data-testid="stSidebar"] .block-container {
            padding-top: 3.2rem;
        }

        .topbar-title {
            font-size: 1.35rem;
            font-weight: 700;
            margin: 0 0 2px 0;
            line-height: 1.25;
            color: var(--text-color);
        }

        .topbar-subtitle {
            color: var(--text-color);
            opacity: 0.7;
            font-size: 0.9rem;
            margin-top: 0;
            line-height: 1.35;
        }

        .page-intro {
            background: var(--secondary-background-color);
            border: 1px solid rgba(127, 127, 127, 0.25);
            border-radius: 22px;
            padding: 24px;
            margin-bottom: 24px;
        }

        .page-intro .intro-badge {
            display: inline-flex;
            padding: 4px 12px;
            border-radius: 999px;
            border: 1px solid var(--primary-color);
            color: var(--primary-color);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .page-intro .intro-title {
            font-size: 2.1rem;
            font-weight: 700;
            margin: 12px 0 6px 0;
            color: var(--text-color);
        }

        .page-intro .intro-subtitle {
            color: var(--text-color);
            opacity: 0.75;
            font-size: 1.05rem;
            margin: 0;
        }

        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin: 12px 0 24px 0;
        }

        .stat-card {
            background: var(--secondary-background-color);
            border: 1px solid rgba(127, 127, 127, 0.25);
            border-radius: 18px;
            padding: 16px;
        }

        .stat-label {
            color: var(--text-color);
            opacity: 0.7;
            font-size: 0.9rem;
            margin-bottom: 8px;
        }

        .stat-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--primary-color);
        }

        .card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 18px;
            margin-top: 8px;
        }

        .card {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 18px 18px 16px 18px;
            border-radius: 18px;
            border: 1px solid rgba(127, 127, 127, 0.25);
            background: var(--secondary-background-color);
            text-decoration: none;
            color: inherit;
            min-height: 150px;
            transition: transform 0.18s ease;
        }

        .card:hover {
            transform: translateY(-2px);
        }

        .card-badge {
            display: inline-flex;
            width: fit-content;
            padding: 4px 10px;
            border-radius: 999px;
            border: 1px solid var(--primary-color);
            color: var(--primary-color);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }

        .card-title {
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--text-color);
        }

        .card-body {
            margin: 0;
            color: var(--text-color);
            opacity: 0.78;
            font-size: 0.95rem;
            line-height: 1.45;
        }

        .card-action {
            margin-top: auto;
            color: var(--primary-color);
            font-weight: 600;
            font-size: 0.9rem;
        }

        .section-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin: 12px 0 8px 0;
            color: var(--text-color);
        }

        .suite-chip {
            background: var(--secondary-background-color);
            border: 1px solid rgba(127, 127, 127, 0.35);
            border-radius: 14px;
            padding: 12px 14px;
            min-height: 52px;
            color: var(--text-color);
            font-size: 0.95rem;
            font-weight: 600;
            line-height: 1.3;
            display: flex;
            align-items: center;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
        }

        .suite-chip:hover {
            border-color: var(--primary-color);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

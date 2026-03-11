from __future__ import annotations

from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import AppConfig
from app.domain.models import Base


def build_engine(config: AppConfig):
    return create_engine(
        f"sqlite:///{config.db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_endpoint_columns(engine)
    _ensure_red_team_result_columns(engine)


def _ensure_endpoint_columns(engine) -> None:
    columns = {
        "response_paths": "response_paths TEXT",
        "response_type": "response_type TEXT",
        "request_mode": "request_mode TEXT DEFAULT 'responses'",
    }
    with engine.begin() as conn:
        existing = [row[1] for row in conn.execute(text("PRAGMA table_info(endpoints)"))]
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {ddl}"))
        conn.execute(
            text(
                "UPDATE endpoints SET request_mode = 'responses' "
                "WHERE request_mode IS NULL OR TRIM(request_mode) = ''"
            )
        )


def _ensure_red_team_result_columns(engine) -> None:
    columns = {
        "llm_judge_model": "llm_judge_model TEXT",
        "evaluation_verdict_justification": "evaluation_verdict_justification TEXT",
        "evaluation_score_justification": "evaluation_score_justification TEXT",
    }
    with engine.begin() as conn:
        existing = [row[1] for row in conn.execute(text("PRAGMA table_info(red_team_run_results)"))]
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE red_team_run_results ADD COLUMN {ddl}"))


def build_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)


@contextmanager
def get_session(session_factory):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

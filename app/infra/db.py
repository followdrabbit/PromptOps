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


def _ensure_endpoint_columns(engine) -> None:
    columns = {
        "response_paths": "response_paths TEXT",
        "response_type": "response_type TEXT",
    }
    with engine.begin() as conn:
        existing = [row[1] for row in conn.execute(text("PRAGMA table_info(endpoints)"))]
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {ddl}"))


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

from __future__ import annotations

from sqlalchemy.orm import Session
from datetime import datetime

from app.domain import models
from app.services.audit_service import record_event


def list_sessions(session: Session, endpoint_id: int | None = None) -> list[models.ChatSession]:
    query = session.query(models.ChatSession)
    if endpoint_id is not None:
        query = query.filter(models.ChatSession.endpoint_id == endpoint_id)
    return query.order_by(models.ChatSession.updated_at.desc()).all()


def create_session(session: Session, title: str, endpoint_id: int) -> models.ChatSession:
    chat_session = models.ChatSession(title=title, endpoint_id=endpoint_id)
    session.add(chat_session)
    session.flush()
    record_event(session, "create", "chat_session", chat_session.id, after_value={"title": title})
    return chat_session


def add_message(session: Session, session_id: int, role: str, content: str, metadata: dict | None = None) -> models.ChatMessage:
    msg = models.ChatMessage(session_id=session_id, role=role, content=content, meta=metadata)
    session.add(msg)
    session.flush()
    chat_session = session.query(models.ChatSession).filter(models.ChatSession.id == session_id).one_or_none()
    if chat_session:
        chat_session.updated_at = datetime.utcnow()
        session.add(chat_session)
    record_event(session, "create", "chat_message", msg.id, after_value={"role": role})
    return msg

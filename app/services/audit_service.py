from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_actor
from app.core.logging import get_logger
from app.core.redaction import redact_dict
from app.domain import models


logger = get_logger("promptops.audit")


def record_event(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
) -> models.AuditEvent:
    safe_before = redact_dict(before_value) if before_value else None
    safe_after = redact_dict(after_value) if after_value else None
    event = models.AuditEvent(
        actor=get_actor(),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_value=safe_before,
        after_value=safe_after,
    )
    session.add(event)
    logger.info("Audit event: %s %s %s", action, entity_type, entity_id)
    return event

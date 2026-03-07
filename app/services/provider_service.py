from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import models
from app.services.audit_service import record_event


def list_providers(session: Session) -> list[models.Provider]:
    return session.query(models.Provider).order_by(models.Provider.name.asc()).all()


def get_provider(session: Session, provider_id: int) -> models.Provider | None:
    return session.query(models.Provider).filter(models.Provider.id == provider_id).one_or_none()


def create_provider(session: Session, data: dict) -> models.Provider:
    provider = models.Provider(**data)
    session.add(provider)
    session.flush()
    record_event(session, "create", "provider", provider.id, after_value=data)
    return provider


def update_provider(session: Session, provider: models.Provider, data: dict) -> models.Provider:
    before = {
        "name": provider.name,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "website": provider.website,
        "region": provider.region,
        "compliance": provider.compliance,
        "tags": provider.tags,
        "notes": provider.notes,
        "is_active": provider.is_active,
    }
    for key, value in data.items():
        setattr(provider, key, value)
    session.add(provider)
    record_event(session, "update", "provider", provider.id, before_value=before, after_value=data)
    return provider


def delete_provider(session: Session, provider: models.Provider) -> None:
    record_event(session, "delete", "provider", provider.id, before_value={"name": provider.name})
    session.delete(provider)

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.secrets import SecretManager
from app.domain import models
from app.services.audit_service import record_event


def list_endpoints(session: Session) -> list[models.Endpoint]:
    return session.query(models.Endpoint).order_by(models.Endpoint.name.asc()).all()


def get_endpoint(session: Session, endpoint_id: int) -> models.Endpoint | None:
    return session.query(models.Endpoint).filter(models.Endpoint.id == endpoint_id).one_or_none()


def create_endpoint(
    session: Session,
    data: dict,
    secret_value: str | None = None,
    secret_type: str = "api_key",
) -> models.Endpoint:
    endpoint = models.Endpoint(**data)
    session.add(endpoint)
    session.flush()

    if secret_value:
        SecretManager().store_secret(session, endpoint.id, secret_value, secret_type)

    record_event(session, "create", "endpoint", endpoint.id, after_value=data)
    return endpoint


def update_endpoint(
    session: Session,
    endpoint: models.Endpoint,
    data: dict,
    secret_value: str | None = None,
    secret_type: str = "api_key",
) -> models.Endpoint:
    before = {
        "name": endpoint.name,
        "provider": endpoint.provider,
        "base_url": endpoint.base_url,
        "endpoint_path": endpoint.endpoint_path,
        "model_name": endpoint.model_name,
        "auth_type": endpoint.auth_type,
        "response_paths": endpoint.response_paths,
        "response_type": endpoint.response_type,
    }
    for key, value in data.items():
        setattr(endpoint, key, value)

    if secret_value:
        SecretManager().store_secret(session, endpoint.id, secret_value, secret_type)
        record_event(session, "rotate", "endpoint_secret", endpoint.id)

    record_event(session, "update", "endpoint", endpoint.id, before_value=before, after_value=data)
    session.add(endpoint)
    return endpoint


def delete_endpoint(session: Session, endpoint: models.Endpoint) -> None:
    record_event(session, "delete", "endpoint", endpoint.id, before_value={"name": endpoint.name})
    session.delete(endpoint)

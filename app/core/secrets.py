from __future__ import annotations

from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security import build_encryption_service
from app.domain import models


class SecretManager:
    def __init__(self) -> None:
        self._encryption = build_encryption_service()

    def store_secret(
        self,
        session: Session,
        endpoint_id: int,
        secret_value: str,
        secret_type: str = "api_key",
    ) -> models.EndpointSecret:
        encrypted = self._encryption.encrypt(secret_value)
        existing = (
            session.query(models.EndpointSecret)
            .filter(models.EndpointSecret.endpoint_id == endpoint_id)
            .one_or_none()
        )
        if existing:
            existing.encrypted_secret = encrypted
            existing.secret_type = secret_type
            existing.last_rotated_at = datetime.utcnow()
            session.add(existing)
            return existing

        secret = models.EndpointSecret(
            endpoint_id=endpoint_id,
            encrypted_secret=encrypted,
            secret_type=secret_type,
        )
        session.add(secret)
        return secret

    def get_secret(self, session: Session, endpoint_id: int) -> Optional[str]:
        secret = (
            session.query(models.EndpointSecret)
            .filter(models.EndpointSecret.endpoint_id == endpoint_id)
            .one_or_none()
        )
        if not secret:
            return None
        return self._encryption.decrypt(secret.encrypted_secret)

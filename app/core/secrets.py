from __future__ import annotations

import json
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
        variables = self.get_variables(session, endpoint_id)
        variables["API_TOKEN"] = secret_value
        return self.store_variables(session, endpoint_id, variables, secret_type=secret_type)

    def store_variables(
        self,
        session: Session,
        endpoint_id: int,
        variables: dict[str, str],
        secret_type: str = "template_vars",
    ) -> models.EndpointSecret:
        payload = {str(key): str(value) for key, value in variables.items() if value is not None}
        encrypted = self._encryption.encrypt(json.dumps(payload))
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

    def get_variables(self, session: Session, endpoint_id: int) -> dict[str, str]:
        secret = (
            session.query(models.EndpointSecret)
            .filter(models.EndpointSecret.endpoint_id == endpoint_id)
            .one_or_none()
        )
        if not secret:
            return {}
        decrypted = self._encryption.decrypt(secret.encrypted_secret)
        try:
            payload = json.loads(decrypted)
            if isinstance(payload, dict):
                return {str(key): str(value) for key, value in payload.items() if value is not None}
        except json.JSONDecodeError:
            pass
        # Backward compatibility: legacy rows may contain only raw token text.
        return {"API_TOKEN": decrypted}

    def get_secret(self, session: Session, endpoint_id: int) -> Optional[str]:
        variables = self.get_variables(session, endpoint_id)
        return variables.get("API_TOKEN")

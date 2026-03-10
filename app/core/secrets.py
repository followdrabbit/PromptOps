from __future__ import annotations

import json
from typing import Any, Optional
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
        variable_types = self.get_variable_types(session, endpoint_id)
        variables["API_TOKEN"] = secret_value
        return self.store_variables(
            session,
            endpoint_id,
            variables,
            variable_types=variable_types,
            secret_type=secret_type,
        )

    def store_variables(
        self,
        session: Session,
        endpoint_id: int,
        variables: dict[str, Any],
        variable_types: dict[str, str] | None = None,
        secret_type: str = "template_vars",
    ) -> models.EndpointSecret:
        payload_values = {str(key): value for key, value in variables.items() if value is not None}
        payload_types = {
            str(key): str(value).strip().lower()
            for key, value in (variable_types or {}).items()
            if str(key).strip() and value is not None
        }
        payload = {
            "__promptops_schema_version": 2,
            "values": payload_values,
            "types": payload_types,
        }
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

    def get_variables(self, session: Session, endpoint_id: int) -> dict[str, Any]:
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
                if isinstance(payload.get("values"), dict):
                    values = payload["values"]
                    return {str(key): value for key, value in values.items() if value is not None}
                return {str(key): value for key, value in payload.items() if value is not None}
        except json.JSONDecodeError:
            pass
        # Backward compatibility: legacy rows may contain only raw token text.
        return {"API_TOKEN": decrypted}

    def get_variable_types(self, session: Session, endpoint_id: int) -> dict[str, str]:
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
            if isinstance(payload, dict) and isinstance(payload.get("values"), dict):
                values = payload["values"]
                raw_types = payload.get("types")
                if isinstance(raw_types, dict):
                    return {
                        str(key): str(raw_types.get(key)).strip().lower()
                        for key in values.keys()
                        if raw_types.get(key) is not None
                    }
        except json.JSONDecodeError:
            pass
        return {}

    def get_secret(self, session: Session, endpoint_id: int) -> Optional[str]:
        variables = self.get_variables(session, endpoint_id)
        return variables.get("API_TOKEN")

from __future__ import annotations

from typing import Any

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


def providers_to_records(providers: list[models.Provider]) -> list[dict[str, Any]]:
    return [
        {
            "name": provider.name,
            "notes": provider.notes or "",
            "is_active": bool(provider.is_active),
        }
        for provider in providers
    ]


def validate_provider_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_names: set[str] = set()

    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"", "true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off"}:
                return False
        raise ValueError(f"invalid boolean value '{value}'")

    for row_index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {row_index}: invalid row format (expected object)")
            continue

        raw_name = row.get("name")
        raw_notes = row.get("notes")
        raw_is_active = row.get("is_active")

        name = "" if raw_name is None else str(raw_name).strip()
        notes = "" if raw_notes is None else str(raw_notes).strip()

        # Ignore fully empty rows from spreadsheets.
        if not name and not notes and raw_is_active in {None, ""}:
            continue

        if not name:
            errors.append(f"row {row_index}: 'name' is required")
            continue
        if len(name) > 120:
            errors.append(f"row {row_index}: 'name' exceeds 120 characters")
            continue

        key = name.lower()
        if key in seen_names:
            errors.append(f"row {row_index}: duplicate provider name '{name}' in file")
            continue
        seen_names.add(key)

        try:
            is_active = _to_bool(raw_is_active)
        except ValueError as exc:
            errors.append(f"row {row_index}: {exc}")
            continue

        normalized.append({"name": name, "notes": notes or None, "is_active": is_active})

    if not normalized and not errors:
        errors.append("no valid provider records found")

    return normalized, errors


def upsert_provider_records(session: Session, records: list[dict[str, Any]]) -> dict[str, Any]:
    created = 0
    skipped_existing = 0
    skipped_existing_names: list[str] = []

    existing_providers = session.query(models.Provider).all()
    existing_name_keys = {provider.name.strip().lower() for provider in existing_providers}

    for record in records:
        name = str(record["name"]).strip()
        name_key = name.lower()
        payload = {
            "name": name,
            "notes": record.get("notes"),
            "is_active": bool(record.get("is_active", True)),
        }
        if name_key in existing_name_keys:
            skipped_existing += 1
            skipped_existing_names.append(name)
            continue

        create_provider(session, payload)
        existing_name_keys.add(name_key)
        created += 1

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_existing_names": skipped_existing_names,
    }

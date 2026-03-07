from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain import models


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    setting = session.query(models.Setting).filter(models.Setting.key == key).one_or_none()
    if setting:
        return setting.value
    return default


def set_setting(session: Session, key: str, value: str) -> models.Setting:
    setting = session.query(models.Setting).filter(models.Setting.key == key).one_or_none()
    if setting:
        setting.value = value
        session.add(setting)
        return setting
    setting = models.Setting(key=key, value=value)
    session.add(setting)
    return setting

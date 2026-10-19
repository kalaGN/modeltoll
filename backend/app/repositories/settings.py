"""Branding/model connection persistence against explicit ORM mappings."""
from sqlalchemy import func, select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.models import ModelConnection, PlatformSetting, PricingRule


def branding(db: Session) -> dict | None:
    row = db.execute(select(
        PlatformSetting.name, PlatformSetting.description,
        PlatformSetting.logo_blob.is_not(None).label('has_logo'), PlatformSetting.updated_at,
    ).where(PlatformSetting.id == 1)).mappings().first()
    return dict(row) if row is not None else None


def logo(db: Session) -> bytes | None:
    return db.scalar(select(PlatformSetting.logo_blob).where(PlatformSetting.id == 1))


def save_branding(db: Session, name: str, description: str, image: bytes | None, *, keep_logo: bool) -> None:
    values = {'name': name, 'description': description, 'updated_at': func.utc_timestamp(3)}
    if not keep_logo:
        values.update(logo_blob=image, logo_mime='image/png' if image else None)
    db.execute(update(PlatformSetting).where(PlatformSetting.id == 1).values(**values))


def connection(db: Session) -> dict | None:
    row = db.execute(select(
        ModelConnection.base_url, ModelConnection.model, ModelConnection.timeout_seconds,
        ModelConnection.enabled,
    ).where(ModelConnection.id == 1)).mappings().first()
    return dict(row) if row is not None else None


def ensure_connection(db: Session, base_url: str, model: str, timeout: int) -> None:
    db.execute(insert(ModelConnection).prefix_with('IGNORE').values(
        id=1, base_url=base_url, model=model, timeout_seconds=timeout,
        enabled=0, updated_at=func.utc_timestamp(3),
    ))


def lock_connection(db: Session) -> dict | None:
    row = db.execute(select(ModelConnection.id).where(ModelConnection.id == 1)
                     .with_for_update()).mappings().first()
    return dict(row) if row is not None else None


def active_price(db: Session, model: str) -> dict | None:
    row = db.execute(select(PricingRule.id).where(
        PricingRule.model == model, PricingRule.effective_from <= func.utc_timestamp(3),
    ).limit(1)).mappings().first()
    return dict(row) if row is not None else None


def insert_initial_price(db: Session, values: dict) -> None:
    db.execute(insert(PricingRule).values(
        **values, effective_from=func.utc_timestamp(3), created_at=func.utc_timestamp(3),
    ))


def update_connection(db: Session, base_url: str, model: str, timeout: int, enabled: bool) -> None:
    db.execute(update(ModelConnection).where(ModelConnection.id == 1).values(
        base_url=base_url, model=model, timeout_seconds=timeout,
        enabled=int(enabled), updated_at=func.utc_timestamp(3),
    ))

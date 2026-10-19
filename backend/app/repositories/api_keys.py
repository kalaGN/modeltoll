"""API Key persistence; no policy decisions or transaction commits."""

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.models import ApiKey, User

PUBLIC_COLUMNS = (ApiKey.id, ApiKey.name, ApiKey.display_prefix, ApiKey.last_four,
                  ApiKey.created_at, ApiKey.last_used_at, ApiKey.revoked_at)


def fetch(db: Session, key_id: str) -> dict | None:
    row = db.execute(select(*PUBLIC_COLUMNS).where(ApiKey.id == key_id)).mappings().first()
    return dict(row) if row is not None else None


def create(db: Session, key_id: str, user_id: str, name: str, key_hash: str,
           prefix: str, last_four: str) -> None:
    db.execute(insert(ApiKey).values(id=key_id, user_id=user_id, name=name, key_hash=key_hash,
                                    display_prefix=prefix, last_four=last_four,
                                    created_at=func.utc_timestamp(3)))


def list_for_user(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(select(*PUBLIC_COLUMNS).where(
        ApiKey.user_id == user_id, ApiKey.deleted_at.is_(None),
    ).order_by(ApiKey.created_at.desc(), ApiKey.id.desc())).mappings().all()
    return [dict(row) for row in rows]


def revoke(db: Session, user_id: str, key_id: str) -> int:
    return db.execute(update(ApiKey).where(
        ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None),
        ApiKey.deleted_at.is_(None),
    ).values(revoked_at=func.utc_timestamp(3))).rowcount


def visible_owned_key(db: Session, user_id: str, key_id: str) -> bool:
    return db.scalar(select(ApiKey.id).where(
        ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.deleted_at.is_(None),
    )) is not None


def soft_delete(db: Session, user_id: str, key_id: str) -> int:
    return db.execute(update(ApiKey).where(
        ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_not(None),
        ApiKey.deleted_at.is_(None),
    ).values(deleted_at=func.utc_timestamp(3))).rowcount


def owned_state(db: Session, user_id: str, key_id: str) -> dict | None:
    row = db.execute(select(ApiKey.revoked_at, ApiKey.deleted_at).where(
        ApiKey.id == key_id, ApiKey.user_id == user_id,
    )).mappings().first()
    return dict(row) if row is not None else None


def authenticate(db: Session, key_hash: str) -> dict | None:
    row = db.execute(select(ApiKey.id, ApiKey.display_prefix, ApiKey.last_four,
                            ApiKey.user_id, User.status).join(User, User.id == ApiKey.user_id).where(
        ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None),
    )).mappings().first()
    return dict(row) if row is not None else None


def still_valid(db: Session, key_id: str) -> bool:
    return db.scalar(select(ApiKey.id).join(User, User.id == ApiKey.user_id).where(
        ApiKey.id == key_id, ApiKey.revoked_at.is_(None), User.status == 'active',
    )) is not None


def mark_used(db: Session, key_id: str, at) -> None:
    db.execute(update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=at))

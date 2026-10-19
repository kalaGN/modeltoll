"""Administrator listings and atomic mutation persistence."""

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, aliased

from app.models import AdminAuditEvent, ApiKey, User, UserSession

USER_COLUMNS = (User.id, User.email, User.status, User.is_admin, User.created_at, User.last_login_at)
KEY_COLUMNS = (ApiKey.id, ApiKey.user_id, ApiKey.name, ApiKey.display_prefix, ApiKey.last_four,
               ApiKey.created_at, ApiKey.last_used_at, ApiKey.revoked_at, ApiKey.deleted_at)


def _one(db: Session, statement) -> dict | None:
    row = db.execute(statement).mappings().first()
    return dict(row) if row is not None else None


def list_users(db: Session, search: str, status: str, page: int, limit: int) -> tuple[int, list[dict]]:
    clauses = []
    if search:
        escaped = search.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clauses.append(User.email.like(f'%{escaped}%', escape='!'))
    if status:
        clauses.append(User.status == status)
    total = db.scalar(select(func.count()).select_from(User).where(*clauses))
    rows = db.execute(select(*USER_COLUMNS).where(*clauses).order_by(
        User.created_at.desc(), User.id.desc()).limit(limit).offset((page - 1) * limit)).mappings().all()
    return total, [dict(row) for row in rows]


def user_exists(db: Session, user_id: str) -> bool:
    return db.scalar(select(User.id).where(User.id == user_id)) is not None


def list_keys(db: Session, user_id: str, page: int, limit: int) -> tuple[int, list[dict]]:
    total = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id))
    rows = db.execute(select(*KEY_COLUMNS).where(ApiKey.user_id == user_id).order_by(
        ApiKey.created_at.desc(), ApiKey.id.desc()).limit(limit).offset((page - 1) * limit)).mappings().all()
    return total, [dict(row) for row in rows]


def list_audit_events(db: Session, page: int, limit: int) -> tuple[int, list[dict]]:
    actor, target = aliased(User, name='actor'), aliased(User, name='target')
    total = db.scalar(select(func.count()).select_from(AdminAuditEvent))
    a = AdminAuditEvent
    rows = db.execute(select(a.id, a.actor_id, actor.email.label('actor_email'), a.target_user_id,
                             target.email.label('target_email'), a.target_key_id, a.action,
                             a.previous_status, a.new_status, a.reason, a.created_at)
                      .join(actor, actor.id == a.actor_id).join(target, target.id == a.target_user_id)
                      .order_by(a.created_at.desc(), a.id.desc()).limit(limit)
                      .offset((page - 1) * limit)).mappings().all()
    return total, [dict(row) for row in rows]


def lock_user(db: Session, user_id: str) -> dict | None:
    return _one(db, select(*USER_COLUMNS).where(User.id == user_id).with_for_update())


def set_user_status(db: Session, user_id: str, status: str) -> None:
    db.execute(update(User).where(User.id == user_id).values(status=status, updated_at=func.utc_timestamp(3)))


def revoke_sessions(db: Session, user_id: str) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
               .values(revoked_at=func.utc_timestamp(3)))


def key_owner(db: Session, key_id: str) -> dict | None:
    return _one(db, select(ApiKey.user_id).where(ApiKey.id == key_id))


def lock_key(db: Session, key_id: str, user_id: str) -> dict | None:
    return _one(db, select(*KEY_COLUMNS).where(ApiKey.id == key_id, ApiKey.user_id == user_id).with_for_update())


def revoke_key(db: Session, key_id: str, now) -> None:
    db.execute(update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=now))


def audit(db: Session, event_id: str, actor_id: str, target_user_id: str, target_key_id: str | None,
          action: str, previous: str, new: str, reason: str) -> None:
    db.execute(insert(AdminAuditEvent).values(id=event_id, actor_id=actor_id, target_user_id=target_user_id,
        target_key_id=target_key_id, action=action, previous_status=previous, new_status=new,
        reason=reason, created_at=func.utc_timestamp(3)))

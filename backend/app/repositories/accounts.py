"""Account/session persistence and MySQL atomic login-throttle operations."""
import re

from sqlalchemy import delete, func, insert, literal_column, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LoginThrottle, User, UserSession


def is_email_conflict(error: IntegrityError) -> bool:
    """Fail closed on unknown diagnostics; 1062 alone also covers other indexes."""
    args = getattr(error.orig, 'args', ())
    return (
        len(args) == 2 and type(args[0]) is int and args[0] == 1062
        and isinstance(args[1], str)
        and re.search(r"for key '(?:users\.)?uk_users_email_normalized'\Z", args[1]) is not None
    )


def login_user(db: Session, email: str) -> dict | None:
    row = db.execute(select(User.id, User.email, User.password_hash, User.status)
                     .where(User.email_normalized == email)).mappings().first()
    return dict(row) if row is not None else None


def public_user(db: Session, email: str) -> dict | None:
    row = db.execute(select(User.id, User.email, User.is_admin)
                     .where(User.email_normalized == email)).mappings().first()
    return dict(row) if row is not None else None


def throttle(db: Session, key: str) -> dict | None:
    row = db.execute(select(LoginThrottle.locked_until)
                     .where(LoginThrottle.throttle_key == key)).mappings().first()
    return dict(row) if row is not None else None


def record_failure(db: Session, key: str, now, window_seconds: int, threshold: int, locked_until) -> None:
    # MySQL evaluates assignments left-to-right. Check the threshold before
    # changing failed_count, and reset first_failed_at only after both checks.
    # One UPSERT preserves concurrent increments without a read/insert race.
    reset = func.timestampdiff(literal_column('SECOND'), LoginThrottle.first_failed_at, now) > window_seconds
    next_count = func.if_(reset, 1, LoginThrottle.failed_count + 1)
    statement = mysql_insert(LoginThrottle).values(
        throttle_key=key, failed_count=1, first_failed_at=now, locked_until=None, updated_at=now,
    ).on_duplicate_key_update([
        ('locked_until', func.if_(next_count >= threshold, locked_until, None)),
        ('failed_count', next_count),
        ('first_failed_at', func.if_(reset, now, LoginThrottle.first_failed_at)),
        ('updated_at', now),
    ])
    db.execute(statement)


def create_user(db: Session, user_id: str, email: str, normalized: str, password_hash: str) -> None:
    db.execute(insert(User).values(
        id=user_id, email=email, email_normalized=normalized, password_hash=password_hash,
        status='active', created_at=func.utc_timestamp(3), updated_at=func.utc_timestamp(3),
    ))


def lock_credentials(db: Session, user_id: str) -> dict | None:
    row = db.execute(select(User.id, User.password_hash, User.status).where(User.id == user_id)
                     .with_for_update()).mappings().first()
    return dict(row) if row is not None else None


def clear_throttle(db: Session, key: str) -> None:
    db.execute(delete(LoginThrottle).where(LoginThrottle.throttle_key == key))


def mark_login(db: Session, user_id: str) -> None:
    db.execute(update(User).where(User.id == user_id).values(
        last_login_at=func.utc_timestamp(3), updated_at=func.utc_timestamp(3),
    ))


def create_session(db: Session, session_id: str, user_id: str, token_hash: str, ttl_minutes: int) -> None:
    db.execute(insert(UserSession).values(
        id=session_id, user_id=user_id, token_hash=token_hash, created_at=func.utc_timestamp(3),
        expires_at=func.timestampadd(literal_column('MINUTE'), ttl_minutes, func.utc_timestamp(3)),
    ))


def current_user(db: Session, token_hash: str) -> dict | None:
    row = db.execute(select(User.id, User.email, User.is_admin).select_from(UserSession)
                     .join(User, User.id == UserSession.user_id).where(
                         UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None),
                         UserSession.expires_at > func.utc_timestamp(3), User.status == 'active',
                     )).mappings().first()
    return dict(row) if row is not None else None


def revoke_session(db: Session, token_hash: str) -> None:
    db.execute(update(UserSession).where(
        UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None),
    ).values(revoked_at=func.utc_timestamp(3)))


def bootstrap_user(db: Session, email: str, *, lock: bool = False) -> dict | None:
    statement = select(User.id, User.email, User.status, User.is_admin).where(User.email_normalized == email)
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().first()
    return dict(row) if row is not None else None


def bootstrap_lock(db: Session, *, release: bool = False) -> bool:
    # MySQL named locks are connection-scoped, not transaction-scoped.
    name = func.concat('laya:init-admin:', func.left(func.sha2(func.database(), 256), 40))
    expression = func.release_lock(name) if release else func.get_lock(name, 10)
    return db.scalar(select(expression)) == 1


def any_admin(db: Session) -> bool:
    return db.scalar(select(User.id).where(User.is_admin == 1).limit(1).with_for_update()) is not None


def create_admin(db: Session, user_id: str, email: str, password_hash: str) -> None:
    db.execute(insert(User).values(
        id=user_id, email=email, email_normalized=email, password_hash=password_hash,
        status='active', is_admin=1, created_at=func.utc_timestamp(3), updated_at=func.utc_timestamp(3),
    ))

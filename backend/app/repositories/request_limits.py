"""Persistent fixed-minute counters; callers own both transaction boundaries."""

from datetime import datetime

from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.models import RequestRateWindow


def cleanup(db: Session) -> None:
    db.execute(delete(RequestRateWindow).where(
        RequestRateWindow.window_start < func.utc_timestamp(6) - literal_column('INTERVAL 24 HOUR')
    ).with_dialect_options(mysql_limit=1000))


def now(db: Session) -> datetime:
    return db.execute(select(func.utc_timestamp(6))).scalar_one()


def ensure_window(db: Session, user_id: str, window: datetime) -> None:
    statement = insert(RequestRateWindow).values(user_id=user_id, window_start=window, request_count=0)
    db.execute(statement.on_duplicate_key_update(request_count=RequestRateWindow.request_count))


def lock_count(db: Session, user_id: str, window: datetime) -> int:
    return db.execute(select(RequestRateWindow.request_count).where(
        RequestRateWindow.user_id == user_id, RequestRateWindow.window_start == window
    ).with_for_update()).scalar_one()


def increment(db: Session, user_id: str, window: datetime) -> None:
    db.execute(update(RequestRateWindow).where(
        RequestRateWindow.user_id == user_id, RequestRateWindow.window_start == window
    ).values(request_count=RequestRateWindow.request_count + 1))

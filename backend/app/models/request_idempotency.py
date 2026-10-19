"""Mapping of the existing request_idempotency table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestIdempotency(Base):
    __tablename__ = 'request_idempotency'
    user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    key_hash: Mapped[str] = mapped_column(mysql.CHAR(64, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    request_hash: Mapped[str] = mapped_column(mysql.CHAR(64, charset='ascii', collation='ascii_bin'), nullable=False)
    call_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        UniqueConstraint('call_id', name='uk_request_idempotency_call'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_idempotency_user'),
        ForeignKeyConstraint(['call_id'], ['api_calls.id'], name='fk_idempotency_call'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

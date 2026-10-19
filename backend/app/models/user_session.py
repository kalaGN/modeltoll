"""Mapping of the existing user_sessions table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserSession(Base):
    __tablename__ = 'user_sessions'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    token_hash: Mapped[str] = mapped_column(mysql.CHAR(64, charset='ascii', collation='ascii_bin'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)

    __table_args__ = (
        UniqueConstraint('token_hash', name='uk_sessions_token_hash'),
        Index('idx_sessions_user', 'user_id', 'revoked_at'),
        Index('idx_sessions_expires', 'expires_at'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_sessions_user'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

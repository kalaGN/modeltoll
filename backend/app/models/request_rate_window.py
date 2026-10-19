"""Mapping of the existing request_rate_windows table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestRateWindow(Base):
    __tablename__ = 'request_rate_windows'
    user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    window_start: Mapped[datetime] = mapped_column(mysql.DATETIME(), primary_key=True, autoincrement=False, nullable=False)
    request_count: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False, server_default=text('0'))

    __table_args__ = (
        Index('idx_request_rate_window', 'window_start'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_request_rate_user'),
        CheckConstraint('request_count >= 0', name='chk_request_rate_count'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

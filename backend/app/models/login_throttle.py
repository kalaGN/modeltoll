"""Mapping of the existing login_throttle table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import Index, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoginThrottle(Base):
    __tablename__ = 'login_throttle'
    throttle_key: Mapped[str] = mapped_column(mysql.VARCHAR(300, charset='utf8mb4', collation='utf8mb4_0900_as_cs'), primary_key=True, autoincrement=False, nullable=False)
    failed_count: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False, server_default=text('0'))
    first_failed_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        Index('idx_throttle_locked', 'locked_until'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

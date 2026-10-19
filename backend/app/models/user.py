"""Mapping of the existing users table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    email: Mapped[str] = mapped_column(mysql.VARCHAR(254), nullable=False)
    email_normalized: Mapped[str] = mapped_column(mysql.VARCHAR(254, charset='utf8mb4', collation='utf8mb4_0900_as_cs'), nullable=False)
    password_hash: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(16), nullable=False, server_default=text("'active'"))
    last_login_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    is_admin: Mapped[int] = mapped_column(mysql.TINYINT(display_width=1), nullable=False, server_default=text('FALSE'))

    __table_args__ = (
        UniqueConstraint('email_normalized', name='uk_users_email_normalized'),
        CheckConstraint("status IN ('active', 'disabled')", name='chk_users_status'),
        CheckConstraint('is_admin IN (0, 1)', name='chk_users_admin'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

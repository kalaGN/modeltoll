"""Mapping of the existing platform_settings table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformSetting(Base):
    __tablename__ = 'platform_settings'
    id: Mapped[int] = mapped_column(mysql.TINYINT(), primary_key=True, autoincrement=False, nullable=False)
    name: Mapped[str] = mapped_column(mysql.VARCHAR(60), nullable=False, server_default=text("'Laya'"))
    description: Mapped[str] = mapped_column(mysql.VARCHAR(200), nullable=False, server_default=text("'模型 API 平台'"))
    logo_blob: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB(), nullable=True)
    logo_mime: Mapped[str | None] = mapped_column(mysql.VARCHAR(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        CheckConstraint('id = 1', name='chk_platform_settings_singleton'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

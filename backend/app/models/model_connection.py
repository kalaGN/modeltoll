"""Mapping of the existing model_connection table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelConnection(Base):
    __tablename__ = 'model_connection'
    id: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False, nullable=False)
    base_url: Mapped[str] = mapped_column(mysql.VARCHAR(512), nullable=False)
    model: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True), nullable=False)
    enabled: Mapped[int] = mapped_column(mysql.TINYINT(display_width=1), nullable=False, server_default=text('0'))
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        CheckConstraint('id = 1', name='chk_connection_singleton'),
        CheckConstraint('timeout_seconds BETWEEN 1 AND 300', name='chk_connection_timeout'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

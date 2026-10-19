"""Mapping of the existing api_keys table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiKey(Base):
    __tablename__ = 'api_keys'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    name: Mapped[str] = mapped_column(mysql.VARCHAR(60), nullable=False, server_default=text("''"))
    key_hash: Mapped[str] = mapped_column(mysql.CHAR(64, charset='ascii', collation='ascii_bin'), nullable=False)
    display_prefix: Mapped[str] = mapped_column(mysql.VARCHAR(32), nullable=False)
    last_four: Mapped[str] = mapped_column(mysql.CHAR(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)

    __table_args__ = (
        UniqueConstraint('key_hash', name='uk_api_keys_hash'),
        UniqueConstraint('id', 'user_id', name='uk_api_keys_id_user'),
        Index('idx_api_keys_user_created', 'user_id', 'created_at', 'id'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_api_keys_user'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

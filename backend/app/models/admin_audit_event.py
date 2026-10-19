"""Mapping of the existing admin_audit_events table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminAuditEvent(Base):
    __tablename__ = 'admin_audit_events'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    actor_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    target_user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    target_key_id: Mapped[str | None] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=True)
    action: Mapped[str] = mapped_column(mysql.VARCHAR(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(mysql.VARCHAR(16), nullable=False)
    new_status: Mapped[str] = mapped_column(mysql.VARCHAR(16), nullable=False)
    reason: Mapped[str] = mapped_column(mysql.VARCHAR(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        Index('idx_admin_audit_created', 'created_at', 'id'),
        Index('idx_admin_audit_target', 'target_user_id', 'created_at', 'id'),
        ForeignKeyConstraint(['actor_id'], ['users.id'], name='fk_admin_audit_actor'),
        ForeignKeyConstraint(['target_user_id'], ['users.id'], name='fk_admin_audit_target'),
        ForeignKeyConstraint(['target_key_id', 'target_user_id'], ['api_keys.id', 'api_keys.user_id'], name='fk_admin_audit_key_owner'),
        CheckConstraint("action IN ('user.status_changed', 'api_key.revoked')", name='chk_admin_audit_action'),
        CheckConstraint(" (action = 'user.status_changed' AND target_key_id IS NULL AND previous_status IN ('active', 'disabled') AND new_status IN ('active', 'disabled') AND previous_status <> new_status) OR (action = 'api_key.revoked' AND target_key_id IS NOT NULL AND previous_status = 'active' AND new_status = 'revoked')", name='chk_admin_audit_status'),
        CheckConstraint('CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 200', name='chk_admin_audit_reason'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

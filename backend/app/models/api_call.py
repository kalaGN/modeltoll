"""Mapping of the existing api_calls table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiCall(Base):
    __tablename__ = 'api_calls'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    user_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    api_key_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    endpoint: Mapped[str] = mapped_column(mysql.VARCHAR(128), nullable=False)
    model: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(mysql.VARCHAR(128), nullable=True)
    pricing_rule_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(24), nullable=False)
    http_status: Mapped[int | None] = mapped_column(mysql.SMALLINT(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=3), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    truncated: Mapped[int | None] = mapped_column(mysql.TINYINT(display_width=1), nullable=True)
    state_tokens_dropped: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    billing_status: Mapped[str] = mapped_column(mysql.VARCHAR(16), nullable=False)
    billing_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        Index('idx_calls_user_started', 'user_id', 'started_at', 'id'),
        Index('idx_calls_key_started', 'user_id', 'api_key_id', 'started_at', 'id'),
        Index('idx_calls_endpoint_started', 'user_id', 'endpoint', 'started_at', 'id'),
        Index('idx_calls_billing', 'billing_status', 'started_at'),
        ForeignKeyConstraint(['api_key_id', 'user_id'], ['api_keys.id', 'api_keys.user_id'], name='fk_calls_key_user'),
        ForeignKeyConstraint(['pricing_rule_id'], ['pricing_rules.id'], name='fk_calls_pricing'),
        CheckConstraint(" status IN ('accepted', 'running', 'succeeded', 'failed', 'interrupted') ", name='chk_calls_status'),
        CheckConstraint(" billing_status IN ('pending', 'charged', 'not_billable') ", name='chk_calls_billing_status'),
        CheckConstraint(" status IN ('accepted', 'running') OR completed_at IS NOT NULL ", name='chk_calls_completed'),
        CheckConstraint(" status <> 'succeeded' OR input_tokens IS NOT NULL ", name='chk_calls_succeeded_usage'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

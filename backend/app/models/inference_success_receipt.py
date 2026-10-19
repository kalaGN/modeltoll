"""Mapping of the existing inference_success_receipts table; DDL lives in backend/migrations."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InferenceSuccessReceipt(Base):
    __tablename__ = 'inference_success_receipts'
    call_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    input_tokens: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    output_tokens: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    truncated: Mapped[int | None] = mapped_column(mysql.TINYINT(display_width=1), nullable=True)
    state_tokens_dropped: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    duration_ms: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(['call_id'], ['api_calls.id'], name='fk_success_receipt_call'),
        CheckConstraint('input_tokens <= 9223372036854775807', name='chk_receipt_input'),
        CheckConstraint('output_tokens <= 9223372036854775807', name='chk_receipt_output'),
        CheckConstraint('state_tokens_dropped <= 9223372036854775807', name='chk_receipt_dropped'),
        CheckConstraint('truncated IS NULL OR truncated IN (0, 1)', name='chk_receipt_truncated'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

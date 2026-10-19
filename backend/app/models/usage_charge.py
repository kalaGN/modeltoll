"""Mapping of the existing usage_charges table; DDL lives in backend/migrations."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageCharge(Base):
    __tablename__ = 'usage_charges'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    call_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    pricing_rule_id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), nullable=False)
    billable_input_tokens: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    unit_tokens: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    unit_price_yuan: Mapped[Decimal] = mapped_column(mysql.DECIMAL(20,6, asdecimal=True), nullable=False)
    amount_yuan: Mapped[Decimal] = mapped_column(mysql.DECIMAL(20,6, asdecimal=True), nullable=False)
    currency: Mapped[str] = mapped_column(mysql.CHAR(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        UniqueConstraint('call_id', name='uk_charges_call'),
        Index('idx_charges_created', 'created_at', 'id'),
        ForeignKeyConstraint(['call_id'], ['api_calls.id'], name='fk_charges_call'),
        ForeignKeyConstraint(['pricing_rule_id'], ['pricing_rules.id'], name='fk_charges_pricing'),
        CheckConstraint('billable_input_tokens >= 0', name='chk_charges_tokens'),
        CheckConstraint('unit_tokens > 0', name='chk_charges_unit'),
        CheckConstraint('amount_yuan >= 0', name='chk_charges_amount'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

"""Mapping of the existing pricing_rules table; DDL lives in backend/migrations."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PricingRule(Base):
    __tablename__ = 'pricing_rules'
    id: Mapped[str] = mapped_column(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), primary_key=True, autoincrement=False, nullable=False)
    version: Mapped[str] = mapped_column(mysql.VARCHAR(32), nullable=False)
    model: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    currency: Mapped[str] = mapped_column(mysql.CHAR(3), nullable=False)
    token_basis: Mapped[str] = mapped_column(mysql.VARCHAR(32), nullable=False)
    unit_tokens: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    unit_price_yuan: Mapped[Decimal] = mapped_column(mysql.DECIMAL(20,6, asdecimal=True), nullable=False)
    billing_policy_version: Mapped[str] = mapped_column(mysql.VARCHAR(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), nullable=False)

    __table_args__ = (
        UniqueConstraint('version', name='uk_pricing_version'),
        UniqueConstraint('model', 'effective_from', name='uk_pricing_model_effective'),
        CheckConstraint('unit_tokens > 0', name='chk_pricing_unit_tokens'),
        CheckConstraint('unit_price_yuan >= 0', name='chk_pricing_price'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_0900_ai_ci'},
    )

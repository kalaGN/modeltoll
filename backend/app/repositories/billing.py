"""Price and ledger persistence; transaction ownership stays with services."""
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session
from app.models import PricingRule, UsageCharge


def _price_columns():
    return (PricingRule.id, PricingRule.version, PricingRule.model, PricingRule.currency,
            PricingRule.token_basis, PricingRule.unit_tokens, PricingRule.unit_price_yuan,
            PricingRule.billing_policy_version)


def current_rule(db: Session, model: str) -> dict | None:
    row = db.execute(select(*_price_columns()).where(
        PricingRule.model == model, PricingRule.effective_from <= func.utc_timestamp(3)
    ).order_by(PricingRule.effective_from.desc()).limit(1)).mappings().first()
    return None if row is None else dict(row)


def rule_by_id(db: Session, rule_id: str) -> dict | None:
    row = db.execute(select(*_price_columns()).where(PricingRule.id == rule_id)).mappings().first()
    return None if row is None else dict(row)


def charge(db: Session, call_id: str) -> dict | None:
    row = db.execute(select(
        UsageCharge.pricing_rule_id, UsageCharge.billable_input_tokens, UsageCharge.unit_tokens,
        UsageCharge.unit_price_yuan, UsageCharge.amount_yuan, UsageCharge.currency,
    ).where(UsageCharge.call_id == call_id)).mappings().first()
    return None if row is None else dict(row)


def insert_charge(db: Session, values: dict) -> None:
    db.execute(insert(UsageCharge).values(**values, created_at=func.utc_timestamp(3)))

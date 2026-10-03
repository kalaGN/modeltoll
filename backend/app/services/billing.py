"""价格解析与精确记账。金额一律用 Decimal，禁止二进制浮点累加（需求 R06）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core import config
from app.db import session


class NoPricingRule(Exception):
    """无适用价格时拒绝调用，不静默按零价记账（设计 §6）。"""


@dataclass(frozen=True)
class PricingRule:
    id: str
    version: str
    model: str
    currency: str
    token_basis: str
    unit_tokens: int
    unit_price_yuan: Decimal
    billing_policy_version: str

    @property
    def public(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "model": self.model,
            "currency": self.currency,
            "token_basis": self.token_basis,
            "unit_tokens": self.unit_tokens,
            "unit_price_yuan": str(self.unit_price_yuan),
            "billing_policy_version": self.billing_policy_version,
        }


def current_rule(model: str) -> PricingRule:
    """按模型取 effective_from ≤ 当前 UTC 时间的最新规则并固定其 ID。"""
    with session.cursor() as cur:
        cur.execute(
            "SELECT id, version, model, currency, token_basis, unit_tokens,"
            " unit_price_yuan, billing_policy_version"
            " FROM pricing_rules"
            " WHERE model = %s AND effective_from <= UTC_TIMESTAMP(3)"
            " ORDER BY effective_from DESC LIMIT 1",
            (model,),
        )
        row = cur.fetchone()
    if row is None:
        raise NoPricingRule()
    return PricingRule(
        id=row["id"],
        version=row["version"],
        model=row["model"],
        currency=row["currency"],
        token_basis=row["token_basis"],
        unit_tokens=int(row["unit_tokens"]),
        unit_price_yuan=Decimal(str(row["unit_price_yuan"])),
        billing_policy_version=row["billing_policy_version"],
    )


def amount_yuan(billable_tokens: int, rule: PricingRule) -> Decimal:
    """计费 Token × 单价 ÷ 单位量；当前价格六位小数即为精确值。"""
    raw = Decimal(billable_tokens) * rule.unit_price_yuan / Decimal(rule.unit_tokens)
    return raw.quantize(config.PRICING_AMOUNT_EXPONENT, rounding=ROUND_HALF_UP)


def insert_charge(cur: Any, call_id: str, rule: PricingRule, billable_tokens: int) -> Decimal:
    """在同一事务内写入唯一费用行；UNIQUE(call_id) 防止重复入账。"""
    amount = amount_yuan(billable_tokens, rule)
    cur.execute(
        "INSERT INTO usage_charges (id, call_id, pricing_rule_id, billable_input_tokens,"
        " unit_tokens, unit_price_yuan, amount_yuan, currency, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(3))",
        (
            str(uuid.uuid4()),
            call_id,
            rule.id,
            billable_tokens,
            rule.unit_tokens,
            rule.unit_price_yuan,
            amount,
            rule.currency,
        ),
    )
    return amount

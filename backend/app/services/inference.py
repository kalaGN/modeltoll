"""调用生命周期协调：鉴权后固定价格并写 accepted，终态与入账在同一短事务完成。

不持有数据库事务等待 MPS 推理（设计 §9/§15）；用量只取服务端 Laya 返回值，
客户端上报不参与计费（需求 R05）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db import session
from app.services import api_keys, billing


@dataclass
class Call:
    id: str
    user_id: str
    api_key_id: str
    endpoint: str
    model: str
    rule: billing.PricingRule
    _started_monotonic: float = field(default=0.0, repr=False)

    @property
    def request_id(self) -> str:
        return self.id


class UsageUnavailable(Exception):
    """模型没给出 input_tokens：终态已按失败落库，接口不得再对外声称成功。"""

    def __init__(self, call_id: str):
        super().__init__(call_id)
        self.call_id = call_id


def begin(endpoint: str, principal: api_keys.Principal, model: str) -> Call:
    """接受调用：固定价格版本、写入 accepted，并记录 Key 最近使用时间。"""
    rule = billing.current_rule(model)
    call_id = str(uuid.uuid4())
    started = time.monotonic()
    with session.transaction() as cur:
        cur.execute(
            "INSERT INTO api_calls (id, user_id, api_key_id, endpoint, model,"
            " pricing_rule_id, status, started_at, billing_status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'accepted', UTC_TIMESTAMP(3), 'pending',"
            " UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
            (call_id, principal.user_id, principal.api_key_id, endpoint, model, rule.id),
        )
        cur.execute(
            "UPDATE api_keys SET last_used_at = UTC_TIMESTAMP(3) WHERE id = %s",
            (principal.api_key_id,),
        )
    return Call(
        id=call_id,
        user_id=principal.user_id,
        api_key_id=principal.api_key_id,
        endpoint=endpoint,
        model=model,
        rule=rule,
        _started_monotonic=started,
    )


def mark_running(call: Call) -> None:
    with session.cursor() as cur:
        cur.execute(
            "UPDATE api_calls SET status = 'running', updated_at = UTC_TIMESTAMP(3)"
            " WHERE id = %s AND status = 'accepted'",
            (call.id,),
        )


def _duration_ms(call: Call) -> int:
    return max(0, int((time.monotonic() - call._started_monotonic) * 1000))


def succeeded(call: Call, usage: dict[str, Any], http_status: int = 200) -> Decimal:
    """终态与入账同一事务：写入 Laya 用量、判定计费资格并插入唯一费用行。

    用量缺失时先落 failed/pending 终态，再抛 UsageUnavailable，让调用方对外返回
    失败，避免库内记 500 而 HTTP 仍回 200 的矛盾状态。
    """
    input_tokens = usage.get("input_tokens")
    if input_tokens is None:
        failed(call, "usage_unavailable", http_status=500)
        raise UsageUnavailable(call.id)
    billable = int(input_tokens)
    amount = Decimal("0.000000")
    with session.transaction() as cur:
        cur.execute(
            "UPDATE api_calls SET status = 'succeeded', http_status = %s,"
            " completed_at = UTC_TIMESTAMP(3), duration_ms = %s, input_tokens = %s,"
            " output_tokens = %s, truncated = %s, state_tokens_dropped = %s,"
            " billing_status = 'charged', billing_reason = %s,"
            " updated_at = UTC_TIMESTAMP(3) WHERE id = %s",
            (
                http_status,
                _duration_ms(call),
                billable,
                _nullable_int(usage.get("output_tokens")),
                _nullable_bool(usage.get("truncated")),
                _nullable_int(usage.get("state_tokens_dropped")),
                call.rule.billing_policy_version,
                call.id,
            ),
        )
        amount = billing.insert_charge(cur, call.id, call.rule, billable)
    return amount


def failed(call: Call, error_code: str, http_status: int) -> Decimal:
    """失败调用保留已知用量但按采用策略不计费；用量未知的单列 pending 待核查。

    入账资格只覆盖 succeeded（采用值 `succeeded_only_v1`），失败/超时/断连的
    计费政策仍待产品确认，不隐藏该采用策略。
    """
    usage_unknown = error_code == "usage_unavailable"
    billing_status = "pending" if usage_unknown else "not_billable"
    reason = "usage_unavailable" if usage_unknown else "policy_succeeded_only"
    with session.transaction() as cur:
        cur.execute(
            "UPDATE api_calls SET status = 'failed', http_status = %s, error_code = %s,"
            " completed_at = UTC_TIMESTAMP(3), duration_ms = %s,"
            " billing_status = %s, billing_reason = %s,"
            " updated_at = UTC_TIMESTAMP(3) WHERE id = %s",
            (http_status, error_code[:64], _duration_ms(call), billing_status, reason, call.id),
        )
    return Decimal("0.000000")


def interrupted(call: Call, error_code: str, http_status: int) -> Decimal:
    """运行前被撤销或运行被中止：写入可恢复终态，不产生费用。"""
    with session.transaction() as cur:
        cur.execute(
            "UPDATE api_calls SET status = 'interrupted', http_status = %s,"
            " error_code = %s, completed_at = UTC_TIMESTAMP(3), duration_ms = %s,"
            " billing_status = 'not_billable', billing_reason = %s,"
            " updated_at = UTC_TIMESTAMP(3) WHERE id = %s",
            (http_status, error_code[:64], _duration_ms(call), error_code[:64], call.id),
        )
    return Decimal("0.000000")


def keep_usage(call: Call, usage: dict[str, Any]) -> None:
    """推理已产出用量但后续分支失败时保留已知用量，不默认写 0（设计 §7）。"""
    with session.cursor() as cur:
        cur.execute(
            "UPDATE api_calls SET input_tokens = %s, output_tokens = %s, truncated = %s,"
            " state_tokens_dropped = %s, updated_at = UTC_TIMESTAMP(3)"
            " WHERE id = %s AND input_tokens IS NULL",
            (
                usage.get("input_tokens"),
                _nullable_int(usage.get("output_tokens")),
                _nullable_bool(usage.get("truncated")),
                _nullable_int(usage.get("state_tokens_dropped")),
                call.id,
            ),
        )


def _nullable_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _nullable_bool(value: Any) -> int | None:
    return None if value is None else int(bool(value))

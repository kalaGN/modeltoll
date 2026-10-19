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
from sqlalchemy.exc import IntegrityError

from app.db import session
from app.repositories import calls as repository, billing as billing_repository
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


class CallStateConflict(Exception):
    """调用不存在或生命周期/账务事实矛盾；禁止覆盖历史或伪造成功。"""


class IdempotencyConflict(Exception):
    def __init__(self, code: str, call_id: str):
        super().__init__(code)
        self.code, self.call_id = code, call_id


def success_receipt(cur: Any, call: Call) -> dict[str, Any] | None:
    """Read trusted success facts using the caller's transaction Session."""
    return repository.success_receipt(cur, call.id)


def usage_values(row: dict[str, Any]) -> tuple:
    """Return usage fields in their persisted settlement order."""
    return tuple(row[key] for key in ('input_tokens', 'output_tokens', 'truncated',
                                     'state_tokens_dropped'))


def _locked_call(cur: Any, call: Call) -> dict[str, Any]:
    row = repository.lock_call(cur, call.id)
    if row is None or row['pricing_rule_id'] != call.rule.id:
        raise CallStateConflict(call.id)
    return row


def _charge(cur: Any, call: Call) -> dict[str, Any] | None:
    return billing_repository.charge(cur, call.id)


def _require_active(cur: Any, call: Call, row: dict[str, Any]) -> None:
    if (row['status'] not in {'accepted', 'running'} or
            row['billing_status'] != 'pending' or _charge(cur, call) is not None):
        raise CallStateConflict(call.id)


def begin(endpoint: str, principal: api_keys.Principal, model: str, *,
          idempotency: tuple[str, str] | None = None) -> Call:
    """接受调用：固定价格版本、写入 accepted，并记录 Key 最近使用时间。"""
    rule = billing.current_rule(model)
    call_id = str(uuid.uuid4())
    started = time.monotonic()
    try:
        with session.unit_of_work() as cur:
            repository.accept(cur, dict(id=call_id, user_id=principal.user_id,
                api_key_id=principal.api_key_id, endpoint=endpoint, model=model, pricing_rule_id=rule.id))
            if idempotency is not None:
                repository.reserve(cur, principal.user_id, *idempotency, call_id)
    except IntegrityError as exc:
        if idempotency is None or exc.orig.args[0] != 1062:
            raise
        # Rollback above removes the new call; the unique-key winner is committed now.
        with session.read_session() as cur:
            prior = repository.reservation(cur, principal.user_id, idempotency[0])
        if prior is None:
            raise
        code = ('request_already_processed' if prior['request_hash'] == idempotency[1]
                else 'idempotency_conflict')
        raise IdempotencyConflict(code, prior['call_id']) from None
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
    with session.unit_of_work() as cur:
        row = _locked_call(cur, call)
        _require_active(cur, call, row)
        if row['status'] != 'accepted' or success_receipt(cur, call) is not None:
            raise CallStateConflict(call.id)
        if repository.mark_running(cur, call.id) != 1:
            raise CallStateConflict(call.id)


def _duration_ms(call: Call) -> int:
    return max(0, int((time.monotonic() - call._started_monotonic) * 1000))


def succeeded(call: Call, usage: dict[str, Any], http_status: int = 200) -> Decimal:
    """终态与入账同一事务：写入 Laya 用量、判定计费资格并插入唯一费用行。

    用量缺失时先落 failed/pending 终态，再抛 UsageUnavailable，让调用方对外返回
    失败，避免库内记 500 而 HTTP 仍回 200 的矛盾状态。
    """
    try:
        values = validate_usage(usage)
    except (TypeError, ValueError):
        failed(call, "usage_unavailable", http_status=500)
        raise UsageUnavailable(call.id)
    with session.unit_of_work() as cur:
        return settle_success_in_transaction(cur, call, values, http_status)


def capture_success(call: Call, usage: dict[str, Any]) -> None:
    """Persist a successful, serializable business result's usage without its payload."""
    try:
        values = validate_usage(usage)
    except (TypeError, ValueError):
        failed(call, 'usage_unavailable', 500)
        raise UsageUnavailable(call.id) from None
    with session.unit_of_work() as cur:
        row = _locked_call(cur, call)
        _require_active(cur, call, row)
        previous = usage_values(row)
        if any(value is not None for value in previous) and previous != values:
            raise CallStateConflict(call.id)
        receipt = success_receipt(cur, call)
        if receipt is not None:
            if usage_values(receipt) != values:
                raise CallStateConflict(call.id)
            return
        repository.capture_success(cur, call.id, values, _duration_ms(call))


def settle_success_in_transaction(cur: Any, call: Call, values: tuple, http_status: int = 200) -> Decimal:
    """Settle with the caller-owned transaction; never open or commit a connection.

    Normal settlement and explicit receipt recovery share this exact implementation.
    """
    billable, output_tokens, truncated, dropped = values
    row = _locked_call(cur, call)
    receipt = success_receipt(cur, call)
    if receipt is not None and usage_values(receipt) != values:
        raise CallStateConflict(call.id)
    if row['status'] == 'succeeded':
        charge = _charge(cur, call)
        if receipt is not None and (row['completed_at'] != receipt['completed_at'] or
                                    row['duration_ms'] != receipt['duration_ms']):
            raise CallStateConflict(call.id)
        if (row['http_status'] != http_status or row['error_code'] is not None or
                row['billing_status'] != 'charged' or
                row['billing_reason'] != call.rule.billing_policy_version or
                tuple(row[key] for key in ('input_tokens', 'output_tokens', 'truncated',
                                           'state_tokens_dropped')) != values or
                charge is None or charge['pricing_rule_id'] != call.rule.id or
                charge['billable_input_tokens'] != billable or
                charge['unit_tokens'] != call.rule.unit_tokens or
                Decimal(str(charge['unit_price_yuan'])) != call.rule.unit_price_yuan or
                charge['currency'] != call.rule.currency or
                Decimal(str(charge['amount_yuan'])) != billing.amount_yuan(billable, call.rule)):
            raise CallStateConflict(call.id)
        return Decimal(str(charge['amount_yuan']))
    _require_active(cur, call, row)
    previous = usage_values(row)
    if any(value is not None for value in previous) and previous != values:
        raise CallStateConflict(call.id)
    duration = receipt['duration_ms'] if receipt else _duration_ms(call)
    repository.settle(cur, call.id, dict(status='succeeded', http_status=http_status,
        duration_ms=duration, input_tokens=billable, output_tokens=output_tokens,
        truncated=truncated, state_tokens_dropped=dropped, billing_status='charged',
        billing_reason=call.rule.billing_policy_version),
        completed_at=receipt['completed_at'] if receipt else None)
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
    with session.unit_of_work() as cur:
        row = _locked_call(cur, call)
        if success_receipt(cur, call) is not None:
            raise CallStateConflict(call.id)
        if _same_terminal(cur, call, row, 'failed', error_code[:64], http_status,
                          billing_status, reason):
            return Decimal('0.000000')
        _require_active(cur, call, row)
        repository.settle(cur, call.id, dict(status='failed', http_status=http_status,
            error_code=error_code[:64], duration_ms=_duration_ms(call),
            billing_status=billing_status, billing_reason=reason))
    return Decimal("0.000000")


def interrupted(call: Call, error_code: str, http_status: int) -> Decimal:
    """运行前被撤销或运行被中止：写入可恢复终态，不产生费用。"""
    with session.unit_of_work() as cur:
        row = _locked_call(cur, call)
        if success_receipt(cur, call) is not None:
            raise CallStateConflict(call.id)
        if _same_terminal(cur, call, row, 'interrupted', error_code[:64], http_status,
                          'not_billable', error_code[:64]):
            return Decimal('0.000000')
        _require_active(cur, call, row)
        repository.settle(cur, call.id, dict(status='interrupted', http_status=http_status,
            error_code=error_code[:64], duration_ms=_duration_ms(call),
            billing_status='not_billable', billing_reason=error_code[:64]))
    return Decimal("0.000000")


def keep_usage(call: Call, usage: dict[str, Any]) -> None:
    """推理已产出用量但后续分支失败时保留已知用量，不默认写 0（设计 §7）。"""
    values = validate_usage(usage)
    with session.unit_of_work() as cur:
        row = _locked_call(cur, call)
        _require_active(cur, call, row)
        receipt = success_receipt(cur, call)
        if receipt is not None and usage_values(receipt) != values:
            raise CallStateConflict(call.id)
        previous = tuple(row[key] for key in ('input_tokens', 'output_tokens', 'truncated',
                                             'state_tokens_dropped'))
        if previous == values:
            return
        if any(value is not None for value in previous):
            raise CallStateConflict(call.id)
        repository.keep_usage(cur, call.id, values)


def _same_terminal(cur: Any, call: Call, row: dict[str, Any], status: str,
                   error_code: str, http_status: int, billing_status: str, reason: str) -> bool:
    if row['status'] != status:
        return False
    if (row['error_code'] != error_code or row['http_status'] != http_status or
            row['billing_status'] != billing_status or row['billing_reason'] != reason or
            _charge(cur, call) is not None):
        raise CallStateConflict(call.id)
    return True


def validate_usage(usage: dict[str, Any]) -> tuple[int, int | None, int | None, int | None]:
    if not isinstance(usage, dict):
        raise ValueError('invalid usage')
    values = []
    for key in ('input_tokens', 'output_tokens', 'state_tokens_dropped'):
        value = usage.get(key)
        if value is None and key != 'input_tokens':
            values.append(None)
        elif type(value) is int and 0 <= value <= 2**63 - 1:
            values.append(value)
        else:
            raise ValueError('invalid token count')
    truncated = usage.get('truncated')
    if truncated is not None and type(truncated) is not bool:
        raise ValueError('invalid truncation flag')
    return values[0], values[1], None if truncated is None else int(truncated), values[2]

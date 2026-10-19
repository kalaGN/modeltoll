"""Explicit recovery from trusted receipts; never call models or invent unknown usage."""
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from app.db import session
from app.services import billing, inference


def _rule(row: dict[str, Any]) -> billing.PricingRule:
    return billing.PricingRule(row['id'], row['version'], row['model'], row['currency'],
                               row['token_basis'], int(row['unit_tokens']),
                               Decimal(str(row['unit_price_yuan'])), row['billing_policy_version'])


def _receipt_values(receipt: dict[str, Any]) -> tuple:
    value = receipt['truncated']
    if value is not None and (type(value) is not int or value not in (0, 1)):
        raise ValueError('invalid persisted usage')
    if (receipt['completed_at'] is None or type(receipt['duration_ms']) is not int or
            receipt['duration_ms'] < 0):
        raise ValueError('invalid persisted completion')
    return inference.validate_usage({
        'input_tokens': receipt['input_tokens'], 'output_tokens': receipt['output_tokens'],
        'state_tokens_dropped': receipt['state_tokens_dropped'],
        'truncated': None if value is None else bool(value),
    })


def recover(call_id: str) -> Decimal:
    """Settle one known success using its original price and receipt completion time."""
    with session.transaction() as cur:
        cur.execute('SELECT id, user_id, api_key_id, endpoint, model, pricing_rule_id'
                    ' FROM api_calls WHERE id = %s FOR UPDATE', (call_id,))
        row = cur.fetchone()
        if row is None:
            raise inference.CallStateConflict(call_id)
        cur.execute('SELECT id, version, model, currency, token_basis, unit_tokens,'
                    ' unit_price_yuan, billing_policy_version FROM pricing_rules WHERE id = %s',
                    (row['pricing_rule_id'],))
        pricing = cur.fetchone()
        if pricing is None or pricing['billing_policy_version'] != 'succeeded_only_v1':
            raise inference.CallStateConflict(call_id)
        call = inference.Call(row['id'], row['user_id'], row['api_key_id'], row['endpoint'],
                              row['model'], _rule(pricing))
        if call.rule.model != call.model:
            raise inference.CallStateConflict(call_id)
        receipt = inference.success_receipt(cur, call)
        if receipt is None:
            raise inference.CallStateConflict(call_id)
        try:
            values = _receipt_values(receipt)
        except (TypeError, ValueError):
            raise inference.CallStateConflict(call_id) from None
        return inference.settle_success_in_transaction(cur, call, values)


def inspect_calls(limit: int = 100, call_id: str | None = None,
                  offset: int = 0) -> list[dict[str, Any]]:
    """Read-only bounded metadata inspection; no raw request, credential or response data."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError('offset must be between 0 and 1000000')
    with session.cursor() as cur:
        cur.execute(
            'SELECT c.id, c.status, c.http_status, c.error_code, c.billing_status,'
            ' c.billing_reason, c.input_tokens, c.output_tokens, c.truncated,'
            ' c.state_tokens_dropped, c.completed_at, c.duration_ms, c.started_at,'
            ' c.model, c.pricing_rule_id, r.call_id AS receipt_id,'
            ' r.input_tokens AS r_input, r.output_tokens AS r_output, r.truncated AS r_truncated,'
            ' r.state_tokens_dropped AS r_dropped, r.completed_at AS r_completed,'
            ' r.duration_ms AS r_duration, h.call_id AS charge_id, h.amount_yuan,'
            ' h.pricing_rule_id AS h_rule, h.billable_input_tokens AS h_input,'
            ' h.unit_tokens AS h_unit, h.unit_price_yuan AS h_price, h.currency AS h_currency,'
            ' p.unit_tokens AS p_unit, p.unit_price_yuan AS p_price, p.currency AS p_currency,'
            ' p.billing_policy_version AS p_policy, p.model AS p_model'
            ' FROM api_calls c LEFT JOIN inference_success_receipts r ON r.call_id = c.id'
            ' LEFT JOIN usage_charges h ON h.call_id = c.id'
            ' LEFT JOIN pricing_rules p ON p.id = c.pricing_rule_id'
            + (' WHERE c.id = %s' if call_id is not None else '')
            + ' ORDER BY c.started_at, c.id LIMIT %s OFFSET %s',
            (call_id, limit, offset) if call_id is not None else (limit, offset),
        )
        rows = cur.fetchall()
    return [{
        'call_id': row['id'], 'status': row['status'], 'billing_status': row['billing_status'],
        'classification': _classify(row), 'has_success_receipt': row['receipt_id'] is not None,
        'started_at': row['started_at'].isoformat(),
        'completed_at': None if row['completed_at'] is None else row['completed_at'].isoformat(),
        'input_tokens': row['input_tokens'],
        'amount_yuan': None if row['amount_yuan'] is None else str(row['amount_yuan']),
    } for row in rows]


def _classify(row: dict[str, Any]) -> str:
    if row['receipt_id'] is None or row['p_policy'] != 'succeeded_only_v1' or row['p_model'] != row['model']:
        return 'needs_review'
    receipt = dict(input_tokens=row['r_input'], output_tokens=row['r_output'],
                   truncated=row['r_truncated'], state_tokens_dropped=row['r_dropped'],
                   completed_at=row['r_completed'], duration_ms=row['r_duration'])
    try:
        values = _receipt_values(receipt)
        previous = inference.usage_values(row)
        if row['status'] in {'accepted', 'running'}:
            if (row['billing_status'] == 'pending' and row['charge_id'] is None and
                    (not any(v is not None for v in previous) or previous == values)):
                return 'pending'
        elif (row['status'] == 'succeeded' and row['http_status'] == 200 and
              row['error_code'] is None and row['billing_status'] == 'charged' and
              row['billing_reason'] == row['p_policy'] and previous == values and
              row['completed_at'] == row['r_completed'] and row['duration_ms'] == row['r_duration'] and
              row['charge_id'] is not None and row['h_rule'] == row['pricing_rule_id'] and
              row['h_input'] == values[0] and row['h_unit'] == row['p_unit'] and
              row['h_price'] == row['p_price'] and row['h_currency'] == row['p_currency']):
            expected = (Decimal(values[0]) * row['p_price'] / Decimal(row['p_unit'])).quantize(
                Decimal('.000001'), rounding=ROUND_HALF_UP)
            if Decimal(str(row['amount_yuan'])) == expected:
                return 'succeeded'
    except (TypeError, ValueError, ArithmeticError):
        pass
    return 'needs_review'

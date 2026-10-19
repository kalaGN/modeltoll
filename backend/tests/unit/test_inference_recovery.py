"""可信成功回执与显式恢复的服务回归；仅合成数据。"""
import inspect
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from app.db import session
from app.services import inference, inference_recovery, billing
from tests.support.inference import Cursor


class ReceiptCursor(Cursor):
    def __init__(self):
        super().__init__()
        self.row.update(id='call', user_id='user', api_key_id='key', endpoint='/predict',
                        model='model', completed_at=None, duration_ms=None)
        self.receipt = None
        self.fail_receipt = False
        self.pricing = dict(id='rule', version='v1', model='model', currency='CNY',
                            token_basis='input', unit_tokens=1000000,
                            unit_price_yuan=Decimal('1'), billing_policy_version='succeeded_only_v1')

    def execute(self, sql, args=()):
        if sql.startswith('SELECT') and 'FROM inference_success_receipts' in sql:
            self.result = deepcopy(self.receipt)
        elif sql.startswith('SELECT') and 'FROM pricing_rules' in sql:
            self.result = deepcopy(self.pricing)
        elif sql.startswith('INSERT INTO inference_success_receipts'):
            if self.fail_receipt:
                raise RuntimeError('synthetic receipt fault')
            self.writes.append(sql)
            self.receipt = dict(input_tokens=args[1], output_tokens=args[2], truncated=args[3],
                                state_tokens_dropped=args[4], completed_at=datetime(2026, 10, 10),
                                duration_ms=args[5])
        else:
            super().execute(sql, args)
            if sql.startswith('UPDATE') and "status = 'succeeded'" in sql:
                self.row.update(duration_ms=args[1], completed_at=args[7] if len(args) == 9 else None)


class SuccessReceiptTests(unittest.TestCase):
    def setUp(self):
        self.cur = ReceiptCursor()
        self.rule = billing.PricingRule('rule', 'v1', 'model', 'CNY', 'input',
                                       1000000, Decimal('1'), 'succeeded_only_v1')
        self.call = inference.Call('call', 'user', 'key', '/predict', 'model', self.rule)
        self.usage = {'input_tokens': 10, 'output_tokens': 2, 'truncated': False}

        @contextmanager
        def transaction():
            before = deepcopy((self.cur.row, self.cur.receipt, self.cur.charge))
            try:
                yield self.cur
            except BaseException:
                self.cur.row, self.cur.receipt, self.cur.charge = before
                raise

        self.addCleanup(patch.stopall)
        patch.object(session, 'transaction', transaction).start()
        patch.object(session, 'cursor', transaction).start()

        def insert(cur, call_id, rule, tokens):
            if cur.charge is not None:
                raise RuntimeError('duplicate charge')
            amount = billing.amount_yuan(tokens, rule)
            cur.charge = dict(pricing_rule_id=rule.id, billable_input_tokens=tokens,
                              unit_tokens=rule.unit_tokens, unit_price_yuan=rule.unit_price_yuan,
                              currency=rule.currency, amount_yuan=amount)
            return amount

        self.insert = patch.object(billing, 'insert_charge', side_effect=insert).start()

    def test_capture_is_immutable_and_contains_no_payload(self):
        inference.capture_success(self.call, self.usage)
        before = deepcopy(self.cur.receipt)
        writes = len(self.cur.writes)
        inference.capture_success(self.call, self.usage)
        self.assertEqual(self.cur.receipt, before)
        self.assertEqual(len(self.cur.writes), writes)
        with self.assertRaises(inference.CallStateConflict):
            inference.capture_success(self.call, {'input_tokens': 11})
        self.assertEqual(set(self.cur.receipt), {'input_tokens', 'output_tokens', 'truncated',
                                               'state_tokens_dropped', 'completed_at', 'duration_ms'})
        self.insert.assert_not_called()

    def test_invalid_capture_has_pending_failure_no_receipt(self):
        with self.assertRaises(inference.UsageUnavailable):
            inference.capture_success(self.call, {'input_tokens': True})
        self.assertEqual(self.cur.row['status'], 'failed')
        self.assertEqual(self.cur.row['billing_status'], 'pending')
        self.assertIsNone(self.cur.receipt)
        self.insert.assert_not_called()

    def test_receipt_failure_never_creates_charge(self):
        self.cur.fail_receipt = True
        with self.assertRaises(RuntimeError):
            inference.capture_success(self.call, self.usage)
        self.assertIsNone(self.cur.receipt)
        self.assertEqual(self.cur.row['status'], 'running')
        self.insert.assert_not_called()

    def test_settlement_failure_preserves_receipt_for_explicit_recovery(self):
        inference.capture_success(self.call, self.usage)
        original = self.insert.side_effect
        self.insert.side_effect = RuntimeError('synthetic charge fault')
        with self.assertRaises(RuntimeError):
            inference.succeeded(self.call, self.usage)
        self.assertEqual(self.cur.row['status'], 'running')
        self.assertIsNotNone(self.cur.receipt)
        self.insert.side_effect = original
        self.assertEqual(inference_recovery.recover('call'), Decimal('.000010'))
        self.assertEqual(self.cur.row['completed_at'], self.cur.receipt['completed_at'])
        self.assertEqual(self.cur.row['duration_ms'], self.cur.receipt['duration_ms'])
        writes = len(self.cur.writes)
        self.assertEqual(inference_recovery.recover('call'), Decimal('.000010'))
        self.assertEqual(len(self.cur.writes), writes)

    def test_recovery_and_normal_settlement_share_original_timing_and_charge(self):
        inference.capture_success(self.call, self.usage)
        inference_recovery.recover('call')
        writes = len(self.cur.writes)
        self.assertEqual(inference.succeeded(self.call, self.usage), Decimal('.000010'))
        self.assertEqual(len(self.cur.writes), writes)
        self.insert.assert_called_once()

    def test_receipt_prevents_terminal_failure_and_new_model_execution(self):
        inference.capture_success(self.call, self.usage)
        with self.assertRaises(inference.CallStateConflict):
            inference.keep_usage(self.call, {'input_tokens': 11})
        for action in [inference.failed, inference.interrupted]:
            with self.assertRaises(inference.CallStateConflict):
                action(self.call, 'crash', 500)
        self.cur.row['status'] = 'accepted'
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(self.call)

    def test_missing_receipt_failed_state_and_unknown_call_cannot_recover(self):
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')
        inference.capture_success(self.call, self.usage)
        self.cur.row['status'] = 'failed'
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')
        self.cur.row = None
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')
        self.insert.assert_not_called()

    def test_recovery_uses_original_rule_and_rejects_unknown_policy(self):
        inference.capture_success(self.call, self.usage)
        self.cur.pricing['unit_price_yuan'] = Decimal('2')
        self.assertEqual(inference_recovery.recover('call'), Decimal('.000020'))
        self.assertEqual(self.cur.charge['unit_price_yuan'], Decimal('2'))
        self.cur.pricing['billing_policy_version'] = 'unconfirmed'
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')

    def test_recovery_rejects_mismatched_usage_timing_and_charge(self):
        inference.capture_success(self.call, self.usage)
        inference.succeeded(self.call, self.usage)
        self.cur.row['duration_ms'] += 1
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')
        self.cur.row['duration_ms'] = self.cur.receipt['duration_ms']
        self.cur.receipt['input_tokens'] += 1
        with self.assertRaises(inference.CallStateConflict):
            inference_recovery.recover('call')


class InspectionTests(unittest.TestCase):
    def test_classification_requires_matching_receipt_original_price_and_fee(self):
        row = dict(status='running', http_status=None, error_code=None,
                   billing_status='pending', billing_reason=None, input_tokens=None,
                   output_tokens=None, truncated=None, state_tokens_dropped=None,
                   completed_at=None, duration_ms=None, receipt_id='call', charge_id=None,
                   model='model', pricing_rule_id='rule', p_policy='succeeded_only_v1',
                   p_model='model', p_unit=2, p_price=Decimal('.000001'), p_currency='CNY',
                   r_input=1, r_output=None, r_truncated=None, r_dropped=None,
                   r_completed=datetime(2026, 10, 10), r_duration=5)
        self.assertEqual(inference_recovery._classify(row), 'pending')
        row.update(status='succeeded', http_status=200, billing_status='charged',
                   billing_reason='succeeded_only_v1', input_tokens=1,
                   completed_at=row['r_completed'], duration_ms=5, charge_id='call',
                   h_rule='rule', h_input=1, h_unit=2, h_price=Decimal('.000001'),
                   h_currency='CNY', amount_yuan=Decimal('.000001'))
        # 0.5 micro-yuan must round HALF_UP, exactly as billing.amount_yuan.
        self.assertEqual(inference_recovery._classify(row), 'succeeded')
        row['amount_yuan'] = Decimal('0')
        self.assertEqual(inference_recovery._classify(row), 'needs_review')

    def test_inspection_serializes_real_datetime_and_is_read_only(self):
        from unittest.mock import Mock
        import json
        cur = Mock()
        cur.fetchall.return_value = [dict(
            id='call', status='running', billing_status='pending', receipt_id=None,
            started_at=datetime(2026, 10, 10, 1, 2, 3), completed_at=None,
            input_tokens=None, amount_yuan=None)]

        @contextmanager
        def cursor():
            yield cur

        with patch.object(session, 'cursor', cursor):
            result = inference_recovery.inspect_calls(offset=100)
        self.assertEqual(result[0]['started_at'], '2026-10-10T01:02:03')
        self.assertEqual(result[0]['classification'], 'needs_review')
        self.assertIsNone(result[0]['completed_at'])
        self.assertIn('needs_review', json.dumps(result))
        self.assertEqual(cur.execute.call_args.args[1], (100, 100))
        self.assertTrue(cur.execute.call_args.args[0].startswith('SELECT'))

    def test_inspection_limits_and_offset_are_strict(self):
        for limit in [True, 0, 101, '1']:
            with self.assertRaises(ValueError):
                inference_recovery.inspect_calls(limit=limit)
        for offset in [True, -1, 1000001, '1']:
            with self.assertRaises(ValueError):
                inference_recovery.inspect_calls(offset=offset)

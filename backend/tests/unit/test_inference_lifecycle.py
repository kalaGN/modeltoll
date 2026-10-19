"""调用生命周期回归：合成游标，不连接数据库或运行模型。"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch

from app.db import session
from app.services import billing, inference


from tests.support.inference import Cursor


class InferenceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cur = Cursor()
        self.rule = billing.PricingRule('rule', 'v1', 'model', 'CNY', 'input',
                                       1000000, Decimal('1'), 'succeeded_only_v1')
        self.call = inference.Call('call', 'user', 'key', '/predict', 'model', self.rule)

        @contextmanager
        def transaction():
            before = deepcopy((self.cur.row, self.cur.charge))
            try:
                yield self.cur
            except BaseException:
                self.cur.row, self.cur.charge = before
                raise

        self.addCleanup(patch.stopall)
        patch.object(session, 'unit_of_work', transaction).start()
        patch.object(session, 'read_session', transaction).start()

        def insert_charge(cur, call_id, rule, tokens):
            if cur.charge is not None:
                raise RuntimeError('duplicate charge')
            amount = billing.amount_yuan(tokens, rule)
            cur.charge = {'amount_yuan': amount, 'pricing_rule_id': rule.id,
                          'billable_input_tokens': tokens, 'unit_tokens': rule.unit_tokens,
                          'unit_price_yuan': rule.unit_price_yuan, 'currency': rule.currency}
            return amount

        self.insert = patch.object(billing, 'insert_charge', side_effect=insert_charge).start()

    def test_invalid_input_usage_is_pending_and_never_charged(self):
        for value in [None, True, False, 1.9, '10', -1, 2**63, float('nan')]:
            with self.subTest(value=value):
                self.cur = Cursor()
                with self.assertRaises(inference.UsageUnavailable):
                    inference.succeeded(self.call, {'input_tokens': value})
                self.assertEqual(self.cur.row['status'], 'failed')
                self.assertEqual(self.cur.row['billing_status'], 'pending')
        self.insert.assert_not_called()

    def test_invalid_optional_usage_is_pending(self):
        for field, values in [('output_tokens', [True, 1.5, '1', -1, 2**63]),
                              ('state_tokens_dropped', [False, 1.5, '1', -1, 2**63]),
                              ('truncated', [0, 1, 'false', [], {}])]:
            for value in values:
                with self.subTest(field=field, value=value):
                    self.cur = Cursor()
                    with self.assertRaises(inference.UsageUnavailable):
                        inference.succeeded(self.call, {'input_tokens': 1, field: value})
                    self.assertEqual(self.cur.row['billing_status'], 'pending')
        self.insert.assert_not_called()

    def test_zero_and_upper_bound_are_exact(self):
        for value in [0, 2**63 - 1]:
            self.cur = Cursor()
            amount = inference.succeeded(self.call, {'input_tokens': value, 'truncated': False})
            self.assertEqual(amount, billing.amount_yuan(value, self.rule))
            self.assertEqual(self.cur.row['input_tokens'], value)

    def test_duplicate_success_returns_saved_amount_without_writes(self):
        usage = {'input_tokens': 10, 'output_tokens': 2, 'truncated': True}
        amount = inference.succeeded(self.call, usage)
        writes = len(self.cur.writes)
        self.assertEqual(inference.succeeded(self.call, usage), amount)
        self.assertEqual(len(self.cur.writes), writes)
        self.insert.assert_called_once()

    def test_different_success_usage_conflicts_without_mutation(self):
        inference.succeeded(self.call, {'input_tokens': 10})
        before = deepcopy(self.cur.row)
        with self.assertRaises(inference.CallStateConflict):
            inference.succeeded(self.call, {'input_tokens': 11})
        self.assertEqual(self.cur.row, before)
        self.insert.assert_called_once()

    def test_failed_or_interrupted_cannot_overwrite_success(self):
        inference.succeeded(self.call, {'input_tokens': 10})
        before = deepcopy(self.cur.row)
        for action in [inference.failed, inference.interrupted]:
            with self.assertRaises(inference.CallStateConflict):
                action(self.call, 'crash', 500)
            self.assertEqual(self.cur.row, before)

    def test_terminal_failure_is_idempotent_but_other_terminal_conflicts(self):
        for action in [inference.failed, inference.interrupted]:
            self.cur = Cursor()
            self.assertEqual(action(self.call, 'crash', 500), Decimal('0'))
            writes = len(self.cur.writes)
            self.assertEqual(action(self.call, 'crash', 500), Decimal('0'))
            self.assertEqual(len(self.cur.writes), writes)
            with self.assertRaises(inference.CallStateConflict):
                action(self.call, 'other', 500)
            with self.assertRaises(inference.CallStateConflict):
                inference.succeeded(self.call, {'input_tokens': 1})

    def test_mark_running_requires_one_accepted_call(self):
        self.cur.row['status'] = 'accepted'
        inference.mark_running(self.call)
        self.assertEqual(self.cur.row['status'], 'running')
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(self.call)

    def test_mark_running_rejects_missing_terminal_and_accounting_conflicts(self):
        for state in ['running', 'succeeded', 'failed', 'interrupted', None]:
            self.cur = Cursor(state)
            if state is None:
                self.cur.row = None
            with self.assertRaises(inference.CallStateConflict):
                inference.mark_running(self.call)
            self.assertEqual(self.cur.writes, [])
        self.cur = Cursor('accepted')
        self.cur.charge = {'amount_yuan': Decimal('1')}
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(self.call)
        self.assertEqual(self.cur.writes, [])
        self.cur.charge = None
        self.cur.row['billing_status'] = 'charged'
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(self.call)
        self.assertEqual(self.cur.writes, [])

    def test_mark_running_checks_update_rowcount_even_after_lock(self):
        self.cur = Cursor('accepted')
        original = self.cur.execute

        def zero_update(sql, args=()):
            original(sql, args)
            if getattr(sql, 'is_update', False):
                self.cur.rowcount = 0
            return self.cur

        self.cur.execute = zero_update
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(self.call)
        self.assertEqual(self.cur.row['status'], 'accepted')

    def test_missing_call_rejected(self):
        self.cur.row = None
        with self.assertRaises(inference.CallStateConflict):
            inference.succeeded(self.call, {'input_tokens': 1})
        self.insert.assert_not_called()

    def test_charge_failure_rolls_back_terminal_state(self):
        self.insert.side_effect = RuntimeError('synthetic billing fault')
        with self.assertRaises(RuntimeError):
            inference.succeeded(self.call, {'input_tokens': 1})
        self.assertEqual(self.cur.row['status'], 'running')
        self.assertIsNone(self.cur.row['input_tokens'])

    def test_success_with_missing_or_inconsistent_charge_conflicts(self):
        usage = {'input_tokens': 10}
        inference.succeeded(self.call, usage)
        correct = deepcopy(self.cur.charge)
        wrong_values = {'pricing_rule_id': 'other', 'billable_input_tokens': 11,
                        'unit_tokens': 1, 'unit_price_yuan': Decimal('2'),
                        'currency': 'USD', 'amount_yuan': Decimal('3')}
        for field, value in wrong_values.items():
            with self.subTest(field=field):
                self.cur.charge = {**correct, field: value}
                writes = len(self.cur.writes)
                with self.assertRaises(inference.CallStateConflict):
                    inference.succeeded(self.call, usage)
                self.assertEqual(len(self.cur.writes), writes)
        self.cur.charge = None
        with self.assertRaises(inference.CallStateConflict):
            inference.succeeded(self.call, usage)
        self.insert.assert_called_once()

    def test_active_call_with_existing_charge_rejects_every_terminal_write(self):
        self.cur.charge = {'amount_yuan': Decimal('1')}
        for action, args in [(inference.succeeded, ({'input_tokens': 1},)),
                             (inference.failed, ('error', 500)),
                             (inference.interrupted, ('error', 500))]:
            with self.assertRaises(inference.CallStateConflict):
                action(self.call, *args)
        self.assertEqual(self.cur.writes, [])
        self.insert.assert_not_called()

    def test_pricing_snapshot_mismatch_rejects_terminal_write(self):
        self.cur.row['pricing_rule_id'] = 'other'
        with self.assertRaises(inference.CallStateConflict):
            inference.succeeded(self.call, {'input_tokens': 1})
        self.insert.assert_not_called()

    def test_usage_object_shape_is_rejected_without_charging(self):
        for usage in [None, [], 'usage', {}]:
            self.cur = Cursor()
            with self.assertRaises(inference.UsageUnavailable):
                inference.succeeded(self.call, usage)
            self.assertEqual(self.cur.row['billing_status'], 'pending')
        self.insert.assert_not_called()

    def test_keep_usage_is_strict_idempotent_and_does_not_mutate_terminal(self):
        usage = {'input_tokens': 10, 'output_tokens': 2}
        inference.keep_usage(self.call, usage)
        self.assertEqual(self.cur.row['input_tokens'], 10)
        writes = len(self.cur.writes)
        inference.keep_usage(self.call, usage)
        self.assertEqual(len(self.cur.writes), writes)

        with self.assertRaises(inference.CallStateConflict):
            inference.keep_usage(self.call, {'input_tokens': 11})
        with self.assertRaises(ValueError):
            inference.keep_usage(self.call, {'input_tokens': True})
        inference.succeeded(self.call, usage)
        writes = len(self.cur.writes)
        with self.assertRaises(inference.CallStateConflict):
            inference.keep_usage(self.call, usage)
        self.assertEqual(len(self.cur.writes), writes)

    def test_success_cannot_overwrite_saved_usage(self):
        inference.keep_usage(self.call, {'input_tokens': 10, 'output_tokens': 2})
        before = deepcopy(self.cur.row)
        with self.assertRaises(inference.CallStateConflict):
            inference.succeeded(self.call, {'input_tokens': 11, 'output_tokens': 2})
        self.assertEqual(self.cur.row, before)
        self.insert.assert_not_called()

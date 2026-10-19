"""MySQL statement compilation for metering repositories, without a server."""
import unittest
from decimal import Decimal
from unittest.mock import Mock
from sqlalchemy.dialects import mysql
from app.repositories import calls, billing


def compiled(statement):
    return statement.compile(dialect=mysql.dialect())


class MeteringSQLTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.execute.return_value.mappings.return_value.first.return_value = None
        self.db.execute.return_value.mappings.return_value.all.return_value = []

    def statement(self):
        return self.db.execute.call_args.args[0]

    def test_price_effective_utc_latest_and_decimal_charge(self):
        billing.current_rule(self.db, 'model')
        sql = str(compiled(self.statement()))
        self.assertIn('effective_from <= utc_timestamp(', sql)
        self.assertIn('ORDER BY pricing_rules.effective_from DESC', sql)
        self.assertEqual(self.statement()._limit_clause.value, 1)
        values = dict(id='charge', call_id='call', pricing_rule_id='rule', billable_input_tokens=2,
            unit_tokens=1000000, unit_price_yuan=Decimal('1.000000'), amount_yuan=Decimal('.000002'), currency='CNY')
        billing.insert_charge(self.db, values)
        result = compiled(self.statement())
        self.assertEqual(result.params['amount_yuan'], Decimal('.000002'))
        self.assertIn('utc_timestamp(', str(result))

    def test_lock_and_conditional_running_update(self):
        calls.lock_call(self.db, 'call')
        self.assertIn('WHERE api_calls.id = %s FOR UPDATE', str(compiled(self.statement())))
        calls.mark_running(self.db, 'call')
        result = compiled(self.statement())
        self.assertIn('api_calls.status = %s', str(result))
        self.assertEqual(result.params['status_1'], 'accepted')

    def test_accept_parent_key_then_call_then_user_scoped_reservation(self):
        calls.accept(self.db, dict(id='call', user_id='user', api_key_id='key', endpoint='/predict',
            model='model', pricing_rule_id='rule'))
        calls.reserve(self.db, 'user', 'hash', 'digest', 'call')
        sql = [str(compiled(call.args[0])) for call in self.db.execute.call_args_list]
        self.assertTrue(sql[0].startswith('UPDATE api_keys'))
        self.assertTrue(sql[1].startswith('INSERT INTO api_calls'))
        self.assertTrue(sql[2].startswith('INSERT INTO request_idempotency'))
        calls.reservation(self.db, 'user', 'hash')
        result = compiled(self.statement())
        self.assertIn('request_idempotency.user_id = %s', str(result))
        self.assertEqual(result.params['user_id_1'], 'user')
        self.assertEqual(result.params['key_hash_1'], 'hash')

    def test_receipt_contains_only_metadata_and_inspection_join_is_explicit(self):
        calls.capture_success(self.db, 'call', (2, 1, 0, None), 10)
        result = compiled(self.statement())
        self.assertIn('inference_success_receipts', str(result))
        self.assertEqual(set(result.params), {'call_id', 'input_tokens', 'output_tokens', 'truncated',
            'state_tokens_dropped', 'duration_ms', 'utc_timestamp_1'})
        calls.inspect_calls(self.db, 10, 'call', 20)
        result = compiled(self.statement())
        self.assertEqual(str(result).count('LEFT OUTER JOIN'), 3)
        self.assertIn('WHERE api_calls.id = %s', str(result))
        self.assertIn('ORDER BY api_calls.started_at, api_calls.id', str(result))
        self.assertEqual(self.statement()._limit_clause.value, 10)
        self.assertEqual(self.statement()._offset_clause.value, 20)

    def test_settlement_retains_original_completion_and_usage_write_guard(self):
        from datetime import datetime
        completion = datetime(2026, 10, 10)
        calls.settle(self.db, 'call', dict(status='succeeded'), completed_at=completion)
        self.assertEqual(compiled(self.statement()).params['completed_at'], completion)
        calls.keep_usage(self.db, 'call', (1, None, None, None))
        self.assertIn('api_calls.input_tokens IS NULL', str(compiled(self.statement())))

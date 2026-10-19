import datetime
from contextlib import contextmanager
from decimal import Decimal
import unittest
from unittest.mock import Mock, patch

from sqlalchemy.dialects import mysql
from sqlalchemy.sql.sqltypes import Integer

from app.repositories import statistics as repository
from app.services import admin_overview, statistics


class StatisticsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.execute.return_value.mappings.return_value.__iter__ = Mock(return_value=iter([]))
        self.db.execute.return_value.mappings.return_value.one.return_value = {}
        self.start = datetime.datetime(2026, 10, 1)
        self.end = datetime.datetime(2026, 11, 1)
        self.args = ('tenant', self.start, self.end, 'key', '/v1/predict')

    def statements(self):
        return [call.args[0].compile(dialect=mysql.dialect()) for call in self.db.execute.call_args_list]

    def assert_tenant_filters(self):
        for statement in self.statements():
            sql = str(statement)
            self.assertIn('api_calls.user_id =', sql)
            self.assertIn('api_calls.started_at >=', sql)
            self.assertIn('api_calls.started_at <', sql)
            self.assertIn('api_calls.api_key_id =', sql)
            self.assertIn('api_calls.endpoint =', sql)
            self.assertIn('tenant', statement.params.values())
            self.assertIn(self.start, statement.params.values())
            self.assertIn(self.end, statement.params.values())
            self.assertIn('key', statement.params.values())
            self.assertIn('/v1/predict', statement.params.values())

    def test_summary_all_queries_are_tenant_scoped(self):
        repository.usage_summary(self.db, *self.args)
        self.assertEqual(self.db.execute.call_count, 3)
        self.assert_tenant_filters()
        self.assertIsInstance(repository._count_status('succeeded').type, Integer)
        self.assertIn('CASE WHEN', str(self.statements()[0]))
        self.assertIn('usage_charges.call_id', str(self.statements()[1]))

    def test_billing_summary_scope(self):
        repository.billing_summary(self.db, *self.args)
        self.assert_tenant_filters()

    def test_both_pages_preserve_keyset_order_and_limit(self):
        after = (datetime.datetime(2026, 10, 10), 'call')
        for method in (repository.usage_calls, repository.billing_charges):
            with self.subTest(method=method.__name__):
                self.db.reset_mock()
                method(self.db, *self.args, after, 11)
                self.assert_tenant_filters()
                statement, = self.statements()
                sql = str(statement)
                self.assertIn('(api_calls.started_at, api_calls.id) <', sql)
                self.assertIn('ORDER BY api_calls.started_at DESC, api_calls.id DESC', sql)
                self.assertIn(11, statement.params.values())
                self.assertIn(after[0], statement.params.values())
                self.assertIn(after[1], statement.params.values())

    def test_daily_series_preserves_zero_charge_calls(self):
        repository.daily_series(self.db, *self.args)
        self.assert_tenant_filters()
        sql = str(self.statements()[0])
        self.assertIn('LEFT OUTER JOIN usage_charges', sql)
        self.assertIn('GROUP BY date(api_calls.started_at)', sql)

    def test_admin_queries_remain_independent(self):
        repository.platform_overview(self.db, self.start, self.end)
        statements = self.statements()
        self.assertEqual(len(statements), 3)
        self.assertIn('FROM users', str(statements[0]))
        self.assertIn('api_keys.revoked_at IS NULL', str(statements[1]))
        self.assertIn('api_keys.deleted_at IS NULL', str(statements[1]))
        self.assertIn('users.status =', str(statements[1]))
        self.assertNotIn('api_calls.user_id =', str(statements[2]))
        self.assertIn(self.start, statements[2].params.values())
        self.assertIn(self.end, statements[2].params.values())


class StatisticsProjectionTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime.datetime(2026, 10, 1)
        self.end = datetime.datetime(2026, 11, 1)
        self.db = object()

    @contextmanager
    def read_session(self):
        yield self.db

    def test_summary_retains_large_counts_and_decimal_text(self):
        calls = dict(total=12, succeeded=8, failed=3, in_progress=1, input_tokens=100, output_tokens=2)
        charged = dict(billable_tokens=97, amount=Decimal('0.000097'))
        with patch.object(statistics.session, 'read_session', self.read_session), \
                patch.object(repository, 'usage_summary', return_value=(calls, charged, {'pending': 4})):
            result = statistics.usage_summary('tenant', self.start, self.end)
        self.assertEqual(result['calls_succeeded'], 8)
        self.assertEqual(result['calls_failed'], 3)
        self.assertEqual(result['charged_amount_yuan'], '0.000097')
        self.assertEqual(result['billing_pending_count'], 4)

    def test_admin_summary_decimal_and_utc(self):
        rows = [{'day': self.start.date(), 'calls': 3, 'amount': Decimal('0.000123')}]
        with patch.object(admin_overview.session, 'read_session', self.read_session), \
                patch.object(repository, 'platform_overview', return_value=(7, 5, rows)):
            result = admin_overview.overview(self.start, self.end)
        self.assertEqual(result['totals']['amount_yuan'], '0.000123')
        self.assertEqual(result['totals']['calls'], 3)
        self.assertEqual(result['range']['from'], '2026-10-01T00:00:00Z')

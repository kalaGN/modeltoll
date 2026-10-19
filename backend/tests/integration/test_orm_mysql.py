"""Opt-in disposable mysqld tests: reviewed DDL, real row locks and rollback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.core import config
from app.db import migrations, session
from app.db.engine import get_engine
from app.models import Base, User, ApiCall, UsageCharge, InferenceSuccessReceipt
from app.services.access import accounts, api_keys, admin_management, bootstrap
from app.services.platform import admin_overview
from app.services.inference import lifecycle as inference, recovery as inference_recovery, request_limits
from app.services.metering import statistics
from tests.support.mysql_sandbox import mysql_sandbox


@unittest.skipUnless(os.environ.get('LAYA_TEST_ORM_MYSQL') == '1',
                     'set LAYA_TEST_ORM_MYSQL=1 to start a disposable local mysqld')
class OrmMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = mysql_sandbox()
        cls.sandbox.__enter__()
        cls.addClassCleanup(cls.sandbox.__exit__, None, None, None)
        migrations.init_db()
        migrations.init_db()

    def new_user(self):
        import uuid
        return accounts.register_user(uuid.uuid4().hex + '@example.invalid', 'synthetic-password')

    def principal(self, user):
        key, secret = api_keys.create(user.id, 'synthetic')
        return key, api_keys.authenticate('Bearer ' + secret)

    def test_01_reflected_schema_matches_all_models(self):
        inspector = inspect(get_engine())
        self.assertEqual(set(inspector.get_table_names()), set(Base.metadata.tables))
        for name, table in Base.metadata.tables.items():
            with self.subTest(table=name):
                actual = {column['name']: column for column in inspector.get_columns(name)}
                self.assertEqual(set(actual), set(table.columns.keys()))
                for column in table.columns:
                    reflected = actual[column.name]
                    self.assertEqual(reflected['nullable'], column.nullable, column.name)
                    # Display widths are not part of modern MySQL integer metadata.
                    for attr in ('unsigned', 'precision', 'scale', 'fsp', 'length', 'collation'):
                        expected = getattr(column.type, attr, None)
                        if expected is not None:
                            self.assertEqual(getattr(reflected['type'], attr, None), expected,
                                             f'{name}.{column.name}.{attr}')
                    self.assertEqual(reflected['type'].__class__, column.type.__class__, column.name)
                self.assertEqual(inspector.get_pk_constraint(name)['constrained_columns'],
                                 [column.name for column in table.primary_key])
                actual_fks = {(fk['name'], tuple(fk['constrained_columns']), fk['referred_table'],
                               tuple(fk['referred_columns'])) for fk in inspector.get_foreign_keys(name)}
                expected_fks = {(fk.name, tuple(element.parent.name for element in fk.elements),
                                 fk.referred_table.name, tuple(element.column.name for element in fk.elements))
                                for fk in table.foreign_key_constraints}
                self.assertEqual(actual_fks, expected_fks)
                self.assertEqual({c['name'] for c in inspector.get_check_constraints(name)},
                                 {c.name for c in table.constraints if c.__class__.__name__ == 'CheckConstraint'})
                reflected_indexes = {i['name']: tuple(i['column_names']) for i in inspector.get_indexes(name)}
                for index in table.indexes:
                    self.assertEqual(reflected_indexes[index.name], tuple(c.name for c in index.columns))
                for constraint in table.constraints:
                    if constraint.__class__.__name__ == 'UniqueConstraint':
                        self.assertEqual(reflected_indexes[constraint.name], tuple(c.name for c in constraint.columns))

    def test_02_bootstrap_concurrency_and_pinned_connection(self):
        def initialize(_):
            return bootstrap.init_admin('admin@example.invalid', 'synthetic-password')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(initialize, range(2)))
        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(results[0].id, results[1].id)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.init_admin('other-admin@example.invalid', 'synthetic-password')
        with session.pinned_session() as db:
            before = db.scalar(text('SELECT CONNECTION_ID()'))
            db.scalar(text("SELECT GET_LOCK('orm-fixture-pinned', 0)"))
            db.rollback()
            with db.begin():
                self.assertEqual(db.scalar(text('SELECT CONNECTION_ID()')), before)
                self.assertEqual(db.scalar(text("SELECT IS_USED_LOCK('orm-fixture-pinned')")), before)
            self.assertEqual(db.scalar(text("SELECT RELEASE_LOCK('orm-fixture-pinned')")), 1)

    def test_03_idempotency_receipt_recovery_and_charge_rollback(self):
        user = self.new_user()
        key, principal = self.principal(user)
        def accept(_):
            try:
                return inference.begin('/v1/predict', principal, 'multilingual',
                                       idempotency=('a' * 64, 'b' * 64))
            except inference.IdempotencyConflict as error:
                return error
        with ThreadPoolExecutor(max_workers=6) as pool:
            accepted = list(pool.map(accept, range(6)))
        calls = [value for value in accepted if isinstance(value, inference.Call)]
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertTrue(all(value.call_id == call.id for value in accepted if not isinstance(value, inference.Call)))
        inference.mark_running(call)
        with self.assertRaises(inference.CallStateConflict):
            inference.mark_running(call)
        inference.capture_success(call, {'input_tokens': 100, 'output_tokens': 2, 'truncated': False})
        with get_engine().begin() as db:
            db.exec_driver_sql("CREATE TRIGGER fixture_charge_failure BEFORE INSERT ON usage_charges "
                               "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'")
        try:
            with self.assertRaises(DBAPIError):
                inference.succeeded(call, {'input_tokens': 100, 'output_tokens': 2, 'truncated': False})
        finally:
            with get_engine().begin() as db:
                db.exec_driver_sql('DROP TRIGGER fixture_charge_failure')
        with session.read_session() as db:
            self.assertEqual(db.scalar(select(ApiCall.status).where(ApiCall.id == call.id)), 'running')
            self.assertIsNotNone(db.scalar(select(InferenceSuccessReceipt.call_id).where(InferenceSuccessReceipt.call_id == call.id)))
            self.assertIsNone(db.scalar(select(UsageCharge.id).where(UsageCharge.call_id == call.id)))
        with ThreadPoolExecutor(max_workers=6) as pool:
            amounts = list(pool.map(lambda _: inference_recovery.recover(call.id), range(6)))
        self.assertEqual(amounts, [Decimal('0.000100')] * 6)
        self.assertEqual(inference_recovery.inspect_calls(call_id=call.id)[0]['classification'], 'succeeded')
        with session.read_session() as db:
            self.assertEqual(len(db.scalars(select(UsageCharge.id).where(UsageCharge.call_id == call.id)).all()), 1)
        # Matched-row count must not turn repeated revoke/delete into new changes.
        api_keys.revoke(user.id, key.id)
        api_keys.revoke(user.id, key.id)
        api_keys.delete(user.id, key.id)
        api_keys.delete(user.id, key.id)
        self.assertEqual(api_keys.list_for_user(user.id), [])

    def test_04_admin_audit_rollback_and_login_recheck(self):
        user = self.new_user()
        with session.read_session() as db:
            admin_id = db.scalar(select(User.id).where(User.is_admin == 1))
        with get_engine().begin() as db:
            db.exec_driver_sql("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON admin_audit_events "
                               "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'")
        try:
            with self.assertRaises(DBAPIError):
                admin_management.set_user_status(admin_id, user.id, 'disabled', 'synthetic')
        finally:
            with get_engine().begin() as db:
                db.exec_driver_sql('DROP TRIGGER fixture_audit_failure')
        with session.read_session() as db:
            self.assertEqual(db.scalar(select(User.status).where(User.id == user.id)), 'active')
        real_verify = accounts.security.verify_password
        def disable_after_password_check(password, encoded):
            valid = real_verify(password, encoded)
            admin_management.set_user_status(admin_id, user.id, 'disabled', 'synthetic race')
            return valid
        with patch.object(accounts.security, 'verify_password', side_effect=disable_after_password_check):
            with self.assertRaises(accounts.DisabledAccount):
                accounts.login(user.email, 'synthetic-password', 'fixture')

    def test_05_real_rpm_parallel_and_statistics(self):
        user = self.new_user()
        def reserve(_):
            try:
                request_limits._reserve_rpm(user.id, 3)
                return True
            except request_limits.RateLimitError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(outcomes), 3)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start, end = now - timedelta(days=1), now + timedelta(days=1)
        overview = admin_overview.overview(start, end)
        self.assertGreaterEqual(overview['totals']['users'], 4)
        # Unrelated users cannot see the charged inference from test_03.
        result = statistics.usage_summary(user.id, start, end)
        self.assertEqual(result['calls_total'], 0)

    def test_06_original_gateway_transaction_and_login_throttle(self):
        from tests.integration.test_gateway_mysql import MySQLGatewayTests
        MySQLGatewayTests('test_connection_pricing_call_and_charge_roll_back').test_connection_pricing_call_and_charge_roll_back()
        user = self.new_user()
        for _ in range(config.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(accounts.InvalidCredentials):
                accounts.login(user.email, 'wrong-synthetic-password', 'fixture')
        with self.assertRaises(accounts.AccountLocked):
            accounts.login(user.email, 'synthetic-password', 'fixture')


@unittest.skipUnless(os.environ.get('LAYA_TEST_ORM_MYSQL') == '1',
                     'set LAYA_TEST_ORM_MYSQL=1 to start disposable local mysqld instances')
class ExistingScenarioMySQLTests(unittest.TestCase):
    def test_original_recovery_scenario(self):
        from tests.integration.test_recovery_mysql import _SCENARIO
        with mysql_sandbox():
            exec(compile(_SCENARIO, '<isolated-recovery-scenario>', 'exec'), {})

    def test_original_rate_limits_scenario(self):
        from tests.integration.test_request_limits_mysql import _CLOCKED_DB, _MYSQL_CHECK
        code = '_CLOCK_SOURCE = ' + repr(_CLOCKED_DB) + '\n' + _CLOCKED_DB + _MYSQL_CHECK
        with mysql_sandbox():
            exec(compile(code, '<isolated-rpm-scenario>', 'exec'), {})

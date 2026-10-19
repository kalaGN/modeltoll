"""Request digests and atomic reservation; fake transactions, no database access."""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch
from pymysql.err import IntegrityError as DriverIntegrityError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import mysql
from app.db import session
from app.services.access import api_keys
from app.services.metering import billing
from app.services.inference import idempotency, lifecycle as inference


class IdempotencyPreparationTests(unittest.TestCase):
    def test_missing_header_is_disabled_and_header_is_strict(self):
        self.assertIsNone(idempotency.prepare(None, '/predict', 'm', {}))
        for key in ['', ' ', 'has space', '中文', '\n', '\x7f', 'x' * 129, True]:
            with self.subTest(key=key), self.assertRaises(idempotency.InvalidIdempotencyKey):
                idempotency.prepare(key, '/predict', 'm', {})
        self.assertEqual(len(idempotency.prepare('x' * 128, '/predict', 'm', {})[0]), 64)

    def test_canonical_json_and_endpoint_model_scope(self):
        first = idempotency.prepare('private-key', '/predict', 'm', {'a': 1, 'b': {'z': '合成'}})
        second = idempotency.prepare('private-key', '/predict', 'm', {'b': {'z': '合成'}, 'a': 1})
        self.assertEqual(first, second)
        self.assertNotIn('private-key', repr(first))
        self.assertNotIn('合成', repr(first))
        for endpoint, model, body in [('/chat', 'm', {'a': 1}), ('/predict', 'other', {'a': 1}),
                                      ('/predict', 'm', {'a': 2})]:
            self.assertNotEqual(idempotency.prepare('private-key', endpoint, model, body)[1], first[1])


class AdmissionCursor:
    def __init__(self):
        self.calls = {}
        self.reservations = {}
        self.key_updates = []
        self.sql = []
        self.result = None

    def execute(self, statement, args=()):
        compiled = statement.compile(dialect=mysql.dialect())
        sql, values = str(compiled), compiled.params
        self.sql.append(sql)
        if sql.startswith('UPDATE api_keys'):
            self.key_updates.append(values['id_1'])
        elif sql.startswith('INSERT INTO api_calls'):
            self.calls[values['id']] = values
        elif sql.startswith('INSERT INTO request_idempotency'):
            user, key = values['user_id'], values['key_hash']
            if (user, key) in self.reservations:
                raise IntegrityError(sql, values, DriverIntegrityError(1062, 'synthetic duplicate reservation'))
            self.reservations[(user, key)] = dict(call_id=values['call_id'], request_hash=values['request_hash'])
        elif statement.is_select:
            self.result = self.reservations.get((values['user_id_1'], values['key_hash_1']))
        return self

    def mappings(self):
        return self

    def first(self):
        return self.result


class IdempotencyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cur = AdmissionCursor()
        rule = billing.PricingRule('rule', 'v1', 'model', 'CNY', 'input', 1000000,
                                   Decimal('1'), 'succeeded_only_v1')
        self.principal = api_keys.Principal('user', 'key', 'masked')
        self.digest = idempotency.prepare('private-key', '/predict', 'model', {'a': 1})

        @contextmanager
        def transaction():
            before = deepcopy((self.cur.calls, self.cur.reservations, self.cur.key_updates))
            try:
                yield self.cur
            except BaseException:
                self.cur.calls, self.cur.reservations, self.cur.key_updates = before
                raise

        self.addCleanup(patch.stopall)
        patch.object(session, 'unit_of_work', transaction).start()
        patch.object(session, 'read_session', transaction).start()
        patch.object(billing, 'current_rule', return_value=rule).start()

    def test_duplicate_returns_original_id_and_rolls_back_new_call_and_key_update(self):
        first = inference.begin('/predict', self.principal, 'model', idempotency=self.digest)
        with self.assertRaises(inference.IdempotencyConflict) as error:
            inference.begin('/predict', self.principal, 'model', idempotency=self.digest)
        self.assertEqual(error.exception.code, 'request_already_processed')
        self.assertEqual(error.exception.call_id, first.id)
        self.assertEqual(len(self.cur.calls), 1)
        self.assertEqual(len(self.cur.reservations), 1)
        self.assertEqual(self.cur.key_updates, ['key'])
        self.assertTrue(self.cur.sql[0].startswith('UPDATE api_keys'))

    def test_same_key_different_payload_conflicts(self):
        first = inference.begin('/predict', self.principal, 'model', idempotency=self.digest)
        other = idempotency.prepare('private-key', '/predict', 'model', {'a': 2})
        with self.assertRaises(inference.IdempotencyConflict) as error:
            inference.begin('/predict', self.principal, 'model', idempotency=other)
        self.assertEqual(error.exception.code, 'idempotency_conflict')
        self.assertEqual(error.exception.call_id, first.id)
        self.assertEqual(len(self.cur.calls), 1)

    def test_same_user_keys_share_reservation_but_other_users_do_not(self):
        first = inference.begin('/predict', self.principal, 'model', idempotency=self.digest)
        other_key = api_keys.Principal('user', 'other-key', 'masked')
        with self.assertRaises(inference.IdempotencyConflict) as error:
            inference.begin('/predict', other_key, 'model', idempotency=self.digest)
        self.assertEqual(error.exception.call_id, first.id)
        other_user = api_keys.Principal('other-user', 'other-key', 'masked')
        second = inference.begin('/predict', other_user, 'model', idempotency=self.digest)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.cur.calls), 2)

    def test_no_header_preserves_independent_calls_and_no_reservation(self):
        one = inference.begin('/predict', self.principal, 'model')
        two = inference.begin('/predict', self.principal, 'model')
        self.assertNotEqual(one.id, two.id)
        self.assertEqual(len(self.cur.calls), 2)
        self.assertEqual(self.cur.reservations, {})

    def test_non_duplicate_database_error_is_not_misclassified(self):
        with patch.object(self.cur, 'execute', side_effect=IntegrityError(None, None, DriverIntegrityError(1452, 'synthetic FK fault'))):
            with self.assertRaises(IntegrityError):
                inference.begin('/predict', self.principal, 'model', idempotency=self.digest)
        self.assertEqual(self.cur.calls, {})

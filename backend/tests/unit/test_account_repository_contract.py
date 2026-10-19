"""MySQL SQL shape and account/Key security policy without a database."""

import datetime
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from sqlalchemy.dialects import mysql

from app.repositories import accounts as repository, api_keys as key_repository
from app.services import accounts


class AccountRepositoryContractTests(unittest.TestCase):
    def test_credentials_recheck_is_locked_projection_not_identity_map(self):
        db = Mock()
        db.execute.return_value.mappings.return_value.first.return_value = {
            'id': 'user', 'password_hash': 'new-hash', 'status': 'disabled'}
        row = repository.lock_credentials(db, 'user')
        statement = db.execute.call_args.args[0].compile(dialect=mysql.dialect())
        self.assertIn('FOR UPDATE', str(statement))
        self.assertIn('users.password_hash', str(statement))
        self.assertIn('users.status', str(statement))
        self.assertEqual(statement.params, {'id_1': 'user'})
        self.assertEqual(row['status'], 'disabled')
        self.assertIs(type(row), dict)

    def test_throttle_upsert_retains_assignment_order_and_threshold(self):
        db = Mock()
        now = datetime.datetime(2026, 10, 19)
        repository.record_failure(db, 'email|source', now, 900, 5, now + datetime.timedelta(minutes=15))
        statement = db.execute.call_args.args[0].compile(dialect=mysql.dialect())
        sql = str(statement)
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        updates = sql.split('ON DUPLICATE KEY UPDATE', 1)[1]
        self.assertLess(updates.index('locked_until ='), updates.index('failed_count ='))
        self.assertLess(updates.index('failed_count ='), updates.index('first_failed_at ='))
        self.assertIn('timestampdiff(SECOND', updates)
        self.assertIn(900, statement.params.values())
        self.assertIn(5, statement.params.values())

    def test_current_session_requires_unrevoked_unexpired_active_account(self):
        db = Mock()
        db.execute.return_value.mappings.return_value.first.return_value = None
        self.assertIsNone(repository.current_user(db, 'hash'))
        statement = db.execute.call_args.args[0].compile(dialect=mysql.dialect())
        sql = str(statement)
        self.assertIn('user_sessions.revoked_at IS NULL', sql)
        self.assertIn('user_sessions.expires_at > utc_timestamp', sql)
        self.assertIn('users.status =', sql)
        self.assertIn('active', statement.params.values())
        self.assertNotIn('password_hash', sql)

    def test_key_revoke_condition_excludes_already_revoked_deleted_other_owner(self):
        db = Mock()
        db.execute.return_value.rowcount = 0
        self.assertEqual(key_repository.revoke(db, 'owner', 'key'), 0)
        statement = db.execute.call_args.args[0].compile(dialect=mysql.dialect())
        sql = str(statement)
        self.assertIn('api_keys.user_id =', sql)
        self.assertIn('api_keys.revoked_at IS NULL', sql)
        self.assertIn('api_keys.deleted_at IS NULL', sql)
        self.assertEqual(statement.params['user_id_1'], 'owner')


class LoginCredentialRaceTests(unittest.TestCase):
    def test_registration_hashes_before_opening_write_transaction(self):
        events = []
        db = Mock()

        @contextmanager
        def scope():
            events.append('transaction')
            yield db

        def hash_password(password):
            events.append('hash')
            return 'synthetic-hash'

        with patch.object(accounts.session, 'unit_of_work', scope), \
             patch.object(accounts.repository, 'create_user') as create, \
             patch.object(accounts.security, 'hash_password', side_effect=hash_password), \
             patch.object(accounts, '_fetch_user', return_value=accounts.User('user', 'user@example.invalid')):
            accounts.register_user('user@example.invalid', 'synthetic-password')
        self.assertEqual(events, ['hash', 'transaction'])
        self.assertEqual(create.call_args.args[-1], 'synthetic-hash')

    def test_changed_password_or_deleted_user_cannot_issue_session(self):
        original = {'id': 'user', 'email': 'user@example.invalid',
                    'password_hash': 'old-hash', 'status': 'active'}
        db = Mock()

        @contextmanager
        def scope():
            yield db

        for current in (None, {**original, 'password_hash': 'new-hash'}):
            with self.subTest(current=current), \
                 patch.object(accounts.session, 'read_session', scope), \
                 patch.object(accounts.session, 'unit_of_work', scope), \
                 patch.object(accounts.repository, 'throttle', return_value=None), \
                 patch.object(accounts.repository, 'login_user', return_value=original), \
                 patch.object(accounts.repository, 'lock_credentials', return_value=current), \
                 patch.object(accounts.repository, 'record_failure') as failure, \
                 patch.object(accounts.security, 'verify_password', return_value=True), \
                 patch.object(accounts, '_create_session') as create:
                with self.assertRaises(accounts.InvalidCredentials):
                    accounts.login(original['email'], 'synthetic', 'loopback')
                create.assert_not_called()
                failure.assert_called_once()

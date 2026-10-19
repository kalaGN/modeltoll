"""首个管理员初始化的隔离回归，不访问真实数据库。"""

from contextlib import contextmanager
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import mysql

from app.repositories import accounts as repository
from app.services.access import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.read_db = MagicMock()
        self.events = []
        self.open_sessions = 0
        self.commit_error = None

        @contextmanager
        def read_session():
            self.open_sessions += 1
            self.events.append('read_open')
            try:
                yield self.read_db
            finally:
                self.open_sessions -= 1
                self.events.append('read_closed')

        @contextmanager
        def pinned_session():
            self.open_sessions += 1
            self.events.append('pinned_open')
            try:
                yield self.db
            finally:
                self.open_sessions -= 1
                self.db.close()
                self.events.append('pinned_closed')

        @contextmanager
        def transaction():
            self.events.append('begin')
            try:
                yield self.db
                self.db.commit()
                if self.commit_error:
                    raise self.commit_error
            except BaseException:
                self.db.rollback()
                raise

        self.db.begin.side_effect = transaction
        self.read_context = self.enterContext(patch.object(bootstrap.session, 'read_session', read_session))
        self.enterContext(patch.object(bootstrap.session, 'pinned_session', pinned_session))

        def hash_password(password):
            self.assertEqual(self.open_sessions, 0, 'password hashing must not hold a Session')
            self.events.append('hash')
            return 'argon2-hash'

        self.hasher = self.enterContext(patch.object(bootstrap.security, 'hash_password', side_effect=hash_password))
        self.user = self.enterContext(patch.object(repository, 'bootstrap_user', return_value=None))
        self.lock = self.enterContext(patch.object(repository, 'bootstrap_lock', return_value=True))
        self.other_admin = self.enterContext(patch.object(repository, 'any_admin', return_value=False))
        self.create = self.enterContext(patch.object(repository, 'create_admin'))

    def init(self, email=' ADMIN@example.com ', password='safe-example-password'):
        return bootstrap.init_admin(email, password)

    def test_create_normalizes_hashes_and_commits(self):
        result = self.init()
        self.assertTrue(result.created)
        self.assertEqual(result.email, 'admin@example.com')
        self.hasher.assert_called_once_with('safe-example-password')
        self.create.assert_called_once_with(self.db, result.id, 'admin@example.com', 'argon2-hash')
        self.db.commit.assert_called_once()
        # End GET_LOCK autobegin before entering the business transaction.
        self.db.rollback.assert_called_once()
        self.db.close.assert_called_once()
        self.lock.assert_any_call(self.db, release=True)
        self.assertLess(self.events.index('read_closed'), self.events.index('hash'))
        self.assertLess(self.events.index('hash'), self.events.index('pinned_open'))
        self.user.assert_any_call(self.db, 'admin@example.com', lock=True)

    def test_validation_before_connection(self):
        for email, password in [('invalid', 'password-good'), ('good@example.com\n', 'password-good'),
                                ('good@example.com', 'short'), ('good@example.com', 'x' * 129),
                                (None, 'password-good'), ('good@example.com', None)]:
            with self.subTest(email=email), self.assertRaises(bootstrap.BootstrapError):
                self.init(email, password)
        self.assertEqual(self.events, [])
        self.user.assert_not_called()
        self.lock.assert_not_called()

    def test_existing_active_admin_is_unchanged(self):
        self.user.return_value = dict(id='existing', email='admin@example.com', status='active', is_admin=1)
        result = self.init()
        self.assertFalse(result.created)
        self.hasher.assert_not_called()
        self.create.assert_not_called()
        self.db.commit.assert_called_once()

    def test_existing_regular_or_disabled_user_not_promoted(self):
        for status, admin in [('active', 0), ('disabled', 1)]:
            self.user.return_value = dict(id='existing', email='admin@example.com', status=status, is_admin=admin)
            with self.subTest(status=status), self.assertRaises(bootstrap.BootstrapError):
                self.init()
        self.assertEqual(self.db.rollback.call_count, 4)
        self.db.commit.assert_not_called()
        self.hasher.assert_not_called()
        self.create.assert_not_called()

    def test_other_admin_blocks_creation(self):
        self.other_admin.return_value = True
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.assertEqual(self.db.rollback.call_count, 2)
        self.db.commit.assert_not_called()
        self.create.assert_not_called()
        # Hashing occurs before the locked authoritative check, never inside it.
        self.hasher.assert_called_once()

    def test_lock_timeout_does_not_start_transaction_or_release(self):
        self.lock.return_value = False
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.db.begin.assert_not_called()
        self.db.commit.assert_not_called()
        self.db.close.assert_called_once()
        self.lock.assert_called_once_with(self.db)

    def test_insert_exception_rolls_back_releases_and_closes(self):
        self.create.side_effect = RuntimeError('database-secret-must-not-leak')
        with self.assertRaises(RuntimeError):
            self.init()
        self.assertEqual(self.db.rollback.call_count, 2)
        self.db.commit.assert_not_called()
        self.db.close.assert_called_once()
        self.lock.assert_any_call(self.db, release=True)

    def test_release_failure_is_not_success_and_connection_closes(self):
        self.lock.side_effect = [True, False]
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.db.commit.assert_called_once()
        self.db.close.assert_called_once()

    def test_commit_failure_rolls_back_and_releases(self):
        self.commit_error = RuntimeError('commit unavailable')
        with self.assertRaises(RuntimeError):
            self.init()
        self.assertEqual(self.db.rollback.call_count, 2)
        self.db.close.assert_called_once()
        self.lock.assert_any_call(self.db, release=True)

    def test_account_removed_after_precheck_does_not_hash_under_lock(self):
        self.user.side_effect = [dict(id='existing'), None]
        with self.assertRaisesRegex(bootstrap.BootstrapError, '账号状态已变化'):
            self.init()
        self.hasher.assert_not_called()
        self.create.assert_not_called()

    def test_release_failure_preserves_original_business_failure(self):
        self.create.side_effect = RuntimeError('original failure')
        self.lock.side_effect = [True, RuntimeError('release failed')]
        with self.assertRaisesRegex(RuntimeError, 'original failure'):
            self.init()
        self.db.commit.assert_not_called()
        self.db.close.assert_called_once()


class BootstrapRepositoryTests(unittest.TestCase):
    def test_named_lock_sql_uses_same_db_connection_and_bound_name(self):
        db = MagicMock()
        db.scalar.return_value = 1
        self.assertTrue(repository.bootstrap_lock(db))
        self.assertTrue(repository.bootstrap_lock(db, release=True))
        compiled = [call.args[0].compile(dialect=mysql.dialect()) for call in db.scalar.call_args_list]
        self.assertIn('get_lock(', str(compiled[0]))
        self.assertIn('release_lock(', str(compiled[1]))
        for statement in compiled:
            self.assertIn('database()', str(statement))
            self.assertIn('sha2(', str(statement))
            self.assertIn('laya:init-admin:', statement.params.values())
        self.assertIn(10, compiled[0].params.values())
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


if __name__ == '__main__':
    unittest.main()

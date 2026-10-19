"""首个管理员初始化与运维 CLI 的隔离回归，不访问真实数据库。"""

import contextlib
import io
import unittest
import getpass
import warnings
from unittest.mock import MagicMock, patch

from app import manage
from app.services import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.conn = MagicMock()
        self.cur = MagicMock()
        self.conn.cursor.return_value.__enter__.return_value = self.cur
        self.connect = patch("app.services.bootstrap.session._new_connection", return_value=self.conn)
        self.connect.start()
        self.addCleanup(self.connect.stop)
        self.hash = patch("app.services.bootstrap.security.hash_password", return_value="argon2-hash")
        self.hasher = self.hash.start()
        self.addCleanup(self.hash.stop)
        self.cur.fetchone.side_effect = [{"acquired": 1}, None, None, {"released": 1}]

    def init(self, email=" ADMIN@example.com ", password="safe-example-password"):
        return bootstrap.init_admin(email, password)

    def test_create_normalizes_hashes_and_commits(self):
        result = self.init()
        self.assertTrue(result.created)
        self.assertEqual(result.email, "admin@example.com")
        self.hasher.assert_called_once_with("safe-example-password")
        insert = next(call for call in self.cur.execute.call_args_list if call.args[0].startswith("INSERT"))
        self.assertEqual(insert.args[1][1:4], ("admin@example.com", "admin@example.com", "argon2-hash"))
        self.conn.commit.assert_called_once()
        self.conn.rollback.assert_not_called()
        self.conn.close.assert_called_once()
        self.assertIn("RELEASE_LOCK", self.cur.execute.call_args_list[-1].args[0])

    def test_validation_before_connection(self):
        for email, password in [("invalid", "password-good"), ("good@example.com\n", "password-good"), ("good@example.com", "short"),
                                ("good@example.com", "x" * 129), (None, "password-good"),
                                ("good@example.com", None)]:
            with self.subTest(email=email), self.assertRaises(bootstrap.BootstrapError):
                self.init(email, password)
        self.conn.cursor.assert_not_called()

    def test_existing_active_admin_is_unchanged(self):
        self.cur.fetchone.side_effect = [{"acquired": 1},
            {"id": "existing", "email": "admin@example.com", "status": "active", "is_admin": 1},
            {"released": 1}]
        result = self.init()
        self.assertFalse(result.created)
        self.hasher.assert_not_called()
        self.assertFalse(any(call.args[0].startswith(("INSERT", "UPDATE")) for call in self.cur.execute.call_args_list))
        self.conn.commit.assert_called_once()

    def test_existing_regular_or_disabled_user_not_promoted(self):
        for status, admin in [("active", 0), ("disabled", 1)]:
            self.cur.fetchone.side_effect = [{"acquired": 1},
                {"id": "existing", "email": "admin@example.com", "status": status, "is_admin": admin},
                {"released": 1}]
            with self.subTest(status=status), self.assertRaises(bootstrap.BootstrapError):
                self.init()
            self.conn.rollback.assert_called()
            self.hasher.assert_not_called()

    def test_other_admin_blocks_creation(self):
        self.cur.fetchone.side_effect = [{"acquired": 1}, None, {"id": "other-admin"}, {"released": 1}]
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        self.hasher.assert_not_called()

    def test_lock_timeout_does_not_start_transaction_or_release(self):
        self.cur.fetchone.side_effect = [{"acquired": 0}]
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.conn.begin.assert_not_called()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once()
        self.assertEqual(self.cur.execute.call_count, 1)

    def test_insert_exception_rolls_back_releases_and_closes(self):
        def execute(sql, params=None):
            if sql.startswith("INSERT"):
                raise RuntimeError("database-secret-must-not-leak")
        self.cur.execute.side_effect = execute
        with self.assertRaises(RuntimeError):
            self.init()
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        self.conn.close.assert_called_once()
        self.assertIn("RELEASE_LOCK", self.cur.execute.call_args_list[-1].args[0])

    def test_release_failure_is_not_success_and_connection_closes(self):
        self.cur.fetchone.side_effect = [{"acquired": 1}, None, None, {"released": 0}]
        with self.assertRaises(bootstrap.BootstrapError):
            self.init()
        self.conn.commit.assert_called_once()
        self.conn.close.assert_called_once()

    def test_commit_failure_rolls_back_and_releases(self):
        self.conn.commit.side_effect = RuntimeError("commit unavailable")
        with self.assertRaises(RuntimeError):
            self.init()
        self.conn.rollback.assert_called_once()
        self.conn.close.assert_called_once()
        self.assertIn("RELEASE_LOCK", self.cur.execute.call_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()

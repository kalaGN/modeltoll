"""首个管理员初始化与运维 CLI 的隔离回归，不访问真实数据库。"""

import contextlib
import io
import unittest
import getpass
import warnings
from unittest.mock import MagicMock, patch

from app import manage
from app.services import bootstrap


class ManageTests(unittest.TestCase):
    def run_cli(self, args, stdin="", tty=False):
        output = io.StringIO()
        errors = io.StringIO()
        input_stream = io.StringIO(stdin)
        input_stream.isatty = lambda: tty
        with patch("sys.stdin", input_stream), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = manage.main(args)
        return status, output.getvalue(), errors.getvalue()

    @patch("app.manage.migrations.init_db")
    def test_migrate_success(self, init_db):
        self.assertEqual(self.run_cli(["migrate"])[0], 0)
        init_db.assert_called_once_with()

    @patch("app.manage.migrations.init_db", side_effect=RuntimeError("secret"))
    def test_migration_error_redacted(self, _):
        status, output, errors = self.run_cli(["migrate"])
        self.assertEqual(status, 1)
        self.assertNotIn("secret", output + errors)

    @patch("app.manage.bootstrap.init_admin", return_value=bootstrap.BootstrapResult("id", "admin@example.com", True))
    def test_password_stdin(self, init):
        status, output, errors = self.run_cli(["init-admin", "--email", "admin@example.com", "--password-stdin"], "example-password\n")
        self.assertEqual(status, 0)
        init.assert_called_once_with("admin@example.com", "example-password")
        self.assertNotIn("example-password", output + errors)

    @patch("app.manage.bootstrap.init_admin")
    def test_stdin_multiple_lines_rejected(self, init):
        self.assertEqual(self.run_cli(["init-admin", "--email", "admin@example.com", "--password-stdin"], "first-password\nsecond-password\n")[0], 1)
        init.assert_not_called()

    @patch("app.manage.bootstrap.init_admin", return_value=bootstrap.BootstrapResult("id", "admin@example.com", False))
    @patch("app.manage.getpass.getpass", side_effect=["interactive-password", "interactive-password"])
    def test_interactive_confirmed_without_echo(self, getpass, init):
        status, output, errors = self.run_cli(["init-admin", "--email", "admin@example.com"], tty=True)
        self.assertEqual(status, 0)
        self.assertEqual(getpass.call_count, 2)
        self.assertNotIn("interactive-password", output + errors)

    @patch("app.manage.bootstrap.init_admin")
    @patch("app.manage.getpass.getpass", side_effect=["first-password", "other-password"])
    def test_confirmation_mismatch_rejected(self, _, init):
        self.assertEqual(self.run_cli(["init-admin", "--email", "admin@example.com"], tty=True)[0], 1)
        init.assert_not_called()

    @patch("app.manage.bootstrap.init_admin", side_effect=RuntimeError("MYSQL_PASSWORD=secret"))
    def test_initialization_error_redacted(self, _):
        status, output, errors = self.run_cli(["init-admin", "--email", "admin@example.com", "--password-stdin"], "safe-password\n")
        self.assertEqual(status, 1)
        self.assertNotIn("MYSQL_PASSWORD", output + errors)

    def test_password_argument_not_accepted(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            manage.main(["init-admin", "--email", "admin@example.com", "--password", "secret-must-not-echo"])
        self.assertNotIn("secret-must-not-echo", errors.getvalue())

    @patch("app.manage.getpass.getpass")
    def test_noninteractive_without_explicit_stdin_rejected(self, getpass):
        self.assertEqual(self.run_cli(["init-admin", "--email", "admin@example.com"])[0], 1)
        getpass.assert_not_called()

    @patch("app.manage.bootstrap.init_admin")
    def test_getpass_plaintext_fallback_rejected(self, init):
        def unsafe_prompt(*args):
            warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
            self.fail("GetPassWarning should interrupt before plaintext input")
        with patch("app.manage.getpass.getpass", side_effect=unsafe_prompt):
            self.assertEqual(self.run_cli(["init-admin", "--email", "admin@example.com"], tty=True)[0], 1)
        init.assert_not_called()

    @patch("app.manage.bootstrap.init_admin")
    def test_stdin_oversize_is_rejected(self, init):
        init.side_effect = bootstrap.BootstrapError("密码长度须为 8–128 个字符")
        self.assertEqual(self.run_cli(["init-admin", "--email", "admin@example.com", "--password-stdin"], "x" * 10000)[0], 1)
        self.assertEqual(len(init.call_args.args[1]), 131)


if __name__ == "__main__":
    unittest.main()

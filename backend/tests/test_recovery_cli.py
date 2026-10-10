"""恢复CLI默认只读、显式单调用apply与安全输出契约。"""

import contextlib
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import patch

from app import manage


class RecoveryCliTests(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = manage.main(args)
        return status, out.getvalue(), err.getvalue()

    def test_default_is_readonly(self):
        with patch.object(manage.inference_recovery, 'inspect_calls', return_value=[{'call_id': 'fixture'}]) as inspect, \
             patch.object(manage.inference_recovery, 'recover') as recover:
            status, out, _ = self.run_cli(['recover-calls'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out), [{'call_id': 'fixture'}])
        inspect.assert_called_once_with(limit=100, call_id=None)
        recover.assert_not_called()

    def test_apply_single_call_only(self):
        with patch.object(manage.inference_recovery, 'recover', return_value=Decimal('0.000017')) as recover, \
             patch.object(manage.inference_recovery, 'inspect_calls') as inspect:
            status, out, _ = self.run_cli(['recover-calls', '--apply', '--call-id', 'fixture'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)['amount_yuan'], '0.000017')
        recover.assert_called_once_with('fixture')
        inspect.assert_not_called()

    def test_invalid_arguments_never_enter_service(self):
        with patch.object(manage.inference_recovery, 'recover') as recover, \
             patch.object(manage.inference_recovery, 'inspect_calls') as inspect:
            for args in (['--apply'], ['--limit', '101'], ['--limit', '0'], ['--offset', '-1']):
                with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                    self.run_cli(['recover-calls', *args])
                self.assertEqual(caught.exception.code, 2)
        recover.assert_not_called()
        inspect.assert_not_called()

    def test_readonly_pagination(self):
        with patch.object(manage.inference_recovery, 'inspect_calls', return_value=[]) as inspect:
            self.assertEqual(self.run_cli(['recover-calls', '--offset', '100'])[0], 0)
        inspect.assert_called_once_with(limit=100, call_id=None, offset=100)

    def test_database_error_is_redacted(self):
        with patch.object(manage.inference_recovery, 'recover', side_effect=RuntimeError('secret-db-url')):
            status, out, err = self.run_cli(['recover-calls', '--apply', '--call-id', 'fixture'])
        self.assertEqual(status, 1)
        self.assertNotIn('secret-db-url', out + err)

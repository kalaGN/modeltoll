"""A user disabled during password verification must not get a new session."""

from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from app.services import accounts


class LoginStatusRaceTests(unittest.TestCase):
    def test_disabled_between_read_and_transaction_cannot_receive_session(self):
        original = {'id': 'user-id', 'email': 'user@example.com',
                    'password_hash': 'original-hash', 'status': 'active'}
        read = Mock()
        read.fetchone.side_effect = [None, original]
        write = Mock()
        # The locked re-read sees the administrator's committed disable.
        write.fetchone.side_effect = [None, {**original, 'status': 'disabled'}]

        @contextmanager
        def read_cursor():
            yield read

        @contextmanager
        def write_cursor():
            yield write

        with patch.object(accounts.session, 'cursor', read_cursor), \
             patch.object(accounts.session, 'transaction', write_cursor), \
             patch.object(accounts.security, 'verify_password', return_value=True), \
             patch.object(accounts, '_create_session', return_value='must-not-be-issued') as create:
            with self.assertRaises(accounts.DisabledAccount):
                accounts.login('user@example.com', 'password', '127.0.0.1')
            create.assert_not_called()
        self.assertTrue(any('FOR UPDATE' in call.args[0]
                            for call in write.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()

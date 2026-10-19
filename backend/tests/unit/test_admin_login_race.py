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
        write = Mock()
        # The locked re-read sees the administrator's committed disable.

        @contextmanager
        def read_cursor():
            yield read

        @contextmanager
        def write_cursor():
            yield write

        with patch.object(accounts.session, 'read_session', read_cursor), \
             patch.object(accounts.session, 'unit_of_work', write_cursor), \
             patch.object(accounts.repository, 'throttle', return_value=None), \
             patch.object(accounts.repository, 'login_user', return_value=original), \
             patch.object(accounts.repository, 'lock_credentials', return_value={**original, 'status': 'disabled'}) as lock, \
             patch.object(accounts.security, 'verify_password', return_value=True), \
             patch.object(accounts, '_create_session', return_value='must-not-be-issued') as create:
            with self.assertRaises(accounts.DisabledAccount):
                accounts.login('user@example.com', 'password', '127.0.0.1')
            create.assert_not_called()
        lock.assert_called_once_with(write, original['id'])


if __name__ == '__main__':
    unittest.main()

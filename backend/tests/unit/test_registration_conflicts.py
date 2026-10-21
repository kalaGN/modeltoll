"""Registration maps only the reviewed email unique index to a conflict."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from pymysql.err import IntegrityError as DriverIntegrityError
from sqlalchemy.exc import IntegrityError

from app.services.access import accounts


def database_error(code, message):
    return IntegrityError('INSERT synthetic statement', {'password': 'synthetic-private'},
                          DriverIntegrityError(code, message))


class RegistrationConflictTests(unittest.TestCase):
    def register_with_error(self, error):
        events = []

        @contextmanager
        def transaction():
            try:
                yield object()
            except BaseException:
                events.append('rollback')
                raise

        with patch.object(accounts.session, 'unit_of_work', transaction), \
             patch.object(accounts.security, 'hash_password', return_value='synthetic-private'), \
             patch.object(accounts.repository, 'create_user', side_effect=error), \
             patch.object(accounts, '_fetch_user') as fetch:
            try:
                accounts.register_user('fixture@example.invalid', 'synthetic-private')
            finally:
                self.assertEqual(events, ['rollback'])
                fetch.assert_not_called()

    def test_only_exact_email_unique_key_duplicate_is_public_conflict(self):
        for name in ('uk_users_email_normalized', 'users.uk_users_email_normalized'):
            with self.subTest(key=name), self.assertRaises(accounts.EmailAlreadyRegistered):
                self.register_with_error(database_error(1062, f"Duplicate entry 'fixture' for key '{name}'"))

    def test_other_integrity_errors_keep_original_exception(self):
        cases = [
            (1062, "Duplicate entry 'fixture' for key 'users.PRIMARY'"),
            (1062, "Duplicate entry 'uk_users_email_normalized' for key 'users.other_key'"),
            (1062, "Duplicate entry 'fixture' for key 'users.uk_users_email_normalized_extra'"),
            (1062, 'unrecognized duplicate diagnostic'),
            (1452, "Foreign key failure for key 'users.uk_users_email_normalized'"),
            (1048, "Column 'email_normalized' cannot be null"),
            (3819, "Check constraint 'uk_users_email_normalized' is violated"),
        ]
        for code, message in cases:
            error = database_error(code, message)
            with self.subTest(code=code, message=message):
                with self.assertRaises(IntegrityError) as caught:
                    self.register_with_error(error)
                self.assertIs(caught.exception, error)

    def test_incomplete_driver_diagnostics_do_not_claim_email_conflict(self):
        for args in ((), (1062,), ('1062', "for key 'users.uk_users_email_normalized'"), (1062, None)):
            error = IntegrityError(None, None, DriverIntegrityError(*args))
            with self.subTest(args=args):
                with self.assertRaises(IntegrityError) as caught:
                    self.register_with_error(error)
                self.assertIs(caught.exception, error)

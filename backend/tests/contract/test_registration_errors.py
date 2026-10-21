"""Registration HTTP errors and logs never expose driver values or SQL parameters."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pymysql.err import IntegrityError as DriverIntegrityError
from sqlalchemy.exc import IntegrityError

from app.api.v1 import auth
from app.core import config
from app.main import app
from app.services.access import accounts


class RegistrationErrorContracts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.client.cookies.set(config.CSRF_COOKIE, 'fixture-csrf')

    def register(self):
        return self.client.post('/v1/auth/register', headers={'X-CSRF-Token': 'fixture-csrf'},
                                json={'email': 'private@example.invalid', 'password': 'synthetic-private'})

    def test_email_conflict_keeps_existing_409_contract(self):
        with patch.object(accounts, 'register_user', side_effect=accounts.EmailAlreadyRegistered()):
            response = self.register()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'code': 'email_already_registered', 'message': '该邮箱无法注册'})

    def test_unexpected_integrity_failure_is_500_and_safely_logged(self):
        error = IntegrityError('INSERT secret-sql', {'password': 'synthetic-private'},
                               DriverIntegrityError(1062, "Duplicate entry 'private@example.invalid' for key 'users.PRIMARY'"))
        with patch.object(accounts, 'register_user', side_effect=error), \
             self.assertLogs(auth.logger, level='ERROR') as logs:
            response = self.register()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('set-cookie', response.headers)
        combined = response.text + '\n'.join(logs.output)
        for value in ('private@example.invalid', 'synthetic-private', 'secret-sql', 'PRIMARY', 'Duplicate entry'):
            self.assertNotIn(value, combined)
        self.assertTrue(all(record.exc_info is None and record.stack_info is None for record in logs.records))
        self.assertEqual(logs.records[0].event, 'registration_integrity_failure')

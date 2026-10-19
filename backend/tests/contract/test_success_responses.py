"""Flat response/Cookie contracts; all business operations are synthetic mocks."""
from contextlib import ExitStack
import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import config, security
from app.main import app
from app.services.access import accounts, admin_management, api_keys
from app.services.metering import statistics

USER = accounts.User('fixture-user', 'fixture@example.invalid')


class SuccessResponseContracts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.client.cookies.set(config.CSRF_COOKIE, 'fixture-csrf')
        self.headers = {'X-CSRF-Token': 'fixture-csrf'}
        self.current = patch.object(accounts, 'current_user', return_value=USER)
        self.current.start()
        self.addCleanup(self.current.stop)

    def test_csrf_body_and_cookie_remain_flat(self):
        with patch.object(security, 'new_csrf_token', return_value='fixture-csrf'):
            response = self.client.get('/v1/auth/csrf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'code': 'ok', 'csrf_token': 'fixture-csrf'})
        self.assertEqual(response.cookies[config.CSRF_COOKIE], 'fixture-csrf')
        self.assertNotIn('httponly', response.headers['set-cookie'].lower())

    def test_registration_preserves_201_and_created(self):
        with patch.object(accounts, 'register_user', return_value=USER):
            response = self.client.post('/v1/auth/register', headers=self.headers,
                                        json={'email': USER.email, 'password': 'x' * config.PASSWORD_MIN})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'code': 'created', 'user': USER.public})

    def test_login_error_keeps_flat_401_and_does_not_issue_session(self):
        with patch.object(accounts, 'login', side_effect=accounts.InvalidCredentials()):
            response = self.client.post('/v1/auth/login', headers=self.headers,
                                        json={'email': USER.email, 'password': 'x' * config.PASSWORD_MIN})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'code': 'invalid_credentials', 'message': '邮箱或密码不正确'})
        self.assertNotIn('set-cookie', response.headers)

    def test_unexpected_service_exception_is_not_mapped_to_success(self):
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        with patch.object(accounts, 'current_user', return_value=accounts.User(USER.id, USER.email, True)), \
             patch.object(admin_management, 'list_users', side_effect=RuntimeError('synthetic-internal')):
            response = client.get('/v1/admin/users')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('synthetic-internal', response.text)

    def test_login_me_logout_preserve_session_cookie_behavior(self):
        with patch.object(accounts, 'login', return_value='fixture-session'):
            login = self.client.post('/v1/auth/login', headers=self.headers,
                                     json={'email': USER.email, 'password': 'x' * config.PASSWORD_MIN})
        self.assertEqual(login.json(), {'code': 'ok', 'user': USER.public})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.cookies[config.SESSION_COOKIE], 'fixture-session')
        cookie = login.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie)
        self.assertIn('samesite=lax', cookie)
        self.assertIn('path=/', cookie)
        self.assertEqual(self.client.get('/v1/auth/me').json(), {'code': 'ok', 'user': USER.public})
        with patch.object(accounts, 'logout') as logout:
            response = self.client.post('/v1/auth/logout', headers=self.headers)
        logout.assert_called_once_with('fixture-session')
        self.assertEqual(response.json(), {'code': 'ok'})
        self.assertIn('max-age=0', response.headers['set-cookie'].lower())

    def test_key_creation_preserves_201_and_top_level_secret(self):
        record = SimpleNamespace(id='fixture-key', public={'id': 'fixture-key'})
        with patch.object(api_keys, 'create', return_value=(record, 'synthetic-only')):
            response = self.client.post('/v1/api-keys', headers=self.headers, json={'name': 'fixture'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.json()), {'code', 'api_key', 'secret', 'call_example'})
        self.assertEqual(response.json()['code'], 'created')
        self.assertEqual(response.json()['api_key'], record.public)
        self.assertEqual(response.json()['secret'], 'synthetic-only')

    def test_statistics_keep_flat_range_totals_and_pagination(self):
        start = datetime.datetime(2026, 10, 1)
        end = datetime.datetime(2026, 10, 2)
        date_range = {'from': '2026-10-01T00:00:00Z', 'to': '2026-10-02T00:00:00Z', 'timezone': 'UTC'}
        page = {'items': [], 'next_cursor': None}
        values = {'parse_range': (start, end), 'usage_summary': {'calls': 0},
                  'billing_summary': {'amount_yuan': '0.000000'}, 'daily_series': [],
                  'current_price': {'currency': 'CNY'}, 'usage_calls': page,
                  'billing_charges': page, 'page_size': 20}
        expected = {
            '/v1/usage/summary': {'totals': {'calls': 0}, 'series': []},
            '/v1/billing/summary': {'totals': {'amount_yuan': '0.000000'}, 'series': [], 'price': {'currency': 'CNY'}},
            '/v1/usage/calls': {'limit': 20, **page},
            '/v1/billing/charges': {'limit': 20, **page},
        }
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch.object(statistics, name, return_value=value))
            for path, payload in expected.items():
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {'code': 'ok', 'range': date_range, **payload})

    def test_management_business_data_gets_one_envelope(self):
        admin = accounts.User(USER.id, USER.email, True)
        payload = {'items': [], 'page': 1, 'limit': 20, 'total': 0}
        with patch.object(accounts, 'current_user', return_value=admin), \
             patch.object(admin_management, 'list_users', return_value=payload):
            response = self.client.get('/v1/admin/users')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'code': 'ok', **payload})

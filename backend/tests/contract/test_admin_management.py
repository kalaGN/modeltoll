"""Administrator boundaries, atomic writes and privacy using synthetic data."""

import copy
import datetime
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1 import admin_management as routes
from app.db import migrations, session
from app.services import accounts, admin_management as management

ACTOR = 'ffffffff-ffff-4fff-afff-ffffffffffff'
TARGET = '11111111-1111-4111-a111-111111111111'
KEY = '22222222-2222-4222-a222-222222222222'
NOW = datetime.datetime(2026, 10, 8, 12)


def user(user_id=TARGET, admin=False, status='active'):
    return {'id': user_id, 'email': f'{user_id[:8]}@example.com', 'status': status,
            'is_admin': admin, 'created_at': NOW, 'last_login_at': None}


def key(revoked=None, deleted=None):
    return {'id': KEY, 'user_id': TARGET, 'name': 'synthetic',
            'display_prefix': 'laya_sk_test', 'last_four': '1234',
            'created_at': NOW, 'last_used_at': None,
            'revoked_at': revoked, 'deleted_at': deleted}


class Database:
    """Small fake exercising production transaction commit/rollback orchestration."""
    def __init__(self):
        self.users = {ACTOR: user(ACTOR, admin=True), TARGET: user()}
        self.key = key()
        self.session_revoked = False
        self.events = []
        self.statements = []
        self.audit_failure = False
        self.commits = self.rollbacks = 0
        self.row = None

    def begin(self):
        self.snapshot = copy.deepcopy((self.users, self.key, self.session_revoked, self.events))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.users, self.key, self.session_revoked, self.events = self.snapshot
        self.rollbacks += 1

    def close(self):
        pass

    @contextmanager
    def cursor(self):
        yield self

    def fetchone(self):
        return copy.deepcopy(self.row)

    def execute(self, sql, args=()):
        self.statements.append((sql, args))
        if sql.startswith('SELECT') and 'FROM users' in sql:
            self.row = self.users.get(args[0])
        elif sql.startswith('UPDATE users'):
            self.users[args[1]]['status'] = args[0]
        elif sql.startswith('UPDATE user_sessions'):
            self.session_revoked = True
        elif sql.startswith('SELECT user_id FROM api_keys'):
            self.row = {'user_id': TARGET} if self.key else None
        elif sql.startswith('SELECT') and 'FROM api_keys' in sql:
            self.row = self.key
        elif sql.startswith('UPDATE api_keys'):
            self.key['revoked_at'] = args[0]
        elif sql.startswith('INSERT INTO admin_audit_events'):
            if self.audit_failure:
                raise RuntimeError('synthetic audit failure')
            self.events.append(args)
        else:
            raise AssertionError(f'Unexpected synthetic database operation: {sql}')


class ManagementHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(routes.router)

        @app.exception_handler(HTTPException)
        async def handler(request, exc):
            return JSONResponse(exc.detail, status_code=exc.status_code)

        cls.client = TestClient(app)

    def setUp(self):
        self.auth = patch.object(accounts, 'current_user', return_value=accounts.User(ACTOR, 'admin@example.com', True))
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.client.cookies.clear()
        self.client.cookies.set('laya_csrf', 'synthetic-csrf-token')
        self.headers = {'X-CSRF-Token': 'synthetic-csrf-token'}

    def test_all_routes_require_authenticated_admin(self):
        endpoints = [('GET', '/v1/admin/users', None),
                     ('GET', f'/v1/admin/users/{TARGET}/api-keys', None),
                     ('PATCH', f'/v1/admin/users/{TARGET}/status', {'status': 'disabled', 'reason': 'policy'}),
                     ('POST', f'/v1/admin/api-keys/{KEY}/revoke', {'reason': 'rotation'}),
                     ('GET', '/v1/admin/audit-events', None)]
        for actor, status in ((None, 401), (accounts.User(TARGET, 'user@example.com'), 403)):
            with patch.object(accounts, 'current_user', return_value=actor):
                for method, path, body in endpoints:
                    with self.subTest(method=method, path=path, status=status):
                        result = self.client.request(method, path, json=body, headers=self.headers)
                        self.assertEqual(result.status_code, status)

    def test_writes_require_csrf_and_do_not_call_service(self):
        with patch.object(management, 'set_user_status') as change, patch.object(management, 'revoke_key') as revoke:
            result = self.client.patch(f'/v1/admin/users/{TARGET}/status', json={'status': 'disabled', 'reason': 'policy'})
            self.assertEqual(result.status_code, 403)
            result = self.client.post(f'/v1/admin/api-keys/{KEY}/revoke', json={'reason': 'policy'})
            self.assertEqual(result.status_code, 403)
            change.assert_not_called()
            revoke.assert_not_called()

    def test_strict_reason_fields_and_uuid(self):
        with patch.object(management, 'set_user_status') as change:
            for body in ({'status': 'disabled', 'reason': ''}, {'status': 'disabled', 'reason': '  '},
                         {'status': 'disabled', 'reason': 'x' * 201}, {'status': 'disabled', 'reason': 123},
                         {'status': 'invalid', 'reason': 'policy'},
                         {'status': 'disabled', 'reason': 'policy', 'is_admin': True}):
                with self.subTest(body=body):
                    result = self.client.patch(f'/v1/admin/users/{TARGET}/status', json=body, headers=self.headers)
                    self.assertEqual(result.status_code, 422)
            self.assertEqual(self.client.patch('/v1/admin/users/not-uuid/status',
                             json={'status': 'disabled', 'reason': 'policy'}, headers=self.headers).status_code, 422)
            change.assert_not_called()

    def test_reason_is_trimmed_and_service_errors_are_preserved(self):
        with patch.object(management, 'set_user_status', return_value={'changed': True}) as change:
            result = self.client.patch(f'/v1/admin/users/{TARGET}/status',
                                      json={'status': 'disabled', 'reason': '  policy  '}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            change.assert_called_once_with(ACTOR, TARGET, 'disabled', 'policy')
        with patch.object(management, 'set_user_status', side_effect=management.ManagementError(409, 'protected_admin', 'protected')):
            result = self.client.patch(f'/v1/admin/users/{TARGET}/status',
                                      json={'status': 'disabled', 'reason': 'policy'}, headers=self.headers)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()['code'], 'protected_admin')

    def test_query_and_pagination_bounds(self):
        with patch.object(management, 'list_users', return_value={'items': []}) as listing:
            for params in ({'page': 0}, {'page': 10001}, {'limit': 0}, {'limit': 101},
                           {'q': 'x' * 255}, {'status': 'unknown'}):
                self.assertEqual(self.client.get('/v1/admin/users', params=params).status_code, 422)
            listing.assert_not_called()
            self.assertEqual(self.client.get('/v1/admin/users', params={'page': 10000, 'limit': 100}).status_code, 200)
            listing.assert_called_once_with('', '', 10000, 100)


class MigrationTests(unittest.TestCase):
    def test_registered_migration_uses_ownership_foreign_key_and_checks(self):
        self.assertIn('0008_admin_audit.sql', migrations.MIGRATIONS)
        from app.core import config
        sql = (config.MIGRATIONS_DIR / '0008_admin_audit.sql').read_text()
        self.assertIn('FOREIGN KEY (target_key_id, target_user_id)', sql)
        self.assertIn('REFERENCES api_keys (id, user_id)', sql)
        self.assertIn('CREATE TABLE IF NOT EXISTS', sql)
        self.assertIn('chk_admin_audit_reason', sql)


if __name__ == '__main__':
    unittest.main()

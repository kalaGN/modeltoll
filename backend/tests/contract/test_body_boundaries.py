"""Actual ASGI chunking and auth/CSRF ordering, with synthetic business services."""
import json
import unittest
from unittest.mock import patch

import httpx

from app.core import config
from app.main import app
from app.services import accounts, branding, gateway

ADMIN = accounts.User('fixture-admin', 'fixture@example.invalid', True)


class BodyBoundaryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture')
        self.addAsyncCleanup(self.client.aclose)
        self.client.cookies.set(config.CSRF_COOKIE, 'fixture-csrf')
        self.user_patch = patch.object(accounts, 'current_user', return_value=ADMIN)
        self.user = self.user_patch.start()
        self.addCleanup(self.user_patch.stop)

    async def send(self, path, chunks, *, csrf=True, false_length=False):
        consumed = []
        async def stream():
            for index, chunk in enumerate(chunks):
                consumed.append(index)
                yield chunk
        headers = {'Content-Type': 'application/json'}
        if csrf:
            headers['X-CSRF-Token'] = 'fixture-csrf'
        if false_length:
            headers['Content-Length'] = '1'
        response = await self.client.put(path, content=stream(), headers=headers)
        return response, consumed

    async def test_branding_auth_and_csrf_reject_before_reading(self):
        for user, csrf, expected in [(None, True, 401), (ADMIN, False, 403),
                                     (accounts.User(ADMIN.id, ADMIN.email), True, 403)]:
            self.user.return_value = user
            with self.subTest(user=user, csrf=csrf):
                response, consumed = await self.send('/v1/admin/settings', [b'x' * (3 * 1024 * 1024 + 1)], csrf=csrf)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(consumed, [])

    async def test_gateway_limit_runs_before_auth_and_ignores_false_length(self):
        self.user.return_value = None
        response, consumed = await self.send('/v1/admin/model-connection',
                                             [b'x' * (256 * 1024), b'y', b'not-consumed'],
                                             false_length=True)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {'code': 'body_too_large', 'message': '网关请求不能超过 256 KB'})
        self.assertEqual(consumed, [0, 1])

    async def test_branding_limit_runs_after_csrf_and_stops_at_overflow(self):
        with patch.object(branding, 'save_settings') as save:
            response, consumed = await self.send('/v1/admin/settings',
                                                 [b'x' * (3 * 1024 * 1024), b'y', b'not-consumed'])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {'code': 'body_too_large', 'message': '配置请求过大'})
        self.assertEqual(consumed, [0, 1])
        save.assert_not_called()

    async def test_exact_limits_accept_valid_json_in_chunks_and_preserve_cached_body(self):
        cases = [('/v1/admin/settings', 3 * 1024 * 1024, {'name': 'fixture'}, branding, 'save_settings'),
                 ('/v1/admin/model-connection', 256 * 1024,
                  {'base_url': 'http://127.0.0.1:11434/v1', 'model': 'fixture-model'}, gateway, 'save_connection')]
        for path, limit, value, service, method in cases:
            body = json.dumps(value).encode()
            body += b' ' * (limit - len(body))
            with self.subTest(path=path), patch.object(service, method, return_value={}) as save:
                response, consumed = await self.send(path, [body[:7], body[7:]])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(consumed, [0, 1])
                save.assert_called_once()

    async def test_invalid_json_still_has_original_422_detail(self):
        response, _ = await self.send('/v1/admin/settings', [b'{'])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'detail': '平台名称、简介或 Logo 输入无效'})

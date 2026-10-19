"""自部署上游的协议、权限与失败边界；不请求真实模型。"""
import unittest
import os
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.gateway import ChatRequest, ConnectionRequest
from app.services import accounts, api_keys, gateway

BODY = {"model": "fixture-model", "messages": [{"role": "user", "content": "你好"}]}
RESULT = {"id": "chatcmpl-fixture", "object": "chat.completion", "model": "fixture-model",
          "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
CONNECTION = ConnectionRequest(base_url="http://127.0.0.1:11434/v1", model="fixture-model", enabled=True)


class GatewayHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('laya_csrf', 'fixture-csrf')
        user = accounts.User('fixture', 'fixture@example.invalid', True)
        self.user_patch = patch.object(accounts, 'current_user', return_value=user)
        self.user = self.user_patch.start()
        self.addCleanup(self.user_patch.stop)

    def test_config_requires_admin_and_csrf(self):
        self.user.return_value = None
        self.assertEqual(self.client.get('/v1/admin/model-connection').status_code, 401)
        self.user.return_value = accounts.User('fixture', 'fixture@example.invalid')
        self.assertEqual(self.client.get('/v1/admin/model-connection').status_code, 403)
        self.user.return_value = accounts.User('fixture', 'fixture@example.invalid', True)
        self.assertEqual(self.client.put('/v1/admin/model-connection', json=CONNECTION.model_dump()).status_code, 403)

    def test_platform_key_required(self):
        with patch.object(api_keys, 'authenticate', side_effect=api_keys.InvalidApiKey()):
            self.assertEqual(self.client.get('/v1/models').status_code, 401)
            self.assertEqual(self.client.post('/v1/chat/completions', json=BODY).status_code, 401)

    def test_body_limit_before_parsing(self):
        self.assertEqual(self.client.post('/v1/chat/completions', content=b'x' * (256 * 1024 + 1)).status_code, 413)

    def test_external_lifespan_does_not_build_laya(self):
        with patch.dict(os.environ, {'LAYA_RUNTIME': 'external', 'MYSQL_USER': 'synthetic',
                                   'MYSQL_PASSWORD': 'synthetic', 'MYSQL_DATABASE': 'synthetic'}), \
             patch('app.main.migrations.init_db') as init_db, \
             patch('app.main.model_runtime.build_router') as build:
            with TestClient(app) as client:
                response = client.get('/health')
                self.assertEqual(response.json()['runtime'], 'external')
                self.assertIsNone(response.json()['model'])
                self.assertEqual(response.json()['device'], 'external')
            init_db.assert_called_once()
            build.assert_not_called()

    def test_queue_timeout_never_contacts_upstream(self):
        principal = api_keys.Principal('user', 'key', 'masked')
        with patch.object(api_keys, 'authenticate', return_value=principal), \
             patch.object(gateway, 'connection', return_value=CONNECTION), \
             patch('app.api.v1.gateway.inference.begin') as begin, \
             patch('app.api.v1.gateway.inference.interrupted') as interrupted, \
             patch('app.api.v1.gateway.model_runtime.inference_lock') as lock, \
             patch.object(gateway, 'chat') as chat:
            lock.acquire.return_value = False
            response = self.client.post('/v1/chat/completions', json=BODY)
            self.assertEqual(response.status_code, 503)
            interrupted.assert_called_once_with(begin.return_value, 'queue_timeout', 503)
            chat.assert_not_called()
            lock.release.assert_not_called()

    def test_upstream_failure_does_not_settle_and_releases_lock(self):
        principal = api_keys.Principal('user', 'key', 'masked')
        with patch.object(api_keys, 'authenticate', return_value=principal), \
             patch.object(gateway, 'connection', return_value=CONNECTION), \
             patch('app.api.v1.gateway.inference.begin') as begin, \
             patch('app.api.v1.gateway.inference.mark_running'), \
             patch('app.api.inference_support.key_revoked'), \
             patch('app.api.v1.gateway.inference.failed') as failed, \
             patch('app.api.inference_support.settle') as settle, \
             patch.object(gateway, 'chat', side_effect=gateway.GatewayError('upstream_timeout', 'timeout', 504)):
            begin.return_value.id = 'fixture-call'
            response = self.client.post('/v1/chat/completions', json=BODY)
            self.assertEqual(response.status_code, 504)
            self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
            settle.assert_not_called()
            failed.assert_called_once_with(begin.return_value, 'upstream_timeout', 504)

    def test_external_mode_disables_old_inference_without_accounting(self):
        principal = api_keys.Principal('user', 'key', 'masked')
        with patch.object(api_keys, 'authenticate', return_value=principal), \
             patch('app.api.v1.inference.inference.begin') as begin, \
             patch.object(app.state, 'router', None, create=True):
            response = self.client.post('/v1/customer-service/analyze', json={'message': '退款'})
            self.assertEqual(response.status_code, 503)
            begin.assert_not_called()

    def test_configured_model_only_and_billing_after_success(self):
        principal = api_keys.Principal('user', 'key', 'masked')
        with patch.object(api_keys, 'authenticate', return_value=principal), \
             patch.object(gateway, 'connection', return_value=CONNECTION), \
             patch.object(gateway, 'chat', return_value=(RESULT, {'input_tokens': 10, 'output_tokens': 2})), \
             patch('app.api.v1.gateway.inference.begin') as begin, \
             patch('app.api.v1.gateway.inference.mark_running'), \
             patch('app.api.inference_support.key_revoked'), \
             patch('app.api.inference_support.settle') as settle:
            begin.return_value.id = 'fixture-call'
            response = self.client.post('/v1/chat/completions', json=BODY)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
            settle.assert_called_once()
            response = self.client.post('/v1/chat/completions', json={**BODY, 'model': 'unconfigured'})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(begin.call_count, 1)

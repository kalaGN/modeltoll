"""自部署上游的协议、权限与失败边界；不请求真实模型。"""
import unittest
import os
import json
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
from sqlalchemy.dialects import mysql
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.gateway import ChatRequest, ConnectionRequest
from app.integrations import openai_client
from app.services.access import accounts, api_keys
from app.services.inference import gateway

BODY = {"model": "fixture-model", "messages": [{"role": "user", "content": "你好"}]}
RESULT = {"id": "chatcmpl-fixture", "object": "chat.completion", "model": "fixture-model",
          "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
CONNECTION = ConnectionRequest(base_url="http://127.0.0.1:11434/v1", model="fixture-model", enabled=True)


class GatewayTests(unittest.TestCase):
    def request(self, handler, payload=BODY):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with client:
            return gateway.chat(CONNECTION, ChatRequest.model_validate(payload), client=client)

    def test_success_and_server_usage(self):
        result, usage = self.request(lambda request: httpx.Response(200, json=RESULT))
        self.assertEqual(result, RESULT)
        self.assertEqual(usage, {"input_tokens": 10, "output_tokens": 2})

    def test_adapter_forwards_bearer_and_body_to_fixed_https_url(self):
        connection = ConnectionRequest(base_url='https://upstream.example.invalid/v1',
                                       model='fixture-model', enabled=True)
        def handler(request):
            self.assertEqual(str(request.url), connection.base_url + '/chat/completions')
            self.assertEqual(request.headers['Authorization'], 'Bearer synthetic-fixture')
            self.assertEqual(json.loads(request.content), {**BODY, 'stream': False})
            return httpx.Response(200, json=RESULT)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
             patch.object(openai_client, 'upstream_key', return_value='synthetic-fixture'):
            result, usage = openai_client.chat(connection, ChatRequest.model_validate(BODY), client)
        self.assertEqual(result, RESULT)
        self.assertEqual(usage['input_tokens'], 10)

    def test_adapter_does_not_retry_connect_timeout(self):
        attempts = []
        def handler(request):
            attempts.append(request)
            raise httpx.ConnectTimeout('synthetic timeout', request=request)
        with self.assertRaises(openai_client.GatewayError) as caught:
            self.request(handler)
        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(len(attempts), 1)

    def test_forwards_only_to_fixed_connection(self):
        def handler(request):
            self.assertEqual(str(request.url), CONNECTION.base_url + '/chat/completions')
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, json=RESULT)
        with patch.object(openai_client, 'upstream_key', return_value=''):
            self.request(handler)

    def test_timeout_and_error_do_not_expose_upstream_text(self):
        def timeout(request):
            raise httpx.ReadTimeout('secret', request=request)
        for handler, status in [(timeout, 504), (lambda r: httpx.Response(401, text='secret'), 502),
                                (lambda r: httpx.Response(302, headers={'Location': 'http://evil.invalid'}), 502)]:
            with self.assertRaises(gateway.GatewayError) as ctx:
                self.request(handler)
            self.assertEqual(ctx.exception.status, status)
            self.assertNotIn('secret', ctx.exception.message)

    def test_invalid_usage_rejected(self):
        for tokens in [None, -1, True, '10', 1.5]:
            result = {**RESULT, 'usage': {'prompt_tokens': tokens}}
            with self.assertRaises(gateway.GatewayError) as ctx:
                self.request(lambda r: httpx.Response(200, json=result))
            self.assertEqual(ctx.exception.code, 'usage_unavailable')

    def test_invalid_response_and_size(self):
        for handler in [lambda r: httpx.Response(200, text='no-json'),
                        lambda r: httpx.Response(200, json={'usage': RESULT['usage']}),
                        lambda r: httpx.Response(200, content=b'x' * (openai_client.MAX_RESPONSE_BYTES + 1))]:
            with self.assertRaises(gateway.GatewayError):
                self.request(handler)

    def test_json_nonfinite_number_rejected_before_accounting(self):
        with self.assertRaises(gateway.GatewayError):
            self.request(lambda r: httpx.Response(200, content=b'{"value": NaN}'))

    def test_contract_rejects_unsupported_features(self):
        for extra in [{'stream': True}, {'tools': []}, {'usage': {}}, {'messages': []},
                      {'messages': [{'role': 'user', 'content': [{'type': 'image_url'}]}]}]:
            with self.assertRaises(ValueError):
                ChatRequest.model_validate({**BODY, **extra})

    def test_url_validation(self):
        for url in ['file:///tmp/v1', 'http://user:password@host/v1', 'http://host/v1?secret=1',
                    'http://host/v1#fragment', 'http://host/api', 'http://host:bad/v1']:
            with self.assertRaises(ValueError):
                ConnectionRequest(base_url=url, model='test')

    def test_credentials_require_tls_outside_loopback(self):
        with patch.object(openai_client, 'upstream_key', return_value='secret'):
            with self.assertRaises(gateway.GatewayError):
                openai_client.check_credentials(ConnectionRequest(base_url='http://10.0.0.1/v1', model='test'))

    def test_save_initial_price_and_connection_in_one_transaction(self):
        cur = MagicMock()
        cur.execute.return_value.mappings.return_value.first.side_effect = [{'id': 1}, None]
        @contextmanager
        def transaction():
            yield cur
        with patch.object(gateway.session, 'unit_of_work', transaction), patch.object(openai_client, 'upstream_key', return_value=''):
            result = gateway.save_connection(CONNECTION)
        self.assertEqual(result['connection'], CONNECTION.model_dump())
        statements = [str(args[0].compile(dialect=mysql.dialect())) for args, kwargs in cur.execute.call_args_list]
        self.assertTrue(any('INSERT INTO pricing_rules' in sql for sql in statements))
        self.assertFalse(any('UPDATE pricing_rules' in sql for sql in statements))
        self.assertIn('UPDATE model_connection', statements[-1])

    def test_existing_price_is_not_replaced(self):
        cur = MagicMock()
        cur.execute.return_value.mappings.return_value.first.side_effect = [{'id': 1}, {'id': 'existing-price'}]
        @contextmanager
        def transaction():
            yield cur
        with patch.object(gateway.session, 'unit_of_work', transaction), patch.object(openai_client, 'upstream_key', return_value=''):
            gateway.save_connection(CONNECTION)
        statements = [str(args[0].compile(dialect=mysql.dialect())) for args, kwargs in cur.execute.call_args_list]
        self.assertFalse(any('INSERT INTO pricing_rules' in sql for sql in statements))

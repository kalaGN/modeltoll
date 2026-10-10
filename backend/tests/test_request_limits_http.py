"""用户请求预算的 HTTP 契约；模型和账务使用合成桩，不访问真实数据库。"""

from contextlib import ExitStack, contextmanager
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.gateway import ConnectionRequest
from app.services import api_keys, customer_service, gateway, inference


CHAT = {'model': 'fixture-model', 'messages': [{'role': 'user', 'content': '合成输入'}]}
PREDICT = {'state': '合成输入', 'questions': {'flag': {'type': 'noul', 'instructions': '是否需要协助'}}}
ENDPOINTS = [('/v1/predict', PREDICT), ('/v1/customer-service/analyze', {'message': '合成输入'}),
             ('/v1/chat/completions', CHAT)]
USAGE = {'input_tokens': 2, 'output_tokens': 1}
CONNECTION = ConnectionRequest(base_url='http://127.0.0.1:11434/v1', model='fixture-model', enabled=True)


class RequestLimitsHttpTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.auth = self.stack.enter_context(patch.object(api_keys, 'authenticate'))
        self.auth.side_effect = lambda header: api_keys.Principal(
            'other-user' if header == 'Bearer other-key' else 'fixture-user',
            header.removeprefix('Bearer '), 'masked')
        self.stack.enter_context(patch.object(api_keys, 'still_valid', return_value=True))
        self.connection = self.stack.enter_context(patch.object(gateway, 'connection', return_value=CONNECTION))
        self.begin = self.stack.enter_context(patch.object(inference, 'begin'))
        self.begin.return_value.id = 'fixture-call'
        self.stack.enter_context(patch.object(inference, 'mark_running'))
        self.failed = self.stack.enter_context(patch.object(inference, 'failed'))
        self.stack.enter_context(patch.object(inference, 'interrupted'))
        self.settle = self.stack.enter_context(patch.object(inference, 'succeeded'))
        self.receipt = self.stack.enter_context(patch.object(inference, 'capture_success'))
        self.chat = self.stack.enter_context(patch.object(gateway, 'chat', return_value=({'result': 'ok'}, USAGE)))
        self.analyze = self.stack.enter_context(patch('app.api.v1.inference.customer_service.analyse_with_usage',
                                                     return_value=({'result': 'ok'}, USAGE)))
        self.router = MagicMock()
        self.router.predict.return_value = {'result': 'ok', 'usage': USAGE}
        self.stack.enter_context(patch.object(app.state, 'router', self.router, create=True))

    def post(self, path, body, key='first-key'):
        return self.client.post(path, json=body, headers={'Authorization': 'Bearer ' + key})

    def limits(self, rpm=0, max_inflight=0):
        from app.core import config
        from app.services import request_limits
        self.stack.enter_context(patch.object(config, 'request_limits_config',
                                             return_value=config.RequestLimits(rpm, max_inflight)))
        self.counts = {}
        count_lock = threading.Lock()

        def reserve(user_id, limit):
            with count_lock:
                count = self.counts.get(user_id, 0)
                if count >= limit:
                    raise request_limits.RateLimitError(429, 'rate_limit_exceeded', '请求预算已用尽', 7)
                self.counts[user_id] = count + 1

        self.reserve = self.stack.enter_context(patch.object(request_limits, '_reserve_rpm', side_effect=reserve))
        return request_limits

    def test_each_endpoint_enters_shared_admission_before_accounting(self):
        from app.services import request_limits
        admitted = []

        @contextmanager
        def probe(user_id):
            admitted.append(user_id)
            yield

        self.stack.enter_context(patch.object(request_limits, 'admit', probe))
        for path, body in ENDPOINTS:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, body).status_code, 200)
        self.assertEqual(admitted, ['fixture-user'] * 3)

    def test_idempotency_all_endpoints_duplicate_rejects_before_model(self):
        self.limits()
        for path, body in ENDPOINTS:
            with self.subTest(path=path):
                self.begin.reset_mock()
                self.receipt.reset_mock()
                self.settle.reset_mock()
                self.begin.side_effect = inference.IdempotencyConflict('request_already_processed', 'original-id')
                response = self.client.post(path, json=body, headers={
                    'Authorization': 'Bearer first-key', 'Idempotency-Key': 'synthetic-retry-1'})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['code'], 'request_already_processed')
                self.assertEqual(response.json()['call_id'], 'original-id')
                self.assertEqual(response.headers['X-Request-Id'], 'original-id')
                self.assertIn('idempotency', self.begin.call_args.kwargs)
                self.receipt.assert_not_called()
                self.settle.assert_not_called()
        self.chat.assert_not_called()
        self.analyze.assert_not_called()
        self.router.predict.assert_not_called()

    def test_invalid_idempotency_key_precedes_admission(self):
        self.limits(rpm=1)
        for path, body in ENDPOINTS:
            for key in ('', 'two words', 'x' * 129):
                response = self.client.post(path, json=body, headers={
                    'Authorization': 'Bearer first-key', 'Idempotency-Key': key})
                self.assertEqual(response.status_code, 422)
        self.reserve.assert_not_called()
        self.begin.assert_not_called()

    def test_receipt_precedes_charge_and_failure_has_request_id(self):
        self.limits()
        order = MagicMock()
        order.attach_mock(self.receipt, 'receipt')
        order.attach_mock(self.settle, 'charge')
        response = self.post(*ENDPOINTS[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call[0] for call in order.mock_calls], ['receipt', 'charge'])
        self.receipt.side_effect = RuntimeError('synthetic receipt DB fault')
        self.settle.reset_mock()
        response = self.post(*ENDPOINTS[0])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['code'], 'billing_unavailable')
        self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
        self.settle.assert_not_called()

    def test_unserializable_payload_never_gets_success_receipt(self):
        self.limits()
        for path, body in ENDPOINTS:
            with self.subTest(path=path):
                self.receipt.reset_mock()
                self.settle.reset_mock()
                self.router.predict.return_value = {'usage': USAGE, 'invalid': float('nan')}
                self.analyze.return_value = ({'invalid': float('nan')}, USAGE)
                self.chat.return_value = ({'invalid': float('nan')}, USAGE)
                with patch.object(inference, 'keep_usage') as keep:
                    response = self.post(path, body)
                keep.assert_called_once_with(self.begin.return_value, USAGE)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
                self.receipt.assert_not_called()
                self.settle.assert_not_called()

    def test_postprocessing_failure_preserves_usage_before_failed_without_charge(self):
        self.limits(max_inflight=1)
        self.analyze.side_effect = customer_service.AnalysisPostprocessingError(USAGE)
        order = MagicMock()
        with patch.object(inference, 'keep_usage') as keep:
            order.attach_mock(keep, 'keep')
            order.attach_mock(self.failed, 'failed')
            response = self.post(*ENDPOINTS[1])
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
            keep.assert_called_once_with(self.begin.return_value, USAGE)
            self.assertEqual([call[0] for call in order.mock_calls], ['keep', 'failed'])
        self.settle.assert_not_called()
        self.analyze.side_effect = None
        self.assertEqual(self.post(*ENDPOINTS[1]).status_code, 200)

    def test_postprocessing_usage_write_failure_stays_unsettled(self):
        self.limits(max_inflight=1)
        self.analyze.side_effect = customer_service.AnalysisPostprocessingError(USAGE)
        with patch.object(inference, 'keep_usage', side_effect=RuntimeError('synthetic DB fault')):
            response = self.post(*ENDPOINTS[1])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['code'], 'billing_unavailable')
        self.assertEqual(response.headers['X-Request-Id'], 'fixture-call')
        self.failed.assert_not_called()
        self.settle.assert_not_called()
        self.analyze.side_effect = None
        self.assertEqual(self.post(*ENDPOINTS[1]).status_code, 200)

    def test_postprocessing_invalid_usage_does_not_fabricate_zero_or_charge(self):
        self.limits()
        self.analyze.side_effect = customer_service.AnalysisPostprocessingError({'input_tokens': True})
        with patch.object(inference, 'keep_usage', side_effect=ValueError('invalid usage')):
            response = self.post(*ENDPOINTS[1])
        self.assertEqual(response.status_code, 500)
        self.failed.assert_called_once()
        self.settle.assert_not_called()

    def test_postprocessing_terminal_write_failure_returns_correlatable_error(self):
        self.limits(max_inflight=1)
        self.analyze.side_effect = customer_service.AnalysisPostprocessingError(USAGE)
        self.failed.side_effect = RuntimeError('synthetic failed write fault')
        with patch.object(inference, 'keep_usage') as keep:
            response = self.post(*ENDPOINTS[1])
        keep.assert_called_once_with(self.begin.return_value, USAGE)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers.get('X-Request-Id'), 'fixture-call')
        self.assertEqual(response.json()['code'], 'billing_unavailable')
        self.settle.assert_not_called()

    def test_user_budget_shared_across_keys_and_all_endpoints(self):
        self.limits(rpm=2)
        self.assertEqual(self.post(*ENDPOINTS[0], key='first-key').status_code, 200)
        self.assertEqual(self.post(*ENDPOINTS[1], key='second-key').status_code, 200)
        before = self.begin.call_count, self.settle.call_count
        response = self.post(*ENDPOINTS[2], key='third-key')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['code'], 'rate_limit_exceeded')
        self.assertEqual(response.headers['Retry-After'], '7')
        self.assertEqual((self.begin.call_count, self.settle.call_count), before)
        self.chat.assert_not_called()
        self.assertEqual(self.post(*ENDPOINTS[2], key='other-key').status_code, 200)
        self.assertEqual(self.counts, {'fixture-user': 2, 'other-user': 1})

    def test_database_failure_is_closed_and_never_starts_call(self):
        service = self.limits(rpm=2, max_inflight=1)
        self.reserve.side_effect = service.RateLimitError(503, 'rate_limit_unavailable', '请求计数不可用')
        for path, body in ENDPOINTS:
            with self.subTest(path=path):
                response = self.post(path, body)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'rate_limit_unavailable')
        self.begin.assert_not_called()
        self.settle.assert_not_called()
        self.chat.assert_not_called()
        self.analyze.assert_not_called()
        self.router.predict.assert_not_called()
        self.reserve.side_effect = None
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 200)

    def test_invalid_input_and_unavailable_models_do_not_consume_budget(self):
        self.limits(rpm=1, max_inflight=1)
        for path, _ in ENDPOINTS:
            self.assertEqual(self.post(path, {}).status_code, 422)
        self.assertEqual(self.post('/v1/chat/completions', {**CHAT, 'model': 'unknown'}).status_code, 404)
        self.connection.return_value = None
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 503)
        with patch.object(app.state, 'router', None):
            for path, body in ENDPOINTS[:2]:
                self.assertEqual(self.post(path, body).status_code, 503)
        self.auth.side_effect = api_keys.InvalidApiKey()
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 401)
        self.reserve.assert_not_called()
        self.begin.assert_not_called()

    def test_default_disabled_does_not_read_rpm_store(self):
        self.limits()
        for path, body in ENDPOINTS:
            self.assertEqual(self.post(path, body).status_code, 200)
        self.reserve.assert_not_called()
        self.assertEqual(self.begin.call_count, 3)
        self.assertEqual(self.settle.call_count, 3)

    def test_begin_and_settlement_exceptions_release_inflight(self):
        self.limits(max_inflight=1)
        for path, body in ENDPOINTS:
            with self.subTest(path=path, stage='begin'):
                self.begin.side_effect = RuntimeError('synthetic accounting failure')
                self.assertEqual(self.post(path, body).status_code, 500)
                self.begin.side_effect = None
                self.assertEqual(self.post(path, body).status_code, 200)
            with self.subTest(path=path, stage='settle'):
                self.settle.side_effect = RuntimeError('synthetic settlement failure')
                response = self.post(path, body)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.headers.get('X-Request-Id'), 'fixture-call')
                self.settle.side_effect = None
                self.assertEqual(self.post(path, body).status_code, 200)

    def test_upstream_failure_consumes_rpm_but_releases_inflight(self):
        self.limits(rpm=2, max_inflight=1)
        self.chat.side_effect = gateway.GatewayError('upstream_timeout', '合成超时', 504)
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 504)
        self.settle.assert_not_called()
        self.chat.side_effect = None
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 200)
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 429)
        self.assertEqual(self.counts['fixture-user'], 2)

    def test_inflight_includes_settlement_and_rejects_without_rpm_charge(self):
        self.limits(rpm=10, max_inflight=1)
        entered = threading.Event()
        release = threading.Event()

        def blocked_settlement(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test settlement timeout')

        self.settle.side_effect = blocked_settlement
        result = []
        first = threading.Thread(target=lambda: result.append(self.post(*ENDPOINTS[0])))
        first.start()
        try:
            self.assertTrue(entered.wait(5), 'first request never reached settlement')
            response = self.post(*ENDPOINTS[2], key='second-key')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['code'], 'concurrency_limit_exceeded')
            self.assertEqual(response.headers['Retry-After'], '1')
            self.assertEqual(self.counts, {'fixture-user': 1})
            self.assertEqual(self.begin.call_count, 1)
            self.chat.assert_not_called()
        finally:
            release.set()
            first.join(5)
        self.assertFalse(first.is_alive())
        self.assertEqual(result[0].status_code, 200)
        self.settle.side_effect = None
        self.assertEqual(self.post(*ENDPOINTS[2]).status_code, 200)


if __name__ == '__main__':
    unittest.main()

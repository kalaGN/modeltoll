"""Explicit public errors retain payload and header semantics."""
import unittest

from fastapi import HTTPException

from app.api.errors import error_content, http_error


class ErrorBuilderTests(unittest.TestCase):
    def test_content_is_flat_and_returns_fresh_dicts(self):
        first = error_content('fixture', '可公开消息')
        self.assertEqual(first, {'code': 'fixture', 'message': '可公开消息'})
        first['code'] = 'changed'
        self.assertEqual(error_content('fixture', '可公开消息')['code'], 'fixture')

    def test_http_error_preserves_status_detail_and_headers(self):
        headers = {'X-Request-Id': 'fixture-call', 'Retry-After': '12'}
        exc = http_error(429, 'rate_limited', '稍后重试', headers=headers)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 429)
        self.assertEqual(exc.detail, {'code': 'rate_limited', 'message': '稍后重试'})
        self.assertEqual(exc.headers, headers)
        self.assertEqual(headers, {'X-Request-Id': 'fixture-call', 'Retry-After': '12'})

    def test_absent_headers_remain_absent(self):
        self.assertIsNone(http_error(401, 'unauthenticated', '未登录').headers)

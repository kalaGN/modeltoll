"""管理员权限与品牌配置的边界测试，不加载模型或依赖真实账号。"""
import base64
import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import accounts, admin_overview, branding

USER = accounts.User('00000000-0000-4000-8000-000000000003', 'fixture@example.invalid')
ADMIN = accounts.User(USER.id, USER.email, True)


def image_url(fmt='PNG'):
    out = io.BytesIO()
    image = Image.new('RGB', (20, 20), '#d5f16a')
    image.save(out, format=fmt)
    mime = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp'}[fmt]
    return 'data:image/' + mime + ';base64,' + base64.b64encode(out.getvalue()).decode()


class AdminHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set('laya_csrf', 'fixture-csrf')
        self.patch = patch.object(accounts, 'current_user', return_value=ADMIN)
        self.current = self.patch.start()
        self.addCleanup(self.patch.stop)

    def save(self, body=None, csrf=True):
        return self.client.put('/v1/admin/settings', json=body or {'name': '测试平台'},
                               headers={'X-CSRF-Token': 'fixture-csrf'} if csrf else {})

    def test_anonymous_admin_api_401(self):
        self.current.return_value = None
        self.assertEqual(self.client.get('/v1/admin/overview').status_code, 401)
        self.assertEqual(self.save().status_code, 401)

    def test_ordinary_user_admin_api_403(self):
        self.current.return_value = USER
        self.assertEqual(self.client.get('/v1/admin/overview').json()['code'], 'admin_required')
        self.assertEqual(self.save().status_code, 403)

    def test_demotion_invalidates_current_session_role(self):
        with patch.object(admin_overview, 'overview', return_value={'totals': {}}):
            self.assertEqual(self.client.get('/v1/admin/overview').status_code, 200)
            self.current.return_value = USER
            self.assertEqual(self.client.get('/v1/admin/overview').status_code, 403)

    def test_admin_save_requires_csrf(self):
        with patch.object(branding, 'save_settings') as save:
            self.assertEqual(self.save(csrf=False).json()['code'], 'csrf_failed')
            save.assert_not_called()

    def test_save_normalizes_text_and_keeps_logo_by_default(self):
        with patch.object(branding, 'save_settings', return_value=branding.DEFAULT_BRANDING) as save:
            result = self.save({'name': '  测试  ', 'description': ' 简介 '})
            self.assertEqual(result.status_code, 200)
            save.assert_called_once_with('测试', '简介', None)

    def test_invalid_text_or_unknown_field_rejected(self):
        for body in [{'name': ' '}, {'name': 'x' * 61}, {'name': 'test', 'description': 'x' * 201}, {'name': 'test', 'is_admin': True}]:
            self.assertEqual(self.save(body).status_code, 422)

    def test_request_body_size_is_limited(self):
        result = self.client.put('/v1/admin/settings', content=b'x' * (3 * 1024 * 1024 + 1), headers={'X-CSRF-Token': 'fixture-csrf'})
        self.assertEqual(result.status_code, 413)

    def test_invalid_range_rejected(self):
        self.assertEqual(self.client.get('/v1/admin/overview?from=bad').status_code, 400)
        self.assertEqual(self.client.get('/v1/admin/overview?from=2020-01-01&to=2026-10-07').status_code, 400)

    def test_public_branding_does_not_require_session(self):
        self.current.return_value = None
        with patch.object(branding, 'branding', return_value=branding.DEFAULT_BRANDING):
            result = self.client.get('/v1/platform/branding')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(set(result.json()['branding']), {'name', 'description', 'logo_url'})

    def test_backend_no_longer_serves_business_pages(self):
        for user in [ADMIN, USER, None]:
            self.current.return_value = user
            for page in ['/', '/login', '/admin', '/admin/settings']:
                self.assertEqual(self.client.get(page, follow_redirects=False).status_code, 404)

    def test_me_reports_boolean_role(self):
        self.assertIs(self.client.get('/v1/auth/me').json()['user']['is_admin'], True)

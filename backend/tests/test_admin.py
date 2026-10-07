"""管理员权限与品牌配置的边界测试，不加载模型或依赖真实账号。"""
import base64
import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import accounts, platform

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
        with patch.object(platform, 'overview', return_value={'totals': {}}):
            self.assertEqual(self.client.get('/v1/admin/overview').status_code, 200)
            self.current.return_value = USER
            self.assertEqual(self.client.get('/v1/admin/overview').status_code, 403)

    def test_admin_save_requires_csrf(self):
        with patch.object(platform, 'save_settings') as save:
            self.assertEqual(self.save(csrf=False).json()['code'], 'csrf_failed')
            save.assert_not_called()

    def test_save_normalizes_text_and_keeps_logo_by_default(self):
        with patch.object(platform, 'save_settings', return_value=platform.DEFAULT_BRANDING) as save:
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
        with patch.object(platform, 'branding', return_value=platform.DEFAULT_BRANDING):
            result = self.client.get('/v1/platform/branding')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(set(result.json()['branding']), {'name', 'description', 'logo_url'})

    def test_page_guards_and_root_redirect(self):
        self.assertEqual(self.client.get('/', follow_redirects=False).headers['location'], '/admin')
        self.current.return_value = USER
        self.assertEqual(self.client.get('/', follow_redirects=False).headers['location'], '/keys')
        for page in ['/admin', '/admin/settings']:
            self.assertEqual(self.client.get(page).status_code, 403)
        self.current.return_value = None
        self.assertEqual(self.client.get('/admin', follow_redirects=False).headers['location'], '/login')

    def test_me_reports_boolean_role(self):
        self.assertIs(self.client.get('/v1/auth/me').json()['user']['is_admin'], True)


class LogoTests(unittest.TestCase):
    def test_supported_images_reencoded_to_png(self):
        for fmt in ['PNG', 'JPEG', 'WEBP']:
            raw = platform.validate_logo(image_url(fmt))
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertEqual(image.size, (20, 20))

    def test_corrupt_mismatched_or_svg_rejected(self):
        for value in ['data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,eA==', image_url().replace('image/png', 'image/jpeg'), 'not-an-image']:
            with self.assertRaises(platform.InvalidLogo):
                platform.validate_logo(value)

    def test_oversized_dimensions_rejected(self):
        out = io.BytesIO()
        Image.new('RGB', (4097, 1)).save(out, format='PNG')
        with self.assertRaises(platform.InvalidLogo):
            platform.validate_logo('data:image/png;base64,' + base64.b64encode(out.getvalue()).decode())

    def test_oversized_upload_rejected(self):
        with self.assertRaises(platform.InvalidLogo):
            platform.validate_logo('data:image/png;base64,' + 'x' * 2900000)


class AccountRoleTests(unittest.TestCase):
    def test_role_reads_current_database_row(self):
        class Cursor:
            def execute(self, *args): pass
            def fetchone(self): return {'id': USER.id, 'email': USER.email, 'is_admin': 1}
        @contextmanager
        def cursor(): yield Cursor()
        with patch.object(accounts.session, 'cursor', cursor):
            self.assertIs(accounts.current_user('fixture-token').is_admin, True)

    def test_registration_does_not_accept_admin_field(self):
        with patch.object(accounts, 'register_user', return_value=USER) as register:
            client = TestClient(app)
            client.cookies.set('laya_csrf', 'fixture-csrf')
            result = client.post('/v1/auth/register', json={'email': USER.email, 'password': 'fixture-password', 'is_admin': True}, headers={'X-CSRF-Token': 'fixture-csrf'})
            self.assertEqual(result.status_code, 201)
            self.assertFalse(result.json()['user']['is_admin'])
            register.assert_called_once_with(USER.email, 'fixture-password')

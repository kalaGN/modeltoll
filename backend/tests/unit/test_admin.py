"""管理员权限与品牌配置的边界测试，不加载模型或依赖真实账号。"""
import base64
import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import accounts, branding

USER = accounts.User('00000000-0000-4000-8000-000000000003', 'fixture@example.invalid')
ADMIN = accounts.User(USER.id, USER.email, True)


def image_url(fmt='PNG'):
    out = io.BytesIO()
    image = Image.new('RGB', (20, 20), '#d5f16a')
    image.save(out, format=fmt)
    mime = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp'}[fmt]
    return 'data:image/' + mime + ';base64,' + base64.b64encode(out.getvalue()).decode()


class LogoTests(unittest.TestCase):
    def test_supported_images_reencoded_to_png(self):
        for fmt in ['PNG', 'JPEG', 'WEBP']:
            raw = branding.validate_logo(image_url(fmt))
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertEqual(image.size, (20, 20))

    def test_corrupt_mismatched_or_svg_rejected(self):
        for value in ['data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,eA==', image_url().replace('image/png', 'image/jpeg'), 'not-an-image']:
            with self.assertRaises(branding.InvalidLogo):
                branding.validate_logo(value)

    def test_oversized_dimensions_rejected(self):
        out = io.BytesIO()
        Image.new('RGB', (4097, 1)).save(out, format='PNG')
        with self.assertRaises(branding.InvalidLogo):
            branding.validate_logo('data:image/png;base64,' + base64.b64encode(out.getvalue()).decode())

    def test_oversized_upload_rejected(self):
        with self.assertRaises(branding.InvalidLogo):
            branding.validate_logo('data:image/png;base64,' + 'x' * 2900000)


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

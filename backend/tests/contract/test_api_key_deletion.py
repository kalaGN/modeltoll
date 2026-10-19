"""密钥软删除的用户隔离与 HTTP 契约回归，不需要真实模型。"""
import datetime
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import dependencies
from app.main import app
from app.services import api_keys, accounts

KEY_ID = "00000000-0000-4000-8000-000000000001"
USER_ID = "00000000-0000-4000-8000-000000000002"


class Cursor:
    def __init__(self, rowcount=1, record=None):
        self.rowcount = rowcount
        self.record = record
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))

    def fetchone(self):
        return self.record


@contextmanager
def use_cursor(cursor):
    yield cursor


class DeletionHttpTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[dependencies.require_user] = lambda: accounts.User(USER_ID, "test@example.invalid")
        self.client = TestClient(app)
        self.client.cookies.set("laya_csrf", "test-csrf")

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()

    def test_delete_returns_existing_flat_error_convention(self):
        with patch.object(api_keys, "delete", side_effect=api_keys.ApiKeyNotRevoked()):
            response = self.client.delete(f"/v1/api-keys/{KEY_ID}", headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "api_key_not_revoked")

    def test_csrf_required_and_service_not_called(self):
        with patch.object(api_keys, "delete") as delete:
            response = self.client.delete(f"/v1/api-keys/{KEY_ID}")
        self.assertEqual(response.status_code, 403)
        delete.assert_not_called()

    def test_malformed_id_is_not_found(self):
        with patch.object(api_keys, "delete") as delete:
            response = self.client.delete("/v1/api-keys/invalid", headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(response.status_code, 404)
        delete.assert_not_called()

    def test_success_has_no_secret_and_uses_session_owner(self):
        with patch.object(api_keys, "delete") as delete:
            response = self.client.delete(f"/v1/api-keys/{KEY_ID}", headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"code": "ok"})
        delete.assert_called_once_with(USER_ID, KEY_ID)

    def test_unauthenticated_request_rejected(self):
        def reject():
            from fastapi import HTTPException
            raise HTTPException(401, detail={"code": "unauthenticated", "message": "未登录"})
        app.dependency_overrides[dependencies.require_user] = reject
        with patch.object(api_keys, "delete") as delete:
            response = self.client.delete(f"/v1/api-keys/{KEY_ID}", headers={"X-CSRF-Token": "test-csrf"})
        self.assertEqual(response.status_code, 401)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()

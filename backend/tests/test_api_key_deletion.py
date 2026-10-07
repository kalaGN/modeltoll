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


class DeletionServiceTests(unittest.TestCase):
    def run_delete(self, cursor):
        with patch.object(api_keys.session, "cursor", return_value=use_cursor(cursor)):
            api_keys.delete(USER_ID, KEY_ID)

    def test_only_owner_revoked_undeleted_row_can_be_updated(self):
        cursor = Cursor()
        self.run_delete(cursor)
        sql, params = cursor.queries[0]
        self.assertIn("user_id = %s", sql)
        self.assertIn("revoked_at IS NOT NULL", sql)
        self.assertIn("deleted_at IS NULL", sql)
        self.assertEqual(params, (KEY_ID, USER_ID))

    def test_active_key_conflict(self):
        with self.assertRaises(api_keys.ApiKeyNotRevoked):
            self.run_delete(Cursor(0, {"revoked_at": None, "deleted_at": None}))

    def test_other_owner_or_missing_key_not_found(self):
        cursor = Cursor(0, None)
        with self.assertRaises(api_keys.ApiKeyNotFound):
            self.run_delete(cursor)
        self.assertIn("user_id = %s", cursor.queries[1][0])
        self.assertEqual(cursor.queries[1][1], (KEY_ID, USER_ID))

    def test_repeat_delete_is_success_without_another_update(self):
        now = datetime.datetime(2026, 10, 7)
        cursor = Cursor(0, {"revoked_at": now, "deleted_at": now})
        self.run_delete(cursor)
        self.assertEqual(len(cursor.queries), 2)


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

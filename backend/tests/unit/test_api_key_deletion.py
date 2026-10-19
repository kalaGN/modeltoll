"""密钥软删除的用户隔离与 HTTP 契约回归，不需要真实模型。"""
import datetime
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from sqlalchemy.dialects import mysql

from fastapi.testclient import TestClient
from app.api import dependencies
from app.main import app
from app.services.access import api_keys, accounts

KEY_ID = "00000000-0000-4000-8000-000000000001"
USER_ID = "00000000-0000-4000-8000-000000000002"


class Cursor:
    def __init__(self, rowcount=1, record=None):
        self.rowcount = rowcount
        self.record = record
        self.queries = []

    def execute(self, statement):
        compiled = statement.compile(dialect=mysql.dialect())
        self.queries.append((str(compiled), compiled.params))
        return self

    def mappings(self):
        return self

    def first(self):
        return self.record

    def fetchone(self):
        return self.record


@contextmanager
def use_cursor(cursor):
    yield cursor


class DeletionServiceTests(unittest.TestCase):
    def run_delete(self, cursor):
        with patch.object(api_keys.session, "unit_of_work", return_value=use_cursor(cursor)):
            api_keys.delete(USER_ID, KEY_ID)

    def test_only_owner_revoked_undeleted_row_can_be_updated(self):
        cursor = Cursor()
        self.run_delete(cursor)
        sql, params = cursor.queries[0]
        self.assertIn("user_id = %s", sql)
        self.assertIn("revoked_at IS NOT NULL", sql)
        self.assertIn("deleted_at IS NULL", sql)
        self.assertEqual(params['id_1'], KEY_ID)
        self.assertEqual(params['user_id_1'], USER_ID)

    def test_active_key_conflict(self):
        with self.assertRaises(api_keys.ApiKeyNotRevoked):
            self.run_delete(Cursor(0, {"revoked_at": None, "deleted_at": None}))

    def test_other_owner_or_missing_key_not_found(self):
        cursor = Cursor(0, None)
        with self.assertRaises(api_keys.ApiKeyNotFound):
            self.run_delete(cursor)
        self.assertIn("user_id = %s", cursor.queries[1][0])
        self.assertEqual(cursor.queries[1][1], {'id_1': KEY_ID, 'user_id_1': USER_ID})

    def test_repeat_delete_is_success_without_another_update(self):
        now = datetime.datetime(2026, 10, 7)
        cursor = Cursor(0, {"revoked_at": now, "deleted_at": now})
        self.run_delete(cursor)
        self.assertEqual(len(cursor.queries), 2)


if __name__ == "__main__":
    unittest.main()

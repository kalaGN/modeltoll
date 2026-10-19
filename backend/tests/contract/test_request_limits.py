import os
import queue
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from app.core import config
from app.services import request_limits


class StartupLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_limit_rejected_before_database_or_model(self):
        from app.main import app, lifespan
        with patch.dict(os.environ, {'LAYA_USER_RPM': '-1'}), \
                patch('app.main.migrations.init_db') as database, \
                patch('app.main.model_runtime.build_router') as model:
            with self.assertRaises(ValueError):
                async with lifespan(app):
                    self.fail('invalid configuration must not start')
        database.assert_not_called()
        model.assert_not_called()


class FakeCursor:
    def __init__(self, count=0, cleanup_error=False, times=None):
        self.count = count
        self.cleanup_error = cleanup_error
        self.times = iter(times or [datetime(2026, 10, 9, 12, 0, 30)] * 2)
        self.queries = []
        self.result = None

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if sql.startswith('DELETE') and self.cleanup_error:
            raise RuntimeError('cleanup failure')
        if sql.startswith('SELECT UTC_TIMESTAMP'):
            self.result = {'now': next(self.times)}
        elif sql.startswith('SELECT request_count'):
            self.result = {'request_count': self.count}

    def fetchone(self):
        return self.result

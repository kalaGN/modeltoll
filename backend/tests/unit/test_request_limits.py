import os
import queue
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from sqlalchemy.dialects import mysql

from app.core import config
from app.services import request_limits


class RequestLimitsTests(unittest.TestCase):
    def setUp(self):
        request_limits._inflight.clear()

    def test_defaults_and_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.request_limits_config(), config.RequestLimits(0, 0))
        with patch.dict(os.environ, {'LAYA_USER_RPM': '100000', 'LAYA_USER_MAX_INFLIGHT': '1024'}):
            self.assertEqual(config.request_limits_config(), config.RequestLimits(100000, 1024))

    def test_invalid_configuration(self):
        for key, values in [('LAYA_USER_RPM', ['-1', '100001', '', '1.0', '+1', ' 1', 'x']),
                            ('LAYA_USER_MAX_INFLIGHT', ['-1', '1025', 'x'])]:
            for value in values:
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                    with self.assertRaises(ValueError):
                        config.request_limits_config()

    def test_disabled_does_not_touch_database(self):
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(0, 0)), \
                patch.object(request_limits, '_reserve_rpm') as reserve:
            with request_limits.admit('u'):
                pass
        reserve.assert_not_called()
        self.assertEqual(request_limits._inflight, {})

    def test_error_releases_slot(self):
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(1, 1)), \
                patch.object(request_limits, '_reserve_rpm', side_effect=RuntimeError('database')):
            with self.assertRaises(request_limits.RateLimitError) as caught:
                with request_limits.admit('u'):
                    self.fail('must not enter')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(request_limits._inflight, {})

    def test_body_exception_releases_slot(self):
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(0, 1)):
            with self.assertRaises(ValueError):
                with request_limits.admit('u'):
                    raise ValueError('body')
        self.assertEqual(request_limits._inflight, {})

    def test_rpm_rejection_releases_slot(self):
        error = request_limits.RateLimitError(429, 'rate_limit_exceeded', 'limited', 2)
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(1, 1)), \
                patch.object(request_limits, '_reserve_rpm', side_effect=error):
            with self.assertRaises(request_limits.RateLimitError) as caught:
                with request_limits.admit('u'):
                    self.fail('must not enter')
            self.assertIs(caught.exception, error)
        self.assertEqual(request_limits._inflight, {})

    def test_simultaneous_admissions_never_exceed_cap(self):
        barrier = threading.Barrier(9)
        outcomes = queue.Queue()
        release = threading.Event()
        def attempt():
            barrier.wait(5)
            try:
                with request_limits.admit('u'):
                    outcomes.put('accepted')
                    if not release.wait(5):
                        raise TimeoutError('test did not release')
            except request_limits.RateLimitError:
                outcomes.put('rejected')
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(0, 2)), \
                ThreadPoolExecutor(8) as pool:
            jobs = [pool.submit(attempt) for _ in range(8)]
            barrier.wait(5)
            try:
                statuses = [outcomes.get(timeout=5) for _ in range(8)]
                self.assertEqual(statuses.count('accepted'), 2)
                self.assertEqual(request_limits._inflight, {'u': 2})
            finally:
                release.set()
            for job in jobs:
                job.result()
        self.assertEqual(request_limits._inflight, {})

    def test_concurrent_slot_rejection_does_not_consume_rpm(self):
        entered = threading.Event()
        release = threading.Event()
        def holder():
            with request_limits.admit('u'):
                entered.set()
                self.assertTrue(release.wait(5))
        with patch.object(config, 'request_limits_config', return_value=config.RequestLimits(9, 1)), \
                patch.object(request_limits, '_reserve_rpm') as reserve, ThreadPoolExecutor(8) as pool:
            job = pool.submit(holder)
            self.assertTrue(entered.wait(5))
            try:
                for _ in range(12):
                    with self.assertRaises(request_limits.RateLimitError) as caught:
                        with request_limits.admit('u'):
                            self.fail('rejected')
                    self.assertEqual(caught.exception.code, 'concurrency_limit_exceeded')
                    self.assertEqual(caught.exception.retry_after, 1)
                with request_limits.admit('other'):
                    pass
            finally:
                release.set()
            job.result()
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(request_limits._inflight, {})


class FakeSession:
    def __init__(self, count=0, cleanup_error=False, times=None):
        self.count = count
        self.cleanup_error = cleanup_error
        self.times = iter(times or [datetime(2026, 10, 9, 12, 0, 30)] * 2)
        self.queries = []
        self.result = None

    def execute(self, statement):
        compiled = statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
        sql = str(compiled)
        self.queries.append((sql, compiled.params))
        if sql.startswith('DELETE') and self.cleanup_error:
            raise RuntimeError('cleanup failure')
        if sql.startswith('SELECT utc_timestamp'):
            self.result = {'now': next(self.times)}
        elif sql.startswith('SELECT request_rate_windows.request_count'):
            self.result = {'request_count': self.count}

        return self

    def scalar_one(self):
        return next(iter(self.result.values()))


class RPMTests(unittest.TestCase):
    def run_reservation(self, cursor, rpm=2):
        @contextmanager
        def transaction():
            yield cursor
        with patch.object(request_limits.session, 'unit_of_work', transaction):
            request_limits._reserve_rpm('u', rpm)

    def test_increment_and_retention_scope(self):
        cursor = FakeSession()
        self.run_reservation(cursor)
        sql = '\n'.join(q for q, _ in cursor.queries)
        self.assertIn('FOR UPDATE', sql)
        self.assertIn('UPDATE request_rate_windows', sql)
        self.assertNotIn('api_calls', sql)
        cleanup = next(q for q, _ in cursor.queries if q.startswith('DELETE'))
        self.assertIn('utc_timestamp(6) - INTERVAL 24 HOUR LIMIT 1000', cleanup)

    def test_exceeded_retry_after_and_no_increment(self):
        cursor = FakeSession(count=2)
        with self.assertRaises(request_limits.RateLimitError) as caught:
            self.run_reservation(cursor)
        self.assertEqual(caught.exception.retry_after, 30)
        self.assertFalse(any(q.startswith('UPDATE') for q, _ in cursor.queries))

    def test_cleanup_failure_denies(self):
        with self.assertRaises(RuntimeError):
            self.run_reservation(FakeSession(cleanup_error=True))

    def test_cleanup_connection_closes_before_quota_transaction(self):
        events = []
        @contextmanager
        def cleanup_cursor():
            events.append('cleanup')
            yield FakeSession()
            events.append('cleanup_closed')
        @contextmanager
        def quota_transaction():
            self.assertEqual(events, ['cleanup', 'cleanup_closed'])
            events.append('quota')
            yield FakeSession()
        contexts = iter([cleanup_cursor, quota_transaction])
        with patch.object(request_limits.session, 'unit_of_work', side_effect=lambda: next(contexts)()):
            request_limits._reserve_rpm('u', 2)
        self.assertEqual(events, ['cleanup', 'cleanup_closed', 'quota'])

    def test_commit_failure_denies_before_body(self):
        cursor = FakeSession()
        @contextmanager
        def failed_commit():
            yield cursor
            raise RuntimeError('commit failed')
        @contextmanager
        def cleanup_cursor():
            yield cursor
        contexts = iter([cleanup_cursor, failed_commit])
        with patch.object(request_limits.session, 'unit_of_work', side_effect=lambda: next(contexts)()), \
                patch.object(config, 'request_limits_config', return_value=config.RequestLimits(2, 1)):
            with self.assertRaises(request_limits.RateLimitError) as caught:
                with request_limits.admit('u'):
                    self.fail('body must not run before counter commit')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(request_limits._inflight, {})

    def test_midnight_boundary_retries_new_window(self):
        first = FakeSession(times=[datetime(2026, 10, 9, 23, 59, 59), datetime(2026, 10, 10, 0, 0)])
        second = FakeSession(times=[datetime(2026, 10, 10, 0, 0)] * 2)
        cursors = iter([first, second])
        @contextmanager
        def transaction():
            yield next(cursors)
        @contextmanager
        def cleanup_cursor():
            yield FakeSession()
        contexts = iter([cleanup_cursor, transaction, transaction])
        with patch.object(request_limits.session, 'unit_of_work', side_effect=lambda: next(contexts)()):
            request_limits._reserve_rpm('u', 2)
        self.assertFalse(any(q.startswith('UPDATE') for q, _ in first.queries))
        self.assertTrue(any(q.startswith('UPDATE') for q, _ in second.queries))

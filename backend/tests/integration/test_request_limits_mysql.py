"""Opt-in real MySQL admission checks in a disposable Compose project.

Row locks, transactions, migrations and process restart use MySQL. Only the
UTC clock query is controlled to make minute-boundary assertions deterministic.
No live deployment, .env, model or upstream is used.
"""

import os
from pathlib import Path
import secrets
import subprocess
import textwrap
import unittest
import uuid


from tests.support.paths import ROOT

_CLOCKED_DB = textwrap.dedent('''
    from contextlib import contextmanager
    from datetime import datetime, timedelta
    from unittest.mock import patch
    from app.db import session

    real_transaction = session.transaction
    class ClockCursor:
        def __init__(self, cursor):
            self.cursor = cursor
            self.clock_query = False
        def execute(self, statement, parameters=None):
            self.clock_query = statement == 'SELECT UTC_TIMESTAMP(6) AS now'
            if not self.clock_query:
                return self.cursor.execute(statement, parameters)
        def fetchone(self):
            if self.clock_query:
                return {'now': controlled_now}
            return self.cursor.fetchone()
        def __getattr__(self, name):
            return getattr(self.cursor, name)
    @contextmanager
    def clocked_transaction():
        with real_transaction() as cursor:
            yield ClockCursor(cursor)
''')

_MYSQL_CHECK = textwrap.dedent('''
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import os
    import secrets
    import subprocess
    import sys
    import uuid
    from app.db import migrations
    from app.services import api_keys, inference, request_limits

    migrations.init_db()
    migrations.init_db()
    assert '0009_request_rate_windows.sql' in migrations.MIGRATIONS
    with session.cursor() as cursor:
        cursor.execute('SELECT UTC_TIMESTAMP(6) AS now')
        controlled_now = cursor.fetchone()['now'].replace(second=10, microsecond=0)

    def new_user():
        user_id = str(uuid.uuid4())
        email = user_id + '@example.invalid'
        with session.cursor() as cursor:
            cursor.execute('INSERT INTO users (id, email, email_normalized, password_hash, '
                           'created_at, updated_at) VALUES (%s, %s, %s, %s, '
                           'UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))',
                           (user_id, email, email, secrets.token_urlsafe(32)))
        return user_id

    def snapshot():
        with session.cursor() as cursor:
            cursor.execute('SELECT * FROM api_calls ORDER BY id')
            calls = cursor.fetchall()
            cursor.execute('SELECT * FROM usage_charges ORDER BY id')
            return calls, cursor.fetchall()

    user_id = new_user()
    other_user = new_user()
    key_id = str(uuid.uuid4())
    with session.cursor() as cursor:
        cursor.execute('INSERT INTO api_keys (id, user_id, name, key_hash, display_prefix, '
                       'last_four, created_at) VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(3))',
                       (key_id, user_id, 'synthetic history',
                        hashlib.sha256(secrets.token_bytes(32)).hexdigest(), 'synthetic', '0000'))
        cursor.execute('INSERT INTO request_rate_windows (user_id, window_start, request_count) '
                       'VALUES (%s, %s, 3)',
                       (user_id, controlled_now - timedelta(hours=25)))
    call = inference.begin('/v1/predict', api_keys.Principal(user_id, key_id, 'synthetic'), 'multilingual')
    inference.succeeded(call, {'input_tokens': 100, 'output_tokens': 0})
    history = snapshot()
    assert len(history[0]) == len(history[1]) == 1

    # A repeated terminal callback must neither rewrite history nor charge again.
    with ThreadPoolExecutor(max_workers=8) as pool:
        amounts = list(pool.map(lambda _: inference.succeeded(
            call, {'input_tokens': 100, 'output_tokens': 0}), range(8)))
    assert all(amount == amounts[0] for amount in amounts)
    assert snapshot() == history
    for finish in (lambda: inference.failed(call, 'synthetic failure', 500),
                   lambda: inference.interrupted(call, 'synthetic interruption', 503),
                   lambda: inference.succeeded(call, {'input_tokens': 101, 'output_tokens': 0})):
        try:
            finish()
            raise AssertionError('settled call must not be overwritten')
        except inference.CallStateConflict:
            pass
    assert snapshot() == history

    os.environ['LAYA_USER_RPM'] = '3'
    os.environ['LAYA_USER_MAX_INFLIGHT'] = '0'
    def enter(_):
        try:
            with request_limits.admit(user_id):
                return 'accepted'
        except request_limits.RateLimitError as error:
            assert error.status_code == 429
            assert error.code == 'rate_limit_exceeded'
            assert error.retry_after == 50
            return 'rejected'

    with patch.object(session, 'transaction', clocked_transaction):
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(enter, range(12)))
        assert outcomes.count('accepted') == 3
        assert outcomes.count('rejected') == 9
        with request_limits.admit(other_user):
            pass
    with session.cursor() as cursor:
        cursor.execute('SELECT request_count FROM request_rate_windows WHERE user_id = %s', (user_id,))
        assert cursor.fetchall() == [{'request_count': 3}]
    assert snapshot() == history

    # A separate Python interpreter shares only the persistent MySQL rows.
    restart_code = _CLOCK_SOURCE + """
    import os, sys
    from app.services import request_limits
    controlled_now = datetime.fromisoformat(sys.argv[2])
    with patch.object(session, 'transaction', clocked_transaction):
        try:
            with request_limits.admit(sys.argv[1]):
                raise AssertionError('restart reset the minute budget')
        except request_limits.RateLimitError as error:
            assert error.code == 'rate_limit_exceeded' and error.status_code == 429
        controlled_now += timedelta(minutes=1)
        with request_limits.admit(sys.argv[1]):
            pass
    """
    restarted = subprocess.run([sys.executable, '-c', restart_code, user_id, controlled_now.isoformat()],
                               capture_output=True, text=True, timeout=30)
    assert restarted.returncode == 0, 'separate-process persistence/window check failed'
    with session.cursor() as cursor:
        cursor.execute('SELECT request_count FROM request_rate_windows WHERE user_id = %s '
                       'ORDER BY window_start', (user_id,))
        assert cursor.fetchall() == [{'request_count': 3}, {'request_count': 1}]

    os.environ['LAYA_USER_RPM'] = '0'
    os.environ['LAYA_USER_MAX_INFLIGHT'] = '1'
    with request_limits.admit(user_id):
        try:
            with request_limits.admit(user_id):
                raise AssertionError('concurrent slot exceeded')
        except request_limits.RateLimitError as error:
            assert error.code == 'concurrency_limit_exceeded' and error.retry_after == 1
    try:
        with request_limits.admit(user_id):
            raise RuntimeError('synthetic settlement failure')
    except RuntimeError:
        pass
    with request_limits.admit(user_id):
        pass
    assert user_id not in request_limits._inflight

    # Deliberate schema fault is confined to this random disposable project.
    with session.cursor() as cursor:
        cursor.execute('DROP TABLE request_rate_windows')
    os.environ['LAYA_USER_RPM'] = '3'
    with patch.object(session, 'transaction', clocked_transaction):
        try:
            with request_limits.admit(user_id):
                raise AssertionError('storage failure must fail closed')
        except request_limits.RateLimitError as error:
            assert error.status_code == 503 and error.code == 'rate_limit_unavailable'
    assert user_id not in request_limits._inflight
    migrations.init_db()
    with patch.object(session, 'transaction', clocked_transaction):
        with request_limits.admit(user_id):
            pass
    assert snapshot() == history
    # A completed model with failed business postprocessing retains usage, never a fee.
    failed_call = inference.begin('/v1/customer-service/analyze',
                                  api_keys.Principal(user_id, key_id, 'synthetic'), 'multilingual')
    inference.mark_running(failed_call)
    inference.keep_usage(failed_call, {'input_tokens': 17, 'output_tokens': 0})
    inference.failed(failed_call, 'inference_error', 500)
    with session.cursor() as cursor:
        cursor.execute('SELECT status, input_tokens, output_tokens, billing_status FROM api_calls '
                       'WHERE id = %s', (failed_call.id,))
        assert cursor.fetchone() == {'status': 'failed', 'input_tokens': 17,
                                     'output_tokens': 0, 'billing_status': 'not_billable'}
        cursor.execute('SELECT COUNT(*) AS count FROM usage_charges WHERE call_id = %s',
                       (failed_call.id,))
        assert cursor.fetchone()['count'] == 0
    print('isolated-mysql-admission-ok')
''')


@unittest.skipUnless(os.environ.get('LAYA_TEST_COMPOSE') == '1',
                     '真实 MySQL 验证需显式 LAYA_TEST_COMPOSE=1')
class RequestLimitsMySQLTests(unittest.TestCase):
    def test_atomic_windows_restart_cleanup_and_fail_closed(self):
        image = os.environ.get('LAYA_TEST_IMAGE')
        self.assertTrue(image, '必须显式提供已构建的 LAYA_TEST_IMAGE')
        project = 'laya-limit-' + uuid.uuid4().hex[:12]
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MYSQL_', 'LAYA_', 'UPSTREAM_', 'COMPOSE_')) and key != 'APP_PORT'}
        env.update(MYSQL_DATABASE='laya_limit_test', MYSQL_USER='laya_limit_test',
                   MYSQL_PASSWORD=secrets.token_urlsafe(32), MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(32),
                   APP_PORT=os.environ.get('LAYA_TEST_PORT', '8013'), LAYA_IMAGE=image,
                   UPSTREAM_API_KEY='', LAYA_USER_RPM='0', LAYA_USER_MAX_INFLIGHT='0')
        prefix = ['docker', 'compose', '--env-file', os.devnull, '-f', str(ROOT / 'compose.yaml'), '-p', project]

        def run(*args, timeout=240):
            result = subprocess.run([*prefix, *args], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=timeout)
            # Do not echo env, commands or driver output that could contain passwords.
            self.assertEqual(result.returncode, 0, '隔离限流 MySQL 测试操作失败；检查测试镜像与环境')
            return result

        try:
            run('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'app', 'db', timeout=300)
            code = '_CLOCK_SOURCE = ' + repr(_CLOCKED_DB) + '\n' + _CLOCKED_DB + _MYSQL_CHECK
            result = run('exec', '-T', 'app', 'python', '-c', code, timeout=90)
            self.assertIn('isolated-mysql-admission-ok', result.stdout)
        finally:
            # Only this test-generated project and its synthetic database are removed.
            run('down', '--volumes', '--remove-orphans', timeout=90)

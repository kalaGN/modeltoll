"""Explicit opt-in: recovery and deduplication with disposable real MySQL.

Only synthetic data in a random Compose project is created and removed. No
live .env, model inference, external upstream or live database is accessed.
"""

import os
from pathlib import Path
import secrets
import subprocess
import textwrap
import unittest
import uuid


from tests.support.paths import ROOT

_SCENARIO = textwrap.dedent('''
    from concurrent.futures import ThreadPoolExecutor
    from decimal import Decimal
    import hashlib
    import json
    import secrets
    import subprocess
    import sys
    import uuid
    from pymysql.err import OperationalError
    from app.db import migrations, session
    from app.services import api_keys, idempotency, inference, inference_recovery

    # Report only exception type and line positions, never driver messages or values.
    def safe_failure(kind, error, traceback):
        import traceback as traceback_module
        lines = ','.join(str(frame.lineno) for frame in traceback_module.extract_tb(traceback))
        print('recovery-failure:' + kind.__name__ + ':lines=' + lines, flush=True)
    sys.excepthook = safe_failure

    migrations.init_db()
    migrations.init_db()

    def new_user():
        user_id = str(uuid.uuid4())
        email = user_id + '@example.invalid'
        with session.cursor() as cursor:
            cursor.execute('INSERT INTO users (id, email, email_normalized, password_hash, '
                           'created_at, updated_at) VALUES (%s, %s, %s, %s, '
                           'UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))',
                           (user_id, email, email, secrets.token_urlsafe(32)))
        return user_id

    def new_key(user_id):
        key_id = str(uuid.uuid4())
        with session.cursor() as cursor:
            cursor.execute('INSERT INTO api_keys (id, user_id, name, key_hash, display_prefix, '
                           'last_four, created_at) VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(3))',
                           (key_id, user_id, 'synthetic',
                            hashlib.sha256(secrets.token_bytes(32)).hexdigest(), 'synthetic', '0000'))
        return api_keys.Principal(user_id, key_id, 'synthetic')

    def query(statement, parameters=None):
        with session.cursor() as cursor:
            cursor.execute(statement, parameters)
            return list(cursor.fetchall())

    def snapshot():
        return {table: query('SELECT * FROM ' + table + ' ORDER BY 1')
                for table in ('api_calls', 'usage_charges', 'inference_success_receipts', 'request_idempotency')}

    def begin(principal, prepared=None):
        return inference.begin('/v1/predict', principal, 'multilingual', idempotency=prepared)

    user = new_user()
    principal = new_key(user)
    other_key = new_key(user)
    other_user_key = new_key(new_user())
    raw_key = secrets.token_urlsafe(24)
    marker = 'synthetic-body-' + uuid.uuid4().hex
    body = {'text': marker, 'parameters': {'b': 2, 'a': 1}}
    prepared = idempotency.prepare(raw_key, '/v1/predict', 'multilingual', body)
    equivalent = idempotency.prepare(raw_key, '/v1/predict', 'multilingual',
                                    {'parameters': {'a': 1, 'b': 2}, 'text': marker})
    assert prepared == equivalent
    def competing_begin(_):
        try:
            return ('accepted', begin(principal, prepared).id)
        except inference.IdempotencyConflict as error:
            assert error.code == 'request_already_processed'
            return ('duplicate', error.call_id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(competing_begin, range(8)))
    accepted = [call_id for status, call_id in results if status == 'accepted']
    assert len(accepted) == 1
    assert all(call_id == accepted[0] for _, call_id in results)
    assert len(query('SELECT * FROM api_calls')) == 1
    for candidate, fingerprint, expected in (
            (other_key, equivalent, 'request_already_processed'),
            (principal, idempotency.prepare(raw_key, '/v1/predict', 'multilingual',
                                           {'text': marker + '-different'}), 'idempotency_conflict')):
        try:
            begin(candidate, fingerprint)
            raise AssertionError('duplicate should not create another call')
        except inference.IdempotencyConflict as error:
            assert error.code == expected and error.call_id == accepted[0]
    assert begin(other_user_key, prepared).id != accepted[0]

    # A database fault aborts both accepted-call and deduplication rows.
    rollback_key = secrets.token_urlsafe(24)
    rollback_prepared = idempotency.prepare(rollback_key, '/v1/predict', 'multilingual', body)
    before = snapshot()
    with session.cursor() as cursor:
        cursor.execute("CREATE TRIGGER smoke_recovery_admission BEFORE INSERT ON request_idempotency "
                       "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'synthetic admission fault'")
    try:
        try:
            begin(principal, rollback_prepared)
            raise AssertionError('injected insert failure ignored')
        except OperationalError:
            pass
    finally:
        with session.cursor() as cursor:
            cursor.execute('DROP TRIGGER smoke_recovery_admission')
    assert snapshot() == before
    assert begin(principal, rollback_prepared).id

    usage = {'input_tokens': 1000000, 'output_tokens': 2, 'truncated': False,
             'state_tokens_dropped': 0}
    call = begin(principal)
    inference.mark_running(call)
    inference.capture_success(call, usage)
    receipt = query('SELECT * FROM inference_success_receipts WHERE call_id = %s', (call.id,))[0]
    with session.cursor() as cursor:
        cursor.execute("CREATE TRIGGER smoke_recovery_fee BEFORE INSERT ON usage_charges "
                       "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'synthetic settlement fault'")
    try:
        try:
            inference.succeeded(call, usage)
            raise AssertionError('injected fee failure ignored')
        except OperationalError:
            pass
    finally:
        with session.cursor() as cursor:
            cursor.execute('DROP TRIGGER smoke_recovery_fee')
    assert query('SELECT status, billing_status FROM api_calls WHERE id = %s', (call.id,)) == [
        {'status': 'running', 'billing_status': 'pending'}]
    assert query('SELECT * FROM inference_success_receipts WHERE call_id = %s', (call.id,)) == [receipt]
    assert query('SELECT * FROM usage_charges WHERE call_id = %s', (call.id,)) == []

    # Current price changes, but recovery must retain this call's original rule.
    with session.cursor() as cursor:
        cursor.execute('INSERT INTO pricing_rules (id, version, model, currency, token_basis, '
                       'unit_tokens, unit_price_yuan, billing_policy_version, effective_from, created_at) '
                       "VALUES (%s, %s, 'multilingual', 'CNY', 'laya_usage_input_tokens', 1000000, "
                       "9.000000, 'succeeded_only_v1', UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
                       (str(uuid.uuid4()), uuid.uuid4().hex[:20]))
    before_inspect = snapshot()
    inspection = inference_recovery.inspect_calls(limit=100, call_id=call.id)
    assert inspection[0]['classification'] == 'pending'
    assert snapshot() == before_inspect
    cli = subprocess.run([sys.executable, '-m', 'app.manage', 'recover-calls', '--call-id', call.id],
                         capture_output=True, text=True, timeout=30)
    assert cli.returncode == 0 and json.loads(cli.stdout)
    assert snapshot() == before_inspect
    with ThreadPoolExecutor(max_workers=8) as pool:
        amounts = list(pool.map(lambda _: inference_recovery.recover(call.id), range(8)))
    assert amounts == [Decimal('1.000000')] * 8
    settled = snapshot()
    assert inference_recovery.recover(call.id) == Decimal('1.000000')
    assert inference.succeeded(call, usage) == Decimal('1.000000')
    assert snapshot() == settled
    charges = query('SELECT * FROM usage_charges WHERE call_id = %s', (call.id,))
    assert len(charges) == 1 and charges[0]['pricing_rule_id'] == call.rule.id
    assert charges[0]['amount_yuan'] == Decimal('1.000000')
    terminal = query('SELECT completed_at, duration_ms FROM api_calls WHERE id = %s', (call.id,))[0]
    assert terminal == {'completed_at': receipt['completed_at'], 'duration_ms': receipt['duration_ms']}

    # Normal settlement and explicit recovery race on the same trusted success.
    raced = begin(principal)
    inference.mark_running(raced)
    inference.capture_success(raced, usage)
    with ThreadPoolExecutor(max_workers=8) as pool:
        mixed = list(pool.map(lambda index: inference.succeeded(raced, usage) if index % 2
                             else inference_recovery.recover(raced.id), range(8)))
    assert all(amount == mixed[0] for amount in mixed)
    assert len(query('SELECT * FROM usage_charges WHERE call_id = %s', (raced.id,))) == 1

    # CLI apply is explicit and repeatable; default inspect never writes.
    cli_call = begin(principal)
    inference.mark_running(cli_call)
    inference.capture_success(cli_call, usage)
    original = snapshot()
    default = subprocess.run([sys.executable, '-m', 'app.manage', 'recover-calls'],
                             capture_output=True, text=True, timeout=30)
    assert default.returncode == 0 and json.loads(default.stdout)
    assert snapshot() == original
    for _ in range(2):
        applied = subprocess.run([sys.executable, '-m', 'app.manage', 'recover-calls',
                                  '--apply', '--call-id', cli_call.id],
                                 capture_output=True, text=True, timeout=30)
        assert applied.returncode == 0
        assert Decimal(json.loads(applied.stdout)['amount_yuan']) == Decimal('9.000000')
    assert len(query('SELECT * FROM usage_charges WHERE call_id = %s', (cli_call.id,))) == 1

    unknown = begin(principal)
    inference.mark_running(unknown)
    with session.cursor() as cursor:
        cursor.execute("UPDATE api_calls SET started_at = '2000-01-01' WHERE id = %s", (unknown.id,))
    failed = begin(principal)
    inference.failed(failed, 'synthetic failure', 500)
    failed_with_receipt = begin(principal)
    inference.mark_running(failed_with_receipt)
    inference.capture_success(failed_with_receipt, usage)
    with session.cursor() as cursor:
        cursor.execute("UPDATE api_calls SET status = 'failed', billing_status = 'not_billable', "
                       "http_status = 500, error_code = 'synthetic contradiction', "
                       'completed_at = UTC_TIMESTAMP(3) WHERE id = %s', (failed_with_receipt.id,))
    contradiction = begin(principal)
    inference.mark_running(contradiction)
    inference.capture_success(contradiction, usage)
    with session.cursor() as cursor:
        cursor.execute('INSERT INTO usage_charges (id, call_id, pricing_rule_id, billable_input_tokens, '
                       'unit_tokens, unit_price_yuan, amount_yuan, currency, created_at) '
                       "VALUES (%s, %s, %s, 1, 1000000, 9.000000, 1.000000, 'CNY', UTC_TIMESTAMP(3))",
                       (str(uuid.uuid4()), contradiction.id, contradiction.rule.id))
    protected = snapshot()
    for call_id in (unknown.id, failed.id, failed_with_receipt.id, contradiction.id, str(uuid.uuid4())):
        try:
            inference_recovery.recover(call_id)
            raise AssertionError('untrusted or contradictory call recovered')
        except inference.CallStateConflict:
            pass
    assert snapshot() == protected

    rows = query('SELECT * FROM request_idempotency')
    assert len(rows) == 3
    assert all(set(row) == {'user_id', 'key_hash', 'request_hash', 'call_id', 'created_at'} for row in rows)
    assert all(len(row['key_hash']) == len(row['request_hash']) == 64 for row in rows)
    assert raw_key not in repr(rows) and marker not in repr(rows)
    receipt_columns = {'call_id', 'input_tokens', 'output_tokens', 'truncated',
                       'state_tokens_dropped', 'completed_at', 'duration_ms'}
    assert all(set(row) == receipt_columns for row in query('SELECT * FROM inference_success_receipts'))
    assert marker not in repr(inspection) and raw_key not in repr(inspection)

    # Real HTTP routes + real SQL; only the model/authentication use synthetic fixtures.
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from app.main import app
    from app.schemas.gateway import ConnectionRequest
    from app.services import billing, gateway
    connection = ConnectionRequest(base_url='http://127.0.0.1:11434/v1',
                                   model='multilingual', enabled=True)
    request_body = {'model': 'multilingual', 'messages': [{'role': 'user', 'content': 'synthetic'}]}
    headers = {'Authorization': 'Bearer synthetic', 'Idempotency-Key': str(uuid.uuid4())}
    with TestClient(app, raise_server_exceptions=False) as client, \\
         patch.object(api_keys, 'authenticate', return_value=principal), \\
         patch.object(api_keys, 'still_valid', return_value=True), \\
         patch.object(gateway, 'connection', return_value=connection), \\
         patch.object(gateway, 'chat', return_value=({'synthetic': 'ok'}, {'input_tokens': 10})) as model:
        with patch.object(billing, 'insert_charge', side_effect=RuntimeError('synthetic charge fault')):
            failed_http = client.post('/v1/chat/completions', json=request_body, headers=headers)
        assert failed_http.status_code == 500
        http_call_id = failed_http.headers['X-Request-Id']
        assert failed_http.json()['code'] == 'billing_unavailable'
        assert len(query('SELECT * FROM inference_success_receipts WHERE call_id = %s', (http_call_id,))) == 1
        assert query('SELECT * FROM usage_charges WHERE call_id = %s', (http_call_id,)) == []
        repeated = client.post('/v1/chat/completions', json=request_body, headers=headers)
        assert repeated.status_code == 409 and repeated.json()['call_id'] == http_call_id
        assert model.call_count == 1
        first_amount = inference_recovery.recover(http_call_id)
        assert inference_recovery.recover(http_call_id) == first_amount
        recovered_repeat = client.post('/v1/chat/completions', json=request_body, headers=headers)
        assert recovered_repeat.status_code == 409 and model.call_count == 1
        assert len(query('SELECT * FROM usage_charges WHERE call_id = %s', (http_call_id,))) == 1
        headers['Idempotency-Key'] = str(uuid.uuid4())
        success_http = client.post('/v1/chat/completions', json=request_body, headers=headers)
        assert success_http.status_code == 200 and model.call_count == 2
    print('isolated-mysql-recovery-ok')
''')


@unittest.skipUnless(os.environ.get('LAYA_TEST_COMPOSE') == '1',
                     '真实 MySQL 恢复验证需显式 LAYA_TEST_COMPOSE=1')
class RecoveryMySQLTests(unittest.TestCase):
    def test_deduplication_receipt_recovery_and_cli(self):
        image = os.environ.get('LAYA_TEST_IMAGE')
        self.assertTrue(image, '必须显式提供已构建的 LAYA_TEST_IMAGE')
        project = 'laya-recover-' + uuid.uuid4().hex[:12]
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MYSQL_', 'LAYA_', 'UPSTREAM_', 'COMPOSE_')) and key != 'APP_PORT'}
        env.update(MYSQL_DATABASE='laya_recovery_test', MYSQL_USER='laya_recovery_test',
                   MYSQL_PASSWORD=secrets.token_urlsafe(32), MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(32),
                   APP_PORT=os.environ.get('LAYA_TEST_PORT', '8014'), LAYA_IMAGE=image,
                   UPSTREAM_API_KEY='', LAYA_USER_RPM='0', LAYA_USER_MAX_INFLIGHT='0')
        prefix = ['docker', 'compose', '--env-file', os.devnull, '-f', str(ROOT / 'compose.yaml'), '-p', project]

        def run(*args, timeout=240):
            result = subprocess.run([*prefix, *args], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=timeout)
            safe_diagnostic = next((line for line in result.stdout.splitlines()
                                    if line.startswith('recovery-failure:')), '')
            self.assertEqual(result.returncode, 0,
                             '隔离恢复 MySQL 测试操作失败；检查测试镜像与环境 ' + safe_diagnostic)
            return result

        try:
            run('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'app', 'db', timeout=300)
            # Only this disposable MySQL instance permits synthetic fault triggers.
            run('exec', '-T', 'db', 'sh', '-c',
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot '
                '-e "SET GLOBAL log_bin_trust_function_creators = 1"')
            result = run('exec', '-T', 'app', 'python', '-c', _SCENARIO, timeout=120)
            self.assertIn('isolated-mysql-recovery-ok', result.stdout)
        finally:
            # This random project and synthetic volume are the only cleanup targets.
            run('down', '--volumes', '--remove-orphans', timeout=90)

"""显式 opt-in 的容器 E2E：独立 Compose 项目，合成数据，结束删除测试专用卷。

先构建 LAYA_TEST_IMAGE，再设置 LAYA_TEST_COMPOSE=1；不读取真实 .env。
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import subprocess
import unittest
import uuid

import httpx

from tests.support.paths import ROOT


@unittest.skipUnless(os.environ.get('LAYA_TEST_COMPOSE') == '1', '容器 E2E 需显式 LAYA_TEST_COMPOSE=1')
class DeploymentRuntimeTests(unittest.TestCase):
    def test_isolated_stack_admin_race_auth_and_gateway(self):
        image = os.environ.get('LAYA_TEST_IMAGE')
        self.assertTrue(image, '必须显式提供已构建的 LAYA_TEST_IMAGE')
        frontend_image = os.environ.get('LAYA_TEST_FRONTEND_IMAGE')
        self.assertTrue(frontend_image, '必须显式提供已构建的 LAYA_TEST_FRONTEND_IMAGE')
        project = 'laya-smoke-' + uuid.uuid4().hex[:12]
        port = os.environ.get('LAYA_TEST_PORT', '8012')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MYSQL_', 'LAYA_', 'UPSTREAM_', 'COMPOSE_')) and key != 'APP_PORT'}
        env.update(MYSQL_DATABASE='laya_smoke', MYSQL_USER='laya_smoke',
                   MYSQL_PASSWORD=secrets.token_urlsafe(32), MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(32),
                   APP_PORT=port, LAYA_IMAGE=image, LAYA_FRONTEND_IMAGE=frontend_image, UPSTREAM_API_KEY='')
        prefix = ['docker', 'compose', '--env-file', os.devnull, '-f', str(ROOT / 'compose.yaml'), '-p', project]

        def run(*args, input_text=None, ok=True, timeout=240):
            result = subprocess.run([*prefix, *args], cwd=ROOT, env=env, input=input_text,
                                    text=True, capture_output=True, timeout=timeout)
            if ok:
                # 不把命令参数、CLI输入或解析后的Compose配置（可能含口令）输出到测试日志。
                self.assertEqual(result.returncode, 0, '隔离 Compose 操作失败，检查测试环境或镜像')
            return result

        def manage(*args, password=None, ok=True):
            return run('exec', '-T', 'app', 'python', '-m', 'app.manage', *args,
                       input_text=None if password is None else password + '\n', ok=ok)

        password = secrets.token_urlsafe(24)
        emails = ['ops-a@example.invalid', 'ops-b@example.invalid']
        try:
            run('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', timeout=300)
            manage('migrate')
            manage('migrate')  # DDL 重复执行，不改变现有数据。
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda email: manage('init-admin', '--email', email, '--password-stdin',
                                                             password=password, ok=False), emails))
            self.assertEqual(sorted(result.returncode for result in results), [0, 1])
            denied = next(result for result in results if result.returncode == 1)
            self.assertIn('平台已有管理员', denied.stderr)
            admin_email = emails[next(index for index, result in enumerate(results) if result.returncode == 0)]
            manage('init-admin', '--email', admin_email, '--password-stdin', password=secrets.token_urlsafe(24))

            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15, trust_env=False) as client:
                self.assertEqual(client.get('/health').json()['runtime'], 'external')
                self.assertEqual(client.get('/login').status_code, 200)
                csrf = client.get('/v1/auth/csrf').json()['csrf_token']
                headers = {'X-CSRF-Token': csrf}
                result = client.post('/v1/auth/login', headers=headers,
                                     json={'email': admin_email, 'password': password})
                self.assertEqual(result.status_code, 200)  # 幂等 CLI 没有重置原密码。
                self.assertIs(result.json()['user']['is_admin'], True)
                self.assertEqual(client.get('/admin/settings').status_code, 200)
                self.assertEqual(client.get('/v1/admin/overview').status_code, 200)
                self.assertEqual(client.put('/v1/admin/model-connection', headers=headers,
                                 json={'base_url': 'http://127.0.0.1:9/v1', 'model': 'fixture-model', 'enabled': True}).status_code, 200)
                self.assertEqual(client.post('/v1/auth/logout', headers=headers).status_code, 200)
                ordinary_email = 'ordinary@example.invalid'
                result = client.post('/v1/auth/register', headers=headers,
                                     json={'email': ordinary_email, 'password': password})
                self.assertEqual(result.status_code, 201)
                rejected = manage('init-admin', '--email', ordinary_email, '--password-stdin', password=password, ok=False)
                self.assertEqual(rejected.returncode, 1)
                result = client.post('/v1/auth/login', headers=headers,
                                     json={'email': ordinary_email, 'password': password})
                self.assertEqual(result.status_code, 200)
                self.assertIs(result.json()['user']['is_admin'], False)
                self.assertEqual(client.get('/v1/admin/overview').status_code, 403)
                self.assertEqual(client.get('/keys').status_code, 200)
                self.assertEqual(client.get('/v1/usage/summary').json()['totals']['calls_total'], 0)
                key_result = client.post('/v1/api-keys', headers=headers, json={'name': 'smoke'})
                self.assertEqual(key_result.status_code, 201)
                bearer = {'Authorization': 'Bearer ' + key_result.json()['secret']}
                self.assertEqual(client.get('/v1/models', headers=bearer).json()['data'][0]['id'], 'fixture-model')
                retry_headers = {**bearer, 'Idempotency-Key': uuid.uuid4().hex}
                result = client.post('/v1/chat/completions', headers=retry_headers,
                                     json={'model': 'fixture-model', 'messages': [{'role': 'user', 'content': '合成测试'}]})
                self.assertEqual(result.status_code, 502)  # 配置的是本容器未开放的端口，无真实推理。
                self.assertIn('X-Request-Id', result.headers)
                original_call_id = result.headers['X-Request-Id']
                duplicate = client.post('/v1/chat/completions', headers=retry_headers,
                                        json={'model': 'fixture-model', 'messages': [{'role': 'user', 'content': '合成测试'}]})
                self.assertEqual(duplicate.status_code, 409)
                self.assertEqual(duplicate.json()['call_id'], original_call_id)
                self.assertEqual(duplicate.headers['X-Request-Id'], original_call_id)
                totals = client.get('/v1/usage/summary').json()['totals']
                self.assertEqual(totals['calls_total'], 1)
                self.assertEqual(totals['calls_failed'], 1)
                self.assertEqual(totals['charged_amount_yuan'], '0')
                user_id = client.get('/v1/auth/me').json()['user']['id']
                key_id = key_result.json()['api_key']['id']
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15, trust_env=False) as admin:
                    admin_csrf = admin.get('/v1/auth/csrf').json()['csrf_token']
                    admin_headers = {'X-CSRF-Token': admin_csrf}
                    login = admin.post('/v1/auth/login', headers=admin_headers,
                                       json={'email': admin_email, 'password': password})
                    self.assertEqual(login.status_code, 200)
                    admin_id = login.json()['user']['id']
                    self.assertEqual(admin.get('/admin/users').status_code, 200)
                    self.assertEqual(client.get('/v1/admin/users').status_code, 403)
                    self.assertEqual(admin.patch(f'/v1/admin/users/{user_id}/status',
                                     json={'status': 'disabled', 'reason': '合成测试'}).status_code, 403)
                    self.assertEqual(admin.patch(f'/v1/admin/users/{admin_id}/status', headers=admin_headers,
                                     json={'status': 'disabled', 'reason': '保护边界测试'}).status_code, 409)
                    users = admin.get('/v1/admin/users', params={'q': ordinary_email, 'limit': 1}).json()
                    self.assertEqual(users['total'], 1)
                    self.assertEqual(users['items'][0]['id'], user_id)
                    self.assertNotIn('password_hash', users['items'][0])
                    keys = admin.get(f'/v1/admin/users/{user_id}/api-keys').json()['items']
                    self.assertEqual(keys[0]['id'], key_id)
                    self.assertNotIn('key_hash', keys[0])
                    self.assertNotIn('secret', keys[0])
                    disabled = admin.patch(f'/v1/admin/users/{user_id}/status', headers=admin_headers,
                                           json={'status': 'disabled', 'reason': '停用合成账号'})
                    self.assertEqual(disabled.status_code, 200)
                    self.assertTrue(disabled.json()['changed'])
                    self.assertEqual(client.get('/v1/auth/me').status_code, 401)
                    self.assertEqual(client.get('/v1/models', headers=bearer).status_code, 403)
                    duplicate = admin.patch(f'/v1/admin/users/{user_id}/status', headers=admin_headers,
                                            json={'status': 'disabled', 'reason': '重复停用'})
                    self.assertFalse(duplicate.json()['changed'])
                    enabled = admin.patch(f'/v1/admin/users/{user_id}/status', headers=admin_headers,
                                          json={'status': 'active', 'reason': '重新启用'})
                    self.assertEqual(enabled.status_code, 200)
                    self.assertEqual(client.get('/v1/auth/me').status_code, 401)
                    self.assertEqual(client.get('/v1/models', headers=bearer).status_code, 200)
                    revoked = admin.post(f'/v1/admin/api-keys/{key_id}/revoke', headers=admin_headers,
                                         json={'reason': '管理员撤销合成Key'})
                    self.assertEqual(revoked.status_code, 200)
                    self.assertTrue(revoked.json()['changed'])
                    self.assertEqual(client.get('/v1/models', headers=bearer).status_code, 401)
                    self.assertFalse(admin.post(f'/v1/admin/api-keys/{key_id}/revoke', headers=admin_headers,
                                                json={'reason': '重复撤销'}).json()['changed'])
                    audit = admin.get('/v1/admin/audit-events', params={'limit': 1}).json()
                    self.assertEqual(audit['total'], 3)
                    self.assertTrue(audit['has_more'])
                    self.assertEqual(audit['items'][0]['action'], 'api_key.revoked')
                    self.assertEqual(audit['items'][0]['target_key_id'], key_id)
                    self.assertEqual(audit['items'][0]['actor_id'], admin_id)
                self.assertEqual(client.post('/v1/auth/login', headers=headers,
                                 json={'email': ordinary_email, 'password': password}).status_code, 200)
                self.assertEqual(client.get('/v1/usage/summary').json()['totals'], totals)
                historical = client.post('/v1/api-keys', headers=headers, json={'name': '历史软删除测试'}).json()['api_key']['id']
                self.assertEqual(client.post(f'/v1/api-keys/{historical}/revoke', headers=headers,
                                            json={}).status_code, 200)
                self.assertEqual(client.delete(f'/v1/api-keys/{historical}', headers=headers).status_code, 200)
                # Deliberate unhandled 500 responses cause Uvicorn to close the
                # connection. Avoid racing that close with the next rollback
                # assertion; no request is retried and all assertions still run.
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15, trust_env=False,
                                  limits=httpx.Limits(max_keepalive_connections=0)) as admin:
                    admin_headers = {'X-CSRF-Token': admin.get('/v1/auth/csrf').json()['csrf_token']}
                    self.assertEqual(admin.post('/v1/auth/login', headers=admin_headers,
                                     json={'email': admin_email, 'password': password}).status_code, 200)
                    historical_keys = admin.get(f'/v1/admin/users/{user_id}/api-keys').json()['items']
                    deleted_key = next(key for key in historical_keys if key['id'] == historical)
                    self.assertEqual(deleted_key['status'], 'deleted')
                    self.assertIsNotNone(deleted_key['deleted_at'])
                    self.assertFalse(admin.post(f'/v1/admin/api-keys/{historical}/revoke', headers=admin_headers,
                                                json={'reason': '已删除无变更'}).json()['changed'])
                    self.assertEqual(admin.get('/v1/admin/audit-events').json()['total'], 3)
                    rollback_key = client.post('/v1/api-keys', headers=headers,
                                               json={'name': '真实回滚验证'}).json()
                    rollback_bearer = {'Authorization': 'Bearer ' + rollback_key['secret']}
                    rollback_id = rollback_key['api_key']['id']
                    # MySQL binary logging otherwise requires SUPER to create
                    # triggers. Relax only this disposable test DB instance.
                    run('exec', '-T', 'db', 'sh', '-c',
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot '
                        '-e "SET GLOBAL log_bin_trust_function_creators = 1"')
                    # Test-only DB trigger forces the audit INSERT to fail. The
                    # generated Compose database is disposable and isolated.
                    run('exec', '-T', 'app', 'python', '-c',
                        "from app.db.engine import get_engine\nwith get_engine().begin() as connection:\n"
                        " connection.exec_driver_sql(\"CREATE TRIGGER smoke_audit_failure BEFORE INSERT ON admin_audit_events "
                        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'synthetic audit failure'\")")
                    try:
                        failed_status = admin.patch(f'/v1/admin/users/{user_id}/status', headers=admin_headers,
                                                    json={'status': 'disabled', 'reason': '数据库回滚测试'})
                        self.assertEqual(failed_status.status_code, 500)
                        self.assertEqual(admin.get('/v1/admin/users', params={'q': ordinary_email}).json()
                                         ['items'][0]['status'], 'active')
                        self.assertEqual(client.get('/v1/auth/me').status_code, 200)
                        self.assertEqual(client.get('/v1/models', headers=rollback_bearer).status_code, 200)
                        failed_key = admin.post(f'/v1/admin/api-keys/{rollback_id}/revoke', headers=admin_headers,
                                                json={'reason': 'Key数据库回滚测试'})
                        self.assertEqual(failed_key.status_code, 500)
                        self.assertEqual(client.get('/v1/models', headers=rollback_bearer).status_code, 200)
                        self.assertEqual(admin.get('/v1/admin/audit-events').json()['total'], 3)
                        self.assertEqual(client.get('/v1/usage/summary').json()['totals'], totals)
                    finally:
                        run('exec', '-T', 'app', 'python', '-c',
                            "from app.db.engine import get_engine\nwith get_engine().begin() as connection:\n"
                            " connection.exec_driver_sql('DROP TRIGGER smoke_audit_failure')")
        finally:
            # 唯一随机项目名，只包含本测试创建的数据；绝不使用真实部署 project。
            run('down', '--volumes', '--remove-orphans', timeout=90)

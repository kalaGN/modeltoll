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

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('LAYA_TEST_COMPOSE') == '1', '容器 E2E 需显式 LAYA_TEST_COMPOSE=1')
class DeploymentRuntimeTests(unittest.TestCase):
    def test_isolated_stack_admin_race_auth_and_gateway(self):
        image = os.environ.get('LAYA_TEST_IMAGE')
        self.assertTrue(image, '必须显式提供已构建的 LAYA_TEST_IMAGE')
        project = 'laya-smoke-' + uuid.uuid4().hex[:12]
        port = os.environ.get('LAYA_TEST_PORT', '8012')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MYSQL_', 'LAYA_', 'UPSTREAM_', 'COMPOSE_')) and key != 'APP_PORT'}
        env.update(MYSQL_DATABASE='laya_smoke', MYSQL_USER='laya_smoke',
                   MYSQL_PASSWORD=secrets.token_urlsafe(32), MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(32),
                   APP_PORT=port, LAYA_IMAGE=image, UPSTREAM_API_KEY='')
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
                result = client.post('/v1/chat/completions', headers=bearer,
                                     json={'model': 'fixture-model', 'messages': [{'role': 'user', 'content': '合成测试'}]})
                self.assertEqual(result.status_code, 502)  # 配置的是本容器未开放的端口，无真实推理。
                self.assertIn('X-Request-Id', result.headers)
                totals = client.get('/v1/usage/summary').json()['totals']
                self.assertEqual(totals['calls_total'], 1)
                self.assertEqual(totals['calls_failed'], 1)
                self.assertEqual(totals['charged_amount_yuan'], '0')
        finally:
            # 唯一随机项目名，只包含本测试创建的数据；绝不使用真实部署 project。
            run('down', '--volumes', '--remove-orphans', timeout=90)

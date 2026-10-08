"""Deployment contract checks. These do not prove an image can run."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DockerfileContractTests(unittest.TestCase):
    def test_external_image_is_minimal_non_root_and_single_worker(self):
        source = (ROOT / 'Dockerfile').read_text()
        self.assertIn('FROM node:22-bookworm-slim AS frontend', source)
        self.assertIn('RUN npm ci', source)
        self.assertIn('RUN npm run build', source)
        self.assertIn('FROM python:3.12-slim-bookworm AS runtime', source)
        self.assertIn('LAYA_RUNTIME=external', source)
        self.assertIn('USER 10001:10001', source)
        self.assertIn('"--workers", "1"', source)
        self.assertNotIn('COPY . ', source)
        self.assertNotIn('COPY .env', source)
        self.assertIn('COPY backend/migrations', source)
        self.assertIn('COPY --from=frontend', source)
        requirements = (ROOT / 'requirements-api.txt').read_text().lower()
        self.assertNotIn('torch', requirements)
        self.assertNotIn('laya', requirements)

    def test_build_context_allowlist_excludes_secrets_and_caches(self):
        patterns = (ROOT / '.dockerignore').read_text().splitlines()
        self.assertIn('**', patterns)
        self.assertIn('!backend/app/**', patterns)
        self.assertIn('!frontend/src/**', patterns)
        self.assertIn('**/.env', patterns)
        self.assertIn('**/.env.*', patterns)
        self.assertIn('**/__pycache__/', patterns)
        self.assertFalse(any(line.startswith('!') and '.env' in line for line in patterns))

    def test_example_has_no_default_password(self):
        env = dict(line.split('=', 1) for line in (ROOT / '.env.example').read_text().splitlines()
                   if line and not line.startswith('#'))
        self.assertEqual(env['MYSQL_PASSWORD'], '')
        self.assertEqual(env['MYSQL_ROOT_PASSWORD'], '')
        self.assertEqual(env['UPSTREAM_API_KEY'], '')

    def test_external_import_without_model_packages(self):
        code = '''
import importlib.abc
import sys
class NoModelPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'laya', 'torch', 'transformers'}:
            raise ImportError('Model package imported by external backend')
sys.meta_path.insert(0, NoModelPackages())
import app.main
assert '/v1/chat/completions' in app.main.app.openapi()['paths']
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'backend'), LAYA_RUNTIME='external')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, 'External backend imported model packages')


class ComposeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('docker'):
            raise unittest.SkipTest('Docker CLI unavailable; Compose config not verified')
        check = subprocess.run(['docker', 'compose', 'version'], capture_output=True)
        if check.returncode:
            raise unittest.SkipTest('Docker Compose unavailable; Compose config not verified')

    def compose_config(self, **overrides):
        # Ignore real .env and inherited credentials. Never print resolved config.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('MYSQL_', 'LAYA_', 'UPSTREAM_')) and k != 'APP_PORT'}
        env.update(MYSQL_DATABASE='laya_contract_test', MYSQL_USER='laya_test',
                   MYSQL_PASSWORD='synthetic-test-password',
                   MYSQL_ROOT_PASSWORD='synthetic-root-password')
        env.update(overrides)
        return subprocess.run(
            ['docker', 'compose', '--env-file', os.devnull, '-f', str(ROOT / 'compose.yaml'),
             'config', '--format', 'json'],
            cwd=ROOT, env=env, text=True, capture_output=True,
        )

    def test_loopback_persistent_database_and_health_dependency(self):
        result = self.compose_config()
        self.assertEqual(result.returncode, 0, 'Compose config failed')
        config = json.loads(result.stdout)
        app, db = config['services']['app'], config['services']['db']
        self.assertEqual(app['ports'][0]['host_ip'], '127.0.0.1')
        self.assertEqual(app['ports'][0]['published'], '8000')
        self.assertEqual(app['depends_on']['db']['condition'], 'service_healthy')
        self.assertEqual(app['environment']['LAYA_RUNTIME'], 'external')
        self.assertEqual(app['environment']['MYSQL_HOST'], 'db')
        self.assertNotIn('MYSQL_ROOT_PASSWORD', app['environment'])
        self.assertTrue(app['read_only'])
        self.assertEqual(db['image'], 'mysql:8.4')
        self.assertNotIn('ports', db)
        self.assertEqual(db['volumes'][0]['type'], 'volume')
        self.assertEqual(db['volumes'][0]['target'], '/var/lib/mysql')
        self.assertIn('--protocol=TCP', db['healthcheck']['test'][1])
        self.assertIn('--database=', db['healthcheck']['test'][1])
        self.assertIn('MYSQL_PWD=', db['healthcheck']['test'][1])

    def test_port_override(self):
        result = self.compose_config(APP_PORT='8012')
        self.assertEqual(result.returncode, 0, 'Compose config failed')
        self.assertEqual(json.loads(result.stdout)['services']['app']['ports'][0]['published'], '8012')

    def test_empty_database_credentials_fail_closed(self):
        for name in ('MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD'):
            with self.subTest(name=name):
                result = self.compose_config(**{name: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)


if __name__ == '__main__':
    unittest.main()

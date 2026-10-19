"""Disposable local mysqld for opt-in ORM integration tests, never the user's DB."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from unittest.mock import patch

import pymysql


@contextmanager
def mysql_sandbox():
    executable = shutil.which('mysqld')
    if not executable:
        raise RuntimeError('mysqld is required for isolated ORM integration tests')
    # TemporaryDirectory owns only this freshly created, synthetic instance.
    with tempfile.TemporaryDirectory(prefix='modeltoll-orm-', dir='/private/tmp') as directory:
        root = Path(directory)
        datadir = root / 'data'
        error_log = root / 'mysql.log'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        common = [executable, '--no-defaults', f'--datadir={datadir}',
                  f'--log-error={error_log}']
        subprocess.run([*common, '--initialize-insecure'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        process = subprocess.Popen([
            *common, f'--socket={root / "mysql.sock"}', f'--pid-file={root / "mysql.pid"}',
            '--bind-address=127.0.0.1', f'--port={port}', '--mysqlx=OFF',
            '--skip-log-bin', '--innodb-buffer-pool-size=64M',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connection = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('isolated mysqld exited before readiness')
                try:
                    connection = pymysql.connect(host='127.0.0.1', port=port, user='root',
                                                 connect_timeout=1, autocommit=True)
                    break
                except pymysql.OperationalError:
                    time.sleep(0.1)
            if connection is None:
                raise RuntimeError('isolated mysqld readiness timed out')
            password = secrets.token_urlsafe(32)
            database = 'modeltoll_orm_fixture'
            with connection.cursor() as cursor:
                cursor.execute('CREATE DATABASE modeltoll_orm_fixture CHARACTER SET utf8mb4')
                cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (password,))
            connection.close()
            connection = None
            environment = {'MYSQL_HOST': '127.0.0.1', 'MYSQL_PORT': str(port),
                           'MYSQL_USER': 'root', 'MYSQL_PASSWORD': password, 'MYSQL_DATABASE': database}
            # Prevent reading private .env even though all DB keys are overridden.
            from app.core import config
            from app.db.engine import get_engine
            get_engine.cache_clear()
            runtime = {'LAYA_RUNTIME': 'external', 'LAYA_USER_RPM': '0', 'LAYA_USER_MAX_INFLIGHT': '0',
                       'HF_HUB_OFFLINE': '1'}
            with patch.dict(os.environ, {**environment, **runtime}), patch.object(config, 'read_env_file', return_value=environment):
                try:
                    yield
                finally:
                    get_engine().dispose()
                    get_engine.cache_clear()
        finally:
            if connection is not None:
                connection.close()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

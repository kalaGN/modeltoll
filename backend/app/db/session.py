"""MySQL 连接工厂与短事务。连接按操作获取并立即释放，不跨线程共享。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from app.core import config


def _new_connection(autocommit: bool) -> pymysql.connections.Connection:
    settings = config.database_config()
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=autocommit,
        connect_timeout=5,
    )


@contextmanager
def cursor() -> Iterator[DictCursor]:
    """单条语句的自动提交游标，用于读取和无需与原子的写入。"""
    conn = _new_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[DictCursor]:
    """短事务：提交成功才对外可见，异常一律回滚。"""
    conn = _new_connection(autocommit=False)
    try:
        conn.begin()
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

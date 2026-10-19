"""Native MySQL connection reserved for the reviewed SQL migration executor."""
from collections.abc import Iterator
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from app.core import config


@contextmanager
def cursor() -> Iterator[DictCursor]:
    settings = config.database_config()
    connection = pymysql.connect(
        host=settings.host, port=settings.port, user=settings.user,
        password=settings.password, database=settings.database, charset="utf8mb4",
        cursorclass=DictCursor, autocommit=True, connect_timeout=5,
    )
    try:
        with connection.cursor() as current:
            yield current
    finally:
        connection.close()

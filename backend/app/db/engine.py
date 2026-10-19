"""Lazy synchronous SQLAlchemy engine; importing application code never connects."""
from functools import lru_cache

from sqlalchemy import Engine, URL, create_engine
from sqlalchemy.pool import NullPool

from app.core import config


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = config.database_config()
    url = URL.create(
        'mysql+pymysql', username=settings.user, password=settings.password,
        host=settings.host, port=settings.port, database=settings.database,
        query={'charset': 'utf8mb4'},
    )
    return create_engine(
        url, poolclass=NullPool, echo=False, hide_parameters=True,
        connect_args={'connect_timeout': 5},
    )

"""Operation-local ORM sessions and service-owned short transactions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.db.engine import get_engine
from sqlalchemy.orm import Session


@contextmanager
def read_session() -> Iterator[Session]:
    """An operation-local read session; close releases its read transaction."""
    with Session(get_engine(), autoflush=False) as db:
        yield db


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """One service-owned short business transaction, committed or rolled back once."""
    with Session(get_engine(), autoflush=False) as db, db.begin():
        yield db


@contextmanager
def pinned_session() -> Iterator[Session]:
    """Keep connection-level locks on one physical connection across transactions."""
    with get_engine().connect() as connection:
        with Session(connection, autoflush=False) as db:
            yield db

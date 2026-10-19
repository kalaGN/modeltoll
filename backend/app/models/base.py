"""Declarative metadata only. Never creates or alters tables at runtime."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

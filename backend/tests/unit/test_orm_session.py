"""Session lifecycle tests; SQLite here proves commit/rollback only, not MySQL locks."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db import engine, session


class EngineTests(unittest.TestCase):
    def test_factory_is_lazy_cached_and_does_not_log_secrets(self):
        settings = SimpleNamespace(user='fixture', password='synthetic-only', host='127.0.0.1',
                                   port=3306, database='fixture')
        engine.get_engine.cache_clear()
        self.addCleanup(engine.get_engine.cache_clear)
        with patch.object(engine.config, 'database_config', return_value=settings), \
             patch.object(engine, 'create_engine') as create:
            self.assertIs(engine.get_engine(), engine.get_engine())
        create.assert_called_once()
        args, kwargs = create.call_args
        self.assertEqual(args[0].drivername, 'mysql+pymysql')
        self.assertNotIn(settings.password, str(args[0]))
        self.assertIs(kwargs['poolclass'], NullPool)
        self.assertTrue(kwargs['hide_parameters'])
        self.assertEqual(kwargs['connect_args'], {'connect_timeout': 5})


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE fixture (n INTEGER NOT NULL)'))
        self.patch = patch.object(session, 'get_engine', return_value=self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_transaction_commits_and_read_session_does_not_commit_writes(self):
        with session.unit_of_work() as db:
            db.execute(text('INSERT INTO fixture VALUES (1)'))
            self.assertFalse(db.autoflush)
        with session.read_session() as db:
            self.assertEqual(db.scalar(text('SELECT COUNT(*) FROM fixture')), 1)
            db.execute(text('INSERT INTO fixture VALUES (2)'))
        with session.read_session() as db:
            self.assertEqual(db.scalar(text('SELECT COUNT(*) FROM fixture')), 1)

    def test_exception_rolls_back_and_does_not_leak_pending_changes(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            with session.unit_of_work() as db:
                db.execute(text('INSERT INTO fixture VALUES (1)'))
                raise RuntimeError('synthetic')
        with session.read_session() as db:
            self.assertEqual(db.scalar(text('SELECT COUNT(*) FROM fixture')), 0)

"""可选真实 MySQL 回归，所有合成业务记录在同一事务回滚；不加载模型。"""
import os
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from pymysql.cursors import DictCursor
from sqlalchemy.orm import Session
from app.db import session
from app.db.engine import get_engine
from app.schemas.gateway import ConnectionRequest
from app.integrations import openai_client
from app.services import api_keys, gateway, inference


@unittest.skipUnless(os.environ.get('LAYA_TEST_MYSQL') == '1', '设置 LAYA_TEST_MYSQL=1 才连接真实数据库')
class MySQLGatewayTests(unittest.TestCase):
    def test_connection_pricing_call_and_charge_roll_back(self):
        conn = get_engine().connect()
        outer = conn.begin()
        user_id, key_id = str(uuid.uuid4()), str(uuid.uuid4())
        model = 'test-' + uuid.uuid4().hex
        email = model + '@example.invalid'
        try:
            with conn.connection.cursor(DictCursor) as cur:
                cur.execute("INSERT INTO users (id, email, email_normalized, password_hash, created_at, updated_at)"
                            " VALUES (%s, %s, %s, 'not-a-real-password-hash', UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
                            (user_id, email, email))
                cur.execute("INSERT INTO api_keys (id, user_id, key_hash, display_prefix, last_four, created_at)"
                            " VALUES (%s, %s, %s, 'fixture', '0000', UTC_TIMESTAMP(3))",
                            (key_id, user_id, uuid.uuid4().hex + uuid.uuid4().hex))
                @contextmanager
                def same_transaction():
                    with Session(bind=conn, autoflush=False, join_transaction_mode='create_savepoint') as db, db.begin():
                        yield db
                # 服务层的短事务暂时借用外层测试事务，不提交任何测试数据。
                with patch.object(session, 'unit_of_work', same_transaction), \
                     patch.object(session, 'read_session', same_transaction), \
                     patch.object(openai_client, 'upstream_key', return_value=''):
                    value = ConnectionRequest(base_url='http://127.0.0.1:11434/v1', model=model, enabled=True)
                    gateway.save_connection(value)
                    self.assertEqual(gateway.connection(), value)
                    call = inference.begin('/v1/chat/completions', api_keys.Principal(user_id, key_id, 'fixture'), model)
                    inference.mark_running(call)
                    amount = inference.succeeded(call, {'input_tokens': 10, 'output_tokens': 2})
                    self.assertEqual(amount, Decimal('0.000010'))
                    cur.execute('SELECT status, input_tokens, output_tokens, billing_status FROM api_calls WHERE id = %s', (call.id,))
                    self.assertEqual(cur.fetchone(), {'status': 'succeeded', 'input_tokens': 10,
                                                     'output_tokens': 2, 'billing_status': 'charged'})
                    cur.execute('SELECT COUNT(*) AS total FROM usage_charges WHERE call_id = %s', (call.id,))
                    self.assertEqual(cur.fetchone()['total'], 1)
        finally:
            outer.rollback()
            conn.close()
        with get_engine().connect() as db:
            self.assertEqual(db.exec_driver_sql('SELECT COUNT(*) FROM users WHERE id = %s', (user_id,)).scalar_one(), 0)
